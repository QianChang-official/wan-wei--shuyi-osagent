"""仓库根 conftest：保证 ``backend.app.*`` 绝对导入在任何 cwd 下都可用。

背景
----
测试套件里 50 个文件用 ``from backend.app...`` 绝对导入，4 个用 ``from app...``
短导入。前者要求**仓库根目录**在 ``sys.path`` 上；后者要求 ``backend/`` 在
``sys.path`` 上。而 ``backend/`` 下没有 ``__init__.py``，pytest 的 rootdir
自动插值又依赖 conftest 的所在位置，于是从 ``backend/`` 目录执行 pytest 时
会出现 ``ModuleNotFoundError: No module named 'backend'``（8 个文件收集失败）。

pytest 会在收集任何测试模块**之前**自动加载本文件，因此在这里补齐两条路径
即可让两种导入风格都成立，且无需修改任何测试文件、无需依赖调用者的 cwd。
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_BACKEND = _REPO_ROOT / "backend"

# 顺序无关紧要，但保持"根在前"与既有测试内的 sys.path.insert 习惯一致。
for _path in (_REPO_ROOT, _BACKEND):
    _entry = str(_path)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
