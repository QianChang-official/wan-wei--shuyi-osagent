"""
command_loop 单元测试 (v0.9.6 T2)

覆盖：
- classify_risk 的 low / medium / high / critical 分支
- execution_mode_for 映射
- run_command_loop 的确认点生成、blocked_actions、unsafe_autonomy 红线

安全关键模块 —— 风险分级与确认流程必须有断言。
"""

from backend.app.memory_runtime.command_loop import (
    classify_risk,
    execution_mode_for,
    run_command_loop,
)


def test_classify_low_risk():
    assert classify_risk("介绍一下天气") == "low"


def test_classify_medium_risk_by_keyword():
    assert classify_risk("帮我做一个计划") == "medium"
    assert classify_risk("代码审查") == "medium"


def test_classify_high_risk():
    assert classify_risk("删除这个文件") == "high"
    assert classify_risk("rm -rf /tmp/x") == "high"
    assert classify_risk("部署到服务器") == "high"


def test_classify_critical_risk():
    assert classify_risk("格式化磁盘") == "critical"
    assert classify_risk("导出私钥") == "critical"
    assert classify_risk("连接生产数据库") == "critical"


def test_critical_takes_priority_over_high():
    # 同时含 critical 和 high 词，应判 critical
    assert classify_risk("删除生产数据库") == "critical"


def test_execution_mode_mapping():
    assert execution_mode_for("low") == "advisory_mode"
    assert execution_mode_for("medium") == "advisory_mode"
    assert execution_mode_for("high") == "supervised_mode"
    assert execution_mode_for("critical") == "read_only_mode"


def test_run_command_loop_low_risk_no_confirmation(isolated_db):
    r = run_command_loop(goal="介绍天气情况")
    assert r["risk_assessment"]["risk_class"] == "low"
    assert r["confirmation_points"] == []
    assert r["risk_assessment"]["unsafe_autonomy"] is False
    assert r["execution_mode"] == "advisory_mode"


def test_run_command_loop_high_risk_has_confirmation(isolated_db):
    r = run_command_loop(goal="删除旧日志文件")
    assert r["risk_assessment"]["risk_class"] == "high"
    assert len(r["confirmation_points"]) == 1
    assert r["confirmation_points"][0]["reason"] == "high_risk"
    assert r["confirmation_points"][0]["default_action_if_no_response"] == "do_not_execute"
    assert r["execution_mode"] == "supervised_mode"


def test_run_command_loop_critical_blocks_autonomous_execution(isolated_db):
    r = run_command_loop(goal="格式化生产数据库")
    assert r["risk_assessment"]["risk_class"] == "critical"
    assert "execute_without_human_approval" in r["blocked_actions"]
    assert r["execution_mode"] == "read_only_mode"
    assert len(r["confirmation_points"]) == 1
    assert r["confirmation_points"][0]["reason"] == "critical_risk"


def test_run_command_loop_result_shape(isolated_db):
    r = run_command_loop(goal="做个周报计划", scene="reporting")
    assert r["task_understanding"]["scene"] == "reporting"
    assert r["task_understanding"]["task_id"].startswith("task_")
    assert "recommended_plan" in r
    assert r["recommended_plan"][0]["step"] == 1
    assert "reflection_plan" in r
    assert r["reflection_plan"]["required"] is True


def test_run_command_loop_unsafe_autonomy_always_false(isolated_db):
    # 安全红线：即便 critical，也不得出现 unsafe autonomy
    for goal in ["介绍天气", "做计划", "删除文件", "格式化磁盘"]:
        r = run_command_loop(goal=goal)
        assert r["risk_assessment"]["unsafe_autonomy"] is False
