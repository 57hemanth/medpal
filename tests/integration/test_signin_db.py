"""Mobile sign-in and sharing against real Postgres."""

import uuid

import httpx
import psycopg
import pytest

from services.api.main import create_app
from services.platform import signin
from services.platform.config import get_settings

pytestmark = pytest.mark.integration


class Silent:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, phone: str, message: str) -> None:
        self.sent.append((phone, message))


def _number() -> str:
    return "+9196" + str(uuid.uuid4().int)[:8]


async def test_a_code_works_once_and_wrong_codes_are_capped(pool):
    settings, sms = get_settings(), Silent()
    phone = _number()
    code = await signin.start(pool, phone, settings, sms)
    assert code and code in sms.sent[0][1]
    for _ in range(signin.MAX_ATTEMPTS):
        with pytest.raises(signin.SignInError):
            await signin.verify(pool, phone, "000000" if code != "000000" else "111111", settings)
    with pytest.raises(signin.SignInError):  # capped: even the right code no longer works
        await signin.verify(pool, phone, code, settings)
    code = await signin.start(pool, phone, settings, sms)
    first = await signin.verify(pool, phone, code, settings)
    assert first.user_id is None and first.registration_token  # a new number registers first
    with pytest.raises(signin.SignInError):  # a code is used once
        await signin.verify(pool, phone, code, settings)


async def test_codes_per_number_are_rate_limited(pool):
    settings, sms, phone = get_settings(), Silent(), _number()
    for _ in range(signin.MAX_CODES_PER_HOUR):
        await signin.start(pool, phone, settings, sms)
    with pytest.raises(signin.SignInError, match="Too many"):
        await signin.start(pool, phone, settings, sms)


async def test_the_app_role_cannot_read_codes_outside_the_sign_in_path(pool, world):
    from services.platform.db import scoped

    await signin.start(pool, _number(), get_settings(), Silent())
    auth = {"user_id": world["user"], "role": "patient", "acting_for_patient_id": world["patient"]}
    async with scoped(pool, auth) as conn:  # type: ignore[arg-type]
        rows = await (await conn.execute("SELECT count(*) AS n FROM otp_challenge")).fetchone()
    assert rows["n"] == 0  # type: ignore[index]


async def _sign_in(client: httpx.AsyncClient, phone: str) -> dict:
    code = (await client.post("/api/auth/otp/start", json={"phone": phone})).json()["dev_code"]
    return (await client.post("/api/auth/otp/verify", json={"phone": phone, "code": code})).json()


async def test_sharing_by_number_invites_and_only_the_patient_can_share(admin_url):
    owner_phone, family_phone = _number(), _number()
    patient, user = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, 'Sharer')", (patient,))
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id, phone) VALUES (%s, 'patient', %s, %s)",
            (user, patient, owner_phone),
        )
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://t") as owner,
            httpx.AsyncClient(transport=transport, base_url="http://t") as family,
        ):
            assert (await _sign_in(owner, owner_phone))["role"] == "patient"
            shared = await owner.post(
                "/api/consents/share",
                json={"phone": family_phone, "scope": ["records:read"], "purpose": "family care", "days": 30},
            )
            assert shared.status_code == 201
            listed = (await owner.get("/api/consents")).json()
            assert listed[0]["grantee_name"].endswith(family_phone[-3:])  # masked number until they register
            own = await owner.post(
                "/api/consents/share",
                json={"phone": owner_phone, "scope": ["records:read"], "purpose": "x x", "days": 1},
            )
            assert own.status_code == 400
            joined = await _sign_in(family, family_phone)
            assert joined["role"] == "caregiver" and joined["registration_token"]
            refused = await family.post(
                "/api/consents/share",
                json={"phone": _number(), "scope": ["records:read"], "purpose": "family care", "days": 30},
            )
            assert refused.status_code == 403  # a caregiver can't re-share someone else's record
            assert (await family.get("/api/me")).json()["roles"] == ["caregiver"]
