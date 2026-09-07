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

"""偏好记忆的 Beta 置信度建模（算法设计框架 B1）。

设计文档：``notes/09-algorithm-design-framework.md`` §B1。

把 preference capsule 的 ``state`` 从「拍一个 strength 数字」升级为贝叶斯统计
后验：用 Beta-Binomial 共轭对「这条偏好被采纳 / 被违背」的次数建模。

    prior:        Beta(α₀=1, β₀=1)          # 无信息先验
    被采纳/命中:   α += 1（reflect_task 判定 helpful）
    被违背/失配:   β += 1（用户纠正 / 显式拒绝确认）
    均值:         E = α / (α + β)           # 后验均值
    置信度:       conf = 1 − 2·sd  # sd 即 Beta 后验标准差

计数键写在 capsule ``state`` 内（``preference_alpha`` / ``preference_beta``），
向后兼容——旧读者读到这两个新键也无感；``confidence()`` 对缺失键按 0 处理，
默认落在无信息先验 Beta(1,1) 上。

情感证据权重（Affective Evidence Weight，issue #179）
----------------------------------------------------

**Emotion ≠ Preference**：情感不是偏好本身。本模块禁止 ``高情感 == 高偏好置信度``
的直接映射——情感信号绝不直接产生偏好（如 ``emotion_intensity > threshold →
create_preference()``）。情感显著性只作为「本次偏好证据的强弱调制信号」参与单次
Beta 更新，偏好方向仍完全由 reinforce / deprecate 证据决定：

    Preference Evidence + 情感显著性 → w_affect → Beta 后验更新

加权更新公式（默认等权；feature flag 关闭时与旧语义逐位一致）：

    reinforce → α += w_affect
    deprecate → β += w_affect

- 默认 ``w_affect = 1.0``（中性权重，严格保持既有 Beta 行为）。
- **feature flag 关闭时，无论传入什么权重一律回落 1.0**，从而同一套代码/数据流
  可直接跑「Beta」与「Beta + Affect」两组消融，而不是比较两套同时变化的系统。
- 合法权重为**有限正实数**，并裁剪到配置区间 ``[w_min, w_max]``（保守默认
  ``[0.5, 3.0]``）；NaN / inf / 非正数 / 非数值（含 bool）等非法输入一律
  **精确回落 1.0，不参与区间裁剪**——非法 = 无有效情感信号 = 中性基线，即使
  配置区间不含 1.0（如 ``[2, 4]``）非法输入也不会被抬到 w_min / 压到 w_max。
  区间裁剪只作用于合法的情感权重。
- 每次更新的证据参数**追加**到 ``state[preference_evidence_log]``（有界保留最近
  ``log_limit`` 条，默认 20，上限可配），可追溯「哪次证据 → 什么情感信号 → 用
  什么权重 → 对 α/β 产生什么增量」。旧数据没有该键时自动从空表开始，**不覆盖
  原始证据**。

配置项（环境变量；函数也接受等价的显式参数，显式参数优先于环境变量）：

    WANWEI_AFFECTIVE_EVIDENCE   feature flag 开关，真值取 1/true/yes/on，默认关
    WANWEI_AFFECTIVE_W_MIN       默认 0.5
    WANWEI_AFFECTIVE_W_MAX       默认 3.0
    WANWEI_EVIDENCE_LOG_LIMIT    默认 20

本模块是纯计算、不依赖数据库层，方便检索侧（C2 排序乘子）与漂移检测直接复用
（读取时钟仅用于给审计日志打时间戳，不触碰任何外部状态）。
"""

import math
import os
from typing import Any

from ..utils.datetime_utils import utc_now_iso_compact

#: state JSON 里的计数键名（命名随 state 既有风格：snake_case 整数计数；
#: 情感加权后计数可为非整数 float，见 ``_coerce_count``）。
ALPHA_KEY = "preference_alpha"
BETA_KEY = "preference_beta"

#: state JSON 里的证据审计日志键名（追加式列表，不覆盖原始证据）。
EVIDENCE_LOG_KEY = "preference_evidence_log"

#: Beta 先验参数（无信息先验，等价于各先观察一次）。
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0

#: 权重上下界保守默认：未经实验支持前不凭经验放大单次情感事件的影响。
DEFAULT_W_MIN = 0.5
DEFAULT_W_MAX = 3.0
#: 审计日志有界保留条数默认值。
DEFAULT_LOG_LIMIT = 20

#: feature flag / 权重界 / 日志上限的环境变量名。
AFFECTIVE_EVIDENCE_ENV = "WANWEI_AFFECTIVE_EVIDENCE"
W_MIN_ENV = "WANWEI_AFFECTIVE_W_MIN"
W_MAX_ENV = "WANWEI_AFFECTIVE_W_MAX"
LOG_LIMIT_ENV = "WANWEI_EVIDENCE_LOG_LIMIT"

#: 布尔环境变量真值集合（与 platform_api.guards 同口径）。
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def affective_weight_enabled() -> bool:
    """情感证据权重 feature flag 是否开启（读 ``WANWEI_AFFECTIVE_EVIDENCE``）。

    默认关闭。关闭时 ``update_confidence`` 对任何传入权重一律回落 1.0，保证与
    旧等权 Beta 语义严格一致，可作为消融的严格基线。
    """
    return _env_flag(AFFECTIVE_EVIDENCE_ENV)


def _coerce_count(value: Any) -> int | float:
    """把 state 里的计数键值规整为 int / float。

    - bool / int → int 原样；
    - float（含非整数）→ 仅当**有限且非负**时 float 原样保留——情感加权更新会
      产生非整数计数（如 1.5 次证据），不能像旧实现那样把非整数 float 当 0
      丢掉；但 NaN / ±inf / 负数不是合法计数，放行会让 ``confidence()`` 的
      ``alpha*beta`` 出现负值或非有限值，进而 ``math.sqrt`` 抛 math domain
      error、``total`` 归零抛 ZeroDivisionError（如 ``preference_alpha=-2.0``
      时 α+β=0），恰好违反本函数「不让脏 state 炸成 500」的契约。
    - 其余垃圾值（``"3"``、``None``、``{"x": 1}``、NaN、-2.5 等迁移损坏/老数据
      形态）一律按 0 处理：容错策略——宁可当无证据，也不让非数值 state 一路
      TypeError/ValueError 炸到生命周期接口返回 500。
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value >= 0.0:
            return value
    return 0


def _clamp_weight(raw: float, w_min: float, w_max: float) -> float:
    """把**合法**情感权重裁剪到 ``[w_min, w_max]``。

    只对合法（有限正实数）权重生效；非法输入不经此函数，由
    ``_normalize_weight`` 精确回落 1.0（不参与区间裁剪）。
    """
    return min(max(raw, w_min), w_max)


def _normalize_weight(
    w_affect: Any,
    *,
    enabled: bool,
    w_min: float,
    w_max: float,
) -> float:
    """把一次证据的情感权重归一为合法权重。

    规则（保守，宁可用等权也不让噪声放大 Beta 参数）：
    - flag 关闭 → 一律 1.0（严格等权基线，忽略任何传入权重）；
    - 非法输入（NaN / inf / 非正数 / 非数值，含 bool）→ **精确回落 1.0**，
      不参与区间裁剪——非法 = 无有效情感信号 = 中性基线，即使配置区间不含
      1.0（如 ``[2, 4]``）也不会被抬到 w_min / 压到 w_max；
    - 合法有限正数 → 裁剪到 ``[w_min, w_max]``。

    区间裁剪只作用于合法权重；非法权重恒为精确 1.0，任何路径不产生越界、也
    不会被配置区间改写。
    """
    if not enabled:
        return 1.0
    if isinstance(w_affect, bool):
        return 1.0  # bool 不是合法的连续权重 → 中性基线
    if isinstance(w_affect, (int, float)):
        w = float(w_affect)
    else:
        try:
            w = float(w_affect)
        except (TypeError, ValueError):
            return 1.0
    if math.isnan(w) or math.isinf(w) or w <= 0.0:
        return 1.0
    return _clamp_weight(w, w_min, w_max)


def _resolve_bounds(
    w_min: float | None,
    w_max: float | None,
) -> tuple[float, float]:
    """解析本次更新的权重区间：显式参数 > 环境变量 > 保守默认。

    若配置出的区间非法（非正 / 下界大于上界 / 非有限），回落保守默认，保证
    ``0 < w_min <= w_max`` 恒成立。
    """
    lo = DEFAULT_W_MIN if w_min is None else w_min
    hi = DEFAULT_W_MAX if w_max is None else w_max
    if w_min is None:
        lo = _env_float(W_MIN_ENV, lo)
    if w_max is None:
        hi = _env_float(W_MAX_ENV, hi)
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return DEFAULT_W_MIN, DEFAULT_W_MAX
    invalid = (
        math.isnan(lo_f) or math.isinf(lo_f)
        or math.isnan(hi_f) or math.isinf(hi_f)
        or not (0.0 < lo_f <= hi_f)
    )
    if invalid:
        return DEFAULT_W_MIN, DEFAULT_W_MAX
    return lo_f, hi_f


def _resolve_log_limit(log_limit: int | None) -> int:
    """解析审计日志有界条数：显式参数 > 环境变量 > 默认 20，最小 1。"""
    if log_limit is None:
        limit = _env_int(LOG_LIMIT_ENV, DEFAULT_LOG_LIMIT)
    else:
        try:
            limit = int(log_limit)
        except (TypeError, ValueError):
            limit = DEFAULT_LOG_LIMIT
    return max(1, limit)


def _append_evidence_log(
    meta: dict[str, Any],
    *,
    direction: str,
    raw_affect_score: Any,
    affect_weight: float,
    alpha_delta: float,
    beta_delta: float,
    created_at: str,
    log_limit: int,
) -> None:
    """把一条证据审计记录追加到 state，并裁剪到最近 ``log_limit`` 条。"""
    log = meta.get(EVIDENCE_LOG_KEY)
    if not isinstance(log, list):
        log = []  # 旧数据无该键 / 被损坏 → 从空表开始，不覆盖原始证据
    else:
        log = list(log)  # 复制后再改写，避免与调用方持有的列表共享变更
    log.append({
        "direction": direction,
        "raw_affect_score": raw_affect_score,
        "affect_weight": affect_weight,
        "alpha_delta": alpha_delta,
        "beta_delta": beta_delta,
        "created_at": created_at,
    })
    meta[EVIDENCE_LOG_KEY] = log[-log_limit:]


def update_confidence(
    meta: dict[str, Any],
    outcome: str,
    *,
    w_affect: float = 1.0,
    raw_affect_score: float | None = None,
    enabled: bool | None = None,
    w_min: float | None = None,
    w_max: float | None = None,
    log_limit: int | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """按一次反馈结果更新偏好计数（就地修改 ``meta`` 并返回）。

    Args:
        meta: capsule 的 ``state`` 字典（含 ``preference_alpha`` /
            ``preference_beta`` 计数键，缺省视为 0）。
        outcome: ``"reinforce"`` 表示偏好被采纳 → α 计数 +w_affect；
            ``"deprecate"`` 表示偏好被违背 → β 计数 +w_affect。
        w_affect: 本次证据的情感调制权重（issue #179）。默认 1.0 = 中性证据，
            行为与旧等权 Beta 完全一致；情感信号只调制证据强度、不直接产生偏好。
        raw_affect_score: 原始情感信号（情感模型的输出），仅作审计追溯原样落
            日志，不参与计算。
        enabled: 情感加权 feature flag。``None`` 时读取环境变量
            ``WANWEI_AFFECTIVE_EVIDENCE``（默认关闭）；关闭时无论传入什么
            ``w_affect`` 都按 1.0 等权更新。
        w_min / w_max: 权重裁剪区间，``None`` 时读取环境变量
            ``WANWEI_AFFECTIVE_W_MIN`` / ``WANWEI_AFFECTIVE_W_MAX``，缺省
            ``[0.5, 3.0]``。区间裁剪只作用于合法的情感权重；非法输入
            （NaN / inf / 非正数 / 非数值，含 bool）精确回落 1.0、不参与裁剪，
            任何路径不产生越界权重。
        log_limit: ``preference_evidence_log`` 有界保留条数，``None`` 时读
            ``WANWEI_EVIDENCE_LOG_LIMIT``，缺省 20。
        created_at: 审计记录时间戳，缺省取当前 UTC 紧凑 ISO 时间。

    Raises:
        ValueError: ``outcome`` 不是 ``"reinforce"`` / ``"deprecate"``。
    """
    if outcome not in ("reinforce", "deprecate"):
        raise ValueError(
            f"outcome 必须是 'reinforce' 或 'deprecate'，得到: {outcome!r}"
        )
    flag = affective_weight_enabled() if enabled is None else bool(enabled)
    lo, hi = _resolve_bounds(w_min, w_max)
    w = _normalize_weight(w_affect, enabled=flag, w_min=lo, w_max=hi)
    limit = _resolve_log_limit(log_limit)
    if created_at is None:
        created_at = utc_now_iso_compact()

    alpha = _coerce_count(meta.get(ALPHA_KEY))
    beta = _coerce_count(meta.get(BETA_KEY))
    if outcome == "reinforce":
        alpha_delta, beta_delta = w, 0.0
    else:
        alpha_delta, beta_delta = 0.0, w
    alpha += alpha_delta
    beta += beta_delta

    # 计数键始终写全（含 0）：让 state JSON 的 Beta 模型状态自明，
    # 集成侧无需处理「键缺失」分支。
    meta[ALPHA_KEY] = alpha
    meta[BETA_KEY] = beta
    _append_evidence_log(
        meta,
        direction=outcome,
        raw_affect_score=raw_affect_score,
        affect_weight=w,
        alpha_delta=alpha_delta,
        beta_delta=beta_delta,
        created_at=created_at,
        log_limit=limit,
    )
    return meta


def confidence(meta: dict[str, Any]) -> dict[str, float]:
    """计算当前 Beta 后验参数与置信度。

    返回 ``{"alpha", "beta", "mean", "conf"}``：

    - ``alpha`` / ``beta``：后验参数（先验 + 累计计数）；
    - ``mean``：后验均值 α/(α+β)——即设计文档里写回 ``strength`` 的候选值；
    - ``conf``：置信度 = 1 − 2·sqrt(αβ/((α+β)²(α+β+1)))，样本越多越自信。

    .. warning::
        ``conf`` 的语义是「证据充分度」，**不是**「偏好质量先验」：零证据先验态
        conf≈0.42 属正常现象。下游（如 C2 排序乘子）不得直接乘裸 conf，应设
        下限（如 ``max(conf_floor, conf)``，``conf_floor`` 建议进 tuning），
        由使用方负责映射。
    """
    alpha = PRIOR_ALPHA + _coerce_count(meta.get(ALPHA_KEY))
    beta = PRIOR_BETA + _coerce_count(meta.get(BETA_KEY))
    total = alpha + beta
    mean = alpha / total
    conf = 1.0 - 2.0 * math.sqrt(
        alpha * beta / (total * total * (total + 1.0))
    )
    return {"alpha": alpha, "beta": beta, "mean": mean, "conf": conf}


__all__ = [
    "ALPHA_KEY",
    "BETA_KEY",
    "EVIDENCE_LOG_KEY",
    "PRIOR_ALPHA",
    "PRIOR_BETA",
    "DEFAULT_W_MIN",
    "DEFAULT_W_MAX",
    "DEFAULT_LOG_LIMIT",
    "affective_weight_enabled",
    "confidence",
    "update_confidence",
]
