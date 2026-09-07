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

"""工具调用结果结构化提取层 (Issue #61)

新增三个 source_type：tool_result / manual_config / cross_scene_trace，
并提供一个从工具调用原始 JSON 自动抽取结构化字段的提取器。

对应赛题：XA-202612 (1) 构建多源数据整合模块——支持工具执行结果、
用户行为数据、手动配置信息等数据的统一接入。
"""
from __future__ import annotations

from typing import Any

# 三个新增 source_type（与 capsule_store.write_capsule 的 source_type 参数对接）
SOURCE_TYPE_TOOL_RESULT = "tool_result"
SOURCE_TYPE_MANUAL_CONFIG = "manual_config"
SOURCE_TYPE_CROSS_SCENE_TRACE = "cross_scene_trace"

# 全部合法 source_type（capsule_store 目前使用的 + 新增的）
ALL_SOURCE_TYPES = frozenset(
    {
        "user_input",
        "user",
        "eval",
        "file",
        SOURCE_TYPE_TOOL_RESULT,
        SOURCE_TYPE_MANUAL_CONFIG,
        SOURCE_TYPE_CROSS_SCENE_TRACE,
    }
)

# 工具结果抽取的关键字段白名单（防止任意大对象入库）
_TOOL_RESULT_FIELDS = ("tool_name", "params", "result", "error", "duration_ms")


def extract_tool_result(
    tool_name: str,
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | Any = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """把一次工具调用的原始 JSON 输出，抽取成可写入 capsule 的结构化字段。

    规则：
    - tool_name / error / duration_ms 原样保留（标量）
    - params / result 若为 dict，抽取前 32 个键（防止超大对象）；非 dict 原样保留
    - 返回值只包含白名单字段，null 字段不写入
    """
    extracted: dict[str, Any] = {"tool_name": tool_name}

    if isinstance(params, dict):
        extracted["params"] = dict(list(params.items())[:32])
    elif params is not None:
        extracted["params"] = params

    if isinstance(result, dict):
        extracted["result"] = dict(list(result.items())[:32])
    elif result is not None:
        # 非 dict 结果（字符串/列表/数值）直接包装
        extracted["result"] = {"value": result}

    if error is not None:
        extracted["error"] = str(error)[:2000]
    if duration_ms is not None:
        extracted["duration_ms"] = int(duration_ms)

    return extracted


def build_tool_capsule_content(
    tool_name: str,
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | Any = None,
    error: str | None = None,
    duration_ms: int | None = None,
    scene: str = "general",
    summary: str | None = None,
) -> dict[str, Any]:
    """生成可直接交给 write_capsule 的 content dict（source_type=tool_result）。"""
    content = extract_tool_result(
        tool_name=tool_name,
        params=params,
        result=result,
        error=error,
        duration_ms=duration_ms,
    )
    content["scene"] = scene
    if summary:
        content["summary"] = summary
    return content


def extract_manual_config_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """manual_config 来源：对比配置变更，只记录发生变化的键。"""
    changed = {}
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            changed[key] = {
                "before": before.get(key),
                "after": after.get(key),
            }
    return {"config_changes": changed, "change_count": len(changed)}


def normalize_cross_scene_trace(raw: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """cross_scene_trace 来源：按 scene 归一化聚合。

    输入可以是单条（dict）或多条（list），输出统一为：
    {"scenes": {scene: {"count": n, "recent": last}}}
    """
    if isinstance(raw, dict):
        raw = [raw]

    scenes: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        scene = str(item.get("scene", "general"))
        entry = scenes.setdefault(scene, {"count": 0, "recent": None})
        entry["count"] += 1
        entry["recent"] = item.get("summary") or item.get("text") or entry["recent"]

    return {"scenes": scenes, "scene_count": len(scenes)}


__all__ = [
    "SOURCE_TYPE_TOOL_RESULT",
    "SOURCE_TYPE_MANUAL_CONFIG",
    "SOURCE_TYPE_CROSS_SCENE_TRACE",
    "ALL_SOURCE_TYPES",
    "extract_tool_result",
    "build_tool_capsule_content",
    "extract_manual_config_diff",
    "normalize_cross_scene_trace",
]
