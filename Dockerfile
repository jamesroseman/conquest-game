FROM python:3.12-slim AS builder

ENV POETRY_VERSION=1.8.3 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /app

COPY pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-root

COPY src/ ./src/
COPY README.md ./
RUN poetry install --only main

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src ./src

ENV PYTHONPATH=/app/src

EXPOSE 8080

CMD ["sh", "-c", "uvicorn conquest.main:app --host 0.0.0.0 --port ${PORT}"]
