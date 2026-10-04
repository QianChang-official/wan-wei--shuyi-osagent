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

"""platform_api 子模块：编程框架舱（挂载 ``app.coding`` 的路由）。

``app.coding`` 是独立的编程框架包；本模块只做一件事——把它的 ``router``
暴露给 ``platform_api`` 的自动发现机制，于是实际路径为
``/platform/coding/...``，与其余平台舱位同前缀、同鉴权、同 owner 隔离，
并复用"单模块导入失败只跳过自己"的故障隔离语义。

**为什么 ``app.coding`` 内部的 platform_api 依赖是惰性导入**：
``coding`` 需要复用 ``platform_api.store``（JSON 持久化）与
``platform_api.guards``（root_path 白名单校验）。若这两处在 ``coding``
模块级导入，则「import coding → import platform_api.__init__ → 自动发现
→ import platform_api.coding → import coding.api（半初始化）」会成环。
改为函数内惰性导入后，``coding`` 的模块级导入不再触发 ``platform_api``
包初始化，环被彻底断开；首次调用时两侧均已就绪，导入即时命中缓存。
"""
from __future__ import annotations

from ..coding.api import router  # noqa: F401 —— 供 platform_api 自动发现

__all__ = ['router']
