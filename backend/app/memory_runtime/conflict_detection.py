"""写入时的冲突候选检测 — 规则式最小实现。

设计口径(诚实标注):
- **检测 ≠ 裁决**:本模块只产出候选信号,绝不自动转移生命周期。
  规范硬规则「conflicted 必须显式裁决,不自动覆盖」不变 — 裁决走
  ``memoryos.lifecycle.resolve_conflict``,由人或确认流程触发。
- **规则式,非 LLM**:共享实体词 + 覆盖标记词的轻量信号。
  会漏检语义级冲突(如「我喜欢茶」vs「我厌恶茶」),这是已知边界,
  在返回信号的 ``detector`` 字段如实标注 ``rule_v1``。
- **只读既有数据**:检测读取同 scope 的 active/reinforced 记忆,
  不修改任何既有记录。
"""
from __future__ import annotations

import re
from typing import Any

#: 覆盖/替换类标记词 — 新文本含这些词且与既有记忆共享实体时,判为冲突候选
_OVERRIDE_MARKERS = (
    "改成", "改为", "不再是", "不再", "现在用", "换成", "换成了",
    "别再用", "不要用", "不用了", "停止使用", "放弃",
    "actually", "instead", "no longer", "now use", "switched to",
)

#: 英文/数字实体:连续字母数字串,长度 ≥2
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
#: 中文连续段(后续按 bigram 滑窗拆,避免整段成一个实体)
_CJK_RE = re.compile(r"[一-鿿]+")


def _entities(text: str) -> set[str]:
    """实体词集合:英文整词 + 中文 bigram 滑窗。

    中文不依赖分词库(零依赖约束):连续 CJK 段按 2 字滑窗拆,
    「美式咖啡」→ {美式, 式咖, 咖啡}。bigram 会产出噪声词(式咖),
    但冲突检测只需要新旧文本的**交集非空**,噪声词两侧同现概率低,
    不影响判定方向。
    """
    ents = {m.group(0).lower() for m in _LATIN_RE.finditer(text)}
    for seg in _CJK_RE.findall(text):
        ents.update(seg[i : i + 2] for i in range(len(seg) - 1))
    return ents

#: 共享实体词数量阈值 — 低于此不构成「同一主题」
_MIN_SHARED_ENTITIES = 1

#: 召回的同类候选上限(写入路径,不能为检测付出大开销)
_MAX_CANDIDATES = 10


def _has_override_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _OVERRIDE_MARKERS)


def detect_conflict_candidates(
    new_text: str,
    existing: list[dict[str, Any]],
    *,
    max_candidates: int = _MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """对一批既有记忆做冲突候选检测,返回命中的候选列表。

    判定规则(全部满足):
    1. 新文本含覆盖标记词(「改成」「不再是」「instead」等)
    2. 新文本与既有记忆共享至少 ``_MIN_SHARED_ENTITIES`` 个实体词

    每条候选带 ``shared_entities`` 与 ``detector`` 字段,供裁决界面展示证据。
    """
    if not new_text or not _has_override_marker(new_text):
        return []
    new_entities = _entities(new_text)
    if not new_entities:
        return []

    hits: list[dict[str, Any]] = []
    for cap in existing[:max_candidates]:
        content = cap.get("content") or {}
        old_text = str(content.get("text") or content.get("statement") or "")
        if not old_text:
            continue
        shared = new_entities & _entities(old_text)
        if len(shared) >= _MIN_SHARED_ENTITIES:
            hits.append({
                "capsule_id": cap.get("capsule_id"),
                "shared_entities": sorted(shared),
                "detector": "rule_v1",
                "old_text_preview": old_text[:80],
            })
    return hits


def find_conflict_candidates_for_write(
    new_text: str,
    *,
    memory_class: str,
    owner_id: str | None = None,
    soul_id: str | None = None,
    exclude_capsule_id: str | None = None,
) -> list[dict[str, Any]]:
    """写入路径入口:召回同 scope 的活跃同类记忆并检测冲突候选。

    只召回 ``active``/``reinforced`` 状态的同 memory_class 记忆 — 已归档/
    已删除/隔离的记忆不参与冲突判定(它们已不在决策视野内)。
    """
    from .capsule_store import list_capsules

    existing = [
        cap for cap in list_capsules(200, owner_id=owner_id, soul_id=soul_id)
        if (cap.get("state") or {}).get("lifecycle") in ("active", "reinforced")
        and cap.get("memory_class") == memory_class
        and cap.get("capsule_id") != exclude_capsule_id
    ]
    return detect_conflict_candidates(new_text, existing)


__all__ = ["detect_conflict_candidates", "find_conflict_candidates_for_write"]
