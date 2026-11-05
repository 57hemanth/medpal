"""LangChain provider factory for hosted generation."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from services.platform.config import Settings

Structured = TypeVar("Structured", bound=BaseModel)
log = logging.getLogger(__name__)


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


Provider = str  # "fake" | "gemini" | "openai" | "openai-compatible" | "anthropic"


def _build_one(
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
    temperature: float,
    *,
    env: str = "MEDPAL_CHAT",
    thinking_level: str | None = None,
    timeout: float | None = None,
    max_retries: int = 1,
) -> Any:
    """One LangChain chat model. Vendor imports stay inside this module, so application code depends on
    the LangChain chat-model surface, never on a vendor SDK."""

    def key() -> str:
        if not api_key:
            raise ValueError(f"{env}_API_KEY is required for {provider}")
        return api_key

    match provider:
        case "fake":
            return FakeChatModel()
        case "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            extra: dict[str, Any] = {}
            if thinking_level:
                extra["thinking_config"] = {"thinking_level": thinking_level}
            return cast(Any, ChatGoogleGenerativeAI)(
                model=model,
                google_api_key=key(),
                temperature=temperature,
                timeout=timeout,
                max_retries=max_retries,
                **extra,
            )
        case "openai":
            from langchain_openai import ChatOpenAI

            return cast(Any, ChatOpenAI)(
                model=model, api_key=key(), temperature=temperature, timeout=timeout, max_retries=max_retries
            )
        case "openai-compatible":
            if not base_url:
                raise ValueError(f"{env}_BASE_URL is required for openai-compatible")
            from langchain_openai import ChatOpenAI

            return cast(Any, ChatOpenAI)(
                model=model,
                api_key=key(),
                base_url=base_url,
                temperature=temperature,
                timeout=timeout,
                max_retries=max_retries,
            )
        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            return cast(Any, ChatAnthropic)(
                model_name=model,
                api_key=key(),
                temperature=temperature,
                timeout=timeout,
                max_retries=max_retries,
            )
    raise ValueError(f"unsupported chat provider: {provider}")


def build_chat_model(settings: Settings) -> Any:
    """The primary (large-tier) model from configuration."""
    return _build_one(
        settings.chat_provider,
        settings.chat_model,
        settings.chat_api_key,
        settings.chat_base_url,
        settings.chat_temperature,
        thinking_level=settings.chat_thinking_level,
        timeout=settings.chat_timeout_seconds,
        max_retries=settings.chat_max_retries,
    )


# What the last call in *this* asyncio task used: (model name, (tokens in, tokens out) or None).
# A ContextVar, not an attribute, so parallel branches sharing one model object never mix their numbers.
_LAST_CALL: ContextVar[tuple[str | None, tuple[int, int] | None]] = ContextVar(
    "medpal_last_model_call", default=(None, None)
)


def _status(exc: BaseException) -> str:
    """The provider's status code, if any: enough to tell an outage from a bad request, never the
    message, which could echo request content."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return f"{type(exc).__name__}({code})" if code else type(exc).__name__


def last_call() -> tuple[str | None, tuple[int, int] | None]:
    return _LAST_CALL.get()


def _usage_of(message: Any) -> tuple[int, int] | None:
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict) and "input_tokens" in usage:
        # Output includes reasoning ("thinking") tokens, which providers bill as output.
        return int(usage["input_tokens"]), int(usage.get("output_tokens", 0))
    return None


class FallbackChatModel:
    """Try each model in order. A provider error, or a structured answer that fails its schema, moves on
    to the next model. Callers see one failure only when every model has failed."""

    def __init__(self, models: list[tuple[str, Any]], *, timeout: float | None = None) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.models = models
        self.timeout = timeout  # per attempt: a hung provider gives the next one its turn
        self.last_used: str | None = None

    async def ainvoke(self, messages: list[dict[str, str]]) -> Any:
        last: Exception | None = None
        for name, model in self.models:
            try:
                result = await asyncio.wait_for(model.ainvoke(messages), self.timeout)
                self.last_used = name
                _LAST_CALL.set((name, _usage_of(result)))
                return result
            except Exception as exc:  # noqa: BLE001 - every provider failure is a reason to try the next
                log.warning("model %s failed: %s", name, _status(exc))
                last = exc
        raise last  # type: ignore[misc]

    def with_structured_output(self, schema: type[Structured]) -> _FallbackStructured[Structured]:
        return _FallbackStructured(self, schema)


class _FallbackStructured[Structured: BaseModel]:
    def __init__(self, chain: FallbackChatModel, schema: type[Structured]) -> None:
        self._chain = chain
        self._schema = schema

    async def ainvoke(self, messages: list[dict[str, str]]) -> Structured:
        last: Exception | None = None
        for name, model in self._chain.models:
            try:
                usage = None
                if isinstance(model, FakeChatModel):
                    raw = await asyncio.wait_for(
                        model.with_structured_output(self._schema).ainvoke(messages), self._chain.timeout
                    )
                else:
                    # include_raw keeps the provider's message, so real token usage (thinking included)
                    # is metered instead of estimated.
                    out = await model.with_structured_output(self._schema, include_raw=True).ainvoke(messages)
                    if out.get("parsing_error") is not None or out.get("parsed") is None:
                        raise ValueError(f"unparseable {self._schema.__name__}")
                    raw, usage = out["parsed"], _usage_of(out.get("raw"))
                data = raw.model_dump() if isinstance(raw, BaseModel) else dict(raw)
                result = self._schema.model_validate(data)
                self._chain.last_used = name
                _LAST_CALL.set((name, usage))
                return result
            except Exception as exc:  # noqa: BLE001 - provider errors and invalid output both fall through
                log.warning("model %s failed for %s: %s", name, self._schema.__name__, _status(exc))
                last = exc
        raise last  # type: ignore[misc]


def build_model_routes(settings: Settings) -> dict[str, Any]:
    """Model routing: `small` for classification-style steps, `large` for drafting and cited answers.
    Each tier is a fallback chain (primary, then the configured fallback provider)."""
    primary_large = build_chat_model(settings)
    primary_small = (
        _build_one(
            settings.chat_provider,
            settings.chat_small_model,
            settings.chat_api_key,
            settings.chat_base_url,
            settings.chat_temperature,
            thinking_level=settings.chat_small_thinking_level or settings.chat_thinking_level,
            timeout=settings.chat_timeout_seconds,
            max_retries=settings.chat_max_retries,
        )
        if settings.chat_small_model
        else primary_large
    )
    fallback = (
        _build_one(
            settings.chat_fallback_provider,
            settings.chat_fallback_model or "",
            # Same provider (e.g. a second Gemini model): reuse the primary key unless one is given.
            settings.chat_fallback_api_key
            or (settings.chat_api_key if settings.chat_fallback_provider == settings.chat_provider else None),
            settings.chat_fallback_base_url,
            settings.chat_temperature,
            env="MEDPAL_CHAT_FALLBACK",
            timeout=settings.chat_timeout_seconds,
            max_retries=settings.chat_max_retries,
        )
        if settings.chat_fallback_provider
        else None
    )

    def chain(name: str, model: Any) -> FallbackChatModel:
        models = [(f"{settings.chat_provider}:{name}", model)]
        if fallback is not None:
            models.append((f"{settings.chat_fallback_provider}:{settings.chat_fallback_model}", fallback))
        return FallbackChatModel(models, timeout=settings.chat_timeout_seconds)

    return {
        "small": chain(settings.chat_small_model or settings.chat_model, primary_small),
        "large": chain(settings.chat_model, primary_large),
    }
