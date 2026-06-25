# Sahab Backend

FastAPI control-plane for the Sahab GPU compute platform.

## Quick start (local dev)

```bash
cd backend

# 1. Create virtualenv and install deps
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# 2. Configure environment
cp ../.env.example .env
# Edit .env — at minimum set DATABASE_URL and REDIS_URL for your local services

# 3. Run migrations (requires a real Postgres; skip for SQLite dev mode)
DATABASE_URL=postgresql+psycopg://sahab:sahab@localhost:5432/sahab \
  alembic upgrade head

# 4. Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For local dev without Postgres, the backend falls back to SQLite (`sqlite+aiosqlite:///./sahab_dev.db`) if `DATABASE_URL` is unset. Tables are created automatically on startup via `Base.metadata.create_all`.

## Running the worker

The background worker runs APScheduler jobs for metering (every 60 s) and queue drain (every 30 s).

```bash
# Same venv as above
python -m app.worker
```

In Docker Compose, the worker uses the same image as the API server with an overridden CMD:

```yaml
worker:
  image: sahab-backend
  command: python -m app.worker
  env_file: .env
```

## Running migrations (Alembic)

```bash
# Apply all pending migrations
alembic upgrade head

# Generate a new migration after model changes
alembic revision --autogenerate -m "describe your change"

# Downgrade one step
alembic downgrade -1
```

The `DATABASE_URL` env var is read by `migrations/env.py` at runtime.

## Running tests

Tests use SQLite in-memory + fakeredis — no real Postgres or Redis required.

```bash
# From the backend/ directory with .venv active
pytest -v

# With coverage
pytest --cov=app --cov-report=term-missing
```

## Import sanity check

```bash
python -c "import app.main; print('OK')"
```

## API documentation

When the server is running, interactive docs are at:
- Swagger UI: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

## Environment variables

See `../.env.example` for all configuration knobs. Key ones:

| Variable | Description |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy URL (`postgresql+psycopg://...` or `sqlite+aiosqlite://...`) |
| `REDIS_URL` | Redis connection URL |
| `JWT_SECRET` | 32+ char random string for signing JWTs |
| `ALLOWED_SIGNUP_DOMAINS` | Comma-separated list of allowed email domains |
| `BOOTSTRAP_ADMIN_EMAIL` | Email of the admin seeded on first run |
| `BOOTSTRAP_ADMIN_PASSWORD` | Password of the seeded admin |
| `JUPYTERHUB_API_URL` | JupyterHub REST API base URL |
| `JUPYTERHUB_API_TOKEN` | Service token for the JupyterHub API |
| `CREDITS_PER_MINUTE_L4` | Default GPU credit rate (cpm) |
| `CREDITS_PER_MINUTE_CPU` | Default CPU credit rate (0.0 = free) |
