FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIR=/app/frontend

WORKDIR /app

# Install dependencies first so this layer is cached when only source files change.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY frontend ./frontend

RUN useradd --system --no-create-home app
USER app

EXPOSE 8000

# Apply database migrations, then start the API. Hosting providers set PORT.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn scheduler.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
