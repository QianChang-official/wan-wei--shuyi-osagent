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

"""万枢编程框架 —— 可审计编程记忆桥（差异化能力）。

这是本框架区别于普通 coding agent 的**核心差异点**：把编码过程中的
**决策 / 踩坑 / 约定**写入宛委·枢忆既有的记忆治理层，于是这些记忆天然
获得：

- **不可变账本**：每次写入/删除都追加账目（SQLite 触发器强制 append-only）；
- **生命周期状态机**：记忆状态变更经受控转移表裁决，遗忘不可逆；
- **可证明删除**：删除须经主表 / 全文索引 / 图边 / 向量 / 遗留表五处取证，
  全零才算删净，并可导出删除证书。

换言之——"AI 记住了为什么这么改"，且"能证明它删干净了"。这条链路直接
复用 ``memory_runtime.capsule_store`` 与 ``memoryos.governance``，不新造轮子。

降级口径：记忆库不可用时，本模块**如实返回失败**（``ok=False`` + 原因），
绝不用"假装写入成功"糊弄调用方——与仓库 REVIEW.md 的 implemented/
simulated 边界纪律一致。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 编程记忆的类型
MEMORY_KINDS = ('decision', 'pitfall', 'convention', 'context')
MEMORY_KIND_LABELS = {
    'decision': '决策',
    'pitfall': '踩坑',
    'convention': '约定',
    'context': '背景',
}

# 写入记忆时的记忆类别（memory_class），用于检索隔离
CODING_MEMORY_CLASS = 'coding'


def _session_provenance(session_id: str, workspace: str, kind: str) -> dict[str, Any]:
    return {
        'origin': 'tool',
        'writer_identity': 'coding_framework',
        'source_type': 'cross_scene_trace',
        'source_ids': [session_id],
        'evidence_ids': [],
        'verified': False,
        'verification_method': 'unknown',
        'coding_session_id': session_id,
        'coding_workspace': workspace,
        'coding_kind': kind,
    }


def remember(
    *,
    session_id: str,
    workspace: str,
    kind: str,
    text: str,
    title: str = '',
    owner_id: str | None = None,
) -> dict[str, Any]:
    """把一条编程记忆写入可审计账本。返回 ``{ok, capsule_id, ...}``。"""
    body = (text or '').strip()
    if not body:
        return {'ok': False, 'error': 'empty_memory', 'message': '记忆内容为空'}
    if kind not in MEMORY_KINDS:
        kind = 'context'
    try:
        from ..memory_runtime.capsule_store import write_capsule
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': 'memory_unavailable', 'message': f'记忆模块不可用：{exc}'}

    content = {
        'title': title or MEMORY_KIND_LABELS.get(kind, kind),
        'text': body,
        'kind': kind,
        'session_id': session_id,
    }
    try:
        capsule = write_capsule(
            memory_class=CODING_MEMORY_CLASS,
            content=content,
            source_type='cross_scene_trace',
            scene='coding',
            task_type='planning',
            risk_class='low',
            write_intent='explicit',
            affects_future_behavior=False,
            source_trust='normal',
            provenance=_session_provenance(session_id, workspace, kind),
            owner_id=owner_id,
        )
    except Exception as exc:  # noqa: BLE001 —— 记忆写入失败不阻断编码流程，但如实上报
        logger.warning('[coding.memory] 写入失败：%r', exc)
        return {'ok': False, 'error': 'write_failed', 'message': str(exc)}

    capsule_id = capsule.get('capsule_id') or capsule.get('id') or ''
    lifecycle = ((capsule.get('state') or {}).get('lifecycle') if isinstance(capsule.get('state'), dict) else None) or 'candidate'
    policy = ((capsule.get('governance') or {}).get('policy_result') if isinstance(capsule.get('governance'), dict) else None)
    return {
        'ok': True,
        'capsule_id': capsule_id,
        'kind': kind,
        'kind_label': MEMORY_KIND_LABELS.get(kind, kind),
        'lifecycle': lifecycle,
        'policy_result': policy,
        'title': content['title'],
        'text': body,
    }


def list_memories(*, session_id: str | None = None, owner_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    """列出编程记忆；给定 session_id 时按 provenance 过滤。"""
    try:
        from ..memory_runtime.capsule_store import list_capsules
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': 'memory_unavailable', 'message': str(exc), 'items': []}
    try:
        capsules = list_capsules(limit=limit, owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': 'read_failed', 'message': str(exc), 'items': []}

    items: list[dict[str, Any]] = []
    for cap in capsules:
        provenance = cap.get('provenance') or {}
        if provenance.get('writer_identity') != 'coding_framework':
            continue
        if session_id and provenance.get('coding_session_id') != session_id:
            continue
        content = cap.get('content') or {}
        items.append({
            'capsule_id': cap.get('capsule_id') or cap.get('id'),
            'kind': content.get('kind') or provenance.get('coding_kind') or 'context',
            'kind_label': MEMORY_KIND_LABELS.get(content.get('kind') or provenance.get('coding_kind') or 'context', '背景'),
            'title': content.get('title') or '',
            'text': content.get('text') or '',
            'session_id': provenance.get('coding_session_id') or '',
            'created_at': cap.get('created_at') or '',
            'lifecycle': ((cap.get('state') or {}).get('lifecycle') if isinstance(cap.get('state'), dict) else '') or '',
        })
    return {'ok': True, 'count': len(items), 'items': items}


def forget(*, capsule_id: str, owner_id: str | None = None) -> dict[str, Any]:
    """硬删除一条编程记忆，并返回**五处取证**的删除完整性证据。

    这是"把删除升格为证据"的落地：返回体里的 ``deletion_verification``
    逐项列出主表 / FTS / 图边 / 向量 / 遗留表的残留计数，全零即删净。
    """
    if not capsule_id:
        return {'ok': False, 'error': 'missing_id', 'message': '缺少 capsule_id'}
    try:
        from ..memory_runtime.capsule_store import forget_capsules
        from ..memoryos.governance import verify_deletion
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': 'memory_unavailable', 'message': str(exc)}

    try:
        result = forget_capsules([capsule_id], mode='hard_delete', owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': 'forget_failed', 'message': str(exc)}

    try:
        verification = verify_deletion(capsule_id)
    except Exception as exc:  # noqa: BLE001
        verification = {'error': str(exc), 'complete': None}

    return {
        'ok': True,
        'status': result.get('status', 'forgotten'),
        'capsule_id': capsule_id,
        'audit_id': result.get('audit_id'),
        'deletion_verification': verification,
        'native_vector': result.get('native_vector'),
    }


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    """按类型统计记忆条数，供前端记忆面板展示。"""
    counts: dict[str, int] = dict.fromkeys(MEMORY_KINDS, 0)
    for item in items:
        kind = item.get('kind') or 'context'
        counts[kind] = counts.get(kind, 0) + 1
    return counts
