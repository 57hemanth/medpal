import pytest

from services.platform.egress import EgressChatClient
from services.platform.egress.providers import FakeChatModel
from services.scribe.service import ScribeReviewNeeded, SoapDraft, content_hash, draft_note


def test_content_hash_is_canonical():
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


async def test_draft_note_requires_medicines_to_appear_in_transcript():
    chat = EgressChatClient(
        FakeChatModel(
            structured={
                "subjective": "Cough",
                "objective": "Normal vitals",
                "assessment": "Viral cough",
                "plan": "Start azithromycin",
                "medicines": ["Azithromycin"],
            }
        )
    )

    with pytest.raises(ScribeReviewNeeded, match="medicine_not_in_transcript"):
        await draft_note(chat, transcript="Patient reports cough for two days.")


async def test_draft_note_accepts_transcript_evidence():
    chat = EgressChatClient(
        FakeChatModel(
            structured={
                "subjective": "Cough",
                "objective": "Normal vitals",
                "assessment": "Viral cough",
                "plan": "Continue paracetamol",
                "medicines": ["paracetamol"],
            }
        )
    )

    draft = await draft_note(chat, transcript="Doctor said continue paracetamol if fever returns.")

    assert isinstance(draft, SoapDraft)
    assert draft.medicines == ["paracetamol"]
