#!/usr/bin/env python3
"""Mulan PSL v2 版权头批量管理工具（幂等）。

用途
----
为仓库内自有源码文件统一添加 / 校验木兰宽松许可证第 2 版版权头，
版权所有者为 QianChang-official（2026）。用于满足竞赛交付要求
"源代码需提供完整注释，确保可读性与可复用性，无知识产权纠纷"。

设计要点
--------
- 只处理 ``git ls-files`` 列出的受跟踪文件，天然避开 .gitignore 忽略物。
- 每种文件类型使用其合法注释语法；``.py``/``.sh`` 保留 shebang 与
  PEP 263 编码声明，版权头插在其后。
- 幂等：文件前 ``HEADER_SCAN_LINES`` 行内已含许可证标识即跳过；
  ``--apply`` 重复执行不产生重复头。
- 排除目录覆盖第三方代码、生成物与数据目录，避免触碰非自有资产。

用法
----
    python scripts/license_header.py            # 预览（dry-run）
    python scripts/license_header.py --apply    # 写入
    python scripts/license_header.py --check    # CI 校验，缺失时退出码 1
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

LICENSE_MARKER = "is licensed under Mulan PSL v2"
COPYRIGHT_LINE = "Copyright (c) 2026 QianChang-official"
HEADER_SCAN_LINES = 40

BODY_LINES = (
    "",
    "宛委·枢忆 is licensed under Mulan PSL v2.",
    "You can use this software according to the terms of the Mulan PSL v2.",
    "You may obtain a copy of Mulan PSL v2 at:",
    "http://license.coscl.org.cn/MulanPSL2",
    "",
    'THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,',
    "EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,",
    "MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.",
    "See the Mulan PSL v2 for more details.",
)


@dataclass(frozen=True)
class CommentStyle:
    """一种注释语法。block 风格给出起止符与行前缀。"""

    prefix: str
    block_start: str | None = None
    block_end: str | None = None

    def render(self) -> str:
        lines = [COPYRIGHT_LINE, *BODY_LINES]
        if self.block_start is None:
            return "\n".join(f"{self.prefix} {line}".rstrip() for line in lines) + "\n\n"
        body = "\n".join(f"{self.prefix} {line}".rstrip() for line in lines)
        return f"{self.block_start}\n{body}\n{self.block_end}\n\n"


HASH_STYLE = CommentStyle("#")
SLASH_STYLE = CommentStyle("//")
HTML_STYLE = CommentStyle("", block_start="<!--", block_end="-->")

STYLE_BY_SUFFIX: dict[str, CommentStyle] = {
    ".py": HASH_STYLE,
    ".sh": HASH_STYLE,
    ".ps1": HASH_STYLE,
    ".yml": HASH_STYLE,
    ".yaml": HASH_STYLE,
    ".js": SLASH_STYLE,
    ".mjs": SLASH_STYLE,
    ".cjs": SLASH_STYLE,
    ".ts": SLASH_STYLE,
    ".vue": HTML_STYLE,
}

# 非自有代码 / 生成物 / 数据目录：不添加版权头。
EXCLUDED_PREFIXES = (
    "node_modules/",
    "frontend/console-vue/node_modules/",
    "frontend/console-vue/dist/",
    "desktop/build/",
    "desktop/node_modules/",
    "native/kylin-sdk-bridge/node_modules/",
    "__pycache__/",
    "data/",
    "reports/",
    "assets/",
    "secrets/",
    "AI优化/",
    ".pytest_cache/",
    ".ruff_cache/",
)

EXCLUDED_SUFFIXES = (".min.js", ".d.ts")
EXCLUDED_NAMES = {"package-lock.json"}

SHEBANG_RE = re.compile(r"^#!")
ENCODING_RE = re.compile(r"^#.*coding[:=]\s*[-\w.]+")


def list_tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def is_target(path: Path) -> bool:
    posix = path.as_posix()
    if path.name in EXCLUDED_NAMES:
        return False
    if any(posix.startswith(prefix) or f"/{prefix}" in posix for prefix in EXCLUDED_PREFIXES):
        return False
    if any(posix.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return False
    return path.suffix.lower() in STYLE_BY_SUFFIX


def insertion_index(lines: list[str], suffix: str) -> int:
    """版权头插入点：shebang 与编码声明必须保留在文件最前。"""
    index = 0
    if lines and SHEBANG_RE.match(lines[0]):
        index = 1
    if suffix == ".py" and len(lines) > index and ENCODING_RE.match(lines[index]):
        index += 1
    return index


def needs_header(content: str) -> bool:
    head = "\n".join(content.splitlines()[:HEADER_SCAN_LINES])
    return LICENSE_MARKER not in head


def apply_header(path: Path) -> bool:
    """为单个文件写入版权头。返回是否有改动。"""
    full = REPO_ROOT / path
    raw = full.read_bytes()
    # 保留既有 UTF-8 BOM：部分 Windows 工具链依赖它识别中文编码。
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    content = raw.decode("utf-8-sig")
    if not needs_header(content):
        return False
    style = STYLE_BY_SUFFIX[path.suffix.lower()]
    lines = content.splitlines(keepends=True)
    idx = insertion_index([line.rstrip("\n") for line in lines], path.suffix.lower())
    header = style.render()
    new_content = "".join(lines[:idx]) + header + "".join(lines[idx:])
    data = new_content.encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    full.write_bytes(data)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="写入缺失的版权头")
    group.add_argument("--check", action="store_true", help="只校验，缺失时退出码 1")
    args = parser.parse_args()

    targets = [p for p in list_tracked_files() if is_target(p) and (REPO_ROOT / p).is_file()]
    missing: list[Path] = []
    for path in targets:
        content = (REPO_ROOT / path).read_bytes().decode("utf-8-sig")
        if needs_header(content):
            missing.append(path)

    if args.check:
        if missing:
            print(f"[license-header] {len(missing)} 个文件缺少木兰 PSL v2 版权头：")
            for path in missing:
                print(f"  - {path.as_posix()}")
            return 1
        print(f"[license-header] 全部 {len(targets)} 个源码文件已携带版权头。")
        return 0

    if not args.apply:
        print(f"[license-header] dry-run：{len(missing)}/{len(targets)} 个文件待补版权头（--apply 写入）。")
        return 0

    changed = sum(1 for path in missing if apply_header(path))
    print(f"[license-header] 已为 {changed} 个文件写入版权头（共扫描 {len(targets)} 个源码文件）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
