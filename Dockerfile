# SalesTalk MCP server image (streamable HTTP by default; pass --transport stdio for stdio).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first (cached layer), then the project itself.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 salestalk
USER salestalk

EXPOSE 8765
ENTRYPOINT ["salestalk-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8765"]
