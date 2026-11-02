"""Who is calling, in which role, and on whose behalf.

AuthContext is built by the API from the identity provider and injected into graph state.
Nodes and tools take identities from here, never from model output or request text
(threat model: elevation via prompt injection).
"""

from typing import Literal, TypedDict

Role = Literal["patient", "caregiver", "doctor", "desk", "pharmacist", "compliance"]
ROLES: tuple[Role, ...] = ("patient", "caregiver", "doctor", "desk", "pharmacist", "compliance")


class AuthContext(TypedDict):
    user_id: str
    role: Role
    # The patient this session acts for: the caller themself, or a patient who granted
    # the caller consent. Resolved and consent-checked by the API before any graph runs.
    acting_for_patient_id: str | None
