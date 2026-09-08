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

"""CJK 文本分词工具：FTS5 unicode61 分词器的中文适配共享层。

背景（issue #119 / #133 / #89）：
SQLite FTS5 的 ``unicode61`` 分词器不切分连续 CJK 文本——一整段中文会被
当成**一个** token，导致任何局部中文子串查询在倒排索引上恒 0 命中。
知识库（``platform_api/knowledge.py``）先行落地了「入库侧 CJK 逐字插空格 +
查询侧逐字 atom」方案（fts_schema_version v2）；记忆底座此前未处理，中文
召回实际全靠 ``LIKE '%…%'`` 全表扫描兜底。

查询侧切词策略（issue #89 的选型）：
- **bigram 优先**：连续 CJK 段切为滑动双字（"兼容性" → "兼 容"/"容 性"）。
  FTS5 支持 phrase 语法，双字 phrase 直接消除单字 OR 的「字符重合抽奖」
  精度问题——单字 OR 下「量子色动力学」会命中任何含「学/用/术」的无关
  文本（test_retrieval.test_search_no_match_returns_empty 钉死了这个边界）。
- **单字兜底**：孤立的单个 CJK 字符（长度 1 的段）退化为单字 atom。
- **非 CJK 连续段**整体成 atom，混排 token（"Windows麒麟"）两个语种都保留
  （issue #133：旧实现 if/elif 分支让 ASCII 段被整段丢弃）。

本模块保持无状态（仅正则与纯函数）。应用包内部统一使用相对导入，避免
部署入口 ``app.*`` 与仓库测试入口 ``backend.app.*`` 在同一进程形成两套
模块对象；独立评测入口则固定使用后者，二者不会混载。
"""

from __future__ import annotations

import re

# CJK 统一表意文字（含 Ext A）。比 knowledge 旧版 _CJK_RE 覆盖面一致，
# 保持索引格式兼容（v2 方案本身就是按这套字符类插的空格）。
CJK_CHAR_RE = re.compile(r'([\u4e00-\u9fff\u3400-\u4dbf])')

# FTS5 查询串的 atom 数量上限：防止超长查询被拼接成巨型 MATCH 表达式。
_MAX_QUERY_ATOMS = 48

# FTS5 保留字不能作为裸 atom（避免 MATCH 语法被查询文本劫持）。
_FTS_KEYWORDS = frozenset({'AND', 'OR', 'NOT', 'NEAR'})


def cjk_space(text: str) -> str:
    """对 CJK 字符逐字插入空格，使 unicode61 分词器能逐字索引。

    入库侧使用。返回值只应写入 FTS 索引列，**不要**用于展示
    （展示走原文，见 knowledge 的 title 联表读原值方案）。
    """
    if not text:
        return text
    return CJK_CHAR_RE.sub(r' \1 ', text)


def query_atoms(q: str, *, max_atoms: int = _MAX_QUERY_ATOMS) -> list[str]:
    """把自由文本查询切成 FTS5 atom 列表。

    每个 atom 是以下三种之一：
    - CJK bigram（``"兼 容"`` 形式，带内嵌空格，供 phrase 匹配）
    - CJK 单字（孤立字符兜底）
    - 非 CJK 连续字母数字段（如 ``Windows`` / ``OS24``）
    """
    atoms: list[str] = []
    cjk_run: list[str] = []      # 当前连续 CJK 段
    word_buf: list[str] = []     # 当前连续非 CJK 词段

    def flush_word() -> None:
        if word_buf and len(atoms) < max_atoms:
            atoms.append(''.join(word_buf))
        word_buf.clear()

    def flush_cjk() -> None:
        if not cjk_run:
            return
        if len(cjk_run) == 1:
            if len(atoms) < max_atoms:
                atoms.append(cjk_run[0])
        else:
            for i in range(len(cjk_run) - 1):
                if len(atoms) >= max_atoms:
                    break
                atoms.append(f'{cjk_run[i]} {cjk_run[i + 1]}')
        cjk_run.clear()

    for ch in q or '':
        if CJK_CHAR_RE.match(ch):
            flush_word()
            cjk_run.append(ch)
        elif ch.isalnum() or ch == '_':
            flush_cjk()
            word_buf.append(ch)
        else:
            flush_word()
            flush_cjk()
        if len(atoms) >= max_atoms:
            break
    flush_word()
    flush_cjk()
    return atoms[:max_atoms]


def fts_match_expr(q: str, *, max_atoms: int = _MAX_QUERY_ATOMS) -> str:
    """把自由文本查询转成 FTS5 MATCH 表达式（quoted atom 的 OR 连接）。

    空 atom 时返回空串，由调用方决定是否跳过 FTS 通路。
    """
    atoms = query_atoms(q, max_atoms=max_atoms)
    quoted = [
        f'"{a}"'
        for a in atoms
        if a and '"' not in a and a.upper() not in _FTS_KEYWORDS
    ]
    return ' OR '.join(quoted)
