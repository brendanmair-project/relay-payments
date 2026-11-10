"""Alembic environment: migrations run against DATABASE_URL. The first schema arrives in REL-15."""

import os

from alembic import context
from sqlalchemy import create_engine

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=os.environ["DATABASE_URL"], target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
