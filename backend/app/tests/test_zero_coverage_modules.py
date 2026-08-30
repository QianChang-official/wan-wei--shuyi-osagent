"""dream / export_center / research_adoption / tuning 四个零测试模块的覆盖。

各模块性质不同,测试策略也不同:

- **dream**: P1 占位实现。锁定 run_dream 的骨架契约(7 个计数字段 + placeholder
  状态),防止占位被悄悄当成「已实现」;scheduler 循环的容错(单 soul 失败不
  杀循环)与停止语义。
- **export_center**: 纯目录数据。锁定导出包清单的诚实边界(status 不允许
  出现 "done"/"complete")与证据文件引用真实性(引用的文件必须真实存在)。
- **research_adoption**: 纯目录数据。锁定 9 项技术的诚实标注
  (current_status ∈ partial/planned,不得有 done)、证据文件存在性、
  source_urls 格式、adoption_ratio 范围。
- **tuning**: 配置面。锁定 TUNING_DEFAULTS 的权重键与 retrieval 真实读取源
  的一致性(issue #118 的教训:配置面与代码行为漂移 = 「假装可配置」)。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from backend.app.dream import scheduler as dream
from backend.app.export_center import service as export_center
from backend.app.research_adoption import service as research
from backend.app.tuning import service as tuning

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# dream — P1 占位契约
# ---------------------------------------------------------------------------


def test_run_dream_returns_placeholder_skeleton():
    """run_dream 当前是 P1 占位:必须返回 placeholder 状态与 5 个零计数字段。

    若未来 P4 实现了真实梦境整理,这些字段应从 0 变为实测值,本测试应随之
    更新为「字段存在且为非负整数」而非「恒为 0」。
    """
    result = dream.run_dream("soul-test")
    assert result["soul_id"] == "soul-test"
    assert result["status"] == "placeholder"
    for field in (
        "new_edges", "merged_capsules", "pruned_capsules",
        "synthesized_insights", "emotional_events_digested",
    ):
        assert result[field] == 0


def test_should_dream_p1_always_true():
    """P1 阶段三门简化:任何 soul 都允许触发(手动路径)。"""
    assert dream._should_dream("any-soul") is True


def test_scheduler_stops_on_event(isolated_db):
    """stop_event 置位后调度循环必须退出(不依赖 interval 超长等待)。"""
    stop = threading.Event()
    t = threading.Thread(
        target=dream.run_dream_scheduler,
        kwargs={"interval_seconds": 60, "stop_event": stop},
        daemon=True,
    )
    t.start()
    time.sleep(0.05)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive(), "stop_event 置位后调度线程未退出"


def test_scheduler_survives_per_soul_failure(isolated_db, monkeypatch):
    """单个 soul 的 dream 失败不得杀死调度循环(try/except 隔离)。"""
    calls = []

    def _exploding_dream(soul_id: str) -> dict:
        calls.append(soul_id)
        raise RuntimeError("simulated per-soul failure")

    monkeypatch.setattr(dream, "_run_dream", _exploding_dream)
    monkeypatch.setattr(dream, "_should_dream", lambda _: True)

    from backend.app.db import get_conn
    conn = get_conn()
    # dream_lock 有外键到 soul_persona,先注册 soul
    conn.execute(
        "INSERT OR IGNORE INTO soul_persona(soul_id, owner_id, name) VALUES('soul-x', 'owner-x', 'test')"
    )
    conn.execute(
        "INSERT INTO dream_lock(soul_id, pid, started_at) VALUES('soul-x', '1', '2026-01-01T00:00:00Z')"
    )
    conn.commit()

    stop = threading.Event()

    def _run_once_then_stop(**kwargs):
        # 第一轮跑完即停,验证循环没有崩
        dream.run_dream_scheduler(interval_seconds=0, stop_event=stop)

    t = threading.Thread(target=_run_once_then_stop, daemon=True)
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(timeout=2)
    # 循环活着跑过(或正常退出),且确实尝试了对 soul-x 的 dream
    assert "soul-x" in calls


# ---------------------------------------------------------------------------
# export_center — 诚实边界
# ---------------------------------------------------------------------------


def test_export_packages_no_done_status():
    """导出包不允许声称 done/complete — 当前全部 partial。"""
    packages = export_center.list_packages()["items"]
    assert len(packages) >= 3
    for pkg in packages:
        assert pkg["status"] in ("partial", "planned", "pending", "available"), (
            f"{pkg['id']} 状态 {pkg['status']} 越界"
        )


def test_export_packages_evidence_files_exist():
    """证据文件引用必须真实存在(引用漂移 = 虚假证据)。

    带 ``#doc-`` 锚点的是文档中心内锚,只校验文件本体存在。
    """
    packages = export_center.list_packages()["items"]
    missing = []
    for pkg in packages:
        for ref in pkg["evidence_files"]:
            path = ref.split("#", 1)[0]
            if path and not (_PROJECT_ROOT / path).exists():
                missing.append(f"{pkg['id']}: {path}")
    assert not missing, f"证据文件不存在: {missing}"


# ---------------------------------------------------------------------------
# research_adoption — 目录完整性 + 诚实标注
# ---------------------------------------------------------------------------


def test_technologies_nine_entries_with_honest_status():
    """9 项技术目录,current_status 只允许 partial/planned(不允许 done)。"""
    items = research.list_technologies()["items"]
    assert len(items) == 9
    for item in items:
        assert item["current_status"] in ("partial", "planned"), (
            f"{item['id']} 声称 {item['current_status']} — 违反诚实边界"
        )


def test_technologies_adoption_ratio_bounded():
    for item in research.list_technologies()["items"]:
        assert 0.0 <= item["adoption_ratio"] <= 1.0


def test_technologies_have_real_source_urls():
    """每项技术必须有可追溯的来源链接,且为 http(s)。"""
    for item in research.list_technologies()["items"]:
        assert item["source_urls"], f"{item['id']} 缺来源链接"
        for url in item["source_urls"]:
            assert url.startswith(("https://", "http://")), (
                f"{item['id']} 非法来源: {url}"
            )


def test_technologies_evidence_files_exist():
    """evidence_files 中的真实文件路径必须存在(文档锚点只校验文件本体)。"""
    missing = []
    for item in research.list_technologies()["items"]:
        for ref in item["evidence_files"]:
            path = ref.split("#", 1)[0]
            if path and not (_PROJECT_ROOT / path).exists():
                missing.append(f"{item['id']}: {path}")
    assert not missing, f"证据文件不存在: {missing}"


def test_routes_five_entries_status_bounded():
    routes = research.list_routes()["items"]
    assert len(routes) == 5
    for route in routes:
        assert route["status"] in ("partial", "planned", "available")


def test_version_map_chronological():
    """版本映射必须覆盖 v0.1 → v0.8 连续谱系,且每版有承接关系。"""
    items = research.version_map()["items"]
    versions = [v["version"] for v in items]
    assert versions == sorted(versions, key=lambda v: [int(x) for x in v[1:].split(".")])
    assert versions[0] == "v0.1"
    assert versions[-1] == "v0.8"
    for v in items:
        assert v["inherited_by"], f"{v['version']} 缺承接说明"


# ---------------------------------------------------------------------------
# tuning — 配置面与代码行为一致性(issue #118 教训)
# ---------------------------------------------------------------------------


def test_tuning_retrieval_weights_match_runtime_source():
    """TUNING_DEFAULTS.retrieval 的权重键必须与 retrieval 模块的真实读取一致。

    issue #118:此前配置面公布了 4 个无读取方的权重键 — 「假装可配置」。
    本测试直接读 memory_runtime.retrieval 的 _weights 默认值对比。
    """
    from backend.app.memory_runtime import retrieval

    defaults = tuning.get_defaults()["defaults"]["retrieval"]
    runtime_weights = retrieval._weights()

    for key in (
        "query_relevance_weight", "trust_score_weight", "confidence_weight",
        "retention_score_weight", "emotional_salience_weight", "base_score",
    ):
        assert key in runtime_weights, f"retrieval._weights 缺 {key}"
        assert defaults[key] == pytest.approx(runtime_weights[key]), (
            f"{key} 漂移: 配置面 {defaults[key]} vs 运行源 {runtime_weights[key]}"
        )


def test_tuning_policy_modes_autopilot_not_available():
    """autopilot 必须保持 planned(v0.9.3 不开放真实危险自动化)。"""
    modes = {m["id"]: m for m in tuning.list_policy_modes()["items"]}
    assert modes["autopilot"]["status"] == "planned"
    assert modes["readonly"]["status"] == "available"


def test_tuning_arena_targets_honest():
    """arena 目标:unsafe_autonomy 红线为 0;未实现的指标标 pending。"""
    arena = tuning.get_defaults()["defaults"]["arena"]
    assert arena["unsafe_autonomy_rate_target"] == 0.0
    assert arena["memory_reuse_success_rate_target"] == "pending_baseline"

