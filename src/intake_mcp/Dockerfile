FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

USER 65532
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "intake_mcp.main:app", "--host", "0.0.0.0", "--port", "8080"]
