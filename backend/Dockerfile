# Sahab Backend — multi-stage Dockerfile
# Stage: runtime (shared by API server and worker)
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="sahab-backend"
LABEL org.opencontainers.image.description="Sahab GPU Platform — FastAPI control-plane"

# System deps (libpq needed by psycopg binary wheel)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps from pinned flat requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Non-root user
RUN useradd -m -u 1001 sahab && chown -R sahab:sahab /app
USER sahab

# ---- API server (default CMD) ----
# Override CMD in docker-compose for the worker:
#   command: python -m app.worker
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
