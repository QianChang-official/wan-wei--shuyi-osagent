"""
宛委枢忆 OSAgent 版本管理

统一版本号，供 /health 端点和其他模块使用。
"""

VERSION = "v0.9.6-rate-limit-and-test-hardening"

# 版本历史
VERSION_HISTORY = [
    {
        "version": "v0.9.6-rate-limit-and-test-hardening",
        "date": "2026-07-06",
        "features": [
            "核心模块单元测试（capsule_store / policy_gate / retrieval / command_loop，核心覆盖率 98%）",
            "性能基线采集工具（perf baseline harness）",
            "N+1 查询批量优化（get_capsules_batch + bump_usage_batch）",
            "移除 workflow _RUNS 内存 fallback（持久化已验证）",
            "线程本地连接复用 + WAL",
            "单进程内存令牌桶限流（rate limit）",
            "pytest 第三方 warnings 过滤，项目代码 warnings 视为错误",
        ],
        "status": "in_progress",
    },
    {
        "version": "v0.9.5-workflow-persistence",
        "date": "2026-07-05",
        "features": [
            "Workflow run SQLite 持久化",
            "Workflow run TTL 自动清理",
            "datetime.utcnow() 迁移到 timezone-aware UTC",
            "FastAPI lifespan 迁移",
            "pytest warnings 清理",
        ],
        "status": "released",
    },
    {
        "version": "v0.9.4",
        "date": "2026-07-04",
        "features": [
            "安全基线修复（SSRF、API认证、敏感GET保护）",
            "动态审计 quick wins 加固",
            "Policy gate 完善",
            "中文检索 fallback 修复",
            "依赖升级（FastAPI 0.109.2）",
        ],
        "status": "released",
    },
    {
        "version": "v0.9.3-workflow-run",
        "date": "2026-07-03",
        "features": [
            "Workflow run dry-run loop",
            "Stage-based orchestration",
            "Trace and artifacts API",
        ],
        "status": "released",
    },
]
