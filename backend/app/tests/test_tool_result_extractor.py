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

"""
Issue #61 — 工具调用结果结构化提取层测试

覆盖：三个新 source_type、extract_tool_result 抽取规则、
build_tool_capsule_content 集成、manual_config diff、cross_scene_trace 归一化。
"""


from backend.app.tool_registry.extractor import (
    SOURCE_TYPE_TOOL_RESULT,
    SOURCE_TYPE_MANUAL_CONFIG,
    SOURCE_TYPE_CROSS_SCENE_TRACE,
    ALL_SOURCE_TYPES,
    extract_tool_result,
    build_tool_capsule_content,
    extract_manual_config_diff,
    normalize_cross_scene_trace,
)
from backend.app.memory_runtime import capsule_store as cs


# ---------------------------------------------------------------------------
# source_type 常量
# ---------------------------------------------------------------------------

def test_new_source_types_exist():
    assert SOURCE_TYPE_TOOL_RESULT == "tool_result"
    assert SOURCE_TYPE_MANUAL_CONFIG == "manual_config"
    assert SOURCE_TYPE_CROSS_SCENE_TRACE == "cross_scene_trace"


def test_all_source_types_contains_legacy_and_new():
    assert {"user_input", "user", "eval", "file"} <= ALL_SOURCE_TYPES
    assert {"tool_result", "manual_config", "cross_scene_trace"} <= ALL_SOURCE_TYPES


# ---------------------------------------------------------------------------
# extract_tool_result
# ---------------------------------------------------------------------------

def test_extract_basic_fields():
    out = extract_tool_result(
        tool_name="search_web",
        params={"q": "hello", "limit": 5},
        result={"hits": [1, 2], "total": 2},
        error=None,
        duration_ms=123,
    )
    assert out["tool_name"] == "search_web"
    assert out["params"] == {"q": "hello", "limit": 5}
    assert out["result"] == {"hits": [1, 2], "total": 2}
    assert out["duration_ms"] == 123
    assert "error" not in out  # null 字段不写入


def test_extract_large_dict_truncated_to_32_keys():
    big = {f"k{i}": i for i in range(100)}
    out = extract_tool_result(tool_name="t", params=big, result=None)
    assert len(out["params"]) == 32


def test_extract_non_dict_result_wrapped():
    out = extract_tool_result(tool_name="t", params={}, result="done")
    assert out["result"] == {"value": "done"}


def test_extract_error_truncated():
    out = extract_tool_result(tool_name="t", params={}, result=None, error="x" * 5000)
    assert len(out["error"]) <= 2000


def test_extract_whitelist_only_fields():
    out = extract_tool_result(tool_name="t", params={}, result={"secret": 1})
    assert set(out.keys()) <= {"tool_name", "params", "result", "error", "duration_ms"}


# ---------------------------------------------------------------------------
# build_tool_capsule_content + write_capsule 集成
# ---------------------------------------------------------------------------

def test_build_tool_capsule_content_shape():
    content = build_tool_capsule_content(
        tool_name="nmap_scan",
        params={"target": "127.0.0.1"},
        result={"open_ports": [80]},
        scene="recon",
        summary="端口扫描完成",
    )
    assert content["tool_name"] == "nmap_scan"
    assert content["scene"] == "recon"
    assert content["summary"] == "端口扫描完成"
    assert content["result"] == {"open_ports": [80]}


def _get_provenance(cap):
    """write_capsule 不直接返回 provenance，需回查数据库"""
    capsule_id = cap["capsule_id"]
    rec = cs.get_capsule(capsule_id)
    assert rec is not None, f"capsule {capsule_id} 未写入"
    return rec["provenance"]


def test_write_capsule_with_tool_result_source(isolated_db):
    content = build_tool_capsule_content(
        tool_name="nmap_scan",
        params={"target": "127.0.0.1"},
        result={"open_ports": [80, 443]},
        duration_ms=1500,
        scene="recon",
    )
    cap = cs.write_capsule(
        memory_class="evidence",
        content=content,
        source_type=SOURCE_TYPE_TOOL_RESULT,
        scene="recon",
    )
    prov = _get_provenance(cap)
    assert prov["source_type"] == "tool_result"
    assert prov["origin"] == "tool"
    assert prov["verified"] is False  # 工具结果未人工核验


def test_write_capsule_with_manual_config_source(isolated_db):
    content = extract_manual_config_diff(
        before={"risk_level": "low"},
        after={"risk_level": "high"},
    )
    cap = cs.write_capsule(
        memory_class="config",
        content=content,
        source_type=SOURCE_TYPE_MANUAL_CONFIG,
    )
    prov = _get_provenance(cap)
    assert prov["source_type"] == "manual_config"
    assert prov["origin"] == "config"
    assert prov["verified"] is True  # 手动配置视为人工确认


def test_write_capsule_with_cross_scene_trace_source(isolated_db):
    content = normalize_cross_scene_trace(
        [
            {"scene": "recon", "summary": "扫了80端口"},
            {"scene": "recon", "summary": "扫了443端口"},
            {"scene": "exploit", "summary": "打了一个洞"},
        ]
    )
    cap = cs.write_capsule(
        memory_class="behavior",
        content=content,
        source_type=SOURCE_TYPE_CROSS_SCENE_TRACE,
    )
    prov = _get_provenance(cap)
    assert prov["source_type"] == "cross_scene_trace"
    assert prov["origin"] == "tool"
    assert content["scene_count"] == 2
    assert content["scenes"]["recon"]["count"] == 2


# ---------------------------------------------------------------------------
# extract_manual_config_diff / normalize_cross_scene_trace
# ---------------------------------------------------------------------------

def test_manual_config_diff_only_changed_keys():
    out = extract_manual_config_diff(
        before={"a": 1, "b": 2, "c": 3},
        after={"a": 1, "b": 99, "c": 3},
    )
    assert out["change_count"] == 1
    assert out["config_changes"]["b"] == {"before": 2, "after": 99}


def test_normalize_cross_scene_trace_single_dict():
    out = normalize_cross_scene_trace({"scene": "recon", "summary": "x"})
    assert out["scene_count"] == 1
    assert out["scenes"]["recon"]["count"] == 1


def test_normalize_cross_scene_trace_skips_non_dict():
    out = normalize_cross_scene_trace([{"scene": "a"}, "garbage", None])
    assert out["scene_count"] == 1
    assert out["scenes"]["a"]["count"] == 1
