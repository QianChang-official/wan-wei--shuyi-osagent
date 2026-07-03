from __future__ import annotations


EXPORT_PACKAGES = [
    {
        "id": "technical_solution",
        "name_cn": "技术方案",
        "status": "partial",
        "evidence_files": ["README.md", "docs/V07_MEMORYOPS_AUTOPILOT_PLATFORM.md", "docs/ARCHITECTURE.md"],
        "demo_path": "/console/#/platform",
    },
    {
        "id": "test_report",
        "name_cn": "测试报告",
        "status": "partial",
        "evidence_files": ["reports/production_memory_eval_metrics.json", "reports/production_memory_eval_report.md"],
        "demo_path": "/console/#/",
    },
    {
        "id": "compatibility_report",
        "name_cn": "适配测试报告",
        "status": "partial",
        "evidence_files": ["docs/COMPATIBILITY_TEST_REPORT.md", "docs/KYLIN_DOCS_MAPPING.md"],
        "demo_path": "/console/#/exports",
    },
    {
        "id": "user_manual",
        "name_cn": "用户手册",
        "status": "partial",
        "evidence_files": ["docs/USER_MANUAL.md"],
        "demo_path": "/console/#/exports",
    },
    {
        "id": "ppt_and_video",
        "name_cn": "PPT 与演示视频",
        "status": "pending",
        "evidence_files": [],
        "demo_path": "/console/#/exports",
    },
]


def list_packages() -> dict:
    return {"items": EXPORT_PACKAGES}