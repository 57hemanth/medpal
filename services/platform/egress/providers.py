"""LangChain provider factory for hosted generation."""

from __future__ import annotations

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
        return self._schema.model_validate(self._model.structured)


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
