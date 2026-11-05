import pytest
from pydantic import BaseModel

from services.platform.config import Settings
from services.platform.egress.client import EgressChatClient, ModelRequest, ModelUnavailable
from services.platform.egress.providers import (
    LOCAL_PLACEHOLDER,
    FakeChatModel,
    FallbackChatModel,
    build_chat_model,
    build_model_routes,
)
from services.platform.phi.recognizers import verhoeff_check_digit
from services.platform.phi.scrubber import BlockedIdentifier, EgressBlocked


class Answer(BaseModel):
    answer: str
    citation_ids: list[str]


async def test_chat_egress_tokenises_before_model_and_reidentifies_after():
    model = FakeChatModel(response="Tell <PERSON_1> to review HbA1c.")
    client = EgressChatClient(model)

    out = await client.ask(
        ModelRequest(
            system="You answer records questions.",
            user="Patient Neha Kulkarni asks about HbA1c.",
            purpose="records_qa",
        )
    )

    assert model.seen_messages[0][1]["content"] == "Patient <PERSON_1> asks about HbA1c."
    assert out.text == "Tell Neha Kulkarni to review HbA1c."
    assert out.tokenised_entities == ["PERSON"]


async def test_chat_egress_blocks_aadhaar_before_model_call():
    model = FakeChatModel()
    client = EgressChatClient(model)
    aadhaar = "23412341234" + verhoeff_check_digit("23412341234")

    with pytest.raises(BlockedIdentifier):
        await client.ask(
            ModelRequest(
                system="You answer records questions.",
                user=f"My Aadhaar is {aadhaar}.",
                purpose="records_qa",
            )
        )

    assert model.seen_messages == []


async def test_chat_egress_fails_closed_on_model_identifier_leak():
    client = EgressChatClient(FakeChatModel(response="Call 9876543210."))

    with pytest.raises(EgressBlocked):
        await client.ask(
            ModelRequest(system="You answer records questions.", user="HbA1c 6.8", purpose="records_qa")
        )


async def test_structured_egress_round_trips_nested_text():
    model = FakeChatModel(structured={"answer": "<PERSON_1> should review chunk c1.", "citation_ids": ["c1"]})
    client = EgressChatClient(model)

    out = await client.ask_structured(
        ModelRequest(
            system="Return JSON.",
            user="Patient Neha Kulkarni asks about LDL.",
            purpose="records_qa",
        ),
        Answer,
    )

    assert out.answer == "Neha Kulkarni should review chunk c1."
    assert out.citation_ids == ["c1"]
    assert model.seen_messages[0][1]["content"] == "Patient <PERSON_1> asks about LDL."


def test_fake_provider_is_not_allowed_in_prod():
    with pytest.raises(ValueError, match="chat_provider=fake"):
        Settings(env="prod", auth_mode="oidc")


def test_real_provider_requires_api_key_when_built():
    settings = Settings(chat_provider="gemini", chat_model="gemini-2.5-flash")

    with pytest.raises(ValueError, match="MEDPAL_CHAT_API_KEY"):
        build_chat_model(settings)


# ---- degradation and the local fake model -----------------------------------------------------


class _CitationAnswer(BaseModel):
    answer: str
    citation_ids: list[str] = []


class _Soap(BaseModel):
    subjective: str
    plan: str
    medicines: list[str] = []


class _BrokenModel(FakeChatModel):
    def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
        raise TimeoutError("provider timed out")


async def test_invalid_structured_output_becomes_model_unavailable():
    client = EgressChatClient(FakeChatModel(structured={"unexpected": 1}))
    with pytest.raises(ModelUnavailable) as exc:
        await client.ask_structured(ModelRequest(system="s", user="u", purpose="t"), _CitationAnswer)
    assert exc.value.reason == "model_output_invalid"


async def test_provider_errors_become_model_unavailable():
    client = EgressChatClient(_BrokenModel())
    with pytest.raises(ModelUnavailable) as exc:
        await client.ask_structured(ModelRequest(system="s", user="u", purpose="t"), _CitationAnswer)
    assert exc.value.reason == "model_call_failed"


async def test_local_fake_quotes_and_cites_the_top_passage():
    prompt = (
        "Question: LDL?\n\nContext:\n[C1] document=x page=1\nLDL 162 mg/dL"
        "\n\n[C2] document=y page=2\nHbA1c 6.8"
    )
    out = await EgressChatClient(FakeChatModel()).ask_structured(
        ModelRequest(system="s", user=prompt, purpose="t"), _CitationAnswer
    )
    assert out.citation_ids == ["C1"]
    assert out.answer == "From your record: LDL 162 mg/dL"


async def test_local_fake_never_invents_content_for_other_schemas():
    out = await EgressChatClient(FakeChatModel()).ask_structured(
        ModelRequest(system="s", user="Doctor: start a statin.", purpose="t"), _Soap
    )
    assert out.subjective == LOCAL_PLACEHOLDER and out.plan == LOCAL_PLACEHOLDER
    assert out.medicines == []


# ---- routing and fallback ------------------------------------------------------------------


class _Raises(FakeChatModel):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        raise ConnectionError("primary down")

    def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise ConnectionError("primary down")


async def test_fallback_answers_when_the_primary_errors():
    primary, backup = _Raises(), FakeChatModel(response="from backup")
    chain = FallbackChatModel([("primary", primary), ("backup", backup)])
    out = await EgressChatClient(chain).ask(ModelRequest(system="s", user="u", purpose="t"))
    assert out.text == "from backup" and chain.last_used == "backup" and primary.calls == 1


async def test_fallback_answers_when_the_primary_returns_invalid_structure():
    bad = FakeChatModel(structured={"unexpected": 1})
    good = FakeChatModel(structured={"answer": "ok", "citation_ids": ["C1"]})
    chain = FallbackChatModel([("bad", bad), ("good", good)])
    out = await EgressChatClient(chain).ask_structured(
        ModelRequest(system="s", user="u", purpose="t"), _CitationAnswer
    )
    assert out.citation_ids == ["C1"] and chain.last_used == "good"


async def test_all_models_failing_is_model_unavailable():
    chain = FallbackChatModel([("a", _Raises()), ("b", _Raises())])
    with pytest.raises(ModelUnavailable):
        await EgressChatClient(chain).ask_structured(
            ModelRequest(system="s", user="u", purpose="t"), _CitationAnswer
        )


async def test_small_tier_routes_to_the_small_model():
    small, large = FakeChatModel(response="small"), FakeChatModel(response="large")
    client = EgressChatClient(large, routes={"small": small, "large": large})
    assert (await client.ask(ModelRequest(system="s", user="u", purpose="t", tier="small"))).text == "small"
    assert (await client.ask(ModelRequest(system="s", user="u", purpose="t"))).text == "large"


def test_routes_build_from_configuration():
    settings = Settings(
        chat_provider="fake",
        chat_small_model="tiny",
        chat_fallback_provider="fake",
        chat_fallback_model="backup",
    )
    routes = build_model_routes(settings)
    assert set(routes) == {"small", "large"}
    assert [name for name, _ in routes["small"].models] == ["fake:tiny", "fake:backup"]
    with pytest.raises(ValueError):
        Settings(chat_fallback_provider="fake")  # a fallback provider needs a model
