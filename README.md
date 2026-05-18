# b2cagent API

FastAPI backend (Python 3.12, async SQLAlchemy, Alembic, PostgreSQL, Redis).

## Setup

```bash
cp .env.example .env
poetry install
poetry run uvicorn app.main:app --reload
```

## Migrations

```bash
poetry run alembic revision --autogenerate -m "init"
poetry run alembic upgrade head
```
