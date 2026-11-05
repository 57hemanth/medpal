FROM node:26-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# In-boundary OCR (English and Hindi); no hosted document processing.
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-hin && rm -rf /var/lib/apt/lists/*

# Dependencies first for layer caching
COPY pyproject.toml uv.lock .python-version ./
ARG ENABLE_SPEECH=false
RUN if [ "$ENABLE_SPEECH" = "true" ]; then uv sync --frozen --no-dev --no-install-project --extra speech; else uv sync --frozen --no-dev --no-install-project; fi

COPY alembic.ini ./
COPY infra/migrations infra/migrations
COPY services services
COPY --from=web /web/dist static

RUN mkdir -p /app/objects && useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["sh", "-c", "uvicorn services.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
