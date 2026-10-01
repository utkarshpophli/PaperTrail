# Paper Trail, hosted demo image (Hugging Face Spaces, Docker SDK).
# One container: Postgres + pgvector, FastAPI, Next.js, and nginx in front on
# port 7860. nginx is the only thing listening publicly; the API and database
# bind to loopback, so the backend's loopback-only guard still holds.

# ---- frontend build ----
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_PUBLIC_API_URL=/api \
    NEXT_PUBLIC_DEMO_MODE=1 \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- runtime ----
FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg nginx tesseract-ocr \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16 postgresql-16-pgvector \
 && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node

# Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/.next/standalone frontend/
COPY --from=web /web/.next/static frontend/.next/static
COPY --from=web /web/public frontend/public
COPY deploy/ deploy/
RUN chown -R user:user /app

USER user
ENV HOME=/home/user \
    PATH=/usr/lib/postgresql/16/bin:$PATH \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
