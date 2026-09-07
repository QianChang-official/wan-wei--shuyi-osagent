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

"""issue #121：affect/emotion_detector 否定翻转 / 程度放大 / 混合仲裁 / 排序门禁。

旧版纯子串正则把「好像不太对」「我不太开心」「好烦啊」等明确负向表达
全部判成 positive（4/4 方向性错误），且结果以 0.15 权重进入检索排序、
被永久写进记忆标签。本文件把 issue 实测的 6 条反例钉成回归门禁。
"""

import pytest

from backend.app.affect.emotion_detector import (
    RANKING_GATE_MIN_ACCURACY,
    classify_intent,
    detect_emotion,
    ranking_accuracy,
    ranking_factor,
)


# ---------------------------------------------------------------------------
# issue #121 实测的 6 条反例——方向性必须全部正确
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("好像不太对", "negative"),
        ("好烦啊", "negative"),
        ("我不太开心", "negative"),
        ("这个方案有好多坑", "neutral"),
        ("差不多就行", "neutral"),
        ("这个方案不错", "positive"),
    ],
)
def test_issue121_repro_cases(text, expected):
    assert detect_emotion(text)["emotion_tag"] == expected


def test_negative_delta_is_actually_negative():
    out = detect_emotion("我不太开心")
    assert out["emotion_tag"] == "negative"
    assert out["pleasure_delta"] < 0


# ---------------------------------------------------------------------------
# 否定翻转
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["不开心", "一点都不满意", "这结果我不满意"]) 
def test_negation_flips_or_drops_positive_hits(text):
    assert detect_emotion(text)["emotion_tag"] != "positive"


def test_english_negation_not_positive():
    assert detect_emotion("not happy with this result")["emotion_tag"] != "positive"


def test_negated_anxious_is_dropped():
    # 「别担心」：焦虑命中被否定 → 整条丢弃，不应残留 anxious 标签与负效价
    out = detect_emotion("别担心，会好起来的")
    assert out["emotion_tag"] != "anxious"


# ---------------------------------------------------------------------------
# 程度副词是乘子，不是独立正向信号
# ---------------------------------------------------------------------------
def test_amplifier_scales_magnitude():
    base = detect_emotion("我喜欢这个设计")["pleasure_delta"]
    amplified = detect_emotion("我非常喜欢这个设计")["pleasure_delta"]
    assert 0 < base < amplified


def test_hao_before_negative_word_amplifies_not_praises():
    # 「好」紧跟负向词时是程度语（好烦=很烦），不得再当独立正向词
    out = detect_emotion("今天真的好烦")
    assert out["emotion_tag"] == "negative"
    assert out["pleasure_delta"] < -0.25


# ---------------------------------------------------------------------------
# 正负混存：Δp≈0 时如实判 mixed，不再默认 positive
# ---------------------------------------------------------------------------
def test_mixed_arbitration_not_default_positive():
    text = "界面我很喜欢，但稳定性实在糟糕"  # 喜欢(+1) 糟糕(-1)，无否定无放大
    out = detect_emotion(text)
    assert out["emotion_tag"] in ("mixed", "negative")
    assert out["emotion_tag"] != "positive" or out["pleasure_delta"] > 0.15


# ---------------------------------------------------------------------------
# 排序门禁（issue #121 建议 4）：标注集准确率 <0.7 时禁止 affective 参与排序
# ---------------------------------------------------------------------------
def test_golden_set_accuracy_above_gate():
    acc = ranking_accuracy()
    assert acc >= 0.9, f"标注集准确率 {acc:.2f} 低于自设基线 0.9"
    assert acc >= RANKING_GATE_MIN_ACCURACY
    assert ranking_factor() == 1.0


def test_gate_disables_below_threshold(monkeypatch):
    import backend.app.affect.emotion_detector as det

    monkeypatch.setattr(det, "ranking_accuracy", lambda: 0.5)
    assert det.ranking_factor() == 0.0


# ---------------------------------------------------------------------------
# 返回契约不变形状（下游 emotion_memory / state_machine 依赖）
# ---------------------------------------------------------------------------
def test_return_schema_stable():
    out = detect_emotion("随便一句话")
    assert set(out) == {"emotion_tag", "pleasure_delta", "arousal_delta", "intensity"}
    for key in ("pleasure_delta", "arousal_delta", "intensity"):
        assert -1.0 <= out[key] <= 1.0
    assert isinstance(out["emotion_tag"], str)


def test_empty_and_none_inputs_are_neutral():
    assert detect_emotion("")["emotion_tag"] == "neutral"
    assert detect_emotion(None)["emotion_tag"] == "neutral"


# ---------------------------------------------------------------------------
# classify_intent 同族子串缺陷收窄：裸「差」不再让「差不多」误报 complaint
# ---------------------------------------------------------------------------
def test_chabuduo_is_not_complaint():
    assert classify_intent("差不多就行") != "complaint"
