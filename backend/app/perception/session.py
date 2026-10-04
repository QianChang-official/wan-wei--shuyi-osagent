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

"""感知会话状态机与反馈事件。

与 memoryos.lifecycle 同一 idiom：显式转移表裁决，非法转移抛错而不是
静默放行。每次转移产出一条**反馈事件**（会话面板可订阅、账本可追溯）——
「感知正在做什么」对人是可见的，不是黑箱。

状态图：

    idle ──begin──▶ capturing ──capture_done──▶ understanding
      ▲                                            │ understood
      │                                            ▼
      └──────────── responded ◀────────── responding
      （任意状态）──fault──▶ error ──recover──▶ idle

- ``error`` 不是终态：感知管道必须能从故障中恢复（recover 回 idle），
  传感器断连、解码失败都不该让整个感知会话死掉。
- 所有转移经 :class:`PerceptionSession.transition` 裁决，非法转移抛
  :class:`IllegalPerceptionTransition`（路由层映射 422）。
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from ..memory_runtime.capsule_store import now


class IllegalPerceptionTransition(ValueError):
    def __init__(self, from_state: str, to_state: str) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"illegal perception transition: {from_state} -> {to_state}")


#: 状态转移表：当前状态 → 允许的下一状态集合。
TRANSITIONS: dict[str, frozenset[str]] = {
    "idle": frozenset({"capturing"}),
    "capturing": frozenset({"understanding", "error", "idle"}),
    "understanding": frozenset({"responding", "error", "idle"}),
    "responding": frozenset({"idle", "error"}),
    "error": frozenset({"idle"}),
}

#: 触发词 → 目标状态（对外语义接口，状态名不直接暴露给调用方）。
TRIGGERS: dict[str, tuple[str, str]] = {
    "begin": ("idle", "capturing"),
    "capture_done": ("capturing", "understanding"),
    "understood": ("understanding", "responding"),
    "responded": ("responding", "idle"),
    "abort": ("capturing", "idle"),
    "skip": ("understanding", "idle"),
    "fault": ("*", "error"),       # 任意状态可入故障
    "recover": ("error", "idle"),  # 故障可恢复，不是终态
}


class PerceptionSession:
    """一个感知会话：状态机 + 反馈事件流。

    线程安全（一把锁保护状态与事件缓冲）；反馈事件通过
    ``drain_feedback()`` 取走，由调用方决定落库/推送（控制台 WS）。
    """

    def __init__(
        self,
        session_id: str | None = None,
        *,
        soul_id: str | None = None,
        owner_id: str | None = None,
    ) -> None:
        self.session_id = session_id or "psn_" + uuid.uuid4().hex[:12]
        self.soul_id = soul_id
        self.owner_id = owner_id
        self._state = "idle"
        self._lock = threading.Lock()
        self._feedback: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def can_transition(self, to_state: str) -> bool:
        with self._lock:
            return to_state in TRANSITIONS.get(self._state, frozenset())

    def transition(
        self,
        to_state: str,
        *,
        trigger: str,
        detail: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """受裁决的状态转移，产出反馈事件。非法转移抛错。"""
        with self._lock:
            if to_state not in TRANSITIONS.get(self._state, frozenset()):
                raise IllegalPerceptionTransition(self._state, to_state)
            from_state = self._state
            self._state = to_state
            event = {
                "feedback_id": "pfb_" + uuid.uuid4().hex[:12],
                "session_id": self.session_id,
                "trigger": trigger,
                "from_state": from_state,
                "to_state": to_state,
                "detail": detail[:256],
                "meta": meta or {},
                "created_at": now(),
            }
            self._feedback.append(event)
            self._history.append(event)
            return event

    def fire(self, trigger: str, *, detail: str = "", meta: dict | None = None) -> dict:
        """按语义触发词转移（begin/capture_done/.../fault/recover）。"""
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown trigger: {trigger}")
        expected_from, to_state = TRIGGERS[trigger]
        with self._lock:
            current = self._state
        if expected_from != "*" and current != expected_from:
            raise IllegalPerceptionTransition(current, to_state)
        return self.transition(to_state, trigger=trigger, detail=detail, meta=meta)

    def drain_feedback(self) -> list[dict[str, Any]]:
        """取走自上次以来累积的反馈事件。"""
        with self._lock:
            drained = self._feedback
            self._feedback = []
            return drained

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "state": self._state,
                "soul_id": self.soul_id,
                "owner_id": self.owner_id,
                "history": list(self._history[-50:]),
            }
