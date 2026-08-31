# backend/Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so a source change does not invalidate the layer.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . && pip cache purge

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini cli.py ./
COPY config ./config

EXPOSE 8000

# ADR-017: one image, several entrypoints. Override `command` to run the CLI:
#   docker compose run --rm api python -m cli run-all hvac --location "Houston, TX"
CMD ["uvicorn", "app.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
