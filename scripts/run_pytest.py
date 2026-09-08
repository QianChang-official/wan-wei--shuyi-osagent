#!/usr/bin/env python3
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

"""Repository pytest launcher with a Kylin V11 binary-extension preload guard.

On the validated Kylin V11 x86_64 VM, direct ``python -m pytest`` can fail during
collection while FastAPI lazily imports Pydantic v2's binary ``pydantic_core``
extension with ``failed to map segment from shared object``. A normal interpreter
import of the same extension succeeds when the process is started from stdin or
``-c``. This launcher re-execs into that mode, preloads the modules, then invokes
pytest without skipping or weakening tests.
"""
from __future__ import annotations

import os
import sys

_INLINE = """
from __future__ import annotations
import sys
try:
    import pydantic_core  # noqa: F401
    import pydantic  # noqa: F401
    import fastapi  # noqa: F401
except ImportError:
    pass
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
"""


def main() -> int:
    if os.environ.get("WANWEI_PYTEST_INLINE") != "1":
        env = os.environ.copy()
        env["WANWEI_PYTEST_INLINE"] = "1"
        os.execve(sys.executable, [sys.executable, "-c", _INLINE, *sys.argv[1:]], env)
    # Defensive fallback: normally unreachable because execve replaces process.
    import pytest
    return pytest.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
