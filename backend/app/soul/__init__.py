"""Soul Awakening module — persona, affect injection, and chat routing."""

from .persona import get_persona, update_persona, create_persona
from .injector import build_injection_prompt, get_soul_state
from .chat_router import route_chat

__all__ = [
    "get_persona",
    "update_persona",
    "create_persona",
    "build_injection_prompt",
    "get_soul_state",
    "route_chat",
]
