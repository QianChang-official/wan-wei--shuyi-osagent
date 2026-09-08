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

"""Soul Awakening module — persona, affect injection, and chat routing."""

from .persona import get_persona, update_persona, create_persona
from .injector import build_injection_prompt, get_soul_state
from .chat_router import route_chat

__all__ = [
    "get_persona",
    "update_persona",
    "create_persona",
    "build_injection_prompt",
    "get_soul_state",
    "route_chat",
]
