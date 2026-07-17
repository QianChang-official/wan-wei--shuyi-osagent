"""
Affect engine — PAD three-dimensional emotional state machine for 宛委·枢忆.

Exports:
    AffectState         — dataclass holding pleasure/arousal/dominance/mood
    load_affect         — load current state from DB
    save_affect         — persist state to DB
    transition          — apply a trigger and mutate state
    detect_emotion      — extract emotional signal from raw text
    classify_intent     — simple intent classifier
    bind_emotion_to_capsule — attach affect metadata to a memory capsule
    apply_emotional_weight  — set capsule emotional_weight
    tune_response_style     — adjust reply prose based on affect
    decay_affect            — single decay step toward baseline
    run_decay_daemon        — background decay thread
"""

from .state_machine import AffectState, load_affect, save_affect, transition
from .emotion_detector import detect_emotion, classify_intent
from .emotion_memory import bind_emotion_to_capsule, apply_emotional_weight
from .response_tuner import tune_response_style
from .decay_daemon import decay_affect, run_decay_daemon

__all__ = [
    "AffectState",
    "load_affect",
    "save_affect",
    "transition",
    "detect_emotion",
    "classify_intent",
    "bind_emotion_to_capsule",
    "apply_emotional_weight",
    "tune_response_style",
    "decay_affect",
    "run_decay_daemon",
]
