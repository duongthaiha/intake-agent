FROM python:3.12-slim

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_DEFAULT_INDEX="https://packagefeedproxy.microsoft.io/pypi/simple/" \
    UV_LINK_MODE=copy

WORKDIR /app

RUN python -m pip install --no-cache-dir uv==0.12.3

COPY pyproject.toml uv.lock ./
COPY packages ./packages

RUN uv sync --frozen --no-dev --package intake-mcp --extra server

USER 10001
EXPOSE 8000

CMD ["uvicorn", "intake_mcp.runtime:create_application", "--factory", "--host", "0.0.0.0", "--port", "8000"]
