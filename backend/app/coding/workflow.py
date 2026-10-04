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

"""万枢编程框架 —— 工作流编排（受控并发）。

参照 ZCode「工作流并发限制可动态调整、大工作流实时状态」与 deepseek-harness
``workflow`` 的思路：把一组有依赖关系的节点（工具调用 / 子智能体）编排成
DAG，按**并发上限**并行推进，任一节点失败按依赖关系阻断其下游，其余分支
继续——不做"一损俱损"的全局中止。

并发通过 ``ThreadPoolExecutor`` 落实：节点执行是同步 IO（文件/子进程/HTTP），
线程池是恰当模型；并发上限被钳制在 ``[1, MAX_WORKFLOW_CONCURRENCY]``，
防止调用方传入失控值。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from . import constants

logger = logging.getLogger(__name__)


class WorkflowError(ValueError):
    """工作流定义非法（环 / 未知依赖 / 空图）。"""


@dataclass
class WorkflowNode:
    id: str
    title: str
    kind: str                       # 'tool' / 'subagent' / 'noop'
    payload: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'kind': self.kind,
            'payload': self.payload,
            'depends_on': self.depends_on,
        }


def _topo_order(nodes: list[WorkflowNode]) -> list[str]:
    """Kahn 拓扑排序；存在环即抛 ``WorkflowError``。"""
    ids = {n.id for n in nodes}
    if len(ids) != len(nodes):
        raise WorkflowError('工作流节点 id 重复')
    indegree: dict[str, int] = {n.id: 0 for n in nodes}
    adjacency: dict[str, list[str]] = {n.id: [] for n in nodes}
    for node in nodes:
        for dep in node.depends_on:
            if dep not in ids:
                raise WorkflowError(f'节点 {node.id} 依赖不存在的节点 {dep}')
            adjacency[dep].append(node.id)
            indegree[node.id] += 1
    ready = [nid for nid, deg in indegree.items() if deg == 0]
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for downstream in adjacency[current]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)
    if len(order) != len(nodes):
        raise WorkflowError('工作流存在环，无法调度')
    return order


def run(
    nodes: list[WorkflowNode],
    *,
    executor: Callable[[WorkflowNode], dict[str, Any]],
    concurrency: int = constants.DEFAULT_WORKFLOW_CONCURRENCY,
) -> dict[str, Any]:
    """执行工作流 DAG，返回 ``{nodes, results, ok, failed, blocked}``。

    调度规则：
    - 只有依赖全部成功（``ok``）的节点才会被调度；
    - 任一依赖失败/被阻断，则该节点标记 ``blocked``，不执行；
    - 同层节点按并发上限并行推进。
    """
    if not nodes:
        raise WorkflowError('工作流为空')
    order = _topo_order(nodes)
    by_id = {n.id: n for n in nodes}
    limit = max(1, min(int(concurrency), constants.MAX_WORKFLOW_CONCURRENCY))

    results: dict[str, dict[str, Any]] = {}
    status: dict[str, str] = {}

    for nid in order:
        node = by_id[nid]
        blocked_by = [d for d in node.depends_on if status.get(d) != 'ok']
        if blocked_by:
            status[nid] = 'blocked'
            results[nid] = {'status': 'blocked', 'reason': f'上游未成功：{", ".join(blocked_by)}'}

    # 就绪节点（未被阻断者）按依赖层级分批并行
    ready = [nid for nid in order if status.get(nid) != 'blocked']
    pending = {nid: set(by_id[nid].depends_on) for nid in ready}
    completed: set[str] = set()

    while pending:
        wave = [nid for nid, deps in pending.items() if deps.issubset(completed)]
        if not wave:
            # 理论上不可达（拓扑序保证），防御性兜底
            for nid in list(pending):
                status[nid] = 'blocked'
                results[nid] = {'status': 'blocked', 'reason': '依赖无法满足'}
            break
        with ThreadPoolExecutor(max_workers=min(limit, max(1, len(wave)))) as pool:
            futures = {pool.submit(executor, by_id[nid]): nid for nid in wave}
            for future in as_completed(futures):
                nid = futures[future]
                try:
                    outcome = future.result()
                    results[nid] = outcome if isinstance(outcome, dict) else {'status': 'ok', 'output': outcome}
                    status[nid] = results[nid].get('status', 'ok')
                except Exception as exc:  # noqa: BLE001 —— 单节点失败不拖垮整图
                    logger.warning('[coding.workflow] 节点 %s 失败：%r', nid, exc)
                    status[nid] = 'failed'
                    results[nid] = {'status': 'failed', 'error': str(exc)}
        for nid in wave:
            pending.pop(nid, None)
            completed.add(nid)

    ok = sum(1 for s in status.values() if s == 'ok')
    failed = sum(1 for s in status.values() if s == 'failed')
    blocked = sum(1 for s in status.values() if s == 'blocked')
    return {
        'ok': failed == 0 and blocked == 0,
        'concurrency': limit,
        'total': len(nodes),
        'succeeded': ok,
        'failed': failed,
        'blocked': blocked,
        'order': order,
        'nodes': [n.public() for n in nodes],
        'results': results,
        'status': status,
    }


def default_nodes_from_plan(step_ids: list[tuple[str, str]]) -> list[WorkflowNode]:
    """把 ``[(step_id, title), ...]`` 串成线性 DAG（前一步为后一步依赖）。"""
    nodes: list[WorkflowNode] = []
    prev: str | None = None
    for step_id, title in step_ids:
        nodes.append(WorkflowNode(
            id=step_id,
            title=title,
            kind='noop',
            depends_on=[prev] if prev else [],
        ))
        prev = step_id
    return nodes
