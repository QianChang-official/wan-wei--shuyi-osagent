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

from __future__ import annotations


EXPORT_PACKAGES = [
    {
        "id": "technical_solution",
        "name_cn": "技术方案",
        "status": "partial",
        "evidence_files": ["README.md", "文档中心_DOCUMENTATION_HUB.md#doc-v07-memoryops-autopilot-platform-5b136d61", "文档中心_DOCUMENTATION_HUB.md#doc-architecture-8f6366fd"],
        "demo_path": "/console/#/platform",
    },
    {
        "id": "test_report",
        "name_cn": "测试报告",
        "status": "partial",
        "evidence_files": ["reports/production_memory_eval_metrics.json", "reports/archive/production_memory_eval_report.md"],
        "demo_path": "/console/#/",
    },
    {
        "id": "compatibility_report",
        "name_cn": "适配测试报告",
        "status": "partial",
        "evidence_files": ["文档中心_DOCUMENTATION_HUB.md#doc-compatibility-test-report-b002acd2", "文档中心_DOCUMENTATION_HUB.md#doc-kylin-docs-mapping-86762731"],
        "demo_path": "/console/#/exports",
    },
    {
        "id": "user_manual",
        "name_cn": "用户手册",
        "status": "partial",
        "evidence_files": ["文档中心_DOCUMENTATION_HUB.md#doc-user-manual-47b5dd4f"],
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
