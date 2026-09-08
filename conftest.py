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

"""仓库根 conftest：保证 ``backend.app.*`` 绝对导入在任何 cwd 下都可用。

背景
----
测试套件统一使用 ``from backend.app...`` 绝对导入。仓库根目录必须在
``sys.path`` 上，pytest 的 rootdir 自动插值依赖 conftest 的所在位置。

pytest 会在收集任何测试模块**之前**自动加载本文件，因此在这里插入
仓库根路径即可让绝对导入成立，无需依赖调用者的 cwd。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent

_entry = str(_REPO_ROOT)
if _entry not in sys.path:
    sys.path.insert(0, _entry)

# OriginHostGuardMiddleware 的 Host 白名单默认只含回环字面量；
# Starlette TestClient 发出的请求 Host 是 "testserver"，必须显式放行，
# 否则全部既有测试会在 Host 校验处 403。这是测试专用环境变量，不影响生产。
os.environ.setdefault("WANWEI_ALLOWED_HOSTS", "testserver")
