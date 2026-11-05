"""The model step inside triage: one call, wrapped in code that decides what it may do.

`assess` runs once per triage pass, after the patient has answered the safety questions, and returns:
* extra red flags: a second pass after the rules. It may only ADD emergencies; it can never clear one;
* a specialty guess: used only when the specialty rules are unsure. It must be a specialty MedPal books
  into, with a confidence; below the threshold the patient gets one clarifying question instead.

One combined call (not two) because every call slows the provider for everyone under load. It goes
through the egress client (de-identified, traced, fallback) and has a short deadline of its own: if the
model is slow or down, triage continues on the rules and the patient's explicit safety answers, which is
the fully tested rules-only behaviour.
"""

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from services.platform.egress.client import EgressChatClient, ModelRequest
from services.platform.tracing import Span, capture_model_calls, replay_model_calls

from .specialties import SPECIALTIES, canonical_specialty

log = logging.getLogger(__name__)

RedFlagCategory = Literal[
    "chest_pain", "breathing", "unconscious", "stroke", "bleeding", "poisoning", "self_harm"
]
SPECIALTY_CONFIDENCE_MIN = 0.6

RED_FLAG_SYSTEM = (
    "You are the safety check of a clinic booking assistant. Read the patient's message and list which "
    "of these emergencies it describes as happening now or very recently: "
    "chest_pain (chest pain, pressure or tightness; a possible heart attack), "
    "breathing (severe difficulty breathing, choking, blue lips), "
    "unconscious (fainting, a fit or seizure, someone who won't wake up or respond), "
    "stroke (sudden one-sided weakness or numbness, a drooping face, slurred speech), "
    "bleeding (heavy bleeding that won't stop, vomiting or coughing up blood, black stools), "
    "poisoning (swallowed poison or chemicals, an overdose), "
    "self_harm (thoughts or acts of self-harm or suicide). "
    "Do not list something the patient clearly says they do not have, or an episode long past that has "
    "fully resolved. If you are unsure whether an emergency is present now, list it. "
    "Return an empty list when none apply. Never diagnose."
)
SPECIALTY_SYSTEM = (
    "You route a patient to an outpatient specialty. From the allowed list only, choose the single best "
    "specialty for the symptoms described, optionally one alternative, and your confidence from 0 to 1. "
    "Use a low confidence when the message is vague. Never diagnose.\n\nAllowed specialties: "
    + ", ".join(SPECIALTIES)
)


class RedFlagAssessment(BaseModel):
    flags: list[RedFlagCategory] = Field(default_factory=list)


class SpecialtyAssessment(BaseModel):
    specialty: str
    alternative: str | None = None
    confidence: float = Field(ge=0, le=1)


class TriageAssessment(BaseModel):
    """The combined answer: red flags (may be empty) and the specialty fields."""

    flags: list[RedFlagCategory] = Field(default_factory=list)
    specialty: str = ""
    alternative: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)


TRIAGE_SYSTEM = (
    "Do two things with the patient's message.\n1. Safety: "
    + RED_FLAG_SYSTEM
    + "\n2. Routing: "
    + SPECIALTY_SYSTEM
)


@dataclass(frozen=True)
class SpecialtyGuess:
    specialty: str
    alternative: str | None
    confidence: float


@dataclass(frozen=True)
class Assessment:
    red_flags: list[str]
    specialty: SpecialtyGuess | None
    skipped: str | None = None  # why the model added nothing ("timeout", "unavailable"), for the trace


class TriageAssessor(Protocol):
    def prefetch(self, key: str, text: str) -> None:
        """Start assessing in the background (e.g. while the patient answers the safety questions)."""
        ...

    async def assess(self, text: str, *, key: str | None = None) -> Assessment: ...


_Checked = tuple[TriageAssessment, list[Span]]


class ModelAssessor:
    MAX_PENDING = 2_000  # bounded: a prefetch nobody collects is dropped, oldest first
    PENDING_TTL_SECONDS = 15 * 60

    def __init__(self, chat: EgressChatClient, *, tier: str = "small", deadline_seconds: float = 4.0) -> None:
        self._chat = chat
        self._tier = tier
        self._deadline = deadline_seconds
        # (run key, text digest) -> background call. In-process only: a resume on another instance just
        # makes the call live, under the same deadline.
        self._pending: OrderedDict[tuple[str, str], tuple[float, asyncio.Task[_Checked]]] = OrderedDict()

    def prefetch(self, key: str, text: str) -> None:
        now = time.monotonic()
        while self._pending and (
            len(self._pending) >= self.MAX_PENDING
            or now - next(iter(self._pending.values()))[0] > self.PENDING_TTL_SECONDS
        ):
            _, (_, stale) = self._pending.popitem(last=False)
            stale.cancel()
        task = asyncio.ensure_future(self._call(text))
        task.add_done_callback(_consume_quietly)  # an abandoned prefetch must not log "never retrieved"
        self._pending[(key, _digest(text))] = (now, task)

    async def _call(self, text: str) -> _Checked:
        # Captured, then replayed into the run that uses the result: a prefetch started by one request
        # and consumed by the next is metered once, by the consumer.
        with capture_model_calls() as spans:
            result = await self._chat.ask_structured(
                ModelRequest(system=TRIAGE_SYSTEM, user=text, purpose="triage check", tier=self._tier),
                TriageAssessment,
            )
        return result, spans

    async def assess(self, text: str, *, key: str | None = None) -> Assessment:
        """The deadline counts only the time still to wait: a prefetched call has usually finished."""
        entry = self._pending.pop((key, _digest(text)), None) if key else None
        pending: asyncio.Task[_Checked] = entry[1] if entry else asyncio.ensure_future(self._call(text))
        try:
            result, spans = await asyncio.wait_for(pending, self._deadline)
            replay_model_calls(spans)
        except TimeoutError:
            log.warning("triage check skipped: over %.1fs", self._deadline)
            return Assessment([], None, skipped="timeout")
        except Exception as exc:  # noqa: BLE001  the rules and the safety answers still stand
            log.warning("triage check unavailable: %s", type(exc).__name__)
            return Assessment([], None, skipped="unavailable")
        return Assessment(
            red_flags=sorted({f"redflag_{flag}" for flag in result.flags}),
            specialty=_guess(result.specialty, result.alternative, result.confidence),
        )


def _consume_quietly(task: "asyncio.Task[_Checked]") -> None:
    if not task.cancelled():
        task.exception()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _guess(specialty_name: str, alternative_name: str | None, confidence: float) -> SpecialtyGuess | None:
    specialty = canonical_specialty(specialty_name)
    if specialty is None:
        return None  # not a specialty we book into: never guess a doctor from it
    alternative = canonical_specialty(alternative_name)
    return SpecialtyGuess(
        specialty=specialty,
        alternative=alternative if alternative != specialty else None,
        confidence=confidence,
    )
