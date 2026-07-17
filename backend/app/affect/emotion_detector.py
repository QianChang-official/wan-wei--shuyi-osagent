"""
Lightweight emotion detector & intent classifier.

Uses regex keyword matching and punctuation heuristics.  No ML models required.
"""

import re


def detect_emotion(text: str) -> dict:
    """
    Extract emotional signal from raw Chinese/English text.

    Returns:
        {
            "emotion_tag": str,      # e.g. "positive", "negative", "anxious", "excited"
            "pleasure_delta": float, # [-1, 1] approx
            "arousal_delta": float,  # [-1, 1] approx
            "intensity": float,      # [0, 1]
        }
    """
    text = text or ""
    pleasure_delta = 0.0
    arousal_delta = 0.0
    intensity = 0.3
    tags = []

    # ------------------------------------------------------------------
    # 1. Keyword matching
    # ------------------------------------------------------------------
    positive_kw = re.compile(r"开心|高兴|谢谢|感谢|棒|好|喜欢|赞|不错|满意|愉快|positive|thank|great|good|happy")
    negative_kw = re.compile(r"难过|愤怒|不对|失望|糟糕|差|讨厌|烦|生气|讨厌|negative|angry|bad|disappointed|wrong")
    anxious_kw = re.compile(r"焦虑|担心|害怕|紧张|不安|anxious|worried|nervous|scared|afraid")
    excited_kw = re.compile(r"兴奋|棒极了|太好了|激动|wow|amazing|excellent|excited|awesome")

    if positive_kw.search(text):
        tags.append("positive")
        pleasure_delta += 0.25
        intensity = max(intensity, 0.5)
    if negative_kw.search(text):
        tags.append("negative")
        pleasure_delta -= 0.25
        intensity = max(intensity, 0.5)
    if anxious_kw.search(text):
        tags.append("anxious")
        arousal_delta += 0.15
        pleasure_delta -= 0.10
        intensity = max(intensity, 0.6)
    if excited_kw.search(text):
        tags.append("excited")
        pleasure_delta += 0.30
        arousal_delta += 0.20
        intensity = max(intensity, 0.7)

    # ------------------------------------------------------------------
    # 2. Punctuation density heuristics
    # ------------------------------------------------------------------
    exclamation_count = text.count("!") + text.count("！")
    question_count = text.count("?") + text.count("？")

    if exclamation_count > 2:
        arousal_delta += 0.10
        intensity = max(intensity, 0.6)
    if question_count > 2:
        arousal_delta += 0.05
        intensity = max(intensity, 0.5)

    # ------------------------------------------------------------------
    # 3. Tag arbitration
    # ------------------------------------------------------------------
    if not tags:
        emotion_tag = "neutral"
    elif "excited" in tags:
        emotion_tag = "excited"
    elif "anxious" in tags:
        emotion_tag = "anxious"
    elif "negative" in tags and "positive" in tags:
        # Mixed — default to whichever has stronger delta magnitude
        emotion_tag = "negative" if abs(pleasure_delta) > 0.15 else "positive"
    elif "negative" in tags:
        emotion_tag = "negative"
    else:
        emotion_tag = "positive"

    return {
        "emotion_tag": emotion_tag,
        "pleasure_delta": max(-1.0, min(1.0, pleasure_delta)),
        "arousal_delta": max(-1.0, min(1.0, arousal_delta)),
        "intensity": max(0.0, min(1.0, intensity)),
    }


def classify_intent(text: str) -> str:
    """
    Simple rule-based intent classifier.

    Returns one of: gratitude, complaint, question, share_emotion, neutral
    """
    text = text or ""

    gratitude_kw = re.compile(r"谢谢|感谢|谢了|thank|thanks|grateful|appreciate")
    complaint_kw = re.compile(r"不对|错了|糟糕|差|失望|bug|坏|问题|complain|wrong|bad|terrible")
    question_kw = re.compile(r"\?|？|什么|怎么|为什么|如何|吗|呢|who|what|when|where|why|how|question")
    emotion_kw = re.compile(r"开心|难过|兴奋|焦虑|生气|高兴|担心|害怕|feel|feeling|emotion|mood|sad|happy|angry")

    # Order matters — gratitude / complaint are stronger signals than question.
    if gratitude_kw.search(text):
        return "gratitude"
    if complaint_kw.search(text):
        return "complaint"
    if emotion_kw.search(text):
        return "share_emotion"
    if question_kw.search(text):
        return "question"
    return "neutral"
