"""Privacy-gated model egress.

All hosted model calls go through this package so PHI handling is centralised.
"""

from .client import EgressChatClient, ModelRequest, ModelResponse
from .providers import FallbackChatModel, build_chat_model, build_model_routes

__all__ = [
    "EgressChatClient",
    "FallbackChatModel",
    "ModelRequest",
    "ModelResponse",
    "build_chat_model",
    "build_model_routes",
]
