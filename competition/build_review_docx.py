#!/usr/bin/env python3
"""将 competition/评审报告.md 导出为评委版 Word 文档。

排版规范（Issue #216）：全文微软雅黑；正文小四（12pt）；标题加粗放大；
英文术语已在正文中附中文标注；架构思维导图嵌入第二章。
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "评审报告.md"
OUT = ROOT / "宛委枢忆-评审报告.docx"
MINDMAP = ROOT.parent / "assets" / "mindmap" / "wanwei_shuyi_osagent_2_0_mindmap.png"

FONT = "微软雅黑"


def set_font(run, size_pt: float, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = FONT
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), FONT)
    rfonts.set(qn("w:hAnsi"), FONT)
    rfonts.set(qn("w:eastAsia"), FONT)


def add_runs(par, text: str, size: float, bold: bool = False) -> None:
    """处理 **bold** 与 `code` 行内标记。"""
    for token in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            set_font(par.add_run(token[2:-2]), size, bold=True)
        elif token.startswith("`") and token.endswith("`"):
            run = par.add_run(token[1:-1])
            set_font(run, size)
            run.font.color.rgb = RGBColor(0x7A, 0x33, 0x00)
        else:
            set_font(par.add_run(token), size, bold=bold)


def main() -> None:
    lines = SRC.read_text(encoding="utf-8").splitlines()
    doc = Document()

    # 页面：A4，常规页边距
    for section in doc.sections:
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2.54)
        section.left_margin = section.right_margin = Cm(3.0)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(12)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    table_buffer: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_buffer
        if not table_buffer:
            return
        rows = [r for r in table_buffer if not re.match(r"^\|?\s*:?-+", r)]
        table_buffer = []
        if not rows:
            return
        cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
        table = doc.add_table(rows=len(cells), cols=len(cells[0]))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, row in enumerate(cells):
            for j, val in enumerate(row):
                cell = table.cell(i, j)
                par = cell.paragraphs[0]
                add_runs(par, val, 11)
                if i == 0:
                    for run in par.runs:
                        run.font.bold = True

    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith("|"):
            table_buffer.append(line)
            continue
        flush_table()
        if not line.strip():
            continue
        if line.strip() == ">":  # 空引用行，仅作段落分隔
            continue
        if line.startswith("> "):  # 头部元信息块
            par = doc.add_paragraph()
            add_runs(par, line[2:], 11)
            for run in par.runs:
                run.font.color.rgb = RGBColor(0x5B, 0x6B, 0x7A)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level, title = len(m.group(1)), m.group(2)
            if title.startswith("2.2") and MINDMAP.exists():
                par = doc.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = par.add_run()
                run.add_picture(str(MINDMAP), width=Cm(15.2))
                cap = doc.add_paragraph()
                cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                set_font(cap.add_run("图 2-1 宛委·枢忆 OSAgent 2.0 整体架构"), 10.5)
            if level == 1:
                par = doc.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
                set_font(par.add_run(title), 22, bold=True)
                par.paragraph_format.space_after = Pt(18)
            else:
                sizes = {2: 17, 3: 14, 4: 12.5}
                par = doc.add_paragraph()
                add_runs(par, title, sizes.get(level, 12.5), bold=True)
                par.paragraph_format.space_before = Pt(14)
                par.paragraph_format.space_after = Pt(6)
                if level == 2 and title.startswith("第二章"):
                    pass  # 架构图在 2.1 后嵌入，见下方图片占位行
            continue
        if line.strip() == "---":
            continue
        if line.startswith("- "):
            par = doc.add_paragraph(style="List Bullet")
            add_runs(par, line[2:], 12)
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            # Word "List Number" 样式会跨章节连续编号；改为显式编号文本，
            # 保证每个有序列表在文档内独立从 1 开始。
            par = doc.add_paragraph()
            add_runs(par, f"{m.group(1)}. {m.group(2)}", 12)
            par.paragraph_format.left_indent = Cm(0.6)
            continue
        par = doc.add_paragraph()
        add_runs(par, line, 12)
        par.paragraph_format.first_line_indent = Cm(0.85)
        par.paragraph_format.line_spacing = 1.4

    flush_table()
    doc.save(OUT)
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
