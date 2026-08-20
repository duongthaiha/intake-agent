FROM python:3.12-slim

ENV PATH="/app/.venv/bin:${PATH}" \
    HOME="/home/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_DEFAULT_INDEX="https://packagefeedproxy.microsoft.io/pypi/simple/" \
    UV_LINK_MODE=copy

WORKDIR /app

RUN python -m pip install --no-cache-dir --disable-pip-version-check --progress-bar off uv==0.12.3

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY foundry ./foundry
COPY scripts/foundry/configure_live.py ./scripts/foundry/configure_live.py
COPY scripts/foundry/smoke_live.py ./scripts/foundry/smoke_live.py

RUN python -m uv sync --frozen --no-dev --no-editable --package intake-foundry-prompt
RUN mkdir -p /home/app && chown -R 10001:0 /home/app

USER 10001

CMD ["python", "scripts/foundry/configure_live.py"]
