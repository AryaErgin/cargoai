import os
from contextlib import contextmanager
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def database_url():
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed.render_as_string(hide_password=False)


def build_engine(url):
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    options = {"pool_pre_ping": True}
    if parsed.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if parsed.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
    elif parsed.get_backend_name() == "postgresql":
        options["connect_args"] = {"connect_timeout": 5, "options": "-c timezone=UTC"}
    engine = create_engine(parsed, **options)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


@lru_cache(maxsize=1)
def get_engine():
    return build_engine(database_url())


@contextmanager
def session_scope(engine=None):
    """Infrastructure unit of work. Tenant business access belongs in repositories."""
    with Session(engine if engine is not None else get_engine(), expire_on_commit=False) as session:
        with session.begin():
            yield session


@event.listens_for(Session, "before_flush")
def preserve_rate_history(session, flush_context, instances):
    from database.models import RateSheet, Rate, RateCharge, ExchangeRate, RateEvent
    historical_types = (RateSheet, Rate, RateCharge, ExchangeRate, RateEvent)
    for row in session.new:
        if isinstance(row, Rate):
            if row.status is None:
                row.status = "ARCHIVED" if row.is_active is False else "ACTIVE"
            row.is_active = row.status == "ACTIVE"
    for row in session.deleted:
        if isinstance(row, historical_types):
            raise ValueError("Rate history is append-only; create a new version instead")
    for row in session.dirty:
        if hasattr(row, "tenant_id") and inspect(row).attrs.tenant_id.history.has_changes():
            raise ValueError("Business row tenant ownership cannot be changed")
        if isinstance(row, historical_types) and session.is_modified(row, include_collections=False):
            changed = {attr.key for attr in inspect(row).attrs if attr.history.has_changes()}
            allowed = session.info.get("_rate_management_writes", {}).get(id(row), set())
            if not changed <= allowed:
                raise ValueError("Rate history is append-only; create a new version instead")


@event.listens_for(Session, "do_orm_execute")
def reject_historical_bulk_changes(state):
    if state.is_update or state.is_delete:
        table = getattr(state.statement, "table", None)
        if table is not None and table.name in {"rates", "rate_sheets", "rate_charges", "exchange_rates", "rate_events"}:
            raise ValueError("Rate history is append-only; create a new version instead")
