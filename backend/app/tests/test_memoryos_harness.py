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

"""MEB 评测 harness 测试（规范: AI优化/MemoryOS-BenchmarkHarness.md §5 验收标准）。

覆盖规范列出的四条验收标准：
1. 一个 pytest 命令可跑完 Mini-MEB  ← 本文件即是
2. 每次失败都有可查线索（case_id + step 序号 + 原因）
3. score_report.json 可被 CI 解析并对比基线
4. hidden set 与 public set 分离
"""

import json

import pytest

from backend.app.memoryos import harness
from backend.app.memoryos.report_contract import (
    CATEGORIES,
    DIMENSIONS,
    MHEB_WEIGHTS,
    MQ_SUBSKILLS,
    MQ_WEIGHTS,
    score_report_validation_error,
)


# ---------------------------------------------------------------------------
# 用例集完整性
# ---------------------------------------------------------------------------


def test_public_cases_cover_all_five_categories():
    cases, _ = harness.load_cases(suite="full")
    covered = {case["category"] for case in cases}
    assert covered == set(CATEGORIES), f"缺失类别: {set(CATEGORIES) - covered}"


def test_public_cases_have_at_least_four_per_category():
    cases, _ = harness.load_cases(suite="full")
    for category in CATEGORIES:
        count = sum(1 for case in cases if case["category"] == category)
        assert count >= 4, f"{category} 只有 {count} 例，规范要求每类 ≥4"


def test_case_ids_are_unique():
    cases, _ = harness.load_cases(suite="full")
    ids = [case["case_id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_every_case_has_steps_and_valid_dimension():
    cases, _ = harness.load_cases(suite="full")
    for case in cases:
        assert case.get("steps"), f"{case['case_id']} 没有 steps"
        assert harness._dimension_of(case) in DIMENSIONS


def test_mini_suite_is_a_subset_covering_all_dimensions():
    """Mini-MEB 是每 PR 门禁，四个加权维度都要有用例，否则综合分有盲区。"""
    mini, _ = harness.load_cases(suite="mini")
    full, _ = harness.load_cases(suite="full")
    assert 0 < len(mini) < len(full)
    assert {harness._dimension_of(case) for case in mini} == set(DIMENSIONS)
    # 套件规模是评测口径契约的一部分：加用例 / 丢 mini 标签都会让这里失配，
    # 与 run_suite 的 manifest 漂移守卫同源（见 PUBLIC_SUITE_EXPECTED_CASES）。
    assert len(mini) == harness.PUBLIC_SUITE_EXPECTED_CASES["mini"] == 14
    assert len(full) == harness.PUBLIC_SUITE_EXPECTED_CASES["full"] == 20


def test_redteam_suite_is_safety_only():
    redteam, _ = harness.load_cases(suite="redteam")
    assert redteam
    assert all(harness._dimension_of(case) == "safety" for case in redteam)


def test_hidden_set_absent_from_repo():
    """规范要求隐藏集与公开集分离——仓库内不含隐藏用例，否则就不隐藏了。"""
    cases, hidden_count = harness.load_cases(suite="full")
    assert hidden_count == 0
    assert not any(case.get("_hidden") for case in cases)


def test_hidden_set_loaded_from_env(tmp_path, monkeypatch):
    hidden_case = {
        "case_id": "HIDDEN-001",
        "category": "knowledge_recall",
        "weight_dimension": "ux",
        "title": "隐藏用例",
        "tags": ["mini"],
        "steps": [
            {
                "op": "write",
                "capsule": {
                    "memory_class": "knowledge",
                    "content": {"knowledge_type": "fact", "statement": "隐藏事实 zulu"},
                },
                "expect": {"policy_result": "allow"},
            },
            {"op": "search", "query": "zulu", "expect": {"must_contain": ["zulu"]}},
        ],
    }
    (tmp_path / "hidden.json").write_text(
        json.dumps([hidden_case], ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv(harness.HIDDEN_CASES_ENV, str(tmp_path))

    cases, hidden_count = harness.load_cases(suite="mini")
    assert hidden_count == 1
    assert any(case["case_id"] == "HIDDEN-001" for case in cases)


def test_hidden_count_matches_selected_suite(tmp_path, monkeypatch):
    """隐藏用例数必须跟随套件过滤，而不是目录里有多少算多少。

    不带 ``mini`` 标签的隐藏用例不会进入 mini 套件；若按原始加载数累计，
    ``public = total - hidden`` 就会失真，manifest 漂移守卫也会被误触发。
    """
    hidden_cases = [
        {
            "case_id": "HIDDEN-MINI",
            "category": "knowledge_recall",
            "weight_dimension": "ux",
            "tags": ["mini"],
            "steps": [],
        },
        {
            "case_id": "HIDDEN-FULL-ONLY",
            "category": "knowledge_recall",
            "weight_dimension": "ux",
            "tags": [],
            "steps": [],
        },
    ]
    (tmp_path / "hidden.json").write_text(
        json.dumps(hidden_cases, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv(harness.HIDDEN_CASES_ENV, str(tmp_path))

    mini, mini_hidden = harness.load_cases(suite="mini")
    full, full_hidden = harness.load_cases(suite="full")
    assert mini_hidden == 1
    assert [case["case_id"] for case in mini if case.get("_hidden")] == ["HIDDEN-MINI"]
    assert full_hidden == 2
    assert len([case for case in full if case.get("_hidden")]) == 2


def test_missing_hidden_dir_is_ignored(monkeypatch):
    monkeypatch.setenv(harness.HIDDEN_CASES_ENV, "/nonexistent/path/for/meb")
    _, hidden_count = harness.load_cases(suite="mini")
    assert hidden_count == 0


# ---------------------------------------------------------------------------
# 跑通 Mini-MEB
# ---------------------------------------------------------------------------


def test_mini_meb_all_pass(isolated_db):
    """规范验收标准 1：一个 pytest 命令跑完 Mini-MEB。"""
    report = harness.run_suite(suite="mini", write_report=False)
    failures = report["failures"]
    assert not failures, f"Mini-MEB 有失败用例: {failures}"
    assert report["summary"]["total_cases"] == harness.PUBLIC_SUITE_EXPECTED_CASES["mini"] == 14
    assert report["summary"]["pass_rate"] == 1.0


def test_full_public_suite_all_pass(isolated_db):
    report = harness.run_suite(suite="full", write_report=False)
    assert report["summary"]["total_cases"] == harness.PUBLIC_SUITE_EXPECTED_CASES["full"] == 20
    assert report["summary"]["hidden_cases"] == 0
    assert not report["failures"], f"公开集有失败用例: {report['failures']}"


def test_case_isolation_by_owner_scope(isolated_db):
    """用例共享同一个库；若不按 owner 隔离，A 写的记忆会污染 B 的否定断言。"""
    cases, _ = harness.load_cases(suite="full")
    first, second = cases[0], cases[1]
    result_a = harness.run_case(first)
    result_b = harness.run_case(second)
    assert result_a["passed"] and result_b["passed"]
    # 反序再跑一遍，结果必须一致（不依赖执行顺序）
    assert harness.run_case(second)["passed"]
    assert harness.run_case(first)["passed"]


def test_failure_carries_diagnosable_context(isolated_db):
    """规范验收标准 2：失败要能定位到具体 step 与原因。"""
    broken = {
        "case_id": "BROKEN-001",
        "category": "knowledge_recall",
        "weight_dimension": "ux",
        "title": "故意失败",
        "steps": [
            {
                "op": "write",
                "capsule": {
                    "memory_class": "knowledge",
                    "content": {"knowledge_type": "fact", "statement": "存在的事实"},
                },
                "expect": {"policy_result": "allow"},
            },
            {
                "op": "search",
                "query": "存在",
                "expect": {"must_contain": ["根本不存在的字符串"]},
            },
        ],
    }
    result = harness.run_case(broken)
    assert result["passed"] is False
    assert result["failed_step"] == 1
    assert "must_contain" in result["reason"]
    assert "根本不存在的字符串" in result["reason"]


def test_unknown_step_op_fails_loudly(isolated_db):
    result = harness.run_case({
        "case_id": "BAD-OP",
        "category": "knowledge_recall",
        "title": "未知 op",
        "steps": [{"op": "teleport"}],
    })
    assert result["passed"] is False
    assert "teleport" in result["reason"]


def test_expect_illegal_fails_when_transition_succeeds(isolated_db):
    """expect.illegal 是断言而不是许可——转移成功了就该判失败。"""
    result = harness.run_case({
        "case_id": "ILLEGAL-EXPECT",
        "category": "conflict_update",
        "title": "误标非法",
        "steps": [
            {
                "op": "write",
                "capsule": {
                    "memory_class": "knowledge",
                    "content": {"knowledge_type": "fact", "statement": "合法转移"},
                },
            },
            {
                "op": "transition",
                "capsule_ref": 0,
                "to_state": "reinforced",
                "expect": {"illegal": True},
            },
        ],
    })
    assert result["passed"] is False
    assert "非法转移被拒绝" in result["reason"]


# ---------------------------------------------------------------------------
# 报告与契约
# ---------------------------------------------------------------------------


def test_report_satisfies_contract(isolated_db):
    """规范验收标准 3：报告可被 CI 解析。"""
    report = harness.run_suite(suite="mini", write_report=False)
    assert score_report_validation_error(report) is None


def test_report_contains_economics_and_health(isolated_db):
    """规范 §5：报告须含 5 类评测 + economics + health。"""
    report = harness.run_suite(suite="full", write_report=False)
    assert set(report["category_breakdown"]) == set(CATEGORIES)
    assert "total_cost" in report["economics"]
    assert "mhs" in report["health"]
    assert "ledger" in report["governance"]
    assert report["honesty_notes"]


def test_report_contains_reproducibility_metadata(isolated_db, monkeypatch):
    """报告必须自带 provenance：用例清单哈希、源码树哈希、runner 版本。"""
    monkeypatch.delenv("WANWEI_SOURCE_REVISION", raising=False)
    report = harness.run_suite(suite="mini", write_report=False)
    metadata = report["evaluation"]
    assert metadata["kind"] == "internal_memory_layer_regression"
    assert metadata["source_tree_sha256"]
    assert metadata["case_manifest_sha256"]
    assert metadata["source_revision"] == "working-tree"
    assert metadata["source_revision_pinned"] is False
    assert metadata["source_revision_source"] == "default:working-tree"
    assert metadata["environment"]["architecture"]
    assert metadata["environment"]["execution"] == "in_process"
    assert metadata["limitations"]
    assert metadata["suite_contract"] == {
        "suite": "mini",
        "expected_public_cases": 14,
        "actual_cases_in_report": 14,
        "hidden_cases": 0,
    }
    assert report["competition_metrics"]["metric_definitions"]


def test_report_uses_explicit_source_revision_when_configured(isolated_db, monkeypatch):
    """设置 WANWEI_SOURCE_REVISION 时，报告如实标注为 pinned 版本。"""
    monkeypatch.setenv("WANWEI_SOURCE_REVISION", "deadbeef")
    report = harness.run_suite(suite="mini", write_report=False)
    metadata = report["evaluation"]
    assert metadata["source_revision"] == "deadbeef"
    assert metadata["source_revision_pinned"] is True
    assert metadata["source_revision_source"] == "env:WANWEI_SOURCE_REVISION"
    assert score_report_validation_error(report) is None


def test_report_contains_transparent_competition_metrics(isolated_db):
    """competition_metrics 口径必须诚实：official=false、比率在 [0,1]、targets 为空。"""
    report = harness.run_suite(suite="full", write_report=False)
    metrics = report["competition_metrics"]
    assert metrics["official"] is False
    assert metrics["source"]
    assert 0 <= metrics["preference_extraction_accuracy"] <= 1
    assert 0 <= metrics["knowledge_recall"] <= 1
    assert 0 <= metrics["conflict_correctness"] <= 1
    assert metrics["retrieval_latency_p95_ms"] >= 0
    assert metrics["targets"]["knowledge_recall"] is None
    assert score_report_validation_error(report) is None


def test_report_health_precision_is_self_consistent(isolated_db):
    """同一份报告不能 scores 段有精度、health 段说「未测量」。"""
    report = harness.run_suite(suite="full", write_report=False)
    precision = report["scores"]["retrieval_precision_at_5"]
    assert precision is not None
    assert report["health"]["metrics"]["precision@5"] == precision
    assert report["health"]["unmeasured"] == []


def test_mheb_weights_sum_to_one():
    assert round(sum(MHEB_WEIGHTS.values()), 6) == 1.0


def test_mheb_normalises_over_covered_dimensions_only(isolated_db):
    """缺维度时综合分只按有用例的维度归一化，不被无声压低。"""
    ux_only = {
        "case_id": "UX-ONLY",
        "category": "knowledge_recall",
        "weight_dimension": "ux",
        "title": "只有 ux",
        "steps": [
            {
                "op": "write",
                "capsule": {
                    "memory_class": "knowledge",
                    "content": {"knowledge_type": "fact", "statement": "单维度用例"},
                },
                "expect": {"policy_result": "allow"},
            }
        ],
    }
    report = harness.build_report(
        [harness.run_case(ux_only)], suite="custom", hidden_count=0
    )
    assert report["scores"]["ux"] == 1.0
    assert report["scores"]["safety"] is None
    # 若按全权重归一化会得到 0.40；正确结果是 1.0
    assert report["scores"]["mheb_overall"] == 1.0


def test_run_suite_writes_and_reads_report(isolated_db, tmp_path):
    harness.run_suite(suite="mini", output_dir=tmp_path)
    path = tmp_path / "meb_score_report.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert score_report_validation_error(payload) is None
    assert harness.latest_report(output_dir=tmp_path)["run_id"] == payload["run_id"]


def test_latest_report_none_when_absent(tmp_path):
    assert harness.latest_report(output_dir=tmp_path) is None


def test_save_traces_writes_trace_file(isolated_db, tmp_path):
    """规范 §2.2：每次检索必存 Trace（候选/过滤/重排/注入/耗时）。"""
    harness.run_suite(suite="mini", output_dir=tmp_path, save_traces=True)
    traces = json.loads((tmp_path / "meb_traces.json").read_text(encoding="utf-8"))
    assert traces
    sample = traces[0]
    for field in ("query", "candidates", "filters_applied", "rerank",
                  "injected", "latency_ms"):
        assert field in sample, f"Trace 缺字段 {field}"


def test_run_suite_rejects_self_inconsistent_report(isolated_db, monkeypatch):
    """报告不满足自己的契约时必须在产出时失败，不喂给 CI 门禁。"""
    monkeypatch.setattr(
        harness, "build_report", lambda *a, **k: {"benchmark": "MEB"}
    )
    with pytest.raises(RuntimeError, match="violates its own contract"):
        harness.run_suite(suite="mini", write_report=False)


# ---------------------------------------------------------------------------
# 健康度快照采样（Health 规范 §3.1 的趋势曲线数据来源）
# ---------------------------------------------------------------------------


def test_run_suite_records_health_snapshot(isolated_db, tmp_path):
    """落盘报告时必须真的采到一条快照。

    回归钉子：这里曾经因为 ``run_suite`` 里引用了不存在的 ``owner_id``
    而抛 NameError，被宽 except 咽成一行 warning——评测照报「通过」，
    趋势曲线却整轮没有数据。断言快照条数，才能发现这种静默失效。
    """
    from backend.app.memoryos import health

    assert health.health_trend(days=3650)["count"] == 0
    report = harness.run_suite(suite="mini", output_dir=tmp_path)

    trend = health.health_trend(days=3650)
    assert trend["count"] == 1, "落盘报告后没有采到健康度快照"
    point = trend["points"][0]
    assert point["source"] == "meb:mini"
    # 快照里的 precision 用本轮实测值，不是磁盘上旧报告的值（差一轮）
    assert point["precision_at_5"] == report["scores"]["retrieval_precision_at_5"]
    assert report["run_id"] in point["precision_source"]


def test_dry_run_does_not_pollute_trend(isolated_db):
    """``write_report=False``（pytest 里的一次性运行）不该往趋势表灌数据，
    否则曲线会变成「测试跑了几次」的计数器。"""
    from backend.app.memoryos import health

    harness.run_suite(suite="mini", write_report=False)
    assert health.health_trend(days=3650)["count"] == 0


def test_snapshot_coding_errors_are_not_swallowed(isolated_db, tmp_path, monkeypatch):
    """采样里的编码错误必须炸出来，只有环境性故障才降级成 warning。"""
    from backend.app.memoryos import health

    def _boom(**kwargs):
        raise TypeError("record_snapshot() got an unexpected keyword argument")

    monkeypatch.setattr(health, "record_snapshot", _boom)
    with pytest.raises(TypeError):
        harness.run_suite(suite="mini", output_dir=tmp_path)


def test_snapshot_environment_failure_does_not_fail_the_run(isolated_db, tmp_path, monkeypatch):
    """快照表不可用（如库被占用）时评测仍然产出报告，不白跑一轮。"""
    import sqlite3

    from backend.app.memoryos import health

    def _unavailable(**kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(health, "record_snapshot", _unavailable)
    report = harness.run_suite(suite="mini", output_dir=tmp_path)
    assert report["summary"]["pass_rate"] == 1.0
    assert (tmp_path / "meb_score_report.json").exists()


# ---------------------------------------------------------------------------
# 回归基线门禁（规范 §5「pass_rate 下降 >5% 报警」）
# ---------------------------------------------------------------------------


def _fake_report(pass_rate: float, *, suite: str = "mini", run_id: str = "run_x") -> dict:
    """构造最小报告。基线判定只看 suite/pass_rate/run_id，不必真跑一轮评测。"""
    return {
        "suite": suite,
        "run_id": run_id,
        "timestamp": "2026-08-24T00:00:00Z",
        "summary": {"pass_rate": pass_rate, "total_cases": 14},
        "scores": {"mheb_overall": pass_rate},
    }


def test_baseline_roundtrip_keeps_only_compared_metrics(tmp_path):
    path = harness.write_baseline(_fake_report(1.0), output_dir=tmp_path)
    assert path == tmp_path / "meb_baseline_mini.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    # 基线要能一眼看出改了什么，不塞整份报告
    assert set(payload) == {
        "suite", "run_id", "timestamp", "total_cases", "pass_rate", "mheb_overall",
    }
    assert payload["pass_rate"] == 1.0


def test_baseline_is_per_suite(tmp_path):
    """按套件分文件，套件不匹配在结构上不可能发生。

    回归钉子：此前门禁拿单槽的 meb_score_report.json 当基线，suite 不同就跳过。
    per-PR 写 mini、每日写 full、每周写 redteam，无论提交哪一份都至多匹配一种
    流程——门禁看着在跑却从不触发。
    """
    harness.write_baseline(_fake_report(1.0, suite="mini"), output_dir=tmp_path)
    harness.write_baseline(_fake_report(0.5, suite="full"), output_dir=tmp_path)
    assert (tmp_path / "meb_baseline_mini.json").exists()
    assert (tmp_path / "meb_baseline_full.json").exists()

    # full 的基线是 0.5，拿 full 的 1.0 去比不该被 mini 的基线影响
    verdict = harness.compare_to_baseline(
        _fake_report(1.0, suite="full"), output_dir=tmp_path
    )
    assert verdict["status"] == "ok"
    assert verdict["baseline_pass_rate"] == 0.5


def test_regression_beyond_threshold_fails(tmp_path):
    harness.write_baseline(_fake_report(1.0), output_dir=tmp_path)
    verdict = harness.compare_to_baseline(_fake_report(0.5), output_dir=tmp_path)
    assert verdict["status"] == "regressed"
    assert verdict["ok"] is False
    assert verdict["drop"] == 0.5


def test_drop_within_threshold_passes(tmp_path):
    """4 个百分点的跌幅在 5% 阈值内，不该拦——否则用例集微调就寸步难行。"""
    harness.write_baseline(_fake_report(1.0), output_dir=tmp_path)
    verdict = harness.compare_to_baseline(_fake_report(0.96), output_dir=tmp_path)
    assert verdict["status"] == "ok"


def test_threshold_boundary_is_not_a_regression(tmp_path):
    """恰好等于阈值不算退步（判定是 drop > threshold，不是 >=）。"""
    harness.write_baseline(_fake_report(1.0), output_dir=tmp_path)
    verdict = harness.compare_to_baseline(
        _fake_report(0.95), output_dir=tmp_path,
        threshold=harness.DEFAULT_REGRESSION_THRESHOLD,
    )
    assert verdict["status"] == "ok"


def test_improvement_passes(tmp_path):
    harness.write_baseline(_fake_report(0.8), output_dir=tmp_path)
    verdict = harness.compare_to_baseline(_fake_report(1.0), output_dir=tmp_path)
    assert verdict["status"] == "ok"
    assert verdict["drop"] < 0


def test_missing_baseline_skips_loudly(tmp_path):
    """首次运行没有基线不算失败，但必须给出创建命令，不静默放过。"""
    verdict = harness.compare_to_baseline(_fake_report(1.0), output_dir=tmp_path)
    assert verdict["status"] == "no_baseline"
    assert verdict["ok"] is True
    assert "--write-baseline" in verdict["message"]


def test_malformed_baseline_fails_instead_of_skipping(tmp_path):
    """坏基线会让门禁永久失效，必须让人看见，不能当成「没有基线」放过。"""
    (tmp_path / "meb_baseline_mini.json").write_text(
        json.dumps({"suite": "mini", "pass_rate": "not-a-number"}), encoding="utf-8",
    )
    verdict = harness.compare_to_baseline(_fake_report(1.0), output_dir=tmp_path)
    assert verdict["status"] == "malformed"
    assert verdict["ok"] is False


def test_committed_baselines_exist_for_every_suite():
    """仓库里三套基线都要在，否则对应流程的门禁是空转的。"""
    for suite in ("mini", "full", "redteam"):
        path = harness.baseline_path(suite)
        assert path.is_file(), f"缺少 {path.name}，{suite} 套件的回归门禁不会触发"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["suite"] == suite
        assert isinstance(payload["pass_rate"], (int, float))


def test_real_run_matches_committed_baseline(isolated_db, tmp_path):
    """实跑一轮 mini 与已提交基线比较，确认门禁在真实数据上是通过的。"""
    report = harness.run_suite(suite="mini", output_dir=tmp_path)
    verdict = harness.compare_to_baseline(report)  # 用仓库里的真实基线
    assert verdict["ok"], verdict["message"]


# ---------------------------------------------------------------------------
# MQ 能力视角（规范: AI优化/MemoryOS-IQMQ双轴框架.md §10.3）
# ---------------------------------------------------------------------------


def test_mq_subskills_map_one_to_one_onto_categories():
    """五个子能力与五个用例类别 1:1，不多不少。"""
    from backend.app.memoryos.report_contract import CATEGORIES

    assert len(MQ_SUBSKILLS) == len(CATEGORIES)
    assert set(MQ_SUBSKILLS.values()) == set(CATEGORIES)


def test_mq_weights_sum_to_one():
    from backend.app.memoryos.report_contract import MQ_WEIGHTS

    assert round(sum(MQ_WEIGHTS.values()), 6) == 1.0


def test_mq_scores_full_coverage():
    breakdown = {
        "preference_extraction": {"passed": 2, "total": 2, "rate": 1.0},
        "knowledge_recall": {"passed": 3, "total": 3, "rate": 1.0},
        "conflict_update": {"passed": 3, "total": 3, "rate": 1.0},
        "forgetting": {"passed": 3, "total": 3, "rate": 1.0},
        "poisoning": {"passed": 3, "total": 3, "rate": 1.0},
    }
    mq = harness.build_mq(breakdown)
    assert mq["mq_overall"] == 1.0
    assert mq["uncovered_subskills"] == []
    assert all(value == 1.0 for value in mq["subskills"].values())


def test_mq_weighting_favours_safety():
    """安全治理权重最高：只有它失败，比只有写入精度失败掉得更多。"""
    def one_zero(failed_category: str) -> float:
        breakdown = {
            category: {"passed": 0 if category == failed_category else 2,
                       "total": 2,
                       "rate": 0.0 if category == failed_category else 1.0}
            for category in (
                "preference_extraction", "knowledge_recall",
                "conflict_update", "forgetting", "poisoning",
            )
        }
        return harness.build_mq(breakdown)["mq_overall"]

    assert one_zero("poisoning") < one_zero("preference_extraction")


def test_uncovered_subskill_is_null_not_zero(isolated_db):
    """未覆盖的子能力必须是 null。

    记 0 会让 MQ 被无声压低，读起来像「这项能力很差」，而事实是「没测」。
    redteam 套件只跑 poisoning，是这条规则的真实触发场景。
    """
    report = harness.run_suite(suite="redteam", write_report=False)
    mq = report["mq"]
    assert mq["subskills"]["safety_governance"] is not None
    assert mq["subskills"]["write_precision"] is None
    assert "write_precision" in mq["uncovered_subskills"]
    # 只按已覆盖子能力归一：全过就是 1.0，不该因缺四项而掉到 0.3
    assert mq["mq_overall"] == 1.0


def test_mq_overall_none_when_nothing_covered():
    mq = harness.build_mq({})
    assert mq["mq_overall"] is None
    assert sorted(mq["uncovered_subskills"]) == sorted(mq["subskills"])


def test_mq_never_reports_iq_or_quadrant(isolated_db):
    """IQ 恒为 null，且不输出象限定位——象限需要两个坐标。"""
    report = harness.run_suite(suite="mini", write_report=False)
    mq = report["mq"]
    assert mq["iq"] is None
    # 参照表可以在，但不能有「我们在这个象限」这类自我定位字段
    assert "matrix_reference" in mq
    assert not any(
        key in mq for key in ("quadrant", "position", "our_quadrant", "iq_mq_position")
    )


def test_mq_matches_category_breakdown(isolated_db):
    """MQ 与 category_breakdown 同源，不能给出互相矛盾的两个数。"""

    report = harness.run_suite(suite="mini", write_report=False)
    for subskill, category in MQ_SUBSKILLS.items():
        stats = report["category_breakdown"].get(category)
        expected = None if not stats else round(stats["passed"] / stats["total"], 4)
        assert report["mq"]["subskills"][subskill] == expected


def test_report_with_mq_satisfies_contract(isolated_db):
    report = harness.run_suite(suite="mini", write_report=False)
    assert score_report_validation_error(report) is None


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda mq: mq.pop("iq"), "missing_field:mq.iq"),
        (lambda mq: mq.update(iq=0.8), "iq_must_be_null_this_system_does_not_measure_it"),
        (lambda mq: mq["weights"].update(write_precision=0.9), "mq_weights_do_not_sum_to_one"),
        (lambda mq: mq["subskills"].pop("forgetting_control"), "invalid_mq_subskills"),
        (lambda mq: mq["subskills"].update(write_precision=1.7),
         "invalid_rate:mq.subskills.write_precision"),
        (lambda mq: mq.update(uncovered_subskills=["write_precision"]), "mq_uncovered_mismatch"),
        (lambda mq: mq.update(mq_overall=None), "mq_overall_missing_despite_coverage"),
    ],
)
def test_contract_rejects_malformed_mq(mutate, expected):
    """契约层钉死 MQ 的诚实约束，特别是 iq 必须为 null。

    留一个可以被填成数字的 iq 字段，早晚会有人往里塞一个估算值。
    """
    breakdown = {
        category: {"passed": 1, "total": 1, "rate": 1.0}
        for category in (
            "preference_extraction", "knowledge_recall",
            "conflict_update", "forgetting", "poisoning",
        )
    }
    payload = _minimal_valid_report()
    payload["category_breakdown"] = breakdown
    payload["summary"] = {"total_cases": 5, "passed": 5, "failed": 0, "pass_rate": 1.0}
    payload["failures"] = []
    payload["mq"] = harness.build_mq(breakdown)
    mutate(payload["mq"])
    assert score_report_validation_error(payload) == expected


# ---------------------------------------------------------------------------
# 契约校验器本身
# ---------------------------------------------------------------------------


def _minimal_valid_report() -> dict:
    return {
        "benchmark": "MEB", "suite": "mini", "run_id": "r1", "timestamp": "2026-01-01T00:00:00Z",
        "summary": {"total_cases": 2, "passed": 1, "failed": 1, "pass_rate": 0.5},
        "weights": dict(MHEB_WEIGHTS),
        "scores": {"ux": 0.5, "safety": None, "product": None, "academic": None,
                   "mheb_overall": 0.5, "retrieval_precision_at_5": None,
                   "retrieval_recall_at_5": None},
        "category_breakdown": {"knowledge_recall": {"passed": 1, "total": 2, "rate": 0.5}},
        # mq 段手写而不调 build_mq：契约测试要独立于生产聚合逻辑，
        # 否则两边一起写错时测试反而会通过。
        "mq": {
            "mq_overall": 0.5,
            "subskills": {
                "write_precision": None,
                "retrieval_efficiency": 0.5,
                "update_correctness": None,
                "forgetting_control": None,
                "safety_governance": None,
            },
            "weights": dict(MQ_WEIGHTS),
            "uncovered_subskills": [
                "forgetting_control", "safety_governance",
                "update_correctness", "write_precision",
            ],
            "iq": None,
        },
        "failures": [{"case_id": "x", "reason": "y"}],
        "economics": {}, "health": {},
    }


def test_contract_accepts_minimal_report():
    assert score_report_validation_error(_minimal_valid_report()) is None


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda r: r.pop("economics"), "missing_field:economics"),
        (lambda r: r.pop("health"), "missing_field:health"),
        (lambda r: r["summary"].__setitem__("pass_rate", 0.9), "pass_rate_mismatch"),
        (lambda r: r["summary"].__setitem__("failed", 5), "summary_counts_mismatch"),
        (lambda r: r["weights"].__setitem__("ux", 0.9), "weights_do_not_sum_to_one"),
        (lambda r: r["category_breakdown"].__setitem__("bogus", {"passed": 0, "total": 0, "rate": 0}),
         "unknown_category:bogus"),
        (lambda r: r.__setitem__("failures", []), "failures_length_mismatch"),
        (lambda r: r["scores"].__setitem__("mheb_overall", 1.5), "invalid_rate:scores.mheb_overall"),
        (lambda r: r["scores"].__setitem__("retrieval_precision_at_5", "high"),
         "invalid_rate:scores.retrieval_precision_at_5"),
    ],
)
def test_contract_rejects_malformed(mutate, expected):
    report = _minimal_valid_report()
    mutate(report)
    assert score_report_validation_error(report) == expected


def test_contract_allows_null_precision():
    """未标注相关性时 precision 必须允许为 null——不能逼报告编一个数。"""
    report = _minimal_valid_report()
    report["scores"]["retrieval_precision_at_5"] = None
    assert score_report_validation_error(report) is None


def test_contract_rejects_non_object():
    assert score_report_validation_error([]) == "expected_object"


def _fake_run_result(
    case_id: str,
    category: str,
    passed: bool,
    *,
    hidden: bool = False,
) -> dict:
    """构造最小 run_case 结果（仅覆盖 build_report 用到的字段）。"""
    return {
        "case_id": case_id,
        "category": category,
        "dimension": "ux",
        "passed": passed,
        "reason": None,
        "failed_step": None,
        "hidden": hidden,
        "collected": {"traces": [], "deletion_checks": [], "precision_samples": []},
    }


def test_hidden_cases_never_enter_public_scores(isolated_db):
    """诚实口径回归：隐藏集结果可执行，但绝不混入公开成绩统计。

    防回归点：build_report 入口过滤 hidden 结果（summary/scores/分类/MQ/
    traces/health 全部只基于公开集）；competition_metrics 单独调用时同样过滤。
    """
    public = [
        _fake_run_result("p1", "knowledge_recall", True),
        _fake_run_result("p2", "knowledge_recall", False),
    ]
    hidden = [
        _fake_run_result("h1", "knowledge_recall", True, hidden=True),
        _fake_run_result("h2", "knowledge_recall", True, hidden=True),
    ]
    report = harness.build_report(public + hidden, suite="mini", hidden_count=2)

    summary = report["summary"]
    assert summary["total_cases"] == 2          # 只算公开
    assert summary["public_cases"] == 2
    assert summary["hidden_cases"] == 2         # 隐藏单列，不稀释成绩
    assert summary["passed"] == 1               # h1/h2 的通过不混入

    cm = report["competition_metrics"]
    assert cm["public_cases"] == 2
    assert cm["hidden_cases"] == 2
    assert cm["knowledge_recall"] is None          # 无相关性标注，如实为 None
    assert cm["sample_counts"]["knowledge_recall"] == 2  # 只数公开 case，hidden 不混入

    assert report["evaluation"]["suite_contract"]["actual_cases_in_report"] == 2
    assert report["category_breakdown"]["knowledge_recall"]["total"] == 2
    assert report["traces"]["count"] == 0


def test_competition_metrics_filters_hidden_when_called_directly(isolated_db):
    """防御性过滤：单独调用 _competition_metrics 时 hidden 同样被排除。"""
    public = [_fake_run_result("p1", "knowledge_recall", True)]
    hidden = [_fake_run_result("h1", "knowledge_recall", True, hidden=True)]
    cm = harness._competition_metrics(
        public + hidden, suite="mini", hidden_count=1
    )
    assert cm["public_cases"] == 1
    assert cm["hidden_cases"] == 1
    assert cm["knowledge_recall"] is None          # 无相关性标注，如实为 None
    assert cm["sample_counts"]["knowledge_recall"] == 1
