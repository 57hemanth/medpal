"""LangChain provider factory for hosted generation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from services.platform.config import Settings

Structured = TypeVar("Structured", bound=BaseModel)


class FakeChatModel:
    """Deterministic test double that preserves the LangChain shape we use."""

    def __init__(self, response: str = "ok", structured: Mapping[str, Any] | None = None) -> None:
        self.response = response
        self.structured = dict(structured or {})
        self.seen_messages: list[list[dict[str, str]]] = []

    async def ainvoke(self, messages: list[dict[str, str]]) -> str:
        self.seen_messages.append(messages)
        return self.response

    def with_structured_output(self, schema: type[Structured]) -> FakeStructuredChatModel[Structured]:
        return FakeStructuredChatModel(self, schema)


class FakeStructuredChatModel[Structured: BaseModel]:
    def __init__(self, model: FakeChatModel, schema: type[Structured]) -> None:
        self._model = model
        self._schema = schema

    async def ainvoke(self, messages: list[dict[str, str]]) -> Structured:
        self._model.seen_messages.append(messages)
        data = self._model.structured or _local_default(self._schema, messages)
        return self._schema.model_validate(data)


LOCAL_PLACEHOLDER = "[local fake model: set MEDPAL_CHAT_PROVIDER for real output]"
_FIRST_CHUNK = re.compile(r"\[C1\][^\n]*\n(?P<text>.*?)(?=\n\n\[C\d+\]|\Z)", re.DOTALL)


def _local_default(schema: type[BaseModel], messages: list[dict[str, str]]) -> dict[str, Any]:
    """Schema-valid output for local development without a hosted model.

    Citation answers are extractive: they quote the top retrieved passage and cite it, so the records
    flow works end to end and every word shown is from the patient's own record. Other schemas get
    clearly labelled placeholders (empty lists, never invented content such as medicines).
    """
    fields = schema.model_fields
    if "citation_ids" in fields and "answer" in fields:
        prompt = messages[-1]["content"] if messages else ""
        match = _FIRST_CHUNK.search(prompt)
        if not match:
            return {"answer": LOCAL_PLACEHOLDER, "citation_ids": []}
        quoted = " ".join(match.group("text").split())[:300]
        return {"answer": f"From your record: {quoted}", "citation_ids": ["C1"]}
    data: dict[str, Any] = {}
    for name, info in fields.items():
        if not info.is_required():
            continue
        annotation = str(info.annotation)
        if info.annotation is str:
            data[name] = LOCAL_PLACEHOLDER
        elif annotation.startswith("list"):
            data[name] = []
        elif info.annotation is bool:
            data[name] = False
        elif info.annotation in (int, float):
            data[name] = 0
    return data


def _require_api_key(settings: Settings) -> str:
    if not settings.chat_api_key:
        raise ValueError(f"MEDPAL_CHAT_API_KEY is required for {settings.chat_provider}")
    return settings.chat_api_key


def build_chat_model(settings: Settings) -> Any:
    """Build a LangChain chat model from explicit configuration.

    Provider imports stay inside this module so application code depends on the
    LangChain chat-model surface, not on vendor SDKs.
    """

    match settings.chat_provider:
        case "fake":
            return FakeChatModel()
        case "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI as ChatGoogleGenerativeAI

            gemini_model = cast(Any, ChatGoogleGenerativeAI)
            return gemini_model(
                model=settings.chat_model,
                google_api_key=_require_api_key(settings),
                temperature=settings.chat_temperature,
            )
        case "openai":
            from langchain_openai import ChatOpenAI

            openai_model = cast(Any, ChatOpenAI)
            return openai_model(
                model=settings.chat_model,
                api_key=_require_api_key(settings),
                temperature=settings.chat_temperature,
            )
        case "openai-compatible":
            if not settings.chat_base_url:
                raise ValueError("MEDPAL_CHAT_BASE_URL is required for openai-compatible")
            from langchain_openai import ChatOpenAI

            compatible_model = cast(Any, ChatOpenAI)
            return compatible_model(
                model=settings.chat_model,
                api_key=_require_api_key(settings),
                base_url=settings.chat_base_url,
                temperature=settings.chat_temperature,
            )
        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            anthropic_model = cast(Any, ChatAnthropic)
            return anthropic_model(
                model_name=settings.chat_model,
                api_key=_require_api_key(settings),
                temperature=settings.chat_temperature,
            )
    raise ValueError(f"unsupported chat provider: {cast(str, settings.chat_provider)}")
