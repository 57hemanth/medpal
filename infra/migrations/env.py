"""Alembic environment. Migrations are hand-written SQL (op.execute): the schema is the
contract (docs/data-contracts), so we keep it explicit rather than generated from ORM models."""

from alembic import context
from sqlalchemy import create_engine

from services.platform.config import get_settings


def run_migrations_online() -> None:
    engine = create_engine(get_settings().sqlalchemy_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=get_settings().sqlalchemy_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
