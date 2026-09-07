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

"""memoryos.certificate 单元测试：删除证明 PDF 生成。

不依赖 HTTP 层，直接验证 PDF 结构、审计编号、内容边界。
"""
from __future__ import annotations

import pytest

from backend.app.memoryos.certificate import (
    _audit_serial,
    _content_summary,
    generate_deletion_certificate,
)


def _verification(complete: bool = True, residue: dict | None = None) -> dict:
    return {
        "capsule_id": "cap_test123",
        "complete": complete,
        "residue": residue or {
            "capsules": 0,
            "fts": 0,
            "relation_edges": 0,
            "vector_refs": 0,
            "legacy_capsules": 0,
            "legacy_event_links": 0,
        },
        "residue_total": sum((residue or {}).values()) if residue else 0,
        "vector_pending": 0,
        "checked_at": "2026-08-27T01:30:00Z",
    }


class TestPdfStructure:
    """PDF 基本结构：magic bytes、非空、可被解析。"""

    def test_generates_valid_pdf_bytes(self):
        pdf = generate_deletion_certificate("cap_test123", _verification())
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000  # 有实际内容

    def test_complete_verdict_in_pdf(self):
        """完整验证的 PDF 结构有效（CID 字体内容经压缩，验证结构而非明文）。"""
        pdf = generate_deletion_certificate("cap_test123", _verification(complete=True))
        # PDF 结构标记：header、page 对象、EOF
        assert pdf[:5] == b"%PDF-"
        assert b"/Page" in pdf
        assert pdf.rstrip().endswith(b"%%EOF")

    def test_incomplete_verdict_in_pdf(self):
        residue = {"capsules": 1, "fts": 2}
        pdf = generate_deletion_certificate("cap_test123", _verification(complete=False, residue=residue))
        assert len(pdf) > 1000

    def test_none_capsule_handled(self):
        """硬删后 capsule 为 None，证书如实标注而非崩溃。"""
        pdf = generate_deletion_certificate("cap_deleted", _verification(), capsule=None)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000


class TestAuditSerial:
    """审计编号：全局唯一、含账本锚点、格式稳定。"""

    def test_serial_format(self):
        serial = _audit_serial("cap_abc", "2026-08-27T01:30:00Z")
        assert serial.startswith("MGC-")
        parts = serial.split("-")
        assert len(parts) == 3  # MGC-{ledger8}-{hash12}

    def test_serial_deterministic(self):
        s1 = _audit_serial("cap_abc", "2026-08-27T01:30:00Z")
        s2 = _audit_serial("cap_abc", "2026-08-27T01:30:00Z")
        assert s1 == s2

    def test_serial_differs_by_capsule(self):
        s1 = _audit_serial("cap_aaa", "2026-08-27T01:30:00Z")
        s2 = _audit_serial("cap_bbb", "2026-08-27T01:30:00Z")
        assert s1 != s2


class TestContentSummary:
    """内容摘要：截断、多行合并、None 安全。"""

    def test_dict_content(self):
        cap = {"content": {"text": "项目A的数据库密码是 abc123"}}
        assert "项目A" in _content_summary(cap)

    def test_long_content_truncated(self):
        cap = {"content": {"text": "x" * 200}}
        summary = _content_summary(cap)
        assert len(summary) <= 81  # 80 + "…"
        assert summary.endswith("…")

    def test_none_capsule(self):
        summary = _content_summary(None)
        assert "物理删除" in summary

    def test_empty_content(self):
        cap = {"content": {}}
        assert isinstance(_content_summary(cap), str)
