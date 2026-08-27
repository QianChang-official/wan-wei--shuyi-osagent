"""MEB / MHEB 评测 CLI —— 跑记忆体验基准并落盘 score_report.json。

规范来源：``AI优化/MemoryOS-BenchmarkHarness.md``

用法::

    python scripts/run_meb.py --suite mini      # 每 PR：核心用例
    python scripts/run_meb.py --suite full      # 每日：公开集全量
    python scripts/run_meb.py --suite redteam   # 每周：安全维度用例
    python scripts/run_meb.py --suite mini --check-only   # 只校验既有报告

数据库隔离
----------
默认在临时目录建一次性库并在结束后清理，**绝不继承生产 shell 里的
``WANWEI_MEMORY_DB``**——评测会写入、遗忘、硬删记忆，误指向真实库就是数据事故。
这一点与 ``backend/app/memory_arena/runner.py`` 的处置一致。要针对特定库跑，
必须显式传 ``--database``。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# backend 与仓库根都要在 path 上：仓库内既有 ``backend.app.*`` 也有 ``app.*``
# 两种导入风格（platform_api 子模块用后者）。
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "backend")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MEB / MHEB memory benchmark.")
    parser.add_argument(
        "--suite", choices=("mini", "full", "redteam"), default="mini",
        help="mini=每 PR 核心用例, full=公开集全量, redteam=安全维度用例",
    )
    parser.add_argument(
        "--output-dir", type=pathlib.Path, default=_REPO_ROOT / "reports",
        help="score_report.json 的落盘目录",
    )
    parser.add_argument(
        "--database", type=pathlib.Path, default=None,
        help="显式指定评测数据库；默认用临时库并在结束后删除",
    )
    parser.add_argument(
        "--save-traces", action="store_true",
        help="同时落盘 meb_traces.json（规范 §2.2 的检索 Trace）",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="不跑评测，只校验既有报告是否满足契约",
    )
    parser.add_argument(
        "--fail-under", type=float, default=None,
        help="MHEB 综合分低于该值时以非零码退出（CI 门禁用）",
    )
    parser.add_argument(
        "--write-baseline", action="store_true",
        help="把本次结果记为该套件的回归基线（reports/meb_baseline_<suite>.json）",
    )
    parser.add_argument(
        "--compare-baseline", action="store_true",
        help="与该套件的已提交基线比较 pass_rate，跌幅超阈值即以非零码退出",
    )
    parser.add_argument(
        "--regression-threshold", type=float, default=0.05,
        help="pass_rate 相对基线的允许跌幅（默认 0.05，即 5 个百分点）",
    )
    return parser.parse_args()


# 基线的读写与判定逻辑在 app.memoryos.harness 里（域逻辑，能被常规 pytest 覆盖）；
# 这里只做打印与退出码映射。一个悄悄跳过的门禁比没有门禁更危险，所以判定本身
# 需要测试，而 CLI 里的代码测不到。


def _check_only(output_dir: pathlib.Path) -> int:
    from app.memoryos.report_contract import score_report_validation_error

    path = output_dir / "meb_score_report.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"报告不可读: {path} ({exc})", file=sys.stderr)
        return 2
    error = score_report_validation_error(payload)
    if error is not None:
        print(f"报告不满足契约: {error}", file=sys.stderr)
        return 1
    print(f"报告契约校验通过: {path}")
    return 0


def _print_summary(report: dict) -> None:
    summary = report["summary"]
    scores = report["scores"]
    print(f"\n=== MEB {report['suite']} · {report['run_id']} ===")
    print(f"用例: {summary['passed']}/{summary['total_cases']} 通过 "
          f"(公开 {summary['public_cases']} / 隐藏 {summary['hidden_cases']})")
    print(f"MHEB 综合分: {scores['mheb_overall']}")
    for dimension in ("ux", "safety", "product", "academic"):
        value = scores.get(dimension)
        print(f"  - {dimension:<9}: {'未覆盖' if value is None else value}")
    precision = scores.get("retrieval_precision_at_5")
    print(f"precision@5: {'未标注相关性，如实为空' if precision is None else precision}")
    competition = report.get("competition_metrics") or {}
    print(
        "competition_metrics (official=false): "
        f"preference={competition.get('preference_extraction_accuracy')}, "
        f"knowledge_recall@5={competition.get('knowledge_recall')}, "
        f"conflict={competition.get('conflict_correctness')}, "
        f"retrieval_p95_ms={competition.get('retrieval_latency_p95_ms')}"
    )
    health = report["health"]
    print(
        f"记忆健康: MHS={health['mhs']} "
        f"(level={health['level']}, status={health.get('status', health['level'])})"
    )
    for issue in health["issues"]:
        print(f"  ! {issue}")
    for note in health["unmeasured"]:
        print(f"  ~ {note}")
    evaluation = report.get("evaluation") or {}
    print(
        "证据来源: "
        f"{evaluation.get('source_revision', 'unknown')} "
        f"({'pinned' if evaluation.get('source_revision_pinned') else 'unpinned'})"
    )
    if evaluation.get("source_tree_sha256"):
        print(f"  source_tree_sha256: {evaluation['source_tree_sha256']}")
    if evaluation.get("case_manifest_sha256"):
        print(f"  case_manifest_sha256: {evaluation['case_manifest_sha256']}")
    economics = report["economics"]
    print(f"经济: {economics['memories']} 条记忆, 总成本 {economics['total_cost']}, "
          f"平均 ROI {economics['avg_roi']}, 负 ROI {economics['negative_roi_memories']} 条")
    if report["failures"]:
        print("\n失败用例:")
        for failure in report["failures"]:
            print(f"  ✗ {failure['case_id']} (step#{failure['failed_step']}): {failure['reason']}")


def main() -> int:
    args = _parse_args()
    output_dir: pathlib.Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.check_only:
        return _check_only(output_dir)

    temp_dir: str | None = None
    if args.database is None:
        temp_dir = tempfile.mkdtemp(prefix="wanwei-meb-")
        db_path = pathlib.Path(temp_dir) / "meb.db"
    else:
        db_path = args.database.resolve()

    # 必须在导入 app.db 之前设置：连接按解析后的路径缓存。
    import os

    os.environ["WANWEI_MEMORY_DB"] = str(db_path)

    try:
        from app.db import close_all
        from app.init_db import main as init_db
        from app.memoryos import harness

        close_all()
        init_db()
        report = harness.run_suite(
            suite=args.suite,
            output_dir=output_dir,
            save_traces=args.save_traces,
        )
        _print_summary(report)
        print(f"\n报告已写入: {output_dir / 'meb_score_report.json'}")

        if args.write_baseline:
            print(f"基线已写入: {harness.write_baseline(report, output_dir=output_dir)}")

        # 门禁按「先看绝对门槛、再看相对退步」的顺序判定，并且**都要跑完**
        # 再返回，这样一次运行能把两类问题一起报出来，不必改一处跑一遍。
        exit_code = 0
        if args.fail_under is not None and report["scores"]["mheb_overall"] < args.fail_under:
            print(
                f"\nMHEB {report['scores']['mheb_overall']} < 门槛 {args.fail_under}",
                file=sys.stderr,
            )
            exit_code = 1
        if args.compare_baseline:
            verdict = harness.compare_to_baseline(
                report, output_dir=output_dir, threshold=args.regression_threshold,
            )
            if verdict["status"] == "regressed":
                print(f"::error::{verdict['message']}", file=sys.stderr)
            elif verdict["status"] == "malformed":
                print(verdict["message"], file=sys.stderr)
            else:
                print(verdict["message"])
            if not verdict["ok"]:
                exit_code = 1
        if report["summary"]["failed"]:
            exit_code = 1
        return exit_code
    finally:
        try:
            from app.db import close_all

            close_all()
        except Exception:
            pass
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
