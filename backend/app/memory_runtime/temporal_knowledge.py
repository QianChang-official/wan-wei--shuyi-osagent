"""TKE 时序核心：知识双时态（valid_time / transaction_time）与演化时间轴 — issue #204。

设计背景（与 #202 的分工）
--------------------------
``knowledge_evolution``（#202 / PR #203）回答「知识是什么状态、如何演化」；
本模块补上**时间维度的真值语义**，回答「知识在什么时候为真」：

```text
valid_time:       知识在世界中为真的时间区间（state.valid_from … state.valid_until）
transaction_time: 系统记录时间（created_at / updated_at，DB 自带）
```

两轴区分回答评审必问的问题——「2025 年 7 月时系统认为默认浏览器是什么？」
按 ``created_at`` 排序会把「今天导入的历史知识」误判为最新；as-of 查询按
valid_time 判真、按 transaction_time 判可见，两个错误都避开。

存储口径（零新表，与 #202 一致）
--------------------------------
- ``state.valid_from`` / ``state.valid_until``：valid_time 区间。``valid_until``
  已被 ``lifecycle.scan_stale`` 消费（到期扫描），本模块补上 ``valid_from``
  与区间判定；读取时 state 优先、provenance 回退（与 ``_valid_until`` 同口径）。
- ``state.verified_at``：最近验证时间。provenance 里只有 ``verified`` 布尔位
  （区分不了「验证过」与「多久前验证过」）；因 ``update_capsule`` 只写 state，
  时间戳落 state（写入能力所在处，诚实标注而非硬塞 provenance）。
- ``state.reference_count``：引用计数。可从图上 evidence_for/derived_from 入边
  实时数出——**不落库**，作为 freshness 的动态输入（落库会与图漂移）。

as-of 查询语义
--------------
``knowledge_as_of(ids, at=T, mode=...)`` 两种模式（诚实区分）：
- ``truth``（默认）：只按 valid_time 判真——「T 时刻世界上什么是真的」。
  延迟导入场景（今天导入 2025 年历史知识）靠它回答；命中者的记录时间
  随结果返回，「事后导入」可辨识。
- ``belief``：valid_time **且** transaction_time（``created_at <= T``）双
  过滤——「T 时刻系统*当时*认为什么」，严格双时态口径。

两种模式各答各的问题，混用会把「世界真值」冒充「系统当时认知」（或反
过来把严格口径的错误强加给历史导入场景）。

时效冲突升级（区间判定）
------------------------
#202 的 temporal 冲突只看覆盖标记词（「改用」「现在是」）。本模块的
``classify_temporal_relation`` 在**双方都有显式 valid_time** 时升级为区间判定：
区间不重叠且顺序衔接 → 是版本演化（走 supersedes），不是冲突；区间重叠 →
才是真冲突（两段真值同时声称覆盖同一时段）。

Timeline 聚合
-------------
``knowledge_timeline`` 合并三个数据源成单一时间轴（升序事件流）：
1. 演化链成员（``trace_evolution``，含版本与状态）；
2. 每个成员的账本事件（``ledger_history``：write/update/transition/delete/
   knowledge_evolution…，全部带时间戳——数据早已在，缺的就是这层聚合）；
3. 双时态区间（valid_time + transaction_time 摘要）。

历史回放即「时间轴 + as-of」的组合：给定任意 T，轴上 T 之前的事件构成当时
的系统世界观，``knowledge_as_of`` 给出当时的 active knowledge。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .knowledge_evolution import (
    MAX_EVOLUTION_DEPTH,
    _load_json,
    _parse_ts,
    _text_of,
    _ensure_version,
    trace_evolution,
)

logger = logging.getLogger(__name__)

#: 账本 op_type → 时间轴事件名（未知 op_type 原样透传，不吞新事件类型）。
_LEDGER_EVENT_NAMES = {
    "write": "created",
    "update": "updated",
    "transition": "lifecycle_transition",
    "delete": "forgotten",
    "write_rejected": "write_rejected",
    "knowledge_evolution": "evolution_edge",
    "knowledge_conflict_marked": "conflict_marked",
    "knowledge_derivation": "derivation_edge",
    "quarantine": "quarantined",
}


# ---------------------------------------------------------------------------
# valid_time 读写
# ---------------------------------------------------------------------------

def get_valid_time(cap: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    """读知识的 valid_time 区间 ``(valid_from, valid_until)``。

    读取口径与 ``lifecycle._valid_until`` 同族：state 优先、provenance 回退
    （``write_capsule`` 允许调用方自带 provenance，两侧都认，避免哪边写的
    哪边才生效）。无界的端点返回 ``None``。
    """
    state = _load_json(cap.get("state"), {}) or {}
    prov = _load_json(cap.get("provenance"), {}) or {}
    valid_from = _parse_ts(state.get("valid_from") or prov.get("valid_from"))
    valid_until = _parse_ts(state.get("valid_until") or prov.get("valid_until"))
    return valid_from, valid_until


def set_valid_time(
    capsule_id: str,
    *,
    valid_from: str | None = None,
    valid_until: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    """写入/更新知识的 valid_time 区间（经 ``update_capsule``，账本留痕）。

    ``None`` 参数表示「不改该端点」（不是清空——清空语义用空字符串显式
    传入并按无界处理）。非法时间串 422（ValueError）。
    """
    from .capsule_store import get_capsule, update_capsule

    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise KeyError(capsule_id)
    if cap.get("memory_class") != "knowledge":
        raise ValueError("valid_time 只适用于 knowledge 类胶囊")

    state = dict(cap["state"] or {})
    for key, raw in (("valid_from", valid_from), ("valid_until", valid_until)):
        if raw is None:
            continue
        if str(raw).strip() == "":
            state.pop(key, None)  # 显式清空 → 无界
            continue
        parsed = _parse_ts(str(raw))
        if parsed is None:
            raise ValueError(f"{key} 不是合法的 ISO 时间: {raw!r}")
        state[key] = str(raw)
    # 区间自洽校验：from 必须早于 until（都显式存在时）。
    new_from, new_until = get_valid_time({**cap, "state": state})
    if new_from and new_until and new_from >= new_until:
        raise ValueError(
            f"valid_time 区间非法: valid_from {new_from.isoformat()} "
            f">= valid_until {new_until.isoformat()}"
        )
    return update_capsule(
        capsule_id,
        state=state,
        owner_id=owner_id,
        soul_id=soul_id,
        actor=actor,
        reason=f"tke_valid_time:{valid_from or '~'}..{valid_until or '~'}",
    )


def valid_at(cap: dict[str, Any], at: datetime) -> bool:
    """valid_time 是否覆盖时刻 ``at``（无界端点视为开区间）。"""
    valid_from, valid_until = get_valid_time(cap)
    if valid_from and at < valid_from:
        return False
    if valid_until and at >= valid_until:
        return False
    return True


def recorded_at(cap: dict[str, Any], at: datetime) -> bool:
    """transaction_time 可见性：``created_at <= at``（之后才记录的系统不知道）。"""
    created = _parse_ts(cap.get("created_at"))
    if created is None:
        return True  # 无记录时间（脏数据）：保守放行，由 valid_time 兜底
    return created <= at


# ---------------------------------------------------------------------------
# as-of 查询
# ---------------------------------------------------------------------------

def knowledge_as_of(
    capsule_ids: list[str],
    *,
    at: str | datetime,
    mode: str = "truth",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """时刻 ``at`` 的 active knowledge（历史回放核心）。

    两种 as-of 语义（``mode``，诚实区分、不混用）：

    - ``"truth"``（默认，世界真值）：只按 **valid_time** 判定——「2025 年 7
      月世界上默认浏览器是什么」。**延迟导入场景**（今天导入 2025 年的
      历史知识）靠这个模式回答；命中者的 transaction_time（记录时间）
      随结果如实返回，调用方能看出「这是事后导入的历史」。
    - ``"belief"``（系统当时认知）：valid_time **且** transaction_time
      （``created_at <= at``）双过滤——「2025 年 7 月系统*当时*认为什么」。
      严格双时态口径；今天才导入的知识在历史时刻上系统并不认识。

    多条命中时取 ``knowledge_version`` 最高 → created_at 最新 → id 升序
    （确定性决胜，与 suggest_active_knowledge 同口径）。全不命中返回
    ``active=None`` 并如实上报各阶段淘汰名单，不静默。
    """
    if mode not in ("truth", "belief"):
        raise ValueError(f"mode 必须是 'truth' 或 'belief': {mode!r}")
    if isinstance(at, str):
        at_dt = _parse_ts(at)
        if at_dt is None:
            raise ValueError(f"at 不是合法的 ISO 时间: {at!r}")
    else:
        at_dt = at
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)

    from .capsule_store import get_capsules_batch

    by_id = get_capsules_batch(
        list(dict.fromkeys(capsule_ids)), owner_id=owner_id, soul_id=soul_id
    )
    unknown = [cid for cid in capsule_ids if cid not in by_id]
    candidates = [
        by_id[cid] for cid in dict.fromkeys(capsule_ids)
        if cid in by_id and by_id[cid].get("memory_class") == "knowledge"
    ]

    visible: list[dict[str, Any]] = []
    rejected_unrecorded: list[str] = []
    for cap in candidates:
        if mode == "truth" or recorded_at(cap, at_dt):
            visible.append(cap)
        else:
            rejected_unrecorded.append(cap["capsule_id"])

    covering: list[dict[str, Any]] = []
    rejected_interval: list[dict[str, Any]] = []
    for cap in visible:
        if valid_at(cap, at_dt):
            covering.append(cap)
        else:
            vf, vu = get_valid_time(cap)
            rejected_interval.append({
                "capsule_id": cap["capsule_id"],
                "valid_from": vf.isoformat() if vf else None,
                "valid_until": vu.isoformat() if vu else None,
            })

    if not covering:
        return {
            "at": at_dt.isoformat(),
            "mode": mode,
            "active": None,
            "note": "无 valid_time 覆盖该时刻的知识",
            "rejected_not_recorded": rejected_unrecorded,
            "rejected_interval": rejected_interval,
            "unknown_ids": unknown,
        }

    covering.sort(key=lambda c: (
        -_ensure_version(c),
        str(c.get("created_at") or ""),
        c["capsule_id"],
    ))
    # created_at 决胜要「新在前」——版本降序已排，同版本内再按 created_at 降序。
    top_version = _ensure_version(covering[0])
    same_version = [c for c in covering if _ensure_version(c) == top_version]
    same_version.sort(key=lambda c: str(c.get("created_at") or ""), reverse=True)
    winner = same_version[0]
    vf, vu = get_valid_time(winner)
    return {
        "at": at_dt.isoformat(),
        "mode": mode,
        "active": {
            "capsule_id": winner["capsule_id"],
            "text": _text_of(winner),
            "knowledge_version": _ensure_version(winner),
            "lifecycle": (winner.get("state") or {}).get("lifecycle"),
            "valid_from": vf.isoformat() if vf else None,
            "valid_until": vu.isoformat() if vu else None,
            # transaction_time 如实随行：truth 模式下调用方能看出「事后导入」。
            "recorded_at": winner.get("created_at"),
        },
        "candidates_considered": len(candidates),
        "rejected_not_recorded": rejected_unrecorded,
        "rejected_interval": rejected_interval,
        "unknown_ids": unknown,
    }


# ---------------------------------------------------------------------------
# 时效冲突升级：区间判定
# ---------------------------------------------------------------------------

def classify_temporal_relation(
    new_cap: dict[str, Any],
    old_cap: dict[str, Any],
) -> dict[str, Any] | None:
    """双方都有显式 valid_time 时的区间判定（升级 #202 的标记词口径）。

    - 区间**不重叠**且顺序衔接（old.until <= new.from）→ ``evolution``：
      不同时段的不同真值，是版本演化（走 supersedes），**不是冲突**；
    - 区间**重叠** → ``conflict``（type=temporal）：两段真值声称覆盖同一
      时段，这才是需要裁决的真冲突；
    - 任一方无显式 valid_from → ``None``：区间证据不足，回落标记词口径
      （``classify_conflict`` 的 temporal 分支）。
    """
    new_from, new_until = get_valid_time(new_cap)
    old_from, old_until = get_valid_time(old_cap)
    if new_from is None or old_from is None:
        return None
    if old_until is not None and new_from >= old_until:
        return {
            "relation": "evolution",
            "evidence": (
                f"valid_time 区间不重叠: 旧 [{old_from.isoformat()}, "
                f"{old_until.isoformat()}) → 新 [{new_from.isoformat()}, …) "
                "——不同时段的不同真值，是版本演化而非冲突"
            ),
        }
    overlap_start = max(new_from, old_from)
    overlap_end = min(
        new_until or datetime.max.replace(tzinfo=timezone.utc),
        old_until or datetime.max.replace(tzinfo=timezone.utc),
    )
    if overlap_end > overlap_start:
        return {
            "relation": "conflict",
            "type": "temporal",
            "evidence": (
                f"valid_time 区间重叠于 [{overlap_start.isoformat()}, "
                f"{overlap_end.isoformat()})——两段真值声称覆盖同一时段"
            ),
        }
    # 有 from 无 until 且顺序不可判定（互不覆盖也不重叠的判定证据不足）
    return None


# ---------------------------------------------------------------------------
# Timeline 聚合
# ---------------------------------------------------------------------------

def knowledge_timeline(
    capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    max_depth: int = MAX_EVOLUTION_DEPTH,
    ledger_limit: int = 100,
) -> dict[str, Any]:
    """单条知识（含其演化链）的完整时间轴：账本事件 + 演化链 + 双时态。

    返回结构::

        {
          "root": capsule_id,
          "chain": [链成员摘要（版本/状态/valid_time/文本预览）…],
          "events": [  # 升序事件流
            {"at": ..., "event": created|updated|evolution_edge|…,
             "capsule_id": ..., "detail": ...},
          ],
          "as_of_demo": {"at": T, "active": ...},  # 链上最近一次演化的 as-of
        }

    事件时间用账本 ``created_at``（ISO 字符串保持字典序=时间序）。账本行
    时间倒序返回，这里翻成升序（时间轴语义）。
    """
    from ..memoryos.governance import ledger_history
    from .capsule_store import get_capsule, get_capsules_batch

    root_cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not root_cap:
        raise KeyError(capsule_id)

    path = trace_evolution(
        capsule_id, owner_id=owner_id, soul_id=soul_id, max_depth=max_depth
    )
    chain_ids = [p["capsule_id"] for p in path if p.get("capsule_id")]
    by_id = get_capsules_batch(chain_ids, owner_id=owner_id, soul_id=soul_id)

    chain: list[dict[str, Any]] = []
    for cid in chain_ids:
        cap = by_id.get(cid)
        if not cap:
            continue
        vf, vu = get_valid_time(cap)
        chain.append({
            "capsule_id": cid,
            "knowledge_version": _ensure_version(cap),
            "lifecycle": (cap.get("state") or {}).get("lifecycle"),
            "valid_from": vf.isoformat() if vf else None,
            "valid_until": vu.isoformat() if vu else None,
            "transaction_created_at": cap.get("created_at"),
            "text_preview": _text_of(cap)[:80],
        })

    events: list[dict[str, Any]] = []
    for cid in chain_ids:
        for row in ledger_history(
            cid, limit=ledger_limit, owner_id=owner_id, soul_id=soul_id
        ):
            op = str(row.get("op_type") or "")
            events.append({
                "at": row.get("created_at"),
                "event": _LEDGER_EVENT_NAMES.get(op, op),
                "capsule_id": cid,
                "detail": row.get("reason") or op,
            })
    events.sort(key=lambda e: (str(e.get("at") or ""), e["capsule_id"]))

    # as-of 演示点：链上最新成员的 valid_from（若有无界起点则用 created_at）。
    as_of_demo = None
    if chain_ids:
        root_cap = by_id.get(chain_ids[0])
        if root_cap is not None:
            vf, _vu = get_valid_time(root_cap)
            demo_at = vf or _parse_ts(root_cap.get("created_at"))
            if demo_at is not None:
                as_of_demo = knowledge_as_of(
                    chain_ids, at=demo_at, owner_id=owner_id, soul_id=soul_id
                )
    return {
        "root": capsule_id,
        "chain": chain,
        "events": events,
        "as_of_demo": as_of_demo,
    }


# ---------------------------------------------------------------------------
# freshness 输入：verified_at / reference_count
# ---------------------------------------------------------------------------

def mark_verified(
    capsule_id: str,
    *,
    verified_at: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    """记录知识的最近验证时间（``state.verified_at``，账本留痕）。

    ``verified_at`` 缺省取当前时间。provenance 的 ``verified`` 布尔位由写入
    路径按 source_type 自动判定，本函数不碰它——时间戳是对布尔位的补充
    （「验证过」vs「多久前验证过」），不是替代。
    """
    from ..utils.datetime_utils import utc_now_iso_compact
    from .capsule_store import get_capsule, update_capsule

    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise KeyError(capsule_id)
    if verified_at is not None and _parse_ts(verified_at) is None:
        raise ValueError(f"verified_at 不是合法的 ISO 时间: {verified_at!r}")
    state = dict(cap["state"] or {})
    state["verified_at"] = verified_at or utc_now_iso_compact()
    return update_capsule(
        capsule_id,
        state=state,
        owner_id=owner_id,
        soul_id=soul_id,
        actor=actor,
        reason="tke_verified",
    )


def reference_count(
    capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    raw_edges: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    """知识被引用的次数：指向它的 evidence_for / derived_from 入边数。

    实时从图上数（不落库）——落库计数会与 relation_edges 漂移，宁可每次
    重数（端侧小图，全内存口径与 rrf_fusion 一致）。批量调用方可用
    ``raw_edges`` 传入预加载的边表共享一次全表读。
    """
    from .knowledge_evolution import _load_knowledge_raw_edges

    raw = raw_edges if raw_edges is not None else _load_knowledge_raw_edges(
        owner_id=owner_id, soul_id=soul_id
    )
    return sum(
        1
        for src, elist in raw.items()
        if src != capsule_id
        for e in elist
        if e["type"] in ("evidence_for", "derived_from") and e["target"] == capsule_id
    )


def get_verified_at(cap: dict[str, Any]) -> datetime | None:
    """读最近验证时间（state.verified_at；无则回落 None=从未验证）。"""
    state = _load_json(cap.get("state"), {}) or {}
    return _parse_ts(state.get("verified_at"))


__all__ = [
    "get_valid_time",
    "set_valid_time",
    "valid_at",
    "recorded_at",
    "knowledge_as_of",
    "classify_temporal_relation",
    "knowledge_timeline",
    "mark_verified",
    "reference_count",
    "get_verified_at",
]
