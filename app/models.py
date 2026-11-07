from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.String(26), nullable=False, unique=True)
    url = db.Column(db.Text, nullable=False, unique=True)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    body = db.Column(db.Text)
    authors = db.Column(db.JSON, nullable=False, default=list)
    section = db.Column(db.String(200), index=True)
    published_at = db.Column(db.DateTime(timezone=True), index=True)
    modified_at = db.Column(db.DateTime(timezone=True))
    first_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ScrapeRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(20), nullable=False, default="running")
    discovered = db.Column(db.Integer, nullable=False, default=0)
    processed = db.Column(db.Integer, nullable=False, default=0)
    inserted = db.Column(db.Integer, nullable=False, default=0)
    updated = db.Column(db.Integer, nullable=False, default=0)
    failed = db.Column(db.Integer, nullable=False, default=0)
    deferred = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)
