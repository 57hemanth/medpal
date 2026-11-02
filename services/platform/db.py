"""Connection pools. Business queries and LangGraph checkpoints use separate pools so the
checkpointer's tables stay in their own schema (search_path) and never mix with clinical tables."""

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import Settings

# The LangGraph Postgres checkpointer requires autocommit + dict rows; prepare_threshold=0
# avoids prepared-statement clashes behind poolers. We use the same settings for the app
# pool and open explicit transactions where atomicity matters.
_BASE_KWARGS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}


def app_pool(settings: Settings) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        settings.database_url, max_size=settings.db_pool_max_size, kwargs=dict(_BASE_KWARGS), open=False
    )


def checkpoint_pool(settings: Settings) -> AsyncConnectionPool:
    kwargs = dict(_BASE_KWARGS, options=f"-c search_path={settings.checkpoint_schema}")
    return AsyncConnectionPool(settings.database_url, max_size=5, kwargs=kwargs, open=False)
