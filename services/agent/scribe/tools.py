"""Postgres and model-backed implementation of the scribe tools (ScribeTools)."""

from dataclasses import asdict
from typing import Any

from psycopg_pool import AsyncConnectionPool

from services.platform.auth import AuthContext
from services.platform.egress.client import EgressChatClient
from services.scribe.service import SoapDraft, request_draft, sign_note
from services.scribe.stock import PostgresStockSource, StockFlag


class PgScribeTools:
    def __init__(self, pool: AsyncConnectionPool, chat: EgressChatClient) -> None:
        self._pool = pool
        self._chat = chat
        self._stock = PostgresStockSource(pool)

    async def draft(self, *, transcript: str, comments: str | None) -> SoapDraft:
        return await request_draft(self._chat, transcript=transcript, comments=comments)

    async def formulary(self) -> list[str]:
        return await self._stock.formulary_names()

    async def stock(self, auth: AuthContext, *, encounter_id: str, medicines: list[str]) -> list[StockFlag]:
        return await self._stock.flags(auth, encounter_id=encounter_id, medicines=medicines)

    async def sign(
        self,
        auth: AuthContext,
        *,
        encounter_id: str,
        draft: SoapDraft,
        soap: dict[str, Any],
        edit_history: list[dict[str, Any]],
        medicines: list[str],
    ) -> dict[str, Any]:
        signed = await sign_note(
            self._pool,
            auth,
            encounter_id=encounter_id,
            draft=draft,
            edited_soap=soap,
            edit_history=edit_history,
            medicines=medicines,
        )
        return asdict(signed)
