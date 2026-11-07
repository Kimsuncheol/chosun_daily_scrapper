# Project guide

## Purpose and architecture
Build a REST API that collects English articles from https://www.chosun.com/english/
hourly and persists them in PostgreSQL without duplicates. Flask's application
factory is in `app/__init__.py`; routes, Marshmallow schemas, models, collector,
and persistence orchestration live in separate modules in `app/`.

## Working rules
- Keep HTTP resources under `/api/v1`. Collection creates a scrape-run resource.
- Every new or changed endpoint MUST include Flask-Smorest arguments, response
  schemas, error responses, authentication documentation, and a useful docstring.
  Regenerate `docs/openapi.json` and update the README endpoint table in the same
  change. Do not hand-edit the generated OpenAPI JSON.
- Keep source IDs and canonical URLs unique at the database level. Use upserts;
  application-side existence checks alone do not prevent concurrent duplicates.
- Use Alembic migrations for schema changes. Never call `create_all` at startup.
- Keep the PostgreSQL transaction advisory lock around a complete collection run.
  Do not start a scheduler/thread inside Flask or Gunicorn workers.
- Respect robots.txt, request pacing, the English-host allowlist, response size
  limits, and the collection deadline. Never execute publisher JavaScript.
- Do not log secrets, authorization headers, or database connection strings.
- Keep tests deterministic and offline with synthetic publisher HTML. Live
  scraping is an explicit smoke check, never part of routine tests.
- SQLite exists only for fast local tests; PostgreSQL CI checks must verify the
  actual upsert, migration, and concurrency behavior before deployment.
- Do not deploy, create cloud resources, or change account secrets unless asked.

## Commands (from repository root)
```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
flask --app wsgi db upgrade
flask --app wsgi run --port 8000
pytest -q
ruff check .
ruff format --check .
flask --app wsgi export-openapi
```
`TEST_DATABASE_URL` enables PostgreSQL tests against a dedicated disposable test
database. Tests delete tables there; NEVER point it at production or real data.
The CI PostgreSQL service is disposable. `DATABASE_URL` is for the application.
After an API change, export the spec and run the documentation drift test.

## Deployment constraints
`render.yaml` provisions a free web service and a free PostgreSQL database.
Free Render databases expire after 30 days. GitHub Actions calls the authenticated
collection endpoint hourly because Render cron jobs are paid and free web services
sleep. Scheduled Actions are best effort; do not promise exact hourly execution
or continuous long-term free database hosting. Document any changed assumptions.
