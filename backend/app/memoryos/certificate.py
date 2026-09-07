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

"""Memory Governance Certificate —— 删除证明 PDF 生成。

把 ``verify_deletion`` 的五处逐项取证结果渲染为一份可下载的 PDF 证书，
让「真的删干净了吗」从一句 API JSON 变成一份可归档、可出示的凭证。

设计决策
--------
- **纯内存生成（BytesIO），不落临时文件**：证书是凭证，写临时文件反而增加
  泄露面与清理负担。每次请求现生成，与账本保持实时一致。
- **中文用 reportlab 内置 CID 字体 ``STSong-Light``**：无需打包外部字体，
  麒麟/Windows/Linux 均可渲染。这是 Adobe 亚洲语言包的标准字体，
  reportlab 通过 ``UnicodeCIDFont`` 内置支持。
- **审计编号**：取该 capsule 最近一次 delete 账目的 ``ledger_id``，加验证
  时间戳的 SHA-256 前 12 位——前者锚定不可变账本，后者锚定本次验证动作，
  两者拼接即全局唯一。
"""
from __future__ import annotations

import hashlib
import io
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from .governance import ledger_history, now

# 注册内置中文 CID 字体（模块级一次，幂等）。
_FONT = "STSong-Light"
try:
    pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
except Exception:  # pragma: no cover - 重复注册或环境缺失时静默降级
    _FONT = "Helvetica"

#: 五处取证项的中文标签（与 verify_deletion 的 checks 键一一对应）。
_CHECK_LABELS = {
    "capsules": "主表残留",
    "fts": "全文索引残留",
    "relation_edges": "图边反向引用",
    "vector_refs": "向量索引引用",
    "legacy_capsules": "遗留主表残留",
    "legacy_event_links": "遗留事件关联",
}

#: 证书页边距与行距（mm）。
_MARGIN = 25 * mm
_LINE = 8 * mm


def _audit_serial(capsule_id: str, checked_at: str) -> str:
    """生成审计编号：最近 delete 账目 id + 验证时间戳哈希。

    两部分来源都不可伪造：ledger_id 来自 append-only 账本（触发器强制），
    checked_at 哈希绑定本次验证动作。无 delete 账目时用 capsule_id 占位——
    说明该记忆从未被删除，证书仍如实反映。
    """
    deletes = ledger_history(capsule_id, limit=1, op_type="delete")
    anchor = deletes[0]["ledger_id"] if deletes else f"nodelete:{capsule_id}"
    digest = hashlib.sha256(
        f"{anchor}|{checked_at}".encode("utf-8")
    ).hexdigest()[:12].upper()
    return f"MGC-{anchor[-8:].upper()}-{digest}"


def _content_summary(capsule: dict[str, Any] | None) -> str:
    """从胶囊提取内容摘要（硬删后 capsule 为 None，如实标注）。"""
    if capsule is None:
        return "（该记忆已被物理删除，主表无行——这本身即为删除证据）"
    content = capsule.get("content") or {}
    if isinstance(content, dict):
        text = content.get("text") or content.get("value") or str(content)
    else:
        text = str(content)
    text = text.strip().replace("\n", " ")
    return text[:80] + ("…" if len(text) > 80 else "")


def generate_deletion_certificate(
    capsule_id: str,
    verification: dict[str, Any],
    capsule: dict[str, Any] | None = None,
) -> bytes:
    """生成删除证明 PDF，返回字节流。

    Args:
        capsule_id: 被删除的记忆 id。
        verification: ``verify_deletion`` 的返回（五处逐项计数 + complete 标志）。
        capsule: 当前胶囊快照（硬删后为 None，此时证书如实标注「主表无行」）。

    Returns:
        PDF 文件的完整字节内容，可直接写入 ``Response`` body。
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - _MARGIN

    def line(text: str, size: int = 11, bold: bool = False, gap: float = _LINE):
        nonlocal y
        c.setFont(_FONT, size)
        c.drawString(_MARGIN, y, text)
        y -= gap * (1.4 if bold else 1.0)

    checked_at = verification.get("checked_at") or now()
    serial = _audit_serial(capsule_id, checked_at)

    # ── 标题区 ──────────────────────────────────────────────────────────
    line("宛委·枢忆 记忆治理证明", size=20, bold=True, gap=12 * mm)
    line("Memory Governance Certificate", size=12, gap=10 * mm)
    c.setLineWidth(0.5)
    c.line(_MARGIN, y, width - _MARGIN, y)
    y -= 8 * mm

    # ── 结论区 ──────────────────────────────────────────────────────────
    complete = bool(verification.get("complete"))
    verdict = "删除验证通过：未发现任何残留" if complete else "删除验证未通过：存在残留项"
    line(f"验证结论：{verdict}", size=14, bold=True, gap=12 * mm)
    line(f"审计编号：{serial}", size=11)
    line(f"验证时间：{checked_at}", size=11, gap=10 * mm)

    # ── 对象区 ──────────────────────────────────────────────────────────
    line("删除对象", size=13, bold=True, gap=9 * mm)
    line(f"记忆 ID：{capsule_id}", size=11)
    line(f"内容摘要：{_content_summary(capsule)}", size=11, gap=10 * mm)

    # ── 逐项取证区 ──────────────────────────────────────────────────────
    line("逐项取证结果", size=13, bold=True, gap=9 * mm)
    residue = verification.get("residue") or {}
    for key, label in _CHECK_LABELS.items():
        count = residue.get(key, 0)
        mark = "✓ 无残留" if count == 0 else f"✗ 残留 {count} 处"
        line(f"{label}：{mark}", size=11)
    vector_pending = verification.get("vector_pending", 0)
    pending_mark = "✓ 无在途" if vector_pending == 0 else f"✗ {vector_pending} 条待清扫"
    line(f"向量清扫在途：{pending_mark}", size=11, gap=10 * mm)

    # ── 证据链说明 ──────────────────────────────────────────────────────
    c.setLineWidth(0.5)
    c.line(_MARGIN, y, width - _MARGIN, y)
    y -= 8 * mm
    line("证据链说明", size=13, bold=True, gap=9 * mm)
    line("本证书基于 append-only 治理账本生成，账本由 SQLite 触发器强制", size=10, gap=6 * mm)
    line("（UPDATE/DELETE 直接 ABORT），任何事后篡改都会在链上留下断点。", size=10, gap=6 * mm)
    line("上述五项取证覆盖记忆的全部存储位置：主表、全文索引、图边、", size=10, gap=6 * mm)
    line("向量索引与遗留表。全部为零且向量无在途时，删除方为完整。", size=10, gap=10 * mm)

    # ── 页脚 ────────────────────────────────────────────────────────────
    c.setFont(_FONT, 9)
    c.drawString(
        _MARGIN, _MARGIN,
        "本证书由宛委·枢忆 MemoryOS 治理层自动生成，与不可变账本实时一致。",
    )

    c.showPage()
    c.save()
    return buf.getvalue()
