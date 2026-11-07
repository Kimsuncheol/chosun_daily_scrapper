import json
import os
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate
from flask_smorest import Api
from sqlalchemy.exc import SQLAlchemyError

from .models import db


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__)
    database_url = os.getenv("DATABASE_URL", "sqlite:///chosun.db")
    if database_url.startswith(("postgres://", "postgresql://")):
        database_url = "postgresql+psycopg://" + database_url.split("://", 1)[1]
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SCRAPE_TOKEN=os.getenv("SCRAPE_TOKEN", ""),
        SCRAPER_USER_AGENT=os.getenv("SCRAPER_USER_AGENT", "ChosunDailyScraper/1.0"),
        API_TITLE="Chosun Daily Articles API",
        API_VERSION="1.0.0",
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/",
        OPENAPI_JSON_PATH="openapi.json",
        OPENAPI_SWAGGER_UI_PATH="/docs",
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/",
        MAX_CONTENT_LENGTH=1024,
    )
    if test_config:
        app.config.update(test_config)
    db.init_app(app)
    Migrate(app, db, compare_type=True)
    api = Api(app)
    api.spec.components.security_scheme("BearerAuth", {"type": "http", "scheme": "bearer"})
    from .routes import articles, health, runs

    for blueprint in (articles, runs, health):
        api.register_blueprint(blueprint)

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error("Database operation failed: %s", type(error).__name__)
        return {
            "code": 503,
            "status": "Service Unavailable",
            "message": "Database temporarily unavailable",
        }, 503

    @app.cli.command("scrape")
    def scrape_command():
        """Run the same collector directly (for local cron or paid workers)."""
        from .schemas import RunSchema
        from .service import RunInProgress, collect

        try:
            run = collect()
        except RunInProgress as exc:
            raise click.ClickException("Another scrape run is in progress") from exc
        click.echo(json.dumps(RunSchema().dump(run)))
        if run.status == "failed":
            raise click.ClickException("Scrape failed; inspect the recorded run")

    @app.cli.command("export-openapi")
    @click.option("--output", default="docs/openapi.json")
    def export_openapi(output):
        """Export the generated API contract for review and CI drift checks."""
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(api.spec.to_dict(), indent=2, sort_keys=True) + "\n")
        click.echo(f"Wrote {output}")

    return app
