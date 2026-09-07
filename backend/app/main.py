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

"""FastAPI application entrypoint.

Runtime implementation lives in ``backend.app.app_runtime``.
This module re-exports the FastAPI ``app`` instance for ASGI servers and TestClient.
All route handlers and service functions remain in ``app_runtime`` to avoid
module-level state duplication caused by ``sys.modules`` self-aliasing.
"""
from __future__ import annotations

from .app_runtime import app
