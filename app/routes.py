import hmac
from functools import wraps

from flask import current_app, request, url_for
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import RAISE
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from .models import Article, ScrapeRun, db
from .schemas import ArticlePage, ArticleQuery, ArticleSchema, HealthSchema, RunQuery, RunSchema
from .service import RunInProgress, collect

articles = Blueprint(
    "articles", __name__, url_prefix="/api/v1/articles", description="Collected English articles"
)
runs = Blueprint(
    "scrape_runs",
    __name__,
    url_prefix="/api/v1/scrape-runs",
    description="Authenticated collection operations",
)
health = Blueprint("health", __name__, description="Database readiness")


def require_token(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = current_app.config.get("SCRAPE_TOKEN")
        if not token:
            abort(503, message="Scrape administration is not configured")
        authorization = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        if not hmac.compare_digest(authorization.encode(), expected.encode()):
            abort(
                401, message="Valid bearer token required", headers={"WWW-Authenticate": "Bearer"}
            )
        return fn(*args, **kwargs)

    return wrapped


@articles.route("")
class Articles(MethodView):
    @articles.arguments(ArticleQuery, location="query", unknown=RAISE)
    @articles.alt_response(503, description="Database unavailable")
    @articles.response(200, ArticlePage)
    @articles.alt_response(422, description="Invalid pagination, filters, or date range")
    def get(self, args):
        """List articles, newest publication first.

        Date bounds require a timezone. Unknown publication dates appear last.
        Search matches literal title or description text, case insensitively.
        """
        statement = select(Article)
        if "section" in args:
            statement = statement.where(Article.section == args["section"])
        if "q" in args:
            statement = statement.where(
                Article.title.icontains(args["q"], autoescape=True)
                | Article.description.icontains(args["q"], autoescape=True)
            )
        if "published_from" in args:
            statement = statement.where(Article.published_at >= args["published_from"])
        if "published_to" in args:
            statement = statement.where(Article.published_at < args["published_to"])
        statement = statement.order_by(Article.published_at.desc().nulls_last(), Article.id.desc())
        page = db.paginate(statement, page=args["page"], per_page=args["per_page"], error_out=False)
        return {
            "items": page.items,
            "page": page.page,
            "per_page": page.per_page,
            "total": page.total,
            "pages": page.pages,
        }


@articles.route("/<int:article_id>")
class ArticleDetail(MethodView):
    @articles.alt_response(503, description="Database unavailable")
    @articles.response(200, ArticleSchema)
    @articles.alt_response(404, description="Article not found")
    def get(self, article_id):
        """Retrieve a stored article by its API ID."""
        article = db.session.get(Article, article_id)
        if not article:
            abort(404, message="Article not found")
        return article


@runs.route("")
class Runs(MethodView):
    @runs.doc(security=[{"BearerAuth": []}])
    @runs.arguments(RunQuery, location="query", unknown=RAISE)
    @runs.response(200, RunSchema(many=True))
    @runs.alt_response(401, description="Missing or invalid bearer token")
    @runs.alt_response(503, description="Administration is not configured or database unavailable")
    @runs.alt_response(422, description="Invalid limit")
    @require_token
    def get(self, args):
        """List recent completed scrape attempts."""
        return db.session.scalars(
            select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(args["limit"])
        ).all()

    @runs.doc(security=[{"BearerAuth": []}])
    @runs.response(
        201,
        RunSchema,
        headers={"Location": {"description": "Created run URL", "schema": {"type": "string"}}},
    )
    @runs.alt_response(401, description="Missing or invalid bearer token")
    @runs.alt_response(409, description="Another scrape holds the PostgreSQL transaction lock")
    @runs.alt_response(503, description="Administration is not configured or database unavailable")
    @require_token
    def post(self):
        """Create and execute a bounded scrape run synchronously.

        No request body. Returns after completion (normally within 90 seconds).
        A created run can be succeeded, partial, or failed; inspect status and
        counters even on HTTP 201. At most 40 article requests per run.
        """
        try:
            run = collect()
        except RunInProgress:
            abort(409, message="Another scrape run is in progress")
        return run, 201, {"Location": url_for("scrape_runs.RunDetail", run_id=run.id)}


@runs.route("/<int:run_id>")
class RunDetail(MethodView):
    @runs.doc(security=[{"BearerAuth": []}])
    @runs.response(200, RunSchema)
    @runs.alt_response(401, description="Missing or invalid bearer token")
    @runs.alt_response(404, description="Run not found")
    @runs.alt_response(503, description="Administration is not configured or database unavailable")
    @require_token
    def get(self, run_id):
        """Retrieve the result of a scrape attempt."""
        run = db.session.get(ScrapeRun, run_id)
        if not run:
            abort(404, message="Scrape run not found")
        return run


@health.route("/health")
class Health(MethodView):
    @health.response(200, HealthSchema)
    @health.alt_response(
        503, schema=HealthSchema, description="Database is unavailable or migrations are missing"
    )
    def get(self):
        """Check database connectivity and article table readiness."""
        try:
            db.session.execute(text("SELECT id FROM article LIMIT 1"))
        except SQLAlchemyError:
            db.session.rollback()
            return {"status": "unavailable"}, 503
        return {"status": "ok"}


@health.route("/")
class Explorer(MethodView):
    @health.response(200, content_type="text/html")
    def get(self):
        """Open the browser-based API test website."""
        from flask import make_response, render_template

        return make_response(render_template("index.html"))
