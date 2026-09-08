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

"""Regression tests for issue #90: main.py sys.modules self-aliasing cleanup.

验证:
- main.py 不再包含 sys.modules 自替换
- main.py 仅做简单的 from .app_runtime import app  re-export
- main.py 不暴露 ARENA_METRICS_PATH 等 app_runtime 内部属性
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

MAIN_PY = Path(__file__).resolve().parents[3] / "backend" / "app" / "main.py"


def test_main_py_has_no_sys_modules_self_alias():
    """main.py 不应再出现 sys.modules 自替换。"""
    text = MAIN_PY.read_text(encoding="utf-8")
    assert "sys.modules[" not in text, "main.py still contains sys.modules manipulation"


def test_main_py_only_reexports_app():
    """main.py 应仅 re-export app 实例。"""
    text = MAIN_PY.read_text(encoding="utf-8")
    assert "from .app_runtime import app" in text


def test_main_py_does_not_leak_internal_globals():
    """main.py 不应暴露 app_runtime 的内部全局变量。"""
    from backend.app import main
    # ARENA_METRICS_PATH 是 app_runtime 内部变量，不应通过 main 暴露
    assert not hasattr(main, "ARENA_METRICS_PATH"), (
        "main.py leaks ARENA_METRICS_PATH; tests should import app_runtime directly"
    )
