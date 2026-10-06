from alembic import context

from database.base import Base, UTCDateTime
import database.models  # noqa: F401 -- register all tables
from database.session import build_engine, database_url


config = context.config
target_metadata = Base.metadata


def render_item(kind, obj, autogen_context):
    if kind == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def configure(connection=None, url=None):
    context.configure(connection=connection, url=url, target_metadata=target_metadata,
                      compare_type=True, render_item=render_item,
                      literal_binds=connection is None,
                      dialect_opts={"paramstyle": "named"} if connection is None else {})
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    configure(url=config.attributes.get("database_url") or database_url())
else:
    provided = config.attributes.get("connection")
    if provided is not None:
        configure(connection=provided)
    else:
        engine = build_engine(config.attributes.get("database_url") or database_url())
        with engine.connect() as connection:
            configure(connection=connection)
        engine.dispose()
