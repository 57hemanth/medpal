import pytest

from services.platform.oidc import OidcError, context_from_claims


def test_oidc_claims_become_auth_context():
    ctx = context_from_claims({"sub": "user-1", "medpal_role": "patient", "medpal_patient_id": "patient-1"})

    assert ctx == {"user_id": "user-1", "role": "patient", "acting_for_patient_id": "patient-1"}


def test_oidc_claims_require_valid_role():
    with pytest.raises(OidcError):
        context_from_claims({"sub": "user-1", "medpal_role": "admin"})
