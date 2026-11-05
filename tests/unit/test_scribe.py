from services.platform.egress import EgressChatClient
from services.platform.egress.providers import FakeChatModel
from services.scribe.service import SoapDraft, content_hash, draft_note


def test_content_hash_is_canonical():
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


async def test_draft_note_rejects_medicines_absent_from_the_transcript_and_reports_them():
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

    draft, rejected = await draft_note(chat, transcript="Patient reports cough for two days.")
    assert draft.medicines == []
    assert rejected == ["Azithromycin"]


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

    draft, rejected = await draft_note(chat, transcript="Doctor said continue paracetamol if fever returns.")

    assert isinstance(draft, SoapDraft)
    assert draft.medicines == ["paracetamol"]
    assert rejected == []
