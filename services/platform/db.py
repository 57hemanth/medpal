"""Connection pools and the per-transaction security context.

Business queries and LangGraph checkpoints use separate pools so the checkpointer's tables stay in
their own schema (search_path) and never mix with clinical tables.

Row-level security: every transaction that touches patient data runs inside `scoped(...)`, which sets
`app.user_id` / `app.role` with SET LOCAL semantics (cleared at commit, so a pooled connection never
carries one caller's identity into the next request). Without it, RLS policies return no rows.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .auth import AuthContext
from .config import Settings

# The LangGraph Postgres checkpointer requires autocommit + dict rows; prepare_threshold=0
# avoids prepared-statement clashes behind poolers. We use the same settings for the app
# pool and open explicit transactions where atomicity matters.
_BASE_KWARGS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}

# Identity used by background workers (ingest, retention jobs). Never issued to an end user:
# AuthContext roles cannot be "system", and only scoped_system() sets it.
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"

_SET_CONTEXT = "SELECT set_config('app.user_id', %s, true), set_config('app.role', %s, true)"


def app_pool(settings: Settings) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        settings.database_url, max_size=settings.db_pool_max_size, kwargs=dict(_BASE_KWARGS), open=False
    )


def checkpoint_pool(settings: Settings) -> AsyncConnectionPool:
    kwargs = dict(_BASE_KWARGS, options=f"-c search_path={settings.checkpoint_schema}")
    return AsyncConnectionPool(settings.database_url, max_size=5, kwargs=kwargs, open=False)


@asynccontextmanager
async def scoped(pool: AsyncConnectionPool, auth: AuthContext) -> AsyncIterator[AsyncConnection]:
    """A transaction acting as `auth`: RLS policies see this caller and role, nothing more."""
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(_SET_CONTEXT, (auth["user_id"], auth["role"]))
        yield conn


@asynccontextmanager
async def scoped_system(pool: AsyncConnectionPool) -> AsyncIterator[AsyncConnection]:
    """A transaction for background workers only (e.g. writing chunks). Never call from a request path."""
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(_SET_CONTEXT, (SYSTEM_USER_ID, "system"))
        yield conn
