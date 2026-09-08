# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Lightweight emotion detector & intent classifier.

词表 + 规则，无 ML、离线可用。

v2（issue #121）：旧版是纯子串正则——「好像不太对」「我不太开心」「好烦啊」
等否定/反义表达一律误判为 positive（方向性错误率 4/4），且结果以 0.15 权重
进入检索排序、被永久写进记忆标签。本版在保持纯离线的前提下补上三类规则：

- **否定翻转**：情感词紧邻否定前缀（不太 / 没 / 别 / not / never …）时极性
  取反；焦虑/兴奋类命中被否定时整条丢弃；
- **程度放大**：程度副词（非常 / 太 / 「好+情绪词」 / very …）作幅度乘子
  （×1.5），不再是独立的正向信号；
- **惯用语豁免**：「不错 / 不赖」等否定式正面惯用语先于否定规则参与，
  不会被「不」误翻转。

正负同时命中且 |Δpleasure| ≤ 0.15 时判 ``mixed``，不再默认 positive。
另内置 20 条最小标注集自检：准确率低于 :data:`RANKING_GATE_MIN_ACCURACY`
时 :func:`ranking_factor` 返回 0.0，检索侧应据此停用 affective 排序权重
（消费方见 ``memory_runtime/retrieval.py``）。当前词表下实测 0.95。

已知边界（诚实声明）：不分词、不解析句法、不识别反讽与方言；语义来源
仅限下方词表。标注集中保留了 1 条反讽样例并如实计入错误，用于压住
「门禁永远绿」的幻觉。
"""

from __future__ import annotations

import re

__all__ = ["detect_emotion", "classify_intent", "ranking_factor", "ranking_accuracy", "RANKING_GATE_MIN_ACCURACY"]

# ---------------------------------------------------------------------------
# 词表（可评审清单；改动任何词条都会反映在 golden set 自检里）
# ---------------------------------------------------------------------------
# 否定式正面惯用语：先于否定翻转处理
_POSITIVE_IDIOMS = ("不错", "不赖", "没问题")
# 正面词（旧版的裸「好」已移除：「好像/好多/好烦」的子串误命中率远高于真阳性）
_POSITIVE_WORDS = (
    "开心", "高兴", "谢谢", "感谢", "棒", "喜欢", "赞", "满意", "愉快", "舒心", "安心",
    "positive", "thank", "thanks", "grateful", "great", "good", "happy", "love", "excellent",
)
# 负面词（旧版裸「差」移除，收窄为「差劲」；「烦」从纯 intensity 提升为负向词）。
# 「不太对」整体入表：它与「不对」无公共子串，逐字扫描捕不住这种副词隔断。
_NEGATIVE_WORDS = (
    "难过", "愤怒", "不对", "不太对", "失望", "糟糕", "差劲", "讨厌", "烦", "生气", "心烦", "郁闷", "恼火", "无聊",
    "negative", "angry", "bad", "disappointed", "wrong", "terrible", "awful", "hate",
)
_ANXIOUS_WORDS = (
    "焦虑", "担心", "害怕", "紧张", "不安", "anxious", "worried", "nervous", "scared", "afraid",
)
_EXCITED_WORDS = (
    "兴奋", "棒极了", "太好了", "激动", "wow", "amazing", "excited", "awesome",
)

_NEGATIONS = (
    # 中文最长优先；英文按小写后缀匹配
    "不太", "毫不", "并不", "从不", "毫无", "没有", "不会", "不能", "不要",
    "别", "无", "非", "未", "不", "没",
)
_NEGATIONS_EN = ("not", "never", "n't")
_AMPLIFIERS = ("非常", "特别", "超级", "十分", "极其", "相当", "太", "好", "超", "真", "贼", "very", "so", "really", "super")
# 否定/程度与前词之间允许出现的助词/空隙
_PARTICLE_CHARS = "的地得很太最也还都真就 \t"

_AMPLIFY_FACTOR = 1.5
_HIT_DELTA = 0.25


def _ascii_word_pattern(word: str) -> str:
    """ASCII 词加边界（避免 bad 匹配到 badge），CJK 词原样。"""
    if word.isascii():
        return rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])"
    return re.escape(word)


def _compile(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(_ascii_word_pattern(w) for w in words))


_IDIOM_RE = _compile(_POSITIVE_IDIOMS)
_POS_RE = _compile(_POSITIVE_WORDS)
_NEG_RE = _compile(_NEGATIVE_WORDS)
_ANX_RE = _compile(_ANXIOUS_WORDS)
_EXC_RE = _compile(_EXCITED_WORDS)


def _prefix_window(text: str, start: int, width: int = 4) -> str:
    """取命中起点之前的紧邻窗口，去掉助词后用于否定/程度判断。"""
    return text[max(0, start - width):start].rstrip(_PARTICLE_CHARS)


def _is_negated(text: str, start: int) -> bool:
    prefix = _prefix_window(text, start).lower()
    if not prefix:
        return False
    for neg in _NEGATIONS:
        if prefix.endswith(neg):
            return True
    return any(prefix.endswith(en) for en in _NEGATIONS_EN)


def _is_amplified(text: str, start: int) -> bool:
    prefix = _prefix_window(text, start, width=3).lower()
    if not prefix:
        return False
    return any(prefix.endswith(amp.lower()) for amp in _AMPLIFIERS)


def _scan(text: str, pattern: re.Pattern[str], taken: list[tuple[int, int]]) -> list[re.Match[str]]:
    """找出未被先前类别占用的命中区间（棒极了优先于棒，避免重复计数）。"""
    hits: list[re.Match[str]] = []
    for m in pattern.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        hits.append(m)
        taken.append((m.start(), m.end()))
    return hits


def detect_emotion(text: str) -> dict:
    """
    Extract emotional signal from raw Chinese/English text.

    Returns:
        {
            "emotion_tag": str,      # positive / negative / mixed / anxious / excited / neutral
            "pleasure_delta": float, # [-1, 1] approx
            "arousal_delta": float,  # [-1, 1] approx
            "intensity": float,      # [0, 1]
        }
    """
    text = text or ""
    pleasure_delta = 0.0
    arousal_delta = 0.0
    intensity = 0.3
    tags: list[str] = []
    taken: list[tuple[int, int]] = []

    def _apply(sign: float, start: int, weight: float = 1.0) -> None:
        nonlocal pleasure_delta, intensity
        pleasure_delta += sign * _HIT_DELTA * (_AMPLIFY_FACTOR if _is_amplified(text, start) else 1.0) * weight
        intensity = max(intensity, 0.5)

    # 1. 关键词扫描：惯用语 → 兴奋 → 焦虑 → 负向 → 正向（先占位者赢）
    for m in _scan(text, _IDIOM_RE, taken):
        tags.append("positive")
        _apply(+1.0, m.start())
    for m in _scan(text, _EXC_RE, taken):
        if _is_negated(text, m.start()):
            continue
        tags.append("excited")
        pleasure_delta += 0.30
        arousal_delta += 0.20
        intensity = max(intensity, 0.7)
    for m in _scan(text, _ANX_RE, taken):
        if _is_negated(text, m.start()):
            continue
        tags.append("anxious")
        arousal_delta += 0.15
        pleasure_delta -= 0.10
        intensity = max(intensity, 0.6)
    for m in _scan(text, _NEG_RE, taken):
        negated = _is_negated(text, m.start())
        # 否定后有效极性反转，标签必须跟随有效极性而非原词极性
        # （「不难过」的有效标签是 positive，「不开心」是 negative）
        tags.append("positive" if negated else "negative")
        _apply(+1.0 if negated else -1.0, m.start())
    for m in _scan(text, _POS_RE, taken):
        negated = _is_negated(text, m.start())
        tags.append("negative" if negated else "positive")
        _apply(-1.0 if negated else +1.0, m.start())

    # 2. 标点密度启发式（沿用 v1）
    exclamation_count = text.count("!") + text.count("！")
    question_count = text.count("?") + text.count("？")
    if exclamation_count > 2:
        arousal_delta += 0.10
        intensity = max(intensity, 0.6)
    if question_count > 2:
        arousal_delta += 0.05
        intensity = max(intensity, 0.5)

    # 3. Tag arbitration：正负并存且 Δp≈0 时如实判 mixed（v1 在此默认 positive）
    if not tags:
        emotion_tag = "neutral"
    elif "excited" in tags:
        emotion_tag = "excited"
    elif "anxious" in tags:
        emotion_tag = "anxious"
    elif "negative" in tags and "positive" in tags:
        if pleasure_delta > 0.15:
            emotion_tag = "positive"
        elif pleasure_delta < -0.15:
            emotion_tag = "negative"
        else:
            emotion_tag = "mixed"
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


# ---------------------------------------------------------------------------
# 最小标注集自检与排序门禁（issue #121 建议 4）
# ---------------------------------------------------------------------------
# (text, expected_tag)。第 19 条为反讽样例：词表方案抓不住，如实计入错误，
# 用于防止「门禁永远绿」。准确率跌破阈值时检索侧必须停用 affective 权重。
_GOLDEN_SET: tuple[tuple[str, str], ...] = (
    ("今天很开心", "positive"),
    ("我不太开心", "negative"),
    ("好像不太对", "negative"),
    ("好烦啊", "negative"),
    ("这个方案有好多坑", "neutral"),
    ("差不多就行", "neutral"),
    ("这个方案不错", "positive"),
    ("谢谢你帮了大忙", "positive"),
    ("界面糟糕透了，很失望", "negative"),
    ("非常喜欢这个设计", "positive"),
    ("别担心，会好起来的", "neutral"),
    ("not happy with this", "negative"),
    ("This is great, thank you", "positive"),
    ("这次发布太让人失望了", "negative"),
    ("完美！非常棒！", "positive"),
    ("面试前有点紧张", "anxious"),
    ("收到offer那一刻太兴奋了", "excited"),
    ("这几天无聊得要命", "negative"),
    ("呵呵，可真是太棒了呢", "negative"),  # 反讽：已知误判为 positive
    ("收到，明天上午十点开会", "neutral"),
)

RANKING_GATE_MIN_ACCURACY = 0.7
_gate_cache: dict[str, float] = {}


def ranking_accuracy() -> float:
    """在最小标注集上自检，返回准确率（每进程每版本只算一次）。"""
    cached = _gate_cache.get("accuracy")
    if cached is not None:
        return cached
    correct = sum(
        1 for text, expected in _GOLDEN_SET if detect_emotion(text)["emotion_tag"] == expected
    )
    acc = correct / len(_GOLDEN_SET)
    _gate_cache["accuracy"] = acc
    return acc


def ranking_factor() -> float:
    """检索侧 affective 权重系数：自检达标返回 1.0，否则 0.0（停用参与排序）。"""
    return 1.0 if ranking_accuracy() >= RANKING_GATE_MIN_ACCURACY else 0.0


def classify_intent(text: str) -> str:
    """
    Simple rule-based intent classifier.

    Returns one of: gratitude, complaint, question, share_emotion, neutral
    """
    text = text or ""

    gratitude_kw = re.compile(r"谢谢|感谢|谢了|thank|thanks|grateful|appreciate")
    # 旧版裸「差」会让「差不多就行」误报 complaint；收窄为明确负向组合
    complaint_kw = re.compile(r"不对|错了|糟糕|差劲|差评|太差|失望|bug|坏|问题|complain|wrong|bad|terrible")
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
