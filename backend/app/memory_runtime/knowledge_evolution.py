"""Knowledge Conflict Resolution & Evolution（知识冲突消解与知识演化）— issue #202。

设计背景
--------
偏好记忆已有完整演化链（Preference Graph + EGPM + 冲突裁决建议），但知识记忆
仍停留在「记录 → 检索」：新旧知识冲突无法显式表达（默认浏览器 Firefox vs
Chrome 同时共存），演化路径不可追踪，版本不可治理。本模块为 knowledge 类
capsule 建对应机制，形成双演化体系。

复用与零新表（与 preference_graph 同一存储口径）
------------------------------------------------
- **节点即 capsule**：知识版本就是 ``memory_class='knowledge'`` 的行，
  版本号写在 ``state.knowledge_version``（写入时自动 1 起，演化时递增）。
- **边即 relation_edges**：四类受控边 ``supersedes``（新替旧，演化主链）/
  ``conflicts_with``（冲突对冲）/ ``derived_from``（派生溯源）/
  ``invalidates``（证伪失效——B 出现使 A 直接失效，不替代）。
- 版本链字段复用既有 ``state.superseded_by`` / ``state.supersedes``
  （lifecycle.resolve_conflict 与 evolution.supersede 已维护的同一字段），
  知识状态机**不发明新状态**——issue 里的 active/superseded/deprecated/
  conflicted/forgotten 全部映射到既有 lifecycle 状态
  （active/reinforced→active，superseded/deprecated→deprecated，
  conflicted→conflicted，forgotten→forgotten）。

冲突检测（四类，规则式、可解释）
--------------------------------
1. **事实冲突**（fact）：同 key 不同 value——「默认浏览器=Firefox」vs
   「=Chrome」。抽取 ``K=V`` 结构（中英文等号、冒号、is/为/是），同 key
   异 value 判冲突。
2. **状态冲突**（status）：互斥状态对（运行中/已停止、开/关、
   running/stopped…），共享主语 + 状态词落互斥表。
3. **配置冲突**（config）：``参数=数值`` 同参数不同数值（端口 8080 vs
   9000）。与事实冲突同构，但 value 是数值/量纲词，单独分类供报表。
4. **时效冲突**（temporal）：新文本含覆盖标记词（「改用」「现在是」「流程
   已更新」），复用 conflict_detection 的标记词口径。

裁决（建议式，与 conflict_resolution 同一治理底线）
----------------------------------------------------
四因子 ``knowledge_confidence = 0.30×recency + 0.30×trust +
0.25×source_authority + 0.15×usage``，**只推荐 active knowledge，不自动
覆盖**；实际转移仍走 ``lifecycle.resolve_conflict(actor='human')`` 或本模块
的 ``evolve_knowledge``（演化路径，同样经状态机校验+账本留痕）。

检索增强（只读、纯增量）
------------------------
``knowledge_rerank``：对检索候选按版本状态加权——active 知识乘子 1.0、
superseded/deprecated 按链深衰减、conflicted 标记但降权；不 bump usage。
与 ``preference_rerank`` 平行独立（偏好管「该信谁」，知识管「哪个版本」）。

Knowledge Explain（可解释性）
-----------------------------
``explain_knowledge``：一条知识的当前版本、历史版本链（沿 supersedes
回溯）、冲突记录、裁决建议原因、来源证据，一次查询全部返回。
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

from ..db import get_conn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 受控词表
# ---------------------------------------------------------------------------

#: 知识演化边类型受控词表。supersedes/invalidates 语义区别：
#: supersedes = 新知识**替代**旧知识（Firefox→Chrome）；invalidates =
#: 新知识**证伪**旧知识但不提供替代（「服务器没有装 Firefox」使旧记录失效）。
KNOWLEDGE_EDGE_TYPES = frozenset({
    "supersedes",      # 新知识替代旧知识（版本演化主链）
    "conflicts_with",  # 冲突对冲（待裁决信号）
    "derived_from",    # 派生溯源（B 由 A 推导而来）
    "invalidates",     # 证伪失效（B 出现使 A 失效，非替代）
})

#: 知识冲突四分类（issue #202 检测类型 1-4）。
CONFLICT_TYPES = ("fact", "status", "config", "temporal")

#: knowledge_confidence 四因子默认权重（进 tuning ``knowledge_evolution`` 段）。
DEFAULT_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "recency": 0.30,
    "trust": 0.30,
    "source_authority": 0.25,
    "usage": 0.15,
}

#: 互斥状态词表（状态冲突）。同主语下两个状态词落同一组 → 冲突。
_MUTUAL_EXCLUSION_GROUPS = (
    {"运行中", "已停止", "已停机", "停止", "running", "stopped", "halted"},
    {"开启", "关闭", "已启用", "已禁用", "enabled", "disabled", "on", "off"},
    {"在线", "离线", "online", "offline"},
    {"正常", "故障", "healthy", "failed", "broken"},
)

#: 时效冲突覆盖标记词（与 conflict_detection._OVERRIDE_MARKERS 同源口径）。
_TEMPORAL_MARKERS = (
    "改用", "改为", "换成", "换成了", "现在是", "不再是", "不再",
    "已更新", "已变更", "升级为", "迁移到", "instead", "no longer",
    "now use", "switched to", "migrated to",
)

#: K=V 抽取正则：中英文等号/冒号/is/为/是（左右各 1-40 字符）。
_KV_RE = re.compile(
    r"([\w一-鿿\-·]{1,40})\s*(?:=|：|:|是|为|is)\s*([\w一-鿿\-./%]{1,40})",
    re.IGNORECASE,
)

#: 演化链回溯深度上限（防退化 DAG，与 preference_graph.MAX_CHAIN_DEPTH 同口径）。
MAX_EVOLUTION_DEPTH = 100

#: raw 边读取上限（relation_edges JSON 列无索引，软截断 + warning）。
RAW_EDGE_LOAD_LIMIT = 2000


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_json(value: Any, default: Any) -> Any:
    import json

    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default


def _text_of(cap: dict[str, Any]) -> str:
    content = _load_json(cap.get("content"), {}) or {}
    return str(content.get("text") or content.get("statement") or "")


# ---------------------------------------------------------------------------
# 冲突检测（四类）
# ---------------------------------------------------------------------------

def _kv_pairs(text: str) -> dict[str, str]:
    """抽取 ``K=V`` 对（小写归一 key）。"""
    return {m.group(1).strip().lower(): m.group(2).strip() for m in _KV_RE.finditer(text or "")}


def _status_words(text: str) -> set[str]:
    """命中的互斥状态词（小写归一）。"""
    lowered = (text or "").lower()
    return {
        w
        for group in _MUTUAL_EXCLUSION_GROUPS
        for w in group
        if w.lower() in lowered
    }


def _is_numeric(value: str) -> bool:
    return bool(re.fullmatch(r"[\d.]+%?", value or ""))


def _has_temporal_marker(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _TEMPORAL_MARKERS)


def _words(text: str) -> set[str]:
    """词集合：拉丁/数字整词 + 连续 CJK 段的 bigram 滑窗。

    与 conflict_detection._entities 同思路：中文不依赖分词库（零依赖
    约束），bigram 会产出噪声词，但共享主语判定只需要**交集非空**。
    """
    ents = {m.group(0).lower() for m in _LATIN_WORD_RE.finditer(text or "")}
    for seg in _CJK_RE.findall(text or ""):
        ents.update(seg[i : i + 2] for i in range(len(seg) - 1))
    return ents


#: 拉丁/数字整词（长度 ≥2）。
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
#: 连续中文段。
_CJK_RE = re.compile(r"[一-鿿]+")


def _shared_subject(a: str, b: str) -> str | None:
    """两条文本共享的主语：任一 K=V key 交集，否则共享词里最长者。"""
    ka, kb = _kv_pairs(a), _kv_pairs(b)
    shared_keys = set(ka) & set(kb)
    if shared_keys:
        return sorted(shared_keys)[0]
    overlap = _words(a) & _words(b)
    return max(overlap, key=len) if overlap else None


def classify_conflict(
    new_text: str,
    old_text: str,
) -> dict[str, Any] | None:
    """对一对（新, 旧）知识文本做四类冲突检测。

    返回 ``{"type": fact|status|config|temporal, "subject": 主语,
    "new_value": ..., "old_value": ..., "evidence": ...}``，无冲突返回
    ``None``。纯函数、可解释——每类给出触发证据，供裁决界面展示。

    判定优先级（事实 > 状态 > 配置 > 时效，先具体后宽泛）：
    - fact: 同 key 异 value（value 非纯数值）
    - status: 共享主语 + 双方状态词落同一互斥组
    - config: 同 key 异 value 且 value 是数值（端口 8080 vs 9000）
    - temporal: 共享主语 + 新文本含覆盖标记词
    """
    if not new_text or not old_text:
        return None
    new_kv, old_kv = _kv_pairs(new_text), _kv_pairs(old_text)
    for key in sorted(set(new_kv) & set(old_kv)):
        nv, ov = new_kv[key], old_kv[key]
        if nv == ov:
            continue
        # 值恰为互斥状态对（redis is online / offline）时升为 status 冲突
        # ——语义上这是主语的状态翻转而不是任意的值差异。
        for group in _MUTUAL_EXCLUSION_GROUPS:
            if nv.lower() in group and ov.lower() in group:
                return {
                    "type": "status",
                    "subject": key,
                    "new_value": nv,
                    "old_value": ov,
                    "evidence": f"主语「{key}」状态互斥: {ov} → {nv}",
                }
        ctype = "config" if (_is_numeric(nv) and _is_numeric(ov)) else "fact"
        return {
            "type": ctype,
            "subject": key,
            "new_value": nv,
            "old_value": ov,
            "evidence": f"同 key「{key}」值不同: {ov} → {nv}",
        }
    # 状态冲突：共享主语 + 状态词互斥
    subject = _shared_subject(new_text, old_text)
    if subject is not None:
        ns, os_ = _status_words(new_text), _status_words(old_text)
        for group in _MUTUAL_EXCLUSION_GROUPS:
            if (ns & group) and (os_ & group) and (ns & group) != (os_ & group):
                return {
                    "type": "status",
                    "subject": subject,
                    "new_value": sorted(ns & group)[0],
                    "old_value": sorted(os_ & group)[0],
                    "evidence": f"主语「{subject}」状态互斥: {sorted(os_ & group)[0]} → {sorted(ns & group)[0]}",
                }
        if _has_temporal_marker(new_text):
            return {
                "type": "temporal",
                "subject": subject,
                "new_value": None,
                "old_value": None,
                "evidence": f"新知识含覆盖标记词，主语「{subject}」语义已被更新",
            }
    return None


def detect_knowledge_conflicts(
    new_capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    candidate_limit: int = 200,
) -> list[dict[str, Any]]:
    """写入后的冲突检测入口：对一条新 knowledge 胶囊找同 scope 冲突候选。

    复用 ``list_capsules`` 召回 active/reinforced 的 knowledge 记忆
    （与 conflict_detection.find_conflict_candidates_for_write 同口径——
    已归档/隔离的知识不参与判定），逐对跑 ``classify_conflict`` 四类
    检测。**只产出信号，不转移生命周期**（治理底线）。
    """
    from .capsule_store import get_capsule, list_capsules

    cap = get_capsule(new_capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap or cap.get("memory_class") != "knowledge":
        return []
    new_text = _text_of(cap)

    hits: list[dict[str, Any]] = []
    for existing in list_capsules(candidate_limit, owner_id=owner_id, soul_id=soul_id):
        cid = existing.get("capsule_id")
        if cid == new_capsule_id or existing.get("memory_class") != "knowledge":
            continue
        if str((existing.get("state") or {}).get("lifecycle") or "") not in ("active", "reinforced"):
            continue
        verdict = classify_conflict(new_text, _text_of(existing))
        if verdict:
            hits.append({
                "capsule_id": cid,
                "old_text_preview": _text_of(existing)[:80],
                "detector": "knowledge_v1",
                **verdict,
            })
    return hits


# ---------------------------------------------------------------------------
# knowledge_confidence 四因子
# ---------------------------------------------------------------------------

def _recency_factor(cap: dict[str, Any], *, at: datetime | None) -> float:
    """时间新近性：30 天半衰（与 conflict_resolution._recency_factor 同族）。"""
    state = _load_json(cap.get("state"), {}) or {}
    last = _parse_ts(
        state.get("last_accessed_at") or cap.get("updated_at") or cap.get("created_at")
    )
    if last is None:
        return 0.5
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    return math.exp(-(math.log(2.0) / 30.0) * days)


def _trust_factor(cap: dict[str, Any]) -> float:
    """治理信任分：policy_gate 写入时的 trust_score（0-1，缺省 0.5）。"""
    gov = _load_json(cap.get("governance"), {}) or {}
    try:
        return min(1.0, max(0.0, float(gov.get("trust_score", 0.5))))
    except (TypeError, ValueError):
        return 0.5


_SOURCE_AUTHORITY = {
    "manual_config": 1.0,
    "user_input": 0.8,
    "eval": 0.6,
    "cross_scene_trace": 0.4,
    "tool_result": 0.2,
}


def _source_factor(cap: dict[str, Any]) -> float:
    """来源可信度：复用 conflict_resolution.SOURCE_AUTHORITY 分级。"""
    prov = _load_json(cap.get("provenance"), {}) or {}
    src = str(prov.get("source_type") or prov.get("origin") or "")
    return _SOURCE_AUTHORITY.get(src, 0.5)


def _usage_factor(cap: dict[str, Any]) -> float:
    """使用因子：usage_count log 压缩归一（与 conflict_resolution._reinforce_factor 同式）。"""
    state = _load_json(cap.get("state"), {}) or {}
    n = max(0, int(state.get("usage_count", 0) or 0))
    return math.log1p(n) / math.log1p(50)


def knowledge_confidence(
    capsule: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """单条知识的四因子置信度（可解释分解随分数返回）。

    ``knowledge_confidence = 0.30×recency + 0.30×trust + 0.25×source + 0.15×usage``

    显式 ``weights`` 参数优先；缺省读 tuning ``knowledge_evolution`` 段
    （缺失/异常回落内置常量）。
    """
    w = dict(DEFAULT_CONFIDENCE_WEIGHTS)
    if weights:
        for key in w:
            if key in weights:
                w[key] = float(weights[key])
    else:
        try:
            from ..tuning.service import TUNING_DEFAULTS

            published = TUNING_DEFAULTS.get("knowledge_evolution", {})
            for key in w:
                value = published.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    w[key] = float(value)
        except Exception as exc:  # noqa: BLE001 —— 调参模块不可用时回落常量
            logger.warning(
                "tuning defaults 不可用，knowledge_confidence 权重回落内置常量: %s", exc
            )
    factors = {
        "recency": round(_recency_factor(capsule, at=at), 4),
        "trust": round(_trust_factor(capsule), 4),
        "source_authority": round(_source_factor(capsule), 4),
        "usage": round(_usage_factor(capsule), 4),
    }
    score = sum(w[k] * factors[k] for k in factors)
    return {"score": round(score, 4), "factors": factors}


def suggest_active_knowledge(
    capsule_ids: list[str],
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    weights: dict[str, float] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """对一组（冲突中的）知识胶囊建议 active knowledge。

    **只建议，不执行**（auto_execute 恒 False）：实际生效路径是
    ``evolve_knowledge``（supersedes 演化）或 ``lifecycle.resolve_conflict``
    （人工裁决）。查不到的 id 如实跳过并上报，不猜测。
    """
    from .capsule_store import get_capsules_batch

    by_id = get_capsules_batch(
        list(dict.fromkeys(capsule_ids)),
        owner_id=owner_id, soul_id=soul_id,
    )
    known = [
        cid for cid in dict.fromkeys(capsule_ids)
        if cid in by_id and by_id[cid].get("memory_class") == "knowledge"
    ]
    if not known:
        return {
            "suggested_active": None,
            "auto_execute": False,
            "note": "无可评估的 knowledge 胶囊",
            "unknown_ids": [cid for cid in capsule_ids if cid not in by_id],
        }
    scored: list[tuple[str, dict[str, Any]]] = []
    for cid in known:
        kc = knowledge_confidence(by_id[cid], weights=weights, at=at)
        scored.append((cid, kc))

    # 决胜序：分数降序 → created_at **新者在前**（同秒写入的 capsule 四因子
    # 完全同分，纯 id 字典序会把更旧的知识误选为 active）→ 仍并列按 id
    # 升序保确定性。created_at 是 ISO 字符串，倒序用 cmp 表达。
    import functools

    def _cmp(a: tuple[str, dict[str, Any]], b: tuple[str, dict[str, Any]]) -> int:
        if a[1]["score"] != b[1]["score"]:
            return -1 if a[1]["score"] > b[1]["score"] else 1
        ca = str(by_id[a[0]].get("created_at") or "")
        cb = str(by_id[b[0]].get("created_at") or "")
        if ca != cb:
            return -1 if ca > cb else 1  # ISO 字符串比较 = 时间比较，新在前
        return -1 if a[0] < b[0] else (0 if a[0] == b[0] else 1)

    scored.sort(key=functools.cmp_to_key(_cmp))
    top_id, top = scored[0]
    return {
        "suggested_active": top_id,
        "suggested_active_score": top["score"],
        "suggested_active_factors": top["factors"],
        "ranking": [
            {"capsule_id": cid, "score": kc["score"], "name": _text_of(by_id[cid])[:64]}
            for cid, kc in scored
        ],
        "auto_execute": False,
        "note": "建议式裁决: 需 evolve_knowledge 或 resolve_conflict(actor='human') 显式确认才生效",
        "unknown_ids": [cid for cid in capsule_ids if cid not in by_id],
    }


# ---------------------------------------------------------------------------
# 版本演化（supersedes / invalidates）
# ---------------------------------------------------------------------------

def _next_version(cap: dict[str, Any]) -> int:
    state = _load_json(cap.get("state"), {}) or {}
    try:
        return int(state.get("knowledge_version", 1)) + 1
    except (TypeError, ValueError):
        return 2


def _ensure_version(cap: dict[str, Any]) -> int:
    state = _load_json(cap.get("state"), {}) or {}
    try:
        v = int(state.get("knowledge_version", 1))
    except (TypeError, ValueError):
        v = 1
    return max(1, v)


def evolve_knowledge(
    new_capsule_id: str,
    old_capsule_id: str,
    *,
    edge_type: str = "supersedes",
    conflict_type: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    """记录知识演化边并把旧知识转 deprecated（版本号递增）。

    - ``supersedes``：新知识**替代**旧知识。旧知识经 ``apply_transition``
      转 deprecated（状态机校验 + 账本留痕），版本链字段
      ``superseded_by`` 追加新 id（幂等——已就位则不再转移，零账本噪音，
      与 preference_graph.record_preference_evolution 修复后的同一口径）。
      新知识 state 落 ``knowledge_version = 旧版本+1``。
    - ``invalidates``：新知识**证伪**旧知识但不提供替代。同样把旧知识转
      deprecated，但不递增版本号（没有继任版本可谈），reason 措辞为
      invalidated。
    - ``derived_from``：只写派生边，**不动生命周期、不动版本号**（溯源
      关系不是替换关系）。
    - ``conflicts_with``：只写边标记冲突（治理底线：裁决须显式）。

    Raises:
        KeyError: 胶囊不存在。
        ValueError: 非法 edge_type / 非 knowledge 类胶囊。
    """
    if edge_type not in KNOWLEDGE_EDGE_TYPES:
        raise ValueError(
            f"edge_type 必须是 {sorted(KNOWLEDGE_EDGE_TYPES)} 之一: {edge_type!r}"
        )
    from .capsule_store import get_capsule, update_capsule

    new_cap = get_capsule(new_capsule_id, owner_id=owner_id, soul_id=soul_id)
    old_cap = get_capsule(old_capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not new_cap:
        raise KeyError(new_capsule_id)
    if not old_cap:
        raise KeyError(old_capsule_id)
    for cap, label in ((new_cap, "new"), (old_cap, "old")):
        if cap.get("memory_class") != "knowledge":
            raise ValueError(
                f"{label} capsule 必须是 knowledge 类（得到 {cap.get('memory_class')!r}）"
            )

    def _edge_present(edges: list[dict[str, Any]], dst: str, etype: str) -> bool:
        return any(
            isinstance(e, dict)
            and e.get("type") == etype
            and (e.get("target") or e.get("target_id") or e.get("to")) == dst
            for e in edges or []
        )

    new_edges = list(new_cap["relation_edges"] or [])
    edge_added = not _edge_present(new_edges, old_capsule_id, edge_type)
    if edge_added:
        new_edges.append({
            "target": old_capsule_id,
            "type": edge_type,
            "direction": "outgoing",
            "conflict_type": conflict_type,
            "created_at": _now_compact(),
        })

    result: dict[str, Any] = {
        "edge_type": edge_type,
        "new_capsule_id": new_capsule_id,
        "old_capsule_id": old_capsule_id,
        "edge_added": edge_added,
        "lifecycle_transitioned": False,
        "version_assigned": None,
    }

    # 版本号：supersedes 语义下新知识 = 旧版本+1（演化链长度即版本号）。
    if edge_type in ("supersedes", "invalidates"):
        from ..memoryos.governance import append_ledger
        from ..memoryos.lifecycle import LifecycleState, apply_transition

        superseded_by = list((old_cap["state"] or {}).get("superseded_by") or [])
        chain_mutated = new_capsule_id not in superseded_by
        if chain_mutated:
            superseded_by.append(new_capsule_id)
            reason_word = "superseded" if edge_type == "supersedes" else "invalidated"
            apply_transition(
                old_capsule_id,
                LifecycleState.DEPRECATED.value,
                f"knowledge_{reason_word}_by:{new_capsule_id}",
                actor=actor,
                owner_id=owner_id,
                soul_id=soul_id,
                state_patch={
                    "superseded_by": superseded_by,
                    "deprecation_reason": f"{reason_word}_by:{new_capsule_id}",
                },
            )
        result["lifecycle_transitioned"] = chain_mutated
        if edge_type == "supersedes":
            new_state = dict(new_cap["state"] or {})
            if "knowledge_version" not in new_state:
                new_state["knowledge_version"] = _ensure_version(old_cap) + 1
                result["version_assigned"] = new_state["knowledge_version"]
                # 版本号与边同一事务写入（update_capsule 自带 before/after 账本）。
                if not edge_added:
                    update_capsule(
                        new_capsule_id, state=new_state,
                        owner_id=owner_id, soul_id=soul_id, actor=actor,
                        reason="knowledge_version_assign",
                    )
                else:
                    # edge_added 路径下面 update_capsule 会带 relation_edges，
                    # 这里把 state 一并传下去，避免两次写。
                    pass
        append_ledger(
            op_type="knowledge_evolution",
            capsule_id=new_capsule_id,
            actor=actor,
            reason=f"{edge_type}:{old_capsule_id}",
            owner_id=owner_id or (new_cap.get("provenance") or {}).get("owner_id"),
            soul_id=soul_id or (new_cap.get("provenance") or {}).get("soul_id"),
        )
    else:
        from ..memoryos.governance import append_ledger

        append_ledger(
            op_type="knowledge_conflict_marked" if edge_type == "conflicts_with" else "knowledge_derivation",
            capsule_id=new_capsule_id,
            actor=actor,
            reason=f"{edge_type}:{old_capsule_id}",
            owner_id=owner_id or (new_cap.get("provenance") or {}).get("owner_id"),
            soul_id=soul_id or (new_cap.get("provenance") or {}).get("soul_id"),
        )

    if edge_added:
        patch_state = None
        if edge_type == "supersedes" and result["version_assigned"] is not None:
            patch_state = dict(new_cap["state"] or {})
            patch_state["knowledge_version"] = result["version_assigned"]
        update_capsule(
            new_capsule_id,
            state=patch_state,
            relation_edges=new_edges,
            owner_id=owner_id,
            soul_id=soul_id,
            actor=actor,
            reason=f"knowledge_evolution:{edge_type}",
        )
    return result


# ---------------------------------------------------------------------------
# 演化图回溯 / Knowledge Explain
# ---------------------------------------------------------------------------

def _load_knowledge_raw_edges(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    load_limit: int = RAW_EDGE_LOAD_LIMIT,
) -> dict[str, list[dict[str, Any]]]:
    """读原始 relation_edges 出边（含 deprecated 节点），供链回溯。

    与 preference_graph._load_raw_out_edges 同口径：软截断 + 探测 warning。
    """
    from .capsule_store import _scope_predicate

    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    where = "relation_edges IS NOT NULL AND relation_edges != '[]'"
    params: list[Any] = list(scope_params)
    if scope_sql:
        where += f" AND {scope_sql}"
    params.append(int(load_limit) + 1)
    rows = get_conn().execute(
        f"SELECT capsule_id, relation_edges FROM memory_capsules_v2 "
        f"WHERE {where} LIMIT ?",
        params,
    ).fetchall()
    if len(rows) > load_limit:
        rows = rows[:load_limit]
        logger.warning(
            "_load_knowledge_raw_edges 命中 %d 行上限，剩余带边胶囊未读入——"
            "知识演化链回溯可能不完整（宁可漏不可挂死）",
            load_limit,
        )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cid = row["capsule_id"]
        for edge in _load_json(row["relation_edges"], []) or []:
            if not isinstance(edge, dict):
                continue
            dst = edge.get("target") or edge.get("target_id") or edge.get("to")
            etype = str(edge.get("type") or "")
            if dst and dst != cid:
                out.setdefault(cid, []).append({"target": str(dst), "type": etype})
    return out


def trace_evolution(
    capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    max_depth: int = MAX_EVOLUTION_DEPTH,
) -> list[dict[str, Any]]:
    """沿 supersedes 出边回溯演化链（新 → 旧），返回版本路径。

    限深防退化 DAG（环由 seen 防）。返回逐节点摘要（id / 版本 / 状态 /
    文本预览），无链返回空列表。
    """
    from .capsule_store import get_capsules_batch

    raw = _load_knowledge_raw_edges(owner_id=owner_id, soul_id=soul_id)
    chain_ids: list[str] = []
    seen = {capsule_id}
    frontier = [capsule_id]
    truncated = False
    for _ in range(max_depth):
        if not frontier:
            break
        nxt: list[str] = []
        for src in frontier:
            for edge in raw.get(src) or []:
                if edge["type"] in ("supersedes", "invalidates") and edge["target"] not in seen:
                    seen.add(edge["target"])
                    chain_ids.append(edge["target"])
                    nxt.append(edge["target"])
        frontier = nxt
    else:
        if frontier:
            truncated = True
            logger.warning(
                "知识演化链深度超过 %d（capsule_id=%s），回溯截断", max_depth, capsule_id
            )
    all_ids = [capsule_id] + chain_ids
    by_id = get_capsules_batch(all_ids, owner_id=owner_id, soul_id=soul_id)
    path: list[dict[str, Any]] = []
    for cid in all_ids:
        cap = by_id.get(cid)
        if not cap:
            continue
        path.append({
            "capsule_id": cid,
            "knowledge_version": _ensure_version(cap),
            "lifecycle": (cap.get("state") or {}).get("lifecycle"),
            "text_preview": _text_of(cap)[:80],
            "created_at": cap.get("created_at"),
        })
    if truncated:
        path.append({"capsule_id": None, "note": "depth_truncated"})
    return path


def explain_knowledge(
    capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Knowledge Explain：为什么使用该知识？

    一次返回：当前版本与状态、四因子置信度、演化链（沿 supersedes 回溯的
    历史版本路径）、冲突记录（指向它/它指向的 conflicts_with 边）、裁决建议
    （对冲突对建议 active）、来源证据（provenance 摘要）。
    """
    from .capsule_store import get_capsule

    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise KeyError(capsule_id)

    evolution_path = trace_evolution(
        capsule_id, owner_id=owner_id, soul_id=soul_id
    )
    kc = knowledge_confidence(cap, at=at)

    # 冲突记录：双向 conflicts_with 边。
    raw = _load_knowledge_raw_edges(owner_id=owner_id, soul_id=soul_id)
    out_conflicts = [
        {"with": e["target"], "direction": "outgoing"}
        for e in raw.get(capsule_id, []) if e["type"] == "conflicts_with"
    ]
    in_conflicts = [
        {"with": src, "direction": "incoming"}
        for src, elist in raw.items()
        if src != capsule_id
        for e in elist
        if e["type"] == "conflicts_with" and e["target"] == capsule_id
    ]
    conflicts = in_conflicts + out_conflicts
    suggestion = None
    if conflicts:
        suggestion = suggest_active_knowledge(
            [capsule_id] + [c["with"] for c in conflicts],
            owner_id=owner_id, soul_id=soul_id, at=at,
        )

    prov = cap.get("provenance") or {}
    return {
        "capsule_id": capsule_id,
        "text": _text_of(cap),
        "knowledge_version": _ensure_version(cap),
        "lifecycle": (cap.get("state") or {}).get("lifecycle"),
        "confidence": kc,
        "evolution_path": evolution_path,
        "conflicts": conflicts,
        "resolution_suggestion": suggestion,
        "provenance": {
            "source_type": prov.get("source_type") or prov.get("origin"),
            "verified": prov.get("verified"),
            "writer_identity": prov.get("writer_identity"),
        },
    }


# ---------------------------------------------------------------------------
# 检索增强（只读）
# ---------------------------------------------------------------------------

#: 各 lifecycle 状态的知识乘子（active 1.0；stale 0.85 与检索惩罚同族；
#: conflicted 降权但仍可见——裁决界面要能检索到它）。
_LIFECYCLE_MULTIPLIER = {
    "active": 1.0,
    "reinforced": 1.0,
    "stale": 0.85,
    "conflicted": 0.60,
}

#: superseded/deprecated 的链深衰减：每被一层替换衰减一档（0.5^depth，
#: 封底 0.1）——越旧的版本检索优先级越低，但可追溯（explain 能找到）。
_SUPERSEDED_DECAY_FLOOR = 0.1


def _superseded_depths(
    raw_edges: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """全图「被替换代数」传递计算：``depth(X) = 1 + max(depth(superseder))``。

    直接入边数只给「被几个版本直接顶替」（多分支替换时会低估）；代数
    语义要求传递——v3 supersede v2 supersede v1 时 depth(v1)=2、
    depth(v2)=1、depth(v3)=0。环由 visited 防护（取首次到达深度即可，
    环是脏数据，防挂死优先于精确）。
    """
    # 反向邻接：X 的直接 superseder 集合（supersedes/invalidates 入边）。
    reverse: dict[str, set[str]] = {}
    for src, elist in raw_edges.items():
        for e in elist:
            if e["type"] in ("supersedes", "invalidates"):
                reverse.setdefault(e["target"], set()).add(src)

    depth: dict[str, int] = {}
    visiting: set[str] = set()

    def _depth_of(node: str) -> int:
        if node in depth:
            return depth[node]
        if node in visiting:
            return 0  # 环：脏数据防护，取 0 不递归
        visiting.add(node)
        supers = reverse.get(node)
        d = 0 if not supers else 1 + max(_depth_of(s) for s in supers)
        visiting.discard(node)
        depth[node] = d
        return d

    for node in reverse:
        _depth_of(node)
    return depth


def knowledge_rerank(
    candidates: list[dict[str, Any]],
    *,
    top_k: int | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[dict[str, Any]]:
    """对检索候选按知识版本状态加权（只读，不 bump usage）。

    ``final = retrieval_score × lifecycle_multiplier × superseded_decay``

    - active/reinforced → 1.0；stale → 0.85；conflicted → 0.60（可见但降权）；
    - deprecated（被 supersedes/invalidates）→ 0.5^代数 封底 0.1；
    - 非知识候选恒等通过（偏好/情感通道不受影响）；
    - ``knowledge_multiplier`` / ``superseded_depth`` 字段随结果返回。

    与 ``preference_rerank`` 平行独立：偏好管「该信谁」，知识管「哪个版本」。
    """
    if not candidates:
        return []
    know_ids = [c["capsule_id"] for c in candidates if c.get("memory_class") == "knowledge"]
    raw_edges: dict[str, list[dict[str, Any]]] = {}
    depths: dict[str, int] = {}
    if know_ids:
        raw_edges = _load_knowledge_raw_edges(owner_id=owner_id, soul_id=soul_id)
        depths = _superseded_depths(raw_edges)

    out = []
    for cap in candidates:
        if cap.get("memory_class") != "knowledge":
            cap = dict(cap)
            cap["knowledge_multiplier"] = 1.0
            out.append((float(cap.get("retrieval_score") or 0.0), cap))
            continue
        cap = dict(cap)
        state = cap.get("state") or {}
        lifecycle = str(state.get("lifecycle") or "active")
        mult = _LIFECYCLE_MULTIPLIER.get(lifecycle, 1.0)
        depth = 0
        if lifecycle in ("deprecated", "superseded"):
            depth = depths.get(cap["capsule_id"], 1)
            mult = max(_SUPERSEDED_DECAY_FLOOR, 0.5 ** depth)
        # 基础分缺省取中性 0.5：真实胶囊没有 retrieval_score 字段（那是检索
        # 路径的计算产物），按 0.0 处理会让所有候选同分并列、排序退化为 id
        # 字典序——乘子再准也体现不到顺序上。
        base = float(cap.get("retrieval_score", 0.5))
        cap["knowledge_multiplier"] = round(mult, 4)
        cap["superseded_depth"] = depth
        out.append((base * mult, cap))
    out.sort(key=lambda item: (-item[0], item[1]["capsule_id"]))
    ranked = [cap for _, cap in out]
    return ranked[:top_k] if top_k is not None else ranked


def _now_compact() -> str:
    from ..utils.datetime_utils import utc_now_iso_compact

    return utc_now_iso_compact()


__all__ = [
    "KNOWLEDGE_EDGE_TYPES",
    "CONFLICT_TYPES",
    "DEFAULT_CONFIDENCE_WEIGHTS",
    "MAX_EVOLUTION_DEPTH",
    "classify_conflict",
    "detect_knowledge_conflicts",
    "knowledge_confidence",
    "suggest_active_knowledge",
    "evolve_knowledge",
    "trace_evolution",
    "explain_knowledge",
    "knowledge_rerank",
]
