"""Mobile sign-in pieces that need no database: numbers, signed tokens, and how identity is resolved."""

import time

import pytest

from services.platform import signin
from services.platform.config import Settings
from services.platform.identity import IdentityError, resolve_identity

SETTINGS = Settings(_env_file=None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("98200 00001", "+919820000001"),
        ("+91 98200-00001", "+919820000001"),
        ("09820000001", "+919820000001"),
        ("919820000001", "+919820000001"),
        ("+447700900123", "+447700900123"),
    ],
)
def test_numbers_are_normalised(raw, expected):
    assert signin.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "5820000001", "abc", "", "+0123"])
def test_bad_numbers_are_refused(raw):
    with pytest.raises(signin.SignInError):
        signin.normalize_phone(raw)


def test_a_session_round_trips_and_a_tampered_one_is_refused():
    auth = {"user_id": "u1", "role": "patient", "acting_for_patient_id": "p1"}
    token = signin.session_token(auth, SETTINGS)  # type: ignore[arg-type]
    assert signin.auth_from_session(token, SETTINGS) == auth
    body, mac = token.split(".")
    forged = signin.sign(
        {"purpose": "session", "u": "u1", "r": "compliance", "p": None, "exp": 9e9}, SETTINGS
    )
    with pytest.raises(signin.SignInError):  # someone else's signature over the same claims
        signin.auth_from_session(forged.split(".")[0] + "." + mac, SETTINGS)
    with pytest.raises(signin.SignInError):  # changed claims, original signature
        signin.auth_from_session(forged.split(".")[0] + "." + token.split(".")[1], SETTINGS)


def test_expired_and_wrong_purpose_tokens_are_refused():
    expired = signin.sign({"purpose": "session", "u": "u", "r": "patient", "exp": time.time() - 1}, SETTINGS)
    registration = signin.sign(
        {"purpose": "register", "ph": "+919820000001", "exp": time.time() + 60}, SETTINGS
    )
    for token in (expired, registration):
        with pytest.raises(signin.SignInError):
            signin.auth_from_session(token, SETTINGS)


def test_identity_comes_from_the_session_cookie_before_any_header():
    token = signin.session_token(
        {"user_id": "u1", "role": "patient", "acting_for_patient_id": "p1"}, SETTINGS
    )  # type: ignore[arg-type]
    headers = {
        "cookie": f"{signin.COOKIE}={token}",
        "X-Dev-User-Id": "someone-else",
        "X-Dev-Role": "compliance",
    }
    assert resolve_identity(headers, SETTINGS)["user_id"] == "u1"


def test_otp_mode_never_trusts_dev_headers():
    otp = Settings(_env_file=None, auth_mode="otp")
    with pytest.raises(IdentityError):
        resolve_identity({"X-Dev-User-Id": "u", "X-Dev-Role": "compliance"}, otp)


def test_production_needs_a_real_secret_and_sms_gateway_for_mobile_sign_in():
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(
            _env_file=None, env="prod", auth_mode="otp", chat_provider="openai", object_store_backend="s3"
        )
    with pytest.raises(ValueError, match="SMS provider"):
        Settings(
            _env_file=None,
            env="prod",
            auth_mode="otp",
            session_secret="x" * 40,
            chat_provider="openai",
            object_store_backend="s3",
        )
