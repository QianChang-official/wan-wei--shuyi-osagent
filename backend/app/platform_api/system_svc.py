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

"""System service router entrypoint shim.

Runtime implementation lives in ``_system_svc_runtime``. The module object is
aliased so tests/imports that patch ``backend.app.platform_api.system_svc`` still
patch the live router runtime.
"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys

from . import _system_svc_runtime as _runtime

_runtime = _importlib.reload(_runtime)
_sys.modules[__name__] = _runtime
