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

"""万枢编程框架（WanShu Coding Framework）。

一个"大于万枢平台"的 AI 编程框架：把万枢既有的智能体编排、模型网关、
可审计记忆治理作为**内核**，向外长出面向软件工程的能力面——

==================  =========================================================
模块                职责
==================  =========================================================
``constants``       受控枚举与裁决矩阵（权限模式 × 风险等级、状态机、预算）
``sandbox``         工作区边界 + 命令策略（安全地基）
``tools``           工具系统（能力注册表 + 内置工具 + 统一裁决）
``plan``            计划模式与待办（含"确认门"与状态机）
``skills``          技能系统（File-as-Truth）
``subagent``        子智能体委派（最小权限 + 深度上限）
``guard``           循环护栏（轮次/工具/重复/超时四道闸）
``memory_bridge``   可审计编程记忆（复用 memoryos，可证明删除）
``workflow``        工作流受控并发（DAG）
``llm``             模型适配层（复用万枢模型网关，离线优先）
``store``           会话与事件持久化
``orchestrator``    编码智能体主循环
``api``             HTTP API（platform_api 自动发现）
==================  =========================================================

设计参照 deepseek-harness（插件化 / 一切皆能力）与 wenflow（编排与技能分离、
File-as-Truth、确认门），并吸收 ZCode 的"多形态交付 + 工作流并发"思路，
但不复用其代码。所有能力均在离线环境可跑、可测、可演示。
"""
from __future__ import annotations

__all__ = [
    'constants',
    'sandbox',
    'tools',
    'plan',
    'skills',
    'subagent',
    'guard',
    'memory_bridge',
    'workflow',
    'llm',
    'store',
    'orchestrator',
]
