"""Privacy-gated model egress.

All hosted model calls go through this package so PHI handling is centralised.
"""

from .client import EgressChatClient, ModelRequest, ModelResponse
from .providers import build_chat_model

__all__ = ["EgressChatClient", "ModelRequest", "ModelResponse", "build_chat_model"]
