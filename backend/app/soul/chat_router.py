"""Chat routing with soul injection."""

from typing import Any

from .injector import build_injection_prompt


def route_chat(soul_id: str, messages: list[dict]) -> dict:
    """Inject soul prompt as a system message and return the routed chat payload.

    Returns a dict with ``injected_messages`` (the original list with the soul
    system message prepended) and ``injection_prompt`` so the caller can pass
    the messages to any downstream model gateway or service.
    """
    if not isinstance(messages, list):
        messages = []

    injection_prompt = build_injection_prompt(soul_id)

    injected = list(messages)
    if injection_prompt:
        # Prepend soul system message before the first user message.
        # If the first message is already a system message, insert after it
        # to preserve any upstream system instructions, otherwise prepend.
        if injected and injected[0].get("role") == "system":
            injected.insert(1, {"role": "system", "content": injection_prompt})
        else:
            injected.insert(0, {"role": "system", "content": injection_prompt})

    return {
        "soul_id": soul_id,
        "injected_messages": injected,
        "injection_prompt": injection_prompt,
    }
