"""The single safe door from identified clinical text to hosted chat models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from services.platform.phi.scrubber import TokenMap, assert_clean, reidentify, tokenise

Structured = TypeVar("Structured", bound=BaseModel)
Structured_co = TypeVar("Structured_co", bound=BaseModel, covariant=True)


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

    def __init__(self, model: ChatModel) -> None:
        self._model = model

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
        raw = await self._model.ainvoke(messages)
        text = _content(raw)
        assert_clean(text, known_names=request.known_names)
        return ModelResponse(
            text=reidentify(text, token_map),
            token_map=token_map,
            tokenised_entities=entities,
        )

    async def ask_structured(self, request: ModelRequest, schema: type[Structured]) -> Structured:
        messages, token_map, _entities = self._safe_messages(request)
        raw = await self._model.with_structured_output(schema).ainvoke(messages)
        data = raw.model_dump() if isinstance(raw, BaseModel) else dict(raw)
        return schema.model_validate(_reidentify_value(data, token_map))
