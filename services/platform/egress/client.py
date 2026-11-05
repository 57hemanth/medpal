"""The single safe door from identified clinical text to hosted chat models."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from services.platform.egress.providers import last_call
from services.platform.phi.scrubber import TokenMap, assert_clean, reidentify, tokenise
from services.platform.tracing import estimate_tokens, record_model_call

Structured = TypeVar("Structured", bound=BaseModel)
Structured_co = TypeVar("Structured_co", bound=BaseModel, covariant=True)

log = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """The model could not produce a usable answer: provider error, timeout, refusal or malformed output.

    Callers must degrade to a safe, human path instead of failing the request. The reason is a code;
    the provider's own message is never surfaced because it may echo prompt content.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ChatModel(Protocol):
    """Small protocol implemented by LangChain chat models and local fakes."""

    async def ainvoke(self, messages: list[dict[str, str]]) -> Any: ...

    def with_structured_output(self, schema: type[Structured]) -> StructuredChatModel[Structured]: ...


class StructuredChatModel(Protocol[Structured_co]):
    async def ainvoke(self, messages: list[dict[str, str]]) -> Structured_co | Mapping[str, Any]: ...


@dataclass(frozen=True)
class ModelRequest:
    system: str
    user: str
    purpose: str
    tier: str = "large"  # "small" for classification-style steps, "large" for drafting and cited answers
    known_names: list[str] = field(default_factory=list)
    token_map: TokenMap | None = None


@dataclass(frozen=True)
class ModelResponse:
    text: str
    token_map: TokenMap
    tokenised_entities: list[str]


def _content(value: Any) -> str:
    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text", part)) for part in content)
    return str(content)


def _model_name(model: Any) -> str:
    used = getattr(model, "last_used", None)
    if used:
        return str(used)
    for attr in ("model_name", "model"):
        value = getattr(model, attr, None)
        if isinstance(value, str):
            return value
    return type(model).__name__


def _usage(raw: Any) -> tuple[int, int] | None:
    usage = getattr(raw, "usage_metadata", None)
    if isinstance(usage, dict) and "input_tokens" in usage:
        return int(usage["input_tokens"]), int(usage.get("output_tokens", 0))
    return None


def _reidentify_value(value: Any, token_map: TokenMap) -> Any:
    if isinstance(value, str):
        return reidentify(value, token_map)
    if isinstance(value, list):
        return [_reidentify_value(item, token_map) for item in value]
    if isinstance(value, dict):
        return {key: _reidentify_value(item, token_map) for key, item in value.items()}
    return value


class EgressChatClient:
    """Tokenise before invoking a chat model, then re-identify only after the model returns."""

    def __init__(self, model: ChatModel, *, routes: Mapping[str, ChatModel] | None = None) -> None:
        self._model = model
        self._routes = dict(routes or {})

    def _for(self, request: ModelRequest) -> ChatModel:
        return self._routes.get(request.tier, self._model)

    def _safe_messages(self, request: ModelRequest) -> tuple[list[dict[str, str]], TokenMap, list[str]]:
        token_map = request.token_map or TokenMap()
        entities: list[str] = []
        messages = []
        for role, text in (("system", request.system), ("human", request.user)):
            scrubbed = tokenise(text, token_map, known_names=request.known_names)
            assert_clean(scrubbed.text, known_names=request.known_names)
            entities.extend(scrubbed.entities)
            messages.append({"role": role, "content": scrubbed.text})
        return messages, token_map, entities

    async def ask(self, request: ModelRequest) -> ModelResponse:
        messages, token_map, entities = self._safe_messages(request)
        model = self._for(request)
        prompt_tokens = estimate_tokens("".join(m["content"] for m in messages))
        started = time.perf_counter()
        try:
            raw = await model.ainvoke(messages)
        except Exception as exc:  # vendor SDKs raise many types; one boundary, one error for callers
            log.warning("model call failed for %s: %s", request.purpose, type(exc).__name__)
            record_model_call(
                _model_name(model),
                started=started,
                status="error",
                error_type=type(exc).__name__,
                tokens_in=prompt_tokens,
                tokens_out=0,
                estimated=True,
            )
            raise ModelUnavailable("model_call_failed") from exc
        text = _content(raw)
        usage = _usage(raw)
        record_model_call(
            _model_name(model),
            started=started,
            tokens_in=usage[0] if usage else prompt_tokens,
            tokens_out=usage[1] if usage else estimate_tokens(text),
            estimated=usage is None,
        )
        assert_clean(text, known_names=request.known_names)
        return ModelResponse(
            text=reidentify(text, token_map),
            token_map=token_map,
            tokenised_entities=entities,
        )

    async def ask_structured(self, request: ModelRequest, schema: type[Structured]) -> Structured:
        messages, token_map, _entities = self._safe_messages(request)
        model = self._for(request)
        prompt_tokens = estimate_tokens("".join(m["content"] for m in messages))
        started = time.perf_counter()
        try:
            raw = await model.with_structured_output(schema).ainvoke(messages)
            data = raw.model_dump() if isinstance(raw, BaseModel) else dict(raw)
            result = schema.model_validate(_reidentify_value(data, token_map))
        except ValidationError as exc:
            log.warning("model returned invalid %s for %s", schema.__name__, request.purpose)
            record_model_call(
                _model_name(model),
                started=started,
                status="error",
                error_type="ValidationError",
                tokens_in=prompt_tokens,
                tokens_out=0,
                estimated=True,
            )
            raise ModelUnavailable("model_output_invalid") from exc
        except Exception as exc:  # vendor SDKs raise many types; one boundary, one error for callers
            log.warning("model call failed for %s: %s", request.purpose, type(exc).__name__)
            record_model_call(
                _model_name(model),
                started=started,
                status="error",
                error_type=type(exc).__name__,
                tokens_in=prompt_tokens,
                tokens_out=0,
                estimated=True,
            )
            raise ModelUnavailable("model_call_failed") from exc
        used, usage = last_call()
        record_model_call(
            used or _model_name(model),
            started=started,
            tokens_in=usage[0] if usage else prompt_tokens,
            tokens_out=usage[1] if usage else estimate_tokens(result.model_dump_json()),
            estimated=usage is None,
        )
        return result
