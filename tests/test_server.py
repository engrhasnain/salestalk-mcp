"""Server wiring tests (no database needed)."""

from __future__ import annotations

import pytest

from salestalk_mcp import server
from salestalk_mcp.config import Settings
from salestalk_mcp.db import Database, to_jsonable


def test_instructions_state_currency_and_read_only() -> None:
    assert "READ-ONLY" in server.INSTRUCTIONS
    assert "AED" in server.INSTRUCTIONS


def test_localhost_http_uses_sdk_default_protection() -> None:
    assert server._transport_security("127.0.0.1") is None


def test_all_interfaces_http_keeps_dns_rebinding_protection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALESTALK_ALLOWED_HOSTS", "salestalk.internal:8765")
    sec = server._transport_security("0.0.0.0")
    assert sec is not None and sec.enable_dns_rebinding_protection
    assert "localhost:*" in sec.allowed_hosts
    assert "salestalk.internal:8765" in sec.allowed_hosts


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        server.main(["--version"])
    assert exc.value.code == 0
    assert "salestalk-mcp" in capsys.readouterr().out


def test_settings_clamp_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALESTALK_MAX_ROWS", "999999")
    monkeypatch.setenv("SALESTALK_DEFAULT_ROWS", "50")
    monkeypatch.setenv("SALESTALK_STATEMENT_TIMEOUT_MS", "1")
    s = Settings.from_env()
    assert s.max_rows == 10_000
    assert s.default_rows == 50
    assert s.statement_timeout_ms == 100


def test_describe_target_hides_password() -> None:
    db = Database(Settings(database_url="postgresql://ro:supersecret@db.example:6543/sales"))
    target = db.describe_target()
    assert target == "ro@db.example:6543/sales"
    assert "supersecret" not in target


def test_to_jsonable() -> None:
    from datetime import date
    from decimal import Decimal

    assert to_jsonable(Decimal("12.50")) == 12.5
    assert to_jsonable(Decimal("7")) == 7
    assert to_jsonable(Decimal("NaN")) == "NaN"
    assert to_jsonable(date(2026, 9, 1)) == "2026-09-01"
    assert to_jsonable(b"\x00\x01") == "<2 bytes>"
    assert to_jsonable({"a": [Decimal("1.5")]}) == {"a": [1.5]}
