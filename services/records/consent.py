"""Consent lifecycle operations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from psycopg_pool import AsyncConnectionPool

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped


@dataclass(frozen=True)
class ConsentGrant:
    consent_id: str
    patient_id: str
    grantee_user_id: str
    scope: list[str]
    purpose: str
    expires_at: datetime
    revoked_at: datetime | None


async def list_consents(pool: AsyncConnectionPool, auth: AuthContext) -> list[ConsentGrant]:
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT consent_id::text, patient_id::text, grantee_user_id::text,"
                " scope, purpose, expires_at, revoked_at"
                " FROM consent ORDER BY granted_at DESC"
            )
        ).fetchall()
    return [ConsentGrant(**cast(dict[str, Any], row)) for row in rows]


async def grant_consent(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    patient_id: str,
    grantee_user_id: str,
    scope: list[str],
    purpose: str,
    expires_at: datetime,
) -> ConsentGrant:
    if auth["role"] != "patient" or auth["acting_for_patient_id"] != patient_id:
        raise PermissionError("only the patient can grant consent")
    async with scoped(pool, auth) as conn:
        row = await (
            await conn.execute(
                "INSERT INTO consent (patient_id, grantee_user_id, scope, purpose, granted_by, expires_at)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " RETURNING consent_id::text, patient_id::text, grantee_user_id::text,"
                " scope, purpose, expires_at, revoked_at",
                (patient_id, grantee_user_id, scope, purpose, auth["user_id"], expires_at),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("consent insert returned no row")
        row_dict = cast(dict[str, Any], row)
        await audit.write(
            conn,
            auth,
            action="grant",
            resource="consent",
            record_id=str(row_dict["consent_id"]),
            patient_id=patient_id,
            purpose=purpose,
        )
    return ConsentGrant(**row_dict)


async def revoke_consent(pool: AsyncConnectionPool, auth: AuthContext, *, consent_id: str) -> ConsentGrant:
    if auth["role"] != "patient":
        raise PermissionError("only the patient can revoke consent")
    async with scoped(pool, auth) as conn:
        row = await (
            await conn.execute(
                "UPDATE consent SET revoked_at = now() WHERE consent_id = %s AND revoked_at IS NULL"
                " RETURNING consent_id::text, patient_id::text, grantee_user_id::text,"
                " scope, purpose, expires_at, revoked_at",
                (consent_id,),
            )
        ).fetchone()
        if row is None:
            raise PermissionError("consent is not visible or already revoked")
        row_dict = cast(dict[str, Any], row)
        await audit.write(
            conn,
            auth,
            action="revoke",
            resource="consent",
            record_id=consent_id,
            patient_id=str(row_dict["patient_id"]),
            purpose=str(row_dict["purpose"]),
        )
    return ConsentGrant(**row_dict)
