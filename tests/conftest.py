import os
from pathlib import Path

import pytest
from flask_migrate import upgrade

from app import create_app
from app.models import db


@pytest.fixture
def app(tmp_path):
    # A separate environment variable prevents accidental use of the application DB.
    uri = os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    application = create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": uri, "SCRAPE_TOKEN": "test-secret"}
    )
    with application.app_context():
        db.drop_all()
        # Include Alembic state in cleanup when reusing the disposable CI database.
        with db.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        upgrade(directory=str(Path(__file__).resolve().parents[1] / "migrations"))
        yield application
        db.session.remove()
        db.drop_all()
        with db.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def article_html():
    return (Path(__file__).parent / "fixtures/article.html").read_text()
