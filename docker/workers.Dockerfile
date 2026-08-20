FROM mcr.microsoft.com/azure-functions/python:4-python3.12

ENV AzureWebJobsScriptRoot="/home/site/wwwroot" \
    ASPNETCORE_URLS="http://+:8080" \
    PYTHONUNBUFFERED=1 \
    UV_DEFAULT_INDEX="https://packagefeedproxy.microsoft.io/pypi/simple/"

WORKDIR /app

RUN python -m pip install --no-cache-dir --disable-pip-version-check --progress-bar off uv==0.12.3

COPY pyproject.toml uv.lock ./
COPY packages ./packages

RUN python -m uv sync --frozen --no-dev --no-editable --package intake-workers

WORKDIR /home/site/wwwroot
COPY packages/intake-workers/host.json ./
COPY packages/intake-workers/function_app.py ./
RUN mkdir -p .python_packages/lib/site-packages \
    && cp -a /app/.venv/lib/python3.12/site-packages/. .python_packages/lib/site-packages/ \
    && chown -R app:app /home/site/wwwroot

USER app
