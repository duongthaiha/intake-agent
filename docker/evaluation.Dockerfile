FROM python:3.12-slim

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_DEFAULT_INDEX="https://packagefeedproxy.microsoft.io/pypi/simple/" \
    UV_LINK_MODE=copy

WORKDIR /app

RUN python -m pip install --no-cache-dir --disable-pip-version-check --progress-bar off uv==0.12.3

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY evaluation ./evaluation

RUN python -m uv sync --frozen --no-dev --no-editable --package intake-persistence

USER 10001

CMD ["python", "-m", "evaluation.job"]
