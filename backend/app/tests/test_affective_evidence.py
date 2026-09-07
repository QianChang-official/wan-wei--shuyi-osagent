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

"""
issue #179 Affective Evidence Weight — 情感证据权重测试

覆盖设计规格里的 7 类验收场景（外加 ``_coerce_count`` 浮点兼容用例）：

1. 中性证据兼容性：w=1 与既有等权 Beta 更新一致（flag 关 / 显式 1.0）；
2. reinforce 加权：α += w_affect，β 不变，日志记录 alpha_delta；
3. deprecate 加权：β += w_affect，α 不变，日志记录 beta_delta；
4. 权重上下界：合法权重裁剪到 [w_min, w_max]；非法输入（NaN/inf/非正数/非数值）
   精确回落 1.0、不参与区间裁剪（非法=无有效信号=中性基线）；
5. feature flag：WANWEI_AFFECTIVE_EVIDENCE 默认关闭，关闭时一律等权；
6. 审计可追溯：state[preference_evidence_log] 逐条记录 direction /
   raw_affect_score / affect_weight / alpha_delta / beta_delta / created_at，
   有界保留最近 log_limit 条，旧数据无该键兼容、不覆盖原始证据；
7. 回归：evolution.reinforce()/deprecate() 透传情感参数，非 preference 不受影响。

纯函数层不需要数据库；集成层复用 isolated_db 夹具。
"""

import math

import pytest

from backend.app.memory_runtime import capsule_store as cs
from backend.app.memory_runtime import evolution as ev
from backend.app.memory_runtime.preference_confidence import (
    ALPHA_KEY,
    BETA_KEY,
    DEFAULT_LOG_LIMIT,
    DEFAULT_W_MAX,
    DEFAULT_W_MIN,
    EVIDENCE_LOG_KEY,
    _coerce_count,
    affective_weight_enabled,
    confidence,
    update_confidence,
)

AFFECTIVE_ENV = "WANWEI_AFFECTIVE_EVIDENCE"
W_MIN_ENV = "WANWEI_AFFECTIVE_W_MIN"
W_MAX_ENV = "WANWEI_AFFECTIVE_W_MAX"
LOG_LIMIT_ENV = "WANWEI_EVIDENCE_LOG_LIMIT"


# ---------------------------------------------------------------------------
# 1. 中性证据兼容性：w=1 严格保持既有 Beta 行为
# ---------------------------------------------------------------------------

def test_neutral_weight_matches_legacy_beta_update():
    """flag 关闭（enabled=False）+ w_affect=1 与旧等权 Beta 完全一致。"""
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=1.0, enabled=False)
    assert meta[ALPHA_KEY] == 1
    assert meta[BETA_KEY] == 0
    posterior = confidence(meta)
    assert posterior["alpha"] == 2
    assert posterior["beta"] == 1


def test_default_weight_is_neutral_even_when_enabled():
    """不传 w_affect（默认 1.0）时，即使 flag 开启也保持中性等权。"""
    meta: dict = {}
    update_confidence(meta, "reinforce", enabled=True)
    assert meta[ALPHA_KEY] == 1
    update_confidence(meta, "deprecate", enabled=True)
    assert meta[BETA_KEY] == 1


def test_neutral_log_records_unit_delta():
    """中性证据同样进审计日志：alpha_delta=1、affect_weight=1。"""
    meta: dict = {}
    update_confidence(meta, "reinforce", enabled=False, created_at="2026-09-03T00:00:00Z")
    entry = meta[EVIDENCE_LOG_KEY][-1]
    assert entry["affect_weight"] == 1.0
    assert entry["alpha_delta"] == 1.0
    assert entry["beta_delta"] == 0.0


# ---------------------------------------------------------------------------
# 2. reinforce 加权：α += w_affect
# ---------------------------------------------------------------------------

def test_reinforce_weighted_increases_alpha_only():
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=2.0, enabled=True)
    assert meta[ALPHA_KEY] == 2
    assert meta[BETA_KEY] == 0
    entry = meta[EVIDENCE_LOG_KEY][-1]
    assert entry["direction"] == "reinforce"
    assert entry["alpha_delta"] == 2.0
    assert entry["beta_delta"] == 0.0
    posterior = confidence(meta)
    assert posterior["alpha"] == 3  # 先验(1,1) + 计数(2,0)
    assert posterior["beta"] == 1


def test_reinforce_fractional_weight():
    """非整数权重保留为浮点计数（_coerce_count 浮点兼容的入口）。"""
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=1.5, enabled=True)
    assert meta[ALPHA_KEY] == 1.5
    assert isinstance(meta[ALPHA_KEY], float)


# ---------------------------------------------------------------------------
# 3. deprecate 加权：β += w_affect
# ---------------------------------------------------------------------------

def test_deprecate_weighted_increases_beta_only():
    meta: dict = {}
    update_confidence(meta, "deprecate", w_affect=2.5, enabled=True)
    assert meta[BETA_KEY] == 2.5
    assert meta[ALPHA_KEY] == 0
    entry = meta[EVIDENCE_LOG_KEY][-1]
    assert entry["direction"] == "deprecate"
    assert entry["beta_delta"] == 2.5
    assert entry["alpha_delta"] == 0.0
    posterior = confidence(meta)
    assert posterior["beta"] == 3.5
    assert posterior["mean"] < 0.5


# ---------------------------------------------------------------------------
# 4. 权重上下界：裁剪与非法回落
# ---------------------------------------------------------------------------

def test_weight_clamped_to_upper_bound():
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=100.0, enabled=True)
    assert meta[ALPHA_KEY] == DEFAULT_W_MAX
    assert meta[EVIDENCE_LOG_KEY][-1]["affect_weight"] == DEFAULT_W_MAX


def test_weight_clamped_to_lower_bound():
    meta: dict = {}
    update_confidence(meta, "deprecate", w_affect=0.05, enabled=True)
    assert meta[BETA_KEY] == DEFAULT_W_MIN
    assert meta[EVIDENCE_LOG_KEY][-1]["affect_weight"] == DEFAULT_W_MIN


#: 非法情感权重样本：NaN / inf / 非正数 / 非数值（含 bool）。
_INVALID_WEIGHTS = [
    float("nan"),
    float("inf"),
    float("-inf"),
    -3.0,
    0.0,
    -0.0,
    None,
    "very-strong",
    True,
    False,
]


@pytest.mark.parametrize("bad", _INVALID_WEIGHTS)
def test_invalid_weight_falls_back_to_neutral(bad):
    """NaN/inf/非正数/非数值 → 回落 1.0，且不越界。"""
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=bad, enabled=True)
    delta = meta[EVIDENCE_LOG_KEY][-1]["alpha_delta"]
    assert delta == 1.0
    assert DEFAULT_W_MIN <= delta <= DEFAULT_W_MAX


@pytest.mark.parametrize("bad", _INVALID_WEIGHTS)
def test_invalid_weight_exactly_neutral_when_bounds_exclude_one(bad):
    """区间不含 1.0（[2,4]）时非法输入仍精确回落 1.0，不被区间改写。

    非法 = 无有效情感信号 = 中性基线；区间裁剪只作用于合法情感权重，
    非法输入恒为精确 1.0——不抬到 w_min、不压到 w_max。
    """
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=bad, enabled=True,
                      w_min=2.0, w_max=4.0)
    assert meta[ALPHA_KEY] == 1.0
    entry = meta[EVIDENCE_LOG_KEY][-1]
    assert entry["affect_weight"] == 1.0
    assert entry["alpha_delta"] == 1.0


def test_legal_weight_still_clamped_when_bounds_exclude_one():
    """同区间 [2,4] 下，合法权重照常裁剪到边界（裁剪只作用于合法权重）。"""
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=1.0, enabled=True,
                      w_min=2.0, w_max=4.0)
    assert meta[ALPHA_KEY] == 2.0  # 合法 1.0 → 抬到 w_min
    meta2: dict = {}
    update_confidence(meta2, "reinforce", w_affect=10.0, enabled=True,
                      w_min=2.0, w_max=4.0)
    assert meta2[ALPHA_KEY] == 4.0  # 合法 10.0 → 压到 w_max


def test_invalid_weight_exactly_one_with_bounds_env(monkeypatch):
    """区间经环境变量配置为 [2,4] 时，非法输入同样精确回落 1.0。"""
    monkeypatch.setenv(W_MIN_ENV, "2.0")
    monkeypatch.setenv(W_MAX_ENV, "4.0")
    meta: dict = {}
    update_confidence(meta, "deprecate", w_affect=float("nan"), enabled=True)
    assert meta[BETA_KEY] == 1.0
    assert meta[EVIDENCE_LOG_KEY][-1]["affect_weight"] == 1.0


def test_never_out_of_bounds_for_any_input():
    """任取一组极值输入，更新增量都落在默认区间内。"""
    for w in (-1e9, 1e9, 0.0, float("inf"), float("nan"), 3.14159, 0.75, 42):
        meta: dict = {}
        update_confidence(meta, "reinforce", w_affect=w, enabled=True)
        delta = meta[EVIDENCE_LOG_KEY][-1]["alpha_delta"]
        assert DEFAULT_W_MIN <= delta <= DEFAULT_W_MAX, w


def test_custom_bounds_are_configurable_parameters():
    """w_min/w_max 作为带默认值的参数可配置。"""
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=10.0, enabled=True,
                      w_min=1.0, w_max=4.0)
    assert meta[ALPHA_KEY] == 4.0
    meta2: dict = {}
    update_confidence(meta2, "reinforce", w_affect=0.2, enabled=True,
                      w_min=1.0, w_max=4.0)
    assert meta2[ALPHA_KEY] == 1.0  # 低于 w_min → 抬到 1.0


def test_bounds_env_configurable(monkeypatch):
    """区间也可由环境变量配置（WANWEI_AFFECTIVE_W_MIN/MAX）。"""
    monkeypatch.setenv(W_MIN_ENV, "1.0")
    monkeypatch.setenv(W_MAX_ENV, "2.0")
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=10.0, enabled=True)
    assert meta[ALPHA_KEY] == 2.0


def test_bounds_invalid_config_falls_back_to_defaults(monkeypatch):
    """配置区间非法（min>max）时回落保守默认，不产生越界。"""
    monkeypatch.setenv(W_MIN_ENV, "5.0")
    monkeypatch.setenv(W_MAX_ENV, "1.0")
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=100.0, enabled=True)
    assert meta[ALPHA_KEY] == DEFAULT_W_MAX


# ---------------------------------------------------------------------------
# 5. Feature flag
# ---------------------------------------------------------------------------

def test_feature_flag_default_off(monkeypatch):
    monkeypatch.delenv(AFFECTIVE_ENV, raising=False)
    assert affective_weight_enabled() is False


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "on", "yes"])
def test_feature_flag_true_values(monkeypatch, truthy):
    monkeypatch.setenv(AFFECTIVE_ENV, truthy)
    assert affective_weight_enabled() is True


@pytest.mark.parametrize("falsy", ["0", "false", "off", ""])
def test_feature_flag_false_values(monkeypatch, falsy):
    monkeypatch.setenv(AFFECTIVE_ENV, falsy)
    assert affective_weight_enabled() is False


def test_flag_off_forces_unit_weight_regardless_of_input(monkeypatch):
    """关闭时无论传入什么权重都等权更新（严格基线）。"""
    monkeypatch.delenv(AFFECTIVE_ENV, raising=False)
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=5.0, enabled=None)
    assert meta[ALPHA_KEY] == 1.0
    assert meta[EVIDENCE_LOG_KEY][-1]["affect_weight"] == 1.0


def test_flag_on_applies_weight(monkeypatch):
    monkeypatch.setenv(AFFECTIVE_ENV, "1")
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=2.0, enabled=None)
    assert meta[ALPHA_KEY] == 2.0


def test_explicit_enabled_overrides_env(monkeypatch):
    """显式传 enabled=False 即使环境变量开着也走等权。"""
    monkeypatch.setenv(AFFECTIVE_ENV, "1")
    meta: dict = {}
    update_confidence(meta, "reinforce", w_affect=5.0, enabled=False)
    assert meta[ALPHA_KEY] == 1.0


# ---------------------------------------------------------------------------
# 6. 审计可追溯
# ---------------------------------------------------------------------------

def test_evidence_log_fields_traceable():
    """一条证据可完整追溯：方向 / 原始情感 / 权重 / α/β 增量 / 时间。"""
    meta: dict = {}
    update_confidence(
        meta, "reinforce",
        w_affect=1.7, raw_affect_score=0.85, enabled=True,
        created_at="2026-09-03T00:00:00Z",
    )
    (entry,) = meta[EVIDENCE_LOG_KEY]
    assert entry["direction"] == "reinforce"
    assert entry["raw_affect_score"] == 0.85
    assert entry["affect_weight"] == 1.7
    assert entry["alpha_delta"] == 1.7
    assert entry["beta_delta"] == 0.0
    assert entry["created_at"] == "2026-09-03T00:00:00Z"
    # 审计增量可解释计数变化
    assert meta[ALPHA_KEY] == entry["alpha_delta"]


def test_evidence_log_bounded_to_default_limit():
    """有界保留最近 DEFAULT_LOG_LIMIT 条，计数保留全部历史。"""
    meta: dict = {}
    for _ in range(25):
        update_confidence(meta, "reinforce", w_affect=1.0, enabled=True,
                          log_limit=DEFAULT_LOG_LIMIT)
    assert len(meta[EVIDENCE_LOG_KEY]) == DEFAULT_LOG_LIMIT
    assert meta[ALPHA_KEY] == 25  # 计数不被日志裁剪截断
    assert sum(e["alpha_delta"] for e in meta[EVIDENCE_LOG_KEY]) == DEFAULT_LOG_LIMIT


def test_evidence_log_custom_limit():
    """log_limit 参数可调小保留条数，且丢弃最旧条目。"""
    meta: dict = {}
    for i in range(5):
        update_confidence(meta, "deprecate", w_affect=1.0, enabled=True,
                          log_limit=3, created_at=f"t{i}")
    assert len(meta[EVIDENCE_LOG_KEY]) == 3
    assert meta[BETA_KEY] == 5.0
    assert meta[EVIDENCE_LOG_KEY][0]["created_at"] == "t2"


def test_evidence_log_limit_env_configurable(monkeypatch):
    """日志上限可由环境变量 WANWEI_EVIDENCE_LOG_LIMIT 配置。"""
    monkeypatch.setenv(LOG_LIMIT_ENV, "2")
    meta: dict = {}
    for _ in range(3):
        update_confidence(meta, "reinforce", enabled=True)
    assert len(meta[EVIDENCE_LOG_KEY]) == 2


def test_evidence_log_compat_with_old_state_without_key():
    """旧数据无 preference_evidence_log 键：从空表开始，不覆盖原始计数。"""
    meta: dict = {ALPHA_KEY: 3, BETA_KEY: 2}
    update_confidence(meta, "reinforce", w_affect=2.0, enabled=True,
                      created_at="ts")
    assert meta[ALPHA_KEY] == 5
    assert meta[BETA_KEY] == 2
    assert len(meta[EVIDENCE_LOG_KEY]) == 1


def test_evidence_log_corrupted_key_recovers():
    """state 里该键被损坏成非列表：重置为空表并继续。"""
    meta: dict = {EVIDENCE_LOG_KEY: "not-a-list"}
    update_confidence(meta, "deprecate", enabled=True, created_at="ts")
    assert isinstance(meta[EVIDENCE_LOG_KEY], list)
    assert len(meta[EVIDENCE_LOG_KEY]) == 1


# ---------------------------------------------------------------------------
# _coerce_count 浮点兼容
# ---------------------------------------------------------------------------

def test_coerce_count_bool_and_int():
    assert _coerce_count(True) == 1
    assert isinstance(_coerce_count(True), int)
    assert _coerce_count(False) == 0
    assert _coerce_count(3) == 3
    assert isinstance(_coerce_count(3), int)


def test_coerce_count_float_preserved():
    """非整数 float 原样保留（加权更新的关键），整数形态 float 也不再丢。"""
    assert _coerce_count(2.5) == 2.5
    assert isinstance(_coerce_count(2.5), float)
    assert _coerce_count(3.0) == 3.0
    assert isinstance(_coerce_count(3.0), float)


def test_coerce_count_garbage_to_zero():
    for bad in (None, "3", {}, [], object(), "1.5"):
        assert _coerce_count(bad) == 0


def test_coerce_count_rejects_non_finite_and_negative_floats():
    """NaN / ±inf / 负 float 不是合法计数，按 0 处理（不放行进 confidence）。"""
    for bad in (float("nan"), float("inf"), float("-inf"), -2.0, -2.5):
        assert _coerce_count(bad) == 0


@pytest.mark.parametrize("dirty", [-2.0, -2.5, float("nan"), float("inf")])
def test_confidence_survives_dirty_counts(dirty):
    """脏计数不得炸成 500。

    放行负数会让 ``preference_alpha=-2.0`` 时后验 α+β=0 → ZeroDivisionError；
    放行 NaN/inf 会让 mean/conf 变成 NaN 悄悄污染下游排序乘子。两者都退回
    无证据先验态。
    """
    result = confidence({ALPHA_KEY: dirty})
    assert result == confidence({})
    assert math.isfinite(result["conf"]) and math.isfinite(result["mean"])


def test_confidence_with_fractional_counts():
    """浮点计数进入 confidence()：后验 α/β/mean/conf 正常。"""
    meta: dict = {}
    for _ in range(2):
        update_confidence(meta, "reinforce", w_affect=1.5, enabled=True)
    posterior = confidence(meta)
    assert meta[ALPHA_KEY] == 3.0
    assert posterior["alpha"] == 4.0
    assert posterior["beta"] == 1.0
    assert 0 < posterior["conf"] < 1


# ---------------------------------------------------------------------------
# 集成层：evolution.reinforce()/deprecate() 透传情感参数并落库审计日志
# ---------------------------------------------------------------------------

def test_integration_evolution_weighted_reinforce(isolated_db, monkeypatch):
    monkeypatch.setenv(AFFECTIVE_ENV, "1")
    cid = cs.write_capsule(
        memory_class="preference", content={"text": "用户喜欢用 Markdown 输出"}
    )["capsule_id"]

    ev.reinforce(cid, affect_weight=2.0, raw_affect_score=0.9)
    st = cs.get_capsule(cid)["state"]
    assert st[ALPHA_KEY] == 2.0
    assert st[BETA_KEY] == 0
    entry = st[EVIDENCE_LOG_KEY][-1]
    assert entry["direction"] == "reinforce"
    assert entry["raw_affect_score"] == 0.9
    assert entry["affect_weight"] == 2.0
    assert entry["alpha_delta"] == 2.0
    assert entry["beta_delta"] == 0.0
    assert entry["created_at"]


def test_integration_evolution_weighted_deprecate(isolated_db, monkeypatch):
    monkeypatch.setenv(AFFECTIVE_ENV, "1")
    cid = cs.write_capsule(
        memory_class="preference", content={"text": "用户喜欢喝美式咖啡"}
    )["capsule_id"]

    ev.deprecate(cid, affect_weight=1.5, raw_affect_score=0.7)
    st = cs.get_capsule(cid)["state"]
    assert st[BETA_KEY] == 1.5
    assert st[ALPHA_KEY] == 0
    entry = st[EVIDENCE_LOG_KEY][-1]
    assert entry["direction"] == "deprecate"
    assert entry["beta_delta"] == 1.5
    assert entry["raw_affect_score"] == 0.7


def test_integration_evolution_flag_off_ignores_weight(isolated_db, monkeypatch):
    monkeypatch.delenv(AFFECTIVE_ENV, raising=False)
    cid = cs.write_capsule(
        memory_class="preference", content={"text": "用户偏好简洁回复"}
    )["capsule_id"]

    ev.reinforce(cid, affect_weight=5.0, raw_affect_score=1.0)
    st = cs.get_capsule(cid)["state"]
    assert st[ALPHA_KEY] == 1.0  # 关闭 → 等权
    entry = st[EVIDENCE_LOG_KEY][-1]
    assert entry["affect_weight"] == 1.0
    assert entry["raw_affect_score"] == 1.0  # 原始信号仍留痕，便于审计


def test_integration_non_preference_untouched_with_flag(isolated_db, monkeypatch):
    """flag 开启也不影响非 preference 记忆：无计数键、无审计日志。"""
    monkeypatch.setenv(AFFECTIVE_ENV, "1")
    cid = cs.write_capsule(
        memory_class="knowledge", content={"text": "一些背景知识"}
    )["capsule_id"]

    ev.reinforce(cid, affect_weight=3.0)
    st = cs.get_capsule(cid)["state"]
    assert ALPHA_KEY not in st
    assert BETA_KEY not in st
    assert EVIDENCE_LOG_KEY not in st


def test_integration_log_accumulates_across_updates(isolated_db, monkeypatch):
    """同一 preference 多次加权更新：日志按时间累积并有界。"""
    monkeypatch.setenv(AFFECTIVE_ENV, "1")
    cid = cs.write_capsule(
        memory_class="preference", content={"text": "用户喜欢先给结论"}
    )["capsule_id"]

    for _ in range(3):
        ev.reinforce(cid, affect_weight=2.0)
    st = cs.get_capsule(cid)["state"]
    assert st[ALPHA_KEY] == 6.0
    assert len(st[EVIDENCE_LOG_KEY]) == 3
    assert all(e["affect_weight"] == 2.0 for e in st[EVIDENCE_LOG_KEY])
