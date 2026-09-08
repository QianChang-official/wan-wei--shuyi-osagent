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

"""Regression coverage for the application's canonical ``app.*`` module identity."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = PROJECT_ROOT / "backend" / "app"
STANDALONE_ENTRYPOINTS = {APP_ROOT / "memory_arena" / "runner.py"}


def test_production_package_uses_relative_internal_imports():
    """Production modules must not create a second ``backend.app`` package tree."""
    absolute_imports: list[str] = []

    for path in APP_ROOT.rglob("*.py"):
        if "tests" in path.parts or path in STANDALONE_ENTRYPOINTS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            for module_name in imported_modules:
                if module_name == "backend.app" or module_name.startswith("backend.app."):
                    relative_path = path.relative_to(PROJECT_ROOT)
                    absolute_imports.append(f"{relative_path}:{node.lineno}:{module_name}")

    assert absolute_imports == []


def test_asgi_entrypoint_loads_one_database_module():
    """The deployed ``PYTHONPATH=backend`` entrypoint must keep one DB singleton."""
    probe = """
import json
import sys

import app.db
import app.main
from app.platform_api import knowledge

duplicates = sorted(
    name for name in sys.modules
    if name == 'backend.app' or name.startswith('backend.app.')
)
print('MODULE_IDENTITY=' + json.dumps({
    'duplicates': duplicates,
    'shared_get_conn': knowledge.get_conn is app.db.get_conn,
}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "backend")
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    result_line = next(
        line for line in completed.stdout.splitlines() if line.startswith("MODULE_IDENTITY=")
    )
    result = json.loads(result_line.removeprefix("MODULE_IDENTITY="))

    assert result == {"duplicates": [], "shared_get_conn": True}
