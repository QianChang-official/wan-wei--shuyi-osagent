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

"""沙箱模式 × 审批策略 —— 二维准入裁决。

借鉴 openai/codex（Apache-2.0, Copyright 2025 OpenAI）的权限模型设计，
按本项目 Python/信创环境重新实现，未复制其源码（Rust）。核心语义取自
Codex 官方文档（learn.chatgpt.com/docs/agent-approvals-security）：

    "Sandbox mode" 决定技术上能做什么；
    "Approval policy" 决定越界前是否询问用户。

且必须守住 Codex 明确写出的一条不变量：**``never`` 只关闭审批提示，
不扩大沙箱权限**——把两者混为一谈（「不询问=允许」）是权限设计里最
常见的致命误读。

裁决输出四态（Codex 有「审批拒绝」与「可重试沙箱拒绝」之分）：

============  ==========================================================
outcome       含义
============  ==========================================================
``allow``     沙箱内且无需审批，直接执行
``approval``  技术上被沙箱允许但策略要求人工确认 → 出票据
``retryable`` 被沙箱边界拒绝，可换模式/申请提升后重试
``terminal``  策略层明确禁止（不容许审批的越权组合），重试无意义
============  ==========================================================

Codex 当前文档只定义了 ``never`` 与 ``on-request`` 两个审批取值，
``on-failure`` 为历史值；本项目保留它但**语义自定义**为
「执行失败后才允许人工介入」，并在 :data:`POLICY_SEMANTICS_NOTE`
显式标注差异，不假装与上游一致。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

#: 能力词表（与 agent_bridge 的 Capability 对齐）。
CAPABILITIES = frozenset({"fs_read", "fs_write", "shell", "network", "git", "device"})

#: workspace-write 下递归只读的受保护路径（Codex 同款：.git/.agents/.codex）。
PROTECTED_SUBPATHS = (".git", ".agents", ".codex")

#: 本项目与 Codex 的取值差异声明（诚实清单）。
POLICY_SEMANTICS_NOTE = (
    "Codex 官方文档现仅定义 approval_policy = never | on-request；"
    "on-failure 为历史取值，本项目保留并自定义为「执行失败后才允许人工介入」，"
    "语义与上游不完全一致。"
)

SANDBOX_MODES = ("read_only", "workspace_write", "full_access")
APPROVAL_POLICIES = ("never", "on_failure", "on_request")

#: 各沙箱模式允许的能力集（技术边界）。
#: 注意 ``network`` 在 workspace_write 下**属于**允许集：Codex 把它做成
#: ``sandbox_workspace_write.network_access`` 配置开关 + 审批，而非模式外
#: 能力——所以这里交给后面的网络开关分支裁决，而不是在这里直接拒绝。
_MODE_CAPABILITIES: dict[str, frozenset[str]] = {
    "read_only": frozenset({"fs_read"}),
    "workspace_write": frozenset({"fs_read", "fs_write", "shell", "git", "device", "network"}),
    "full_access": frozenset(CAPABILITIES),
}


class SandboxPolicyError(ValueError):
    """策略参数非法（未知模式/策略/能力）。"""


@dataclass(frozen=True)
class Decision:
    outcome: str                       # allow | approval | retryable | terminal
    reason: str
    capability: str
    sandbox_mode: str
    approval_policy: str
    escalate_to: str | None = None     # retryable 时建议的提升目标模式
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome in {"allow", "approval"}

    def manifest(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "capability": self.capability,
            "sandbox_mode": self.sandbox_mode,
            "approval_policy": self.approval_policy,
            "escalate_to": self.escalate_to,
            "detail": self.detail,
        }


def _is_protected(relative_path: str) -> str | None:
    """路径是否落在受保护子目录（.git/.agents/.codex，递归）。"""
    parts = [p for p in str(relative_path).replace("\\", "/").split("/") if p]
    for part in parts[:-1] if parts else []:
        if part in PROTECTED_SUBPATHS:
            return part
    return None


def decide(
    *,
    capability: str,
    sandbox_mode: str = "workspace_write",
    approval_policy: str = "on_request",
    relative_path: str | None = None,
    in_workspace: bool = True,
    network_enabled: bool = False,
) -> Decision:
    """二维裁决：这次操作在当前沙箱/审批策略下能不能做、要不要问人。

    裁决顺序刻意与 Codex 一致：**先技术边界，后审批**。技术上做不到的
    事情，审批也不该把它变成「能做」——那等于审批机制成了提权后门。
    """
    if sandbox_mode not in _MODE_CAPABILITIES:
        raise SandboxPolicyError(f"unknown sandbox mode: {sandbox_mode}")
    if approval_policy not in APPROVAL_POLICIES:
        raise SandboxPolicyError(f"unknown approval policy: {approval_policy}")
    if capability not in CAPABILITIES:
        raise SandboxPolicyError(f"unknown capability: {capability}")

    allowed_by_mode = _MODE_CAPABILITIES[sandbox_mode]

    # 1) 受保护路径：任何非 full_access 模式下递归只读，写入一律拒绝。
    if relative_path:
        protected = _is_protected(relative_path)
        if protected and capability in {"fs_write", "shell", "git"}:
            if sandbox_mode == "full_access":
                return Decision(
                    "allow", f"full_access ignores protected path {protected}",
                    capability, sandbox_mode, approval_policy,
                    detail={"protected": protected},
                )
            return Decision(
                "retryable", f"protected path {protected} is read-only",
                capability, sandbox_mode, approval_policy,
                escalate_to="full_access",
                detail={"protected": protected, "policy_note": POLICY_SEMANTICS_NOTE},
            )

    # 2) 技术边界：能力不在沙箱允许集内。
    if capability not in allowed_by_mode:
        # full_access 之外，缺能力只能靠「切换模式」重试，不存在审批提权。
        escalate = {
            "fs_write": "workspace_write",
            "shell": "workspace_write",
            "git": "workspace_write",
            "device": "workspace_write",
            "network": "full_access",
            "fs_read": "workspace_write",
        }.get(capability, "full_access")
        # 审批策略在这里**不参与**技术拒绝——但把「never 不扩权」这条不变量
        # 显式写进证据里，避免调用方误以为换个审批策略就能放行。
        detail = (
            {"policy_note": "never 只关闭审批，不扩大沙箱"}
            if approval_policy == "never" else {}
        )
        return Decision(
            "retryable", f"{capability} not permitted in {sandbox_mode}",
            capability, sandbox_mode, approval_policy, escalate_to=escalate,
            detail=detail,
        )

    # 3) 工作区边界：workspace_write 不得写工作区外（Codex 同款语义）。
    if not in_workspace and capability in {"fs_write", "shell", "git"}:
        if sandbox_mode != "full_access":
            if approval_policy == "never":
                return Decision(
                    "retryable", "outside workspace denied under approval=never",
                    capability, sandbox_mode, approval_policy,
                    detail={"in_workspace": False,
                            "policy_note": "never 只关闭审批，不扩大沙箱"},
                )
            return Decision(
                "approval", "outside workspace needs human approval",
                capability, sandbox_mode, approval_policy, escalate_to="full_access",
                detail={"in_workspace": False},
            )

    # 4) 网络：workspace_write 默认关闭，除非显式开启或走审批。
    if capability == "network" and not network_enabled:
        if sandbox_mode != "full_access":
            if approval_policy == "never":
                return Decision(
                    "retryable", "network disabled and approval=never",
                    capability, sandbox_mode, approval_policy,
                    detail={"network_enabled": False},
                )
            return Decision(
                "approval", "network access requires approval",
                capability, sandbox_mode, approval_policy,
                detail={"network_enabled": False},
            )

    # 5) 沙箱内且技术允许：是否需要审批由策略决定。
    if approval_policy == "on_request":
        return Decision(
            "approval", "on_request asks before acting",
            capability, sandbox_mode, approval_policy,
        )
    if approval_policy == "on_failure":
        return Decision(
            "allow", "on_failure allows first attempt",
            capability, sandbox_mode, approval_policy,
            detail={"note": POLICY_SEMANTICS_NOTE},
        )
    return Decision("allow", "within sandbox, approvals disabled", capability,
                    sandbox_mode, approval_policy)


def policy_from_env() -> dict[str, str]:
    """从环境读当前策略（部署可覆盖，默认保持严格）。"""
    mode = os.environ.get("WANWEI_SANDBOX_MODE", "workspace_write").strip()
    policy = os.environ.get("WANWEI_APPROVAL_POLICY", "on_request").strip()
    if mode not in SANDBOX_MODES:
        mode = "workspace_write"
    if policy not in APPROVAL_POLICIES:
        policy = "on_request"
    return {
        "sandbox_mode": mode,
        "approval_policy": policy,
        "semantics_note": POLICY_SEMANTICS_NOTE,
        "source": "openai/codex (Apache-2.0) 机制借鉴，自研实现",
    }


__all__ = [
    "APPROVAL_POLICIES",
    "CAPABILITIES",
    "POLICY_SEMANTICS_NOTE",
    "PROTECTED_SUBPATHS",
    "SANDBOX_MODES",
    "Decision",
    "SandboxPolicyError",
    "decide",
    "policy_from_env",
]
