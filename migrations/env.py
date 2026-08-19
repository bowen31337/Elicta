"""Alembic environment for the Elicta service tier.

The 20 revisions in `versions/` describe the full schema and form one linear
chain, but there was no `alembic.ini` and no `env.py`, so none of them could
be run. This is that missing harness.

`target_metadata` is `None` on purpose: there are no SQLAlchemy models yet,
so `--autogenerate` is not supported. Every revision here is hand-written,
which is what the chain already assumes. When ORM models land, point
`target_metadata` at their `MetaData` and autogenerate starts working with
no other change.

Both modes are supported:

* offline (`alembic upgrade head --sql`) emits SQL without connecting, which
  is how the chain is validated in CI without a database.
* online connects with `asyncpg`, the driver the service already depends on.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM models yet — see the module docstring.
target_metadata = None

DEFAULT_DATABASE_URL = "postgresql+asyncpg://localhost/elicta"


def database_url() -> str:
    """The URL to migrate, from `DATABASE_URL` or the local default.

    Read here rather than from `alembic.ini` so a live credential never has
    to be written into a tracked file.
    """

    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def run_migrations_offline() -> None:
    """Emit SQL for the whole chain without connecting to anything."""

    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply the chain against the configured database."""

    config.set_main_option("sqlalchemy.url", database_url())

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
