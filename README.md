# Chosun Daily Articles API

Flask + PostgreSQL + Flask-Smorest REST API for hourly collection from
<https://www.chosun.com/english/>. Stores article metadata and available full text,
updates existing articles, and prevents duplicates with database unique constraints
and atomic upserts. Swagger UI and OpenAPI are generated from endpoint schemas.

## Run locally

Use Python 3.12 (Python 3.9+ is supported). From this directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Create a PostgreSQL database and set `DATABASE_URL` and a random `SCRAPE_TOKEN` in
`.env`. For example, with Docker installed:

```sh
docker run --name chosun-postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=chosun -p 5432:5432 \
  -v chosun-postgres-data:/var/lib/postgresql/data -d postgres:16
python -c 'import secrets; print(secrets.token_urlsafe(32))'
flask --app wsgi db upgrade
flask --app wsgi run --port 8000
```

The example database URL is `postgresql+psycopg://postgres:postgres@localhost:5432/chosun`.
Render's `postgres://` and `postgresql://` URLs are normalized to psycopg automatically.
Without `DATABASE_URL`, the app uses `instance/chosun.db` (SQLite) for local exploration.
Use PostgreSQL for deployment and concurrent collection; SQLite does not provide
the cross-worker advisory lock.

- Swagger UI: <http://localhost:8000/docs>
- OpenAPI: <http://localhost:8000/openapi.json>
- Readiness: <http://localhost:8000/health>

Collect once from the command line:

```sh
flask --app wsgi scrape
```

Or create a scrape-run resource (replace the token):

```sh
curl -X POST http://localhost:8000/api/v1/scrape-runs \
  -H 'Authorization: Bearer YOUR_SCRAPE_TOKEN'
curl 'http://localhost:8000/api/v1/articles?section=National&per_page=10'
```

## REST resources

| Method | Path | Behavior | Access |
| --- | --- | --- | --- |
| GET | `/api/v1/articles` | Paginated articles; filter by section, title/description search, or publication range | Public |
| GET | `/api/v1/articles/{article_id}` | Retrieve stored article, including body when available | Public |
| POST | `/api/v1/scrape-runs` | Create and synchronously execute a bounded collection run; HTTP 201 and Location header | Bearer token |
| GET | `/api/v1/scrape-runs` | Latest runs, newest first; `limit` defaults to 20, maximum 100 | Bearer token |
| GET | `/api/v1/scrape-runs/{run_id}` | Retrieve a recorded run | Bearer token |
| GET | `/health` | Database and article table readiness; HTTP 200 or 503 | Public |

`/docs` and `/openapi.json` expose the generated documentation. Documentation assets
are loaded from a pinned Swagger UI CDN version.

Article pagination uses `page` (default 1) and `per_page` (default 20, maximum 100).
`section` is an exact match; `q` matches literal title/description text case
insensitively. `published_from` is inclusive and `published_to` exclusive; both
require timezone-aware ISO 8601 timestamps. For a Korean calendar day, use:

```text
/api/v1/articles?published_from=2026-11-07T00:00:00%2B09:00&published_to=2026-11-08T00:00:00%2B09:00
```

Use URL encoding for `+` in time offsets. Articles sort by publication time descending,
then ID descending, with unknown publication dates last. Empty or out-of-range pages
return an empty `items` list. Invalid query parameters return 422; missing resources
return 404; invalid administration credentials return 401. Database outages return
503 without connection details. An unset `SCRAPE_TOKEN` disables administration (503).

A scrape POST has no request body and finishes before returning. HTTP 201 means the
run resource was created; always inspect `status` (`succeeded`, `partial`, or `failed`).
Counters include `discovered`, `processed`, `inserted`, `updated`, `failed`, and
`deferred`. The hourly trigger fails visibly on article errors or a failed run.
An overlapping PostgreSQL run returns 409. Run records become visible at commit;
a process crash rolls back the entire unfinished transaction, including its run record.

## Collection and duplicate prevention

1. Fetch and honor the publisher's `robots.txt`, failing closed if it cannot be fetched.
2. Discover unique English article URLs linked on the homepage. Remove query strings
   and fragments; reject external hosts, non-HTTPS URLs, category pages, and redirects.
3. Prefer unseen article IDs, then revisit known articles for editorial updates.
4. Parse JSON-LD metadata, embedded Arc JSON content (without executing JavaScript),
   and limited HTML fallbacks. Text is stored as plain text. Missing body, description,
   or publication dates are nullable.
5. Upsert by the publisher's immutable 26-character article ID. Unique article IDs
   and canonical URLs prevent duplicates. Preserve `first_seen_at`, refresh
   `last_seen_at`, and update content on later collections.

Requests are sequential with at least 0.5 seconds between starts, honoring a longer
robots crawl delay. Each run has a 75-second collection budget and a 40-article cap;
connection/read timeouts and a 5 MB response cap bound network work. A final request
can slightly exceed the budget while waiting on network I/O. Remaining articles are
reported as deferred. The PostgreSQL transaction lock spans network collection and
persistence; the transaction is short enough for the configured Gunicorn timeout.

Collection follows the current homepage only. It is not a historical archive or a
guarantee of finding every article published that day. Articles removed between runs
can be missed. Publisher markup and availability can change; check scrape-run failures.
Run history and article storage currently have no automatic deletion policy.

## Deploy on Render Free

The included `render.yaml` creates a free Flask web service and free PostgreSQL
instance in the same region. Migrations run before Gunicorn starts because Render
Free does not support one-off jobs. There are no background scheduler threads.

1. Push this project to a GitHub repository.
2. In Render, choose **New → Blueprint**, connect the repository, and select `render.yaml`.
3. After deployment, open `/health` and `/docs` at the assigned HTTPS service URL.
4. Copy the generated `SCRAPE_TOKEN` from the Render service environment.
5. In GitHub repository **Settings → Secrets and variables → Actions**, add:
   - `API_BASE_URL`: the HTTPS service origin, such as `https://YOUR-SERVICE.onrender.com`
     (no path).
   - `SCRAPE_TOKEN`: the same value used by Render.
6. Enable Actions and run **Hourly article collection → Run workflow** once. Inspect
   the run JSON and `/api/v1/articles` to verify storage. The scheduled workflow must
   be on the repository's default branch.

The workflow runs at minute 17 of every hour UTC, first waking the web service with
readiness requests, then posting one authenticated scrape request. No automatic POST
retry is performed after an ambiguous timeout. GitHub's scheduled workflows are
best effort and can be delayed or dropped; public repository schedules can be disabled
after inactivity. Private repositories consume the account's Actions allowance.
See [GitHub scheduling behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

**Render Free is a prototype hosting option:** web services sleep after 15 idle minutes,
free PostgreSQL expires after 30 days, has 1 GB storage, and has no backups. Render
cron jobs have a minimum monthly charge, so this project uses GitHub Actions instead.
For lasting storage, replace `DATABASE_URL` with another hosted PostgreSQL database
or upgrade the Render database before expiry. Export data independently while the
free database is still accessible. The free Blueprint alone does not provide
permanent, guaranteed hourly operation.
See [Render Free limits](https://render.com/docs/free) and [cron pricing](https://render.com/docs/cronjobs).

## Development and verification

```sh
pytest -q
ruff check .
ruff format --check .
flask --app wsgi db check
flask --app wsgi export-openapi
```

Tests use temporary SQLite databases by default. CI supplies a disposable PostgreSQL
16 service through `TEST_DATABASE_URL`, runs the migrations for each API test, and
checks repeat upserts and cross-connection advisory locking. Do not point
`TEST_DATABASE_URL` at any database containing real data; fixtures drop tables.
No tests contact the publisher. The OpenAPI drift test fails whenever endpoint
schemas change without regenerating `docs/openapi.json`.

For schema changes, run `flask --app wsgi db migrate -m 'Describe change'`, inspect
the generated migration, then run `flask --app wsgi db upgrade`. Every endpoint
change must include updated generated OpenAPI and the endpoint table above.
Repository engineering rules are in [AGENTS.md](AGENTS.md).

## Browser test website

Open `http://localhost:8000/` after starting Flask. The HTML explorer supports
article search, publication filters, pagination, article details, health checks,
collection runs, and a raw JSON response inspector. Enter `SCRAPE_TOKEN` to use
collection controls; the page does not persist it in browser storage.

| Method | Path | Behavior | Access |
| --- | --- | --- | --- |
| GET | `/` | HTML API test website | Public |
