from marshmallow import Schema, ValidationError, fields, validate, validates_schema


class ArticleSchema(Schema):
    id = fields.Int()
    source_id = fields.Str()
    url = fields.Url()
    title = fields.Str()
    description = fields.Str(allow_none=True)
    body = fields.Str(allow_none=True)
    authors = fields.List(fields.Str())
    section = fields.Str(allow_none=True)
    published_at = fields.DateTime(allow_none=True)
    modified_at = fields.DateTime(allow_none=True)
    first_seen_at = fields.DateTime()
    last_seen_at = fields.DateTime()


class ArticleQuery(Schema):
    page = fields.Int(load_default=1, validate=validate.Range(min=1, max=100000))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))
    section = fields.Str(validate=validate.Length(min=1, max=200))
    q = fields.Str(validate=validate.Length(min=1, max=200))
    published_from = fields.AwareDateTime(
        metadata={"description": "Inclusive ISO 8601 timestamp with timezone."}
    )
    published_to = fields.AwareDateTime(
        metadata={"description": "Exclusive ISO 8601 timestamp with timezone."}
    )

    @validates_schema
    def validate_dates(self, data, **kwargs):
        if (
            data.get("published_from")
            and data.get("published_to")
            and data["published_from"] >= data["published_to"]
        ):
            raise ValidationError("published_from must precede published_to")


class ArticlePage(Schema):
    items = fields.List(fields.Nested(ArticleSchema))
    page = fields.Int()
    per_page = fields.Int()
    total = fields.Int()
    pages = fields.Int()


class RunSchema(Schema):
    id = fields.Int()
    started_at = fields.DateTime()
    finished_at = fields.DateTime(allow_none=True)
    status = fields.Str(validate=validate.OneOf(["running", "succeeded", "partial", "failed"]))
    discovered = fields.Int()
    processed = fields.Int()
    inserted = fields.Int()
    updated = fields.Int()
    failed = fields.Int()
    deferred = fields.Int()
    error = fields.Str(allow_none=True)


class RunQuery(Schema):
    limit = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))


class HealthSchema(Schema):
    status = fields.Str()
