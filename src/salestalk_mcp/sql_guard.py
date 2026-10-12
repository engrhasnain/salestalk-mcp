"""SELECT-only guard for ``run_sql``.

This is the *first* layer of defense. The database still enforces the real
boundary (a SELECT-only role, read-only transactions and a statement timeout),
but rejecting bad SQL early gives Claude a clear error it can act on.

How it works: a small PostgreSQL-aware lexer splits the input into tokens,
understanding ``-- line`` and nested ``/* block */`` comments, ``'strings'``,
``E'escape strings'``, ``$tag$dollar quotes$tag$`` and ``"quoted identifiers"``.
Every check below runs on tokens, so a keyword hidden in a string literal does
not cause a false positive, and a keyword hidden in a comment cannot sneak past.

Rules:

1. Comments are stripped; what is executed is the comment-free SQL.
2. Exactly one statement (a single trailing ``;`` is tolerated).
3. The statement must start with ``SELECT`` or ``WITH`` (optionally after ``(``).
4. Write/DDL/transaction-control/session keywords are rejected anywhere.
5. ``SELECT ... INTO`` and row-locking clauses (``FOR UPDATE`` / ``FOR SHARE``) are rejected.
6. Functions with side effects or file/network access (``pg_sleep``, ``pg_read_file``,
   ``dblink``, ``set_config``, ``nextval``, ``lo_import``, ``query_to_xml`` ...) are rejected.
7. Input size is capped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_SQL_LENGTH = 20_000

# Keywords that must never appear (outside strings / quoted identifiers) in a read-only query.
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset(
    {
        # DML
        "insert", "update", "delete", "merge", "upsert", "returning",
        # DDL / maintenance
        "create", "alter", "drop", "truncate", "comment", "reindex", "cluster", "vacuum",
        "analyze", "analyse", "refresh",
        # privileges
        "grant", "revoke",
        # bulk I/O
        "copy", "import", "load",
        # procedural / dynamic SQL
        "do", "call", "execute", "exec", "prepare", "deallocate", "declare",
        # session / transaction control
        "set", "reset", "begin", "commit", "rollback", "savepoint", "release", "abort",
        "discard", "checkpoint", "listen", "unlisten", "notify", "lock",
        # SELECT ... INTO creates a table
        "into",
        # custom escape characters would defeat identifier decoding
        "uescape",
    }
)

# Functions that read files, touch the network, sleep, change settings or write.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "pg_sleep", "pg_sleep_for", "pg_sleep_until",
        "pg_read_file", "pg_read_binary_file", "pg_stat_file",
        "pg_ls_dir", "pg_ls_logdir", "pg_ls_waldir", "pg_ls_tmpdir", "pg_ls_archive_statusdir",
        "lo_import", "lo_export", "lo_open", "lo_create", "lo_creat", "lo_unlink", "lo_put",
        "lo_get", "lo_from_bytea", "lo_truncate", "lowrite", "loread",
        "dblink", "dblink_exec", "dblink_connect", "dblink_connect_u", "dblink_send_query",
        "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile",
        "pg_promote", "pg_switch_wal", "pg_create_restore_point", "pg_backup_start",
        "pg_backup_stop", "pg_start_backup", "pg_stop_backup", "pg_logical_emit_message",
        "set_config", "nextval", "setval", "pg_notify", "txid_current", "pg_current_xact_id",
        "pg_export_snapshot", "pg_import_system_collations",
        "query_to_xml", "query_to_xmlschema", "query_to_xml_and_xmlschema",
        "cursor_to_xml", "cursor_to_xmlschema", "database_to_xml", "database_to_xmlschema",
        "database_to_xml_and_xmlschema", "schema_to_xml", "schema_to_xml_and_xmlschema",
    }
)
FORBIDDEN_FUNCTION_PREFIXES: tuple[str, ...] = (
    "pg_advisory", "pg_try_advisory", "pg_stat_reset", "pg_file_", "pg_replication_",
    "pg_create_", "pg_drop_", "pg_ls_", "pg_read_", "dblink_",
)

ALLOWED_FIRST_KEYWORDS = ("select", "with")

_IDENT_START = re.compile(r"[A-Za-z_\u0080-￿]")
_IDENT_CHAR = re.compile(r"[A-Za-z0-9_$\u0080-￿]")
_DOLLAR_TAG = re.compile(r"\$([A-Za-z_\u0080-￿][A-Za-z0-9_\u0080-￿]*)?\$")


class SqlGuardError(ValueError):
    """Raised when SQL is rejected by the guard. The message is safe to show to the model."""


@dataclass(frozen=True)
class Token:
    kind: str  # word | quoted_ident | string | number | symbol | space
    text: str

    @property
    def lower(self) -> str:
        return self.text.lower()


@dataclass(frozen=True)
class GuardedSql:
    """SQL that passed the guard: comments stripped, trailing semicolon removed."""

    sql: str
    tokens: tuple[Token, ...] = field(repr=False, default=())


# --------------------------------------------------------------------------- lexer


def tokenize(sql: str) -> list[Token]:
    """Split SQL into tokens. Comments are dropped (replaced by a single space token)."""
    tokens: list[Token] = []
    i, n = 0, len(sql)

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        # whitespace
        if ch.isspace():
            j = i
            while j < n and sql[j].isspace():
                j += 1
            tokens.append(Token("space", " "))
            i = j
            continue

        # -- line comment
        if ch == "-" and nxt == "-":
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            tokens.append(Token("space", " "))
            continue

        # /* block comment */ (PostgreSQL allows nesting)
        if ch == "/" and nxt == "*":
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth += 1
                    j += 2
                elif sql.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth:
                raise SqlGuardError("Unterminated /* comment.")
            tokens.append(Token("space", " "))
            i = j
            continue

        # 'string' (standard conforming: '' escapes a quote, backslash is literal)
        if ch == "'":
            j = _scan_quoted(sql, i, "'", backslash_escapes=False)
            tokens.append(Token("string", sql[i:j]))
            i = j
            continue

        # "quoted identifier"
        if ch == '"':
            j = _scan_quoted(sql, i, '"', backslash_escapes=False)
            tokens.append(Token("quoted_ident", sql[i + 1 : j - 1].replace('""', '"')))
            i = j
            continue

        # $tag$ dollar-quoted string $tag$  (but $1 is a positional parameter)
        if ch == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                tag = m.group(0)
                end = sql.find(tag, m.end())
                if end == -1:
                    raise SqlGuardError("Unterminated dollar-quoted string.")
                j = end + len(tag)
                tokens.append(Token("string", sql[i:j]))
                i = j
                continue
            j = i + 1
            while j < n and sql[j].isdigit():
                j += 1
            tokens.append(Token("symbol", sql[i:j]))
            i = j
            continue

        # identifiers / keywords (and E'..', B'..', X'..', N'..' string prefixes)
        if _IDENT_START.match(ch):
            j = i + 1
            while j < n and _IDENT_CHAR.match(sql[j]):
                j += 1
            word = sql[i:j]
            # U&"ident" / U&'string' with \XXXX unicode escapes: decode so names cannot be disguised
            if word.lower() == "u" and sql[j : j + 2] in ("&\"", "&'"):
                quote = sql[j + 1]
                k = _scan_quoted(sql, j + 1, quote, backslash_escapes=False)
                if quote == '"':
                    decoded = _decode_unicode_escapes(sql[j + 2 : k - 1].replace('""', '"'))
                    tokens.append(Token("quoted_ident", decoded))
                else:
                    tokens.append(Token("string", sql[i:k]))
                i = k
                continue
            if j < n and sql[j] == "'" and word.lower() in {"e", "b", "x", "n"}:
                k = _scan_quoted(sql, j, "'", backslash_escapes=word.lower() == "e")
                tokens.append(Token("string", sql[i:k]))
                i = k
                continue
            tokens.append(Token("word", word))
            i = j
            continue

        # numbers
        if ch.isdigit() or (ch == "." and nxt.isdigit()):
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "._"):
                j += 1
            tokens.append(Token("number", sql[i:j]))
            i = j
            continue

        # everything else is a single-character symbol
        tokens.append(Token("symbol", ch))
        i += 1

    return tokens


def _scan_quoted(sql: str, start: int, quote: str, *, backslash_escapes: bool) -> int:
    """Return the index just past the closing quote of a quoted token starting at ``start``."""
    i, n = start + 1, len(sql)
    while i < n:
        c = sql[i]
        if backslash_escapes and c == "\\":
            i += 2
            continue
        if c == quote:
            if i + 1 < n and sql[i + 1] == quote:  # doubled quote = escaped quote
                i += 2
                continue
            return i + 1
        i += 1
    kind = "identifier" if quote == '"' else "string literal"
    raise SqlGuardError(f"Unterminated quoted {kind}.")


_UNICODE_ESCAPE = re.compile(r"\\(?:\+([0-9A-Fa-f]{6})|([0-9A-Fa-f]{4})|(\\))")


def _decode_unicode_escapes(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        if m.group(3):
            return "\\"
        return chr(int(m.group(1) or m.group(2), 16))

    return _UNICODE_ESCAPE.sub(repl, text)


def _render(tokens: list[Token]) -> str:
    """Rebuild SQL from tokens (comments are already gone). String literals are untouched."""
    out: list[str] = []
    prev_space = True  # also trims leading whitespace
    for t in tokens:
        if t.kind == "space":
            if not prev_space:
                out.append(" ")
            prev_space = True
            continue
        prev_space = False
        out.append('"' + t.text.replace('"', '""') + '"' if t.kind == "quoted_ident" else t.text)
    return "".join(out).strip()


# --------------------------------------------------------------------------- guard


def strip_comments(sql: str) -> str:
    """Return ``sql`` with all comments removed (string literals preserved)."""
    return _render(tokenize(sql))


def guard_sql(sql: str) -> GuardedSql:
    """Validate that ``sql`` is a single read-only SELECT. Raises :class:`SqlGuardError`."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlGuardError("Empty query. Provide a single SELECT statement.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SqlGuardError(f"Query is too long ({len(sql)} chars, max {MAX_SQL_LENGTH}).")
    if "\x00" in sql:
        raise SqlGuardError("Query contains a NUL byte.")

    tokens = tokenize(sql)
    meaningful = [t for t in tokens if t.kind != "space"]

    # Rule 2: single statement (one optional trailing semicolon).
    while meaningful and meaningful[-1].kind == "symbol" and meaningful[-1].text == ";":
        meaningful.pop()
        # drop the trailing ';' (and anything after it, which can only be whitespace) from tokens
        last_semicolon = max(i for i, t in enumerate(tokens) if t.kind == "symbol" and t.text == ";")
        tokens = tokens[:last_semicolon]
    if not meaningful:
        raise SqlGuardError("Empty query. Provide a single SELECT statement.")
    if any(t.kind == "symbol" and t.text == ";" for t in meaningful):
        raise SqlGuardError("Only a single statement is allowed (found ';' in the middle of the query).")

    # Rule 3: must start with SELECT or WITH, optionally wrapped in parentheses.
    first = next((t for t in meaningful if not (t.kind == "symbol" and t.text == "(")), None)
    if first is None or first.kind != "word" or first.lower not in ALLOWED_FIRST_KEYWORDS:
        shown = first.text if first is not None else "("
        raise SqlGuardError(f"Only SELECT queries are allowed (query starts with '{shown[:20]}').")

    words = [t.lower for t in meaningful if t.kind == "word"]

    # Rule 4: forbidden keywords anywhere.
    bad = sorted({w for w in words if w in FORBIDDEN_KEYWORDS})
    if bad:
        raise SqlGuardError(
            "Read-only mode: the query contains forbidden keyword(s): "
            + ", ".join(b.upper() for b in bad)
            + ". Only plain SELECT queries are allowed (quote identifiers that clash, e.g. \"comment\")."
        )

    # Rule 5: row-locking clauses (FOR UPDATE / FOR NO KEY UPDATE / FOR SHARE / FOR KEY SHARE).
    for idx, w in enumerate(words):
        if w == "for" and idx + 1 < len(words) and words[idx + 1] in {"update", "share", "no", "key"}:
            raise SqlGuardError("Row-locking clauses (FOR UPDATE / FOR SHARE) are not allowed.")

    # Rule 6: dangerous functions (also catches "quoted" names and schema-qualified calls).
    for t in meaningful:
        if t.kind not in ("word", "quoted_ident"):
            continue
        name = t.lower
        if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
            raise SqlGuardError(f"Function '{t.text}' is not allowed in read-only queries.")

    return GuardedSql(sql=_render(tokens), tokens=tuple(meaningful))


def wrap_with_limit(sql: str, limit: int) -> str:
    """Enforce a hard row cap regardless of any LIMIT inside the user's query."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return f"SELECT * FROM (\n{sql}\n) AS salestalk_query LIMIT {int(limit)}"
