"""Mobile-number sign-in for everyone: patients, caregivers and staff.

    start(phone)  -> a 6-digit code is sent (in development it is also returned and logged)
    verify(code)  -> the person's roles, or a registration token if the number is new
    register(...) -> a new patient account for a verified number
    session token -> signed (HMAC-SHA256), carried in an HttpOnly cookie, expires

Codes are stored only as a keyed hash, expire after five minutes, allow five attempts, and each number
may request five codes an hour. Before sign-in there is no user to scope a query to, so this module
works in the system context; it is the only request path that does.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from psycopg_pool import AsyncConnectionPool

from .auth import AuthContext
from .config import Settings
from .db import scoped_system

log = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 5
REGISTRATION_TTL_SECONDS = 10 * 60
COOKIE = "medpal_session"


class SignInError(ValueError):
    """Shown to the person as is: never says whether a number has an account."""


class SmsSender(Protocol):
    async def send(self, phone: str, message: str) -> None: ...


class LogSmsSender:
    """Development only: the message goes to the log. Production must configure a real SMS gateway."""

    async def send(self, phone: str, message: str) -> None:
        log.warning("SMS to %s: %s", phone[:5] + "•••" + phone[-3:], message)


def normalize_phone(raw: str) -> str:
    """'98200 00001', '+91 98200-00001' -> '+919820000001'. Indian mobiles by default; E.164 otherwise."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if re.fullmatch(r"[6-9]\d{9}", digits):
        return "+91" + digits
    if re.fullmatch(r"0[6-9]\d{9}", digits):
        return "+91" + digits[1:]
    if re.fullmatch(r"91[6-9]\d{9}", digits):
        return "+" + digits
    if re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        return digits
    raise SignInError("Enter a valid mobile number")


def mask_phone(phone: str) -> str:
    return phone[:5] + " ••••• " + phone[-3:]


# ---- signed tokens --------------------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict[str, Any], settings: Settings) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(token: str, settings: Settings, *, purpose: str) -> dict[str, Any]:
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            raise ValueError
        payload = cast(dict[str, Any], json.loads(_unb64(body)))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SignInError("Please sign in again") from exc
    if payload.get("purpose") != purpose or payload.get("exp", 0) < time.time():
        raise SignInError("Please sign in again")
    return payload


def session_token(auth: AuthContext, settings: Settings) -> str:
    return sign(
        {
            "purpose": "session",
            "u": auth["user_id"],
            "r": auth["role"],
            "p": auth["acting_for_patient_id"],
            "exp": int(time.time()) + settings.session_hours * 3600,
        },
        settings,
    )


def auth_from_session(token: str, settings: Settings) -> AuthContext:
    payload = unsign(token, settings, purpose="session")
    return AuthContext(user_id=payload["u"], role=payload["r"], acting_for_patient_id=payload.get("p"))


def _code_hash(phone: str, code: str, settings: Settings) -> str:
    return hmac.new(settings.session_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


# ---- the flow ---------------------------------------------------------------------------------------


async def start(
    pool: AsyncConnectionPool, raw_phone: str, settings: Settings, sender: SmsSender
) -> str | None:
    """Send a code. Returns the code only in development, so the demo works without an SMS gateway."""
    phone = normalize_phone(raw_phone)
    code = f"{secrets.randbelow(1_000_000):06d}"
    async with scoped_system(pool) as conn:
        recent = await (
            await conn.execute(
                "SELECT count(*) AS n FROM otp_challenge"
                " WHERE phone = %s AND created_at > now() - interval '1 hour'",
                (phone,),
            )
        ).fetchone()
        if cast(dict[str, Any], recent)["n"] >= MAX_CODES_PER_HOUR:
            raise SignInError("Too many codes requested. Try again in an hour.")
        await conn.execute(
            "INSERT INTO otp_challenge (phone, code_hash, expires_at) VALUES (%s, %s, %s)",
            (phone, _code_hash(phone, code, settings), datetime.now(UTC) + CODE_TTL),
        )
    await sender.send(phone, f"Your MedPal code is {code}. It expires in 5 minutes. Never share it.")
    return code if settings.env == "dev" else None


@dataclass(frozen=True)
class Verified:
    phone: str
    user_id: str | None  # None: a new number, which must register first
    registration_token: str | None = None


async def verify(pool: AsyncConnectionPool, raw_phone: str, code: str, settings: Settings) -> Verified:
    phone = normalize_phone(raw_phone)
    # Decide inside the transaction, raise after it: an error raised inside would roll back the attempt
    # count, and wrong codes would never be counted (found by test_a_code_works_once_...).
    failure: str | None = None
    user: Any = None
    async with scoped_system(pool) as conn:
        row = await (
            await conn.execute(
                "SELECT challenge_id::text, code_hash, expires_at, attempts FROM otp_challenge"
                " WHERE phone = %s AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
                (phone,),
            )
        ).fetchone()
        challenge = cast(dict[str, Any] | None, row)
        if challenge is None or challenge["expires_at"] < datetime.now(UTC):
            failure = "That code is not right or has expired. Request a new one."
        elif challenge["attempts"] >= MAX_ATTEMPTS:
            failure = "Too many attempts. Request a new code."
        elif not hmac.compare_digest(challenge["code_hash"], _code_hash(phone, code.strip(), settings)):
            await conn.execute(
                "UPDATE otp_challenge SET attempts = attempts + 1 WHERE challenge_id = %s",
                (challenge["challenge_id"],),
            )
            failure = "That code is not right or has expired. Request a new one."
        else:
            await conn.execute(
                "UPDATE otp_challenge SET consumed_at = now() WHERE challenge_id = %s",
                (challenge["challenge_id"],),
            )
            user = await (await conn.execute("SELECT app_user_for_phone(%s) AS id", (phone,))).fetchone()
    if failure:
        raise SignInError(failure)
    user_id = cast(dict[str, Any], user)["id"]
    has_own_record = user_id is not None and await _is_patient_or_staff(pool, str(user_id))
    if user_id is not None and has_own_record:
        return Verified(phone, str(user_id))
    # New number, or invited only as someone's caregiver: they may register their own patient record,
    # or continue as a caregiver. Either way the number is now verified.
    token = sign(
        {
            "purpose": "register",
            "ph": phone,
            "u": str(user_id) if user_id else None,
            "exp": int(time.time()) + REGISTRATION_TTL_SECONDS,
        },
        settings,
    )
    return Verified(phone, str(user_id) if user_id else None, token)


async def _is_patient_or_staff(pool: AsyncConnectionPool, user_id: str) -> bool:
    async with scoped_system(pool) as conn:
        row = await (
            await conn.execute("SELECT role FROM app_user WHERE user_id = %s", (user_id,))
        ).fetchone()
    return row is not None and cast(dict[str, Any], row)["role"] != "caregiver"


async def register(
    pool: AsyncConnectionPool,
    registration_token: str,
    *,
    name: str,
    dob: str | None,
    city: str | None,
    settings: Settings,
) -> str:
    """Create the patient record for a verified number (upgrading an invited caregiver account)."""
    payload = unsign(registration_token, settings, purpose="register")
    name = " ".join(name.split())
    if not 2 <= len(name) <= 120:
        raise SignInError("Enter your full name")
    async with scoped_system(pool) as conn:
        # The id is made here: the patient read rule can't see a row inside its own INSERT ... RETURNING.
        patient_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO patient (patient_id, name, dob, city, phone, synthetic)"
            " VALUES (%s, %s, %s, %s, %s, false)",
            (patient_id, name, dob or None, city or None, payload["ph"]),
        )
        if payload.get("u"):
            await conn.execute(
                "UPDATE app_user SET role = 'patient', patient_id = %s"
                " WHERE user_id = %s AND role = 'caregiver'",
                (patient_id, payload["u"]),
            )
            return str(payload["u"])
        user = await (
            await conn.execute(
                "INSERT INTO app_user (role, patient_id, phone) VALUES ('patient', %s, %s)"
                " RETURNING user_id::text",
                (patient_id, payload["ph"]),
            )
        ).fetchone()
    return cast(dict[str, Any], user)["user_id"]


async def roles_for(pool: AsyncConnectionPool, user_id: str) -> list[AuthContext]:
    """Every way this person may act: their own role, plus caregiver if anyone shared records with them."""
    async with scoped_system(pool) as conn:
        user = cast(
            dict[str, Any] | None,
            await (
                await conn.execute(
                    "SELECT role, patient_id::text FROM app_user WHERE user_id = %s", (user_id,)
                )
            ).fetchone(),
        )
        cared = await (
            await conn.execute(
                "SELECT has_active_consent(%s) AS any",
                (user_id,),
            )
        ).fetchone()
    if user is None:
        return []
    roles: list[AuthContext] = []
    if user["role"] != "caregiver":
        roles.append(
            AuthContext(
                user_id=user_id,
                role=user["role"],
                acting_for_patient_id=user["patient_id"] if user["role"] == "patient" else None,
            )
        )
    if user["role"] == "caregiver" or cast(dict[str, Any], cared)["any"]:
        roles.append(AuthContext(user_id=user_id, role="caregiver", acting_for_patient_id=None))
    return roles


async def profile(pool: AsyncConnectionPool, user_id: str) -> dict[str, Any]:
    """Name and masked number for the account menu."""
    async with scoped_system(pool) as conn:
        row = await (
            await conn.execute(
                "SELECT u.phone, COALESCE(p.name, d.name, u.display_name) AS name"
                " FROM app_user u LEFT JOIN patient p ON p.patient_id = u.patient_id"
                " LEFT JOIN doctor d ON d.doctor_id = u.doctor_id WHERE u.user_id = %s",
                (user_id,),
            )
        ).fetchone()
    data = cast(dict[str, Any] | None, row) or {}
    return {"name": data.get("name"), "phone": mask_phone(data["phone"]) if data.get("phone") else None}
