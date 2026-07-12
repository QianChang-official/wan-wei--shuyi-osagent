from __future__ import annotations


TOOLS = [
    {
        "id": "mcp_filesystem_readonly",
        "name_cn": "文件系统只读 MCP",
        "kind": "mcp_server",
        "permission_mode": "readonly",
        "sandbox": "supervised",
        "status": "planned",
        "result_storage": "evidence_card",
        "description": "用于读取项目文件、文档和日志；默认不允许写入。",
    },
    {
        "id": "memory_arena_runner",
        "name_cn": "MemoryArena 运行器",
        "kind": "internal_tool",
        "permission_mode": "advisory",
        "sandbox": "local_runtime",
        "status": "done",
        "result_storage": "reports",
        "description": "运行 5 个 MemoryArena-Lite case 并输出 metrics/report。",
    },
    {
        "id": "github_or_gitee_sync",
        "name_cn": "代码仓同步工具",
        "kind": "external_tool",
        "permission_mode": "supervised",
        "sandbox": "git_remote",
        "status": "partial",
        "result_storage": "audit_log",
        "description": "提交推送必须在本地验证后执行；远程写入保留人工监督语义。",
    },
]

SKILLS = [
    {
        "id": "memory_governance_policy",
        "name_cn": "记忆治理策略",
        "scope": "policy",
        "status": "done",
        "entrypoint": "文档中心_DOCUMENTATION_HUB.md#doc-memory-governance-policy-b93fa11b",
        "description": "定义长期记忆生产、确认、隔离、遗忘和审计规则。",
    },
    {
        "id": "platform_export_pack",
        "name_cn": "参赛材料导出",
        "scope": "deliverable",
        "status": "partial",
        "entrypoint": "文档中心_DOCUMENTATION_HUB.md#doc-competition-requirement-coverage-beaccf0d",
        "description": "把 README、技术方案、测试报告、用户手册、适配报告映射为交付包。",
    },
]


def list_tools() -> dict:
    return {"items": TOOLS}


def list_skills() -> dict:
    return {"items": SKILLS}
