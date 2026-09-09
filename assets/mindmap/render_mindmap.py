#!/usr/bin/env python3
"""渲染 README 整体架构思维导图（微软雅黑，评委可读的大字号）。

数据源为 ``wanwei_shuyi_osagent_2_0_mindmap.mmd`` 的同构内容；两者需同步维护。
输出 ``wanwei_shuyi_osagent_2_0_mindmap.png``（README 引用）。

用法：python assets/mindmap/render_mindmap.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.family"] = "Microsoft YaHei"
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
OUT = HERE / "wanwei_shuyi_osagent_2_0_mindmap.png"

# 架构内容：与 backend/app 实际模块一一对应（2026-09 main 分支现状）。
BRANCHES_LEFT = [
    ("交互层", ["Vue3 控制台", "Electron 麒麟桌面端", "手机端 LAN 配对"], "#4C78A8"),
    ("平台接入", ["FastAPI 后端", "模型网关（多供应商）", "MCP 工具接入", "工作流与审批"], "#58508D"),
    ("安全与隔离", ["owner 数据隔离", "审计 fail-closed", "策略门禁 Policy Gate"], "#BC5090"),
]
BRANCHES_RIGHT = [
    ("偏好记忆（EGPM）", ["Beta 后验置信更新", "情感证据调制", "结果反馈闭环", "偏好记忆图演化", "工具调用序列挖掘"], "#E06C3F"),
    ("知识治理", ["知识冲突检测与消解", "TKE 知识双时态演化", "关联检索：RRF 三路融合", "本地向量索引"], "#2E8B6E"),
    ("记忆流转", ["工作→短期→中期→长期", "遗忘与重要性衰减", "记忆胶囊存储"], "#8C6D1F"),
    ("治理与评测", ["MemoryOS 生命周期状态机", "不可变账本与可证明删除", "MEB 基准与消融实验", "麒麟 V11 实机适配"], "#3D5A80"),
]

FIG_W, FIG_H = 20, 12.5
ROOT_POS = (0.5, 0.5)
ROOT_SIZE = (0.16, 0.09)


def draw_box(ax, cx, cy, w, h, text, fc, fontsize, text_color="white", bold=True, ec="none"):
    box = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.006,rounding_size=0.012",
        linewidth=1.2, edgecolor=ec, facecolor=fc, zorder=3,
    )
    ax.add_patch(box)
    ax.text(
        cx, cy, text, ha="center", va="center", fontsize=fontsize,
        color=text_color, fontweight="bold" if bold else "normal", zorder=4,
    )


def connect(ax, x1, y1, x2, y2, color):
    arrow = FancyArrowPatch(
        (x1, y1), (x2, y2),
        connectionstyle="arc3,rad=0.12",
        arrowstyle="-", linewidth=1.6, color=color, alpha=0.75, zorder=1,
    )
    ax.add_patch(arrow)


def layout_side(ax, branches, side, root_xy):
    """side=-1 左列, +1 右列。分支纵向均布，叶节点排在分支外侧。"""
    rx, ry = root_xy
    n = len(branches)
    ys = [0.845 - i * (0.70 / (n - 1)) for i in range(n)]
    bx = 0.5 + side * 0.185
    leaf_x = 0.5 + side * 0.345
    bw, bh = 0.152, 0.052
    lw, lh = 0.155, 0.038
    for (title, leaves, color), by in zip(branches, ys):
        connect(ax, rx + side * ROOT_SIZE[0] / 2, ry, bx - side * bw / 2, by, color)
        draw_box(ax, bx, by, bw, bh, title, color, 19)
        m = len(leaves)
        # 叶节点以分支中心为轴纵向均布，避免首/末叶越出画布或与相邻分支重叠。
        spacing = lh * 1.42
        ly0 = by + (m - 1) * spacing / 2
        for j, leaf in enumerate(leaves):
            ly = ly0 - j * spacing
            connect(ax, bx + side * bw / 2, by, leaf_x - side * lw / 2, ly, color)
            draw_box(ax, leaf_x, ly, lw, lh, leaf, "#F4F6F8", 15, text_color="#23303D", bold=False, ec=color)


def main() -> None:
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H), dpi=100)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        0.5, 0.985, "宛委·枢忆 OSAgent 2.0 整体架构",
        ha="center", va="top", fontsize=29, fontweight="bold", color="#1A2733",
    )
    ax.text(
        0.5, 0.936, "面向银河麒麟桌面 OS 的端侧偏好与知识记忆系统（与 main 分支模块一一对应）",
        ha="center", va="top", fontsize=16, color="#5B6B7A",
    )

    layout_side(ax, BRANCHES_LEFT, -1, ROOT_POS)
    layout_side(ax, BRANCHES_RIGHT, +1, ROOT_POS)
    draw_box(ax, *ROOT_POS, *ROOT_SIZE, "宛委·枢忆\nOSAgent 2.0", "#23303D", 22)

    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
