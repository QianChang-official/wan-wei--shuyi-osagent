"""
Response style tuner.

Modulates generated prose according to the current PAD state and mood.
Lightweight, deterministic, no LLM calls.
"""

from .state_machine import AffectState


def tune_response_style(text: str, affect: AffectState) -> str:
    """
    Adjust a reply string based on the current affect state.

    Rules (applied in order):
        1. pleasure < 0.3  → prepend comforting prefix
        2. arousal > 0.7   → keep only first sentence, very direct
        3. mood == excited → append exclamation, warm closing
        4. mood == empathetic → lead with empathy, then answer
    """
    if not text:
        return text

    # 1. Comfort when low pleasure
    if affect.pleasure < 0.3:
        text = f"我理解你的感受…… {text}"

    # 2. High arousal → shorten, be direct
    if affect.arousal > 0.7:
        # Take only the first sentence (naïve split on 。or .)
        first = text
        for delim in ("\n", "。", ". ", "."):
            if delim in first:
                first = first.split(delim)[0] + delim.replace(" ", "")
                break
        text = first.strip()

    # 3. Excited mood → warmer, exclamatory tone
    if affect.current_mood == "excited":
        if not text.endswith(("!", "！")):
            text += "！"

    # 4. Empathetic mood → validate feeling before answering
    if affect.current_mood == "empathetic":
        text = f"我能感受到你的心情，{text}"

    return text
