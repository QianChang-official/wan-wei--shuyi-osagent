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

"""操作系统版本描述 —— Windows 10/11 判定必须看 build 号，不能看 ``platform.release()``。

Windows 11 沿用了 10.0 的内核版本号，Microsoft 没有 bump 主版本。因此
``platform.release()`` 在 Win11 上可能返回 ``'10'``（Python 3.11 实测），
也可能返回 ``'11'``（Python 3.13 实测）—— 取决于解释器版本与具体构建，
**不可作为判定依据**。唯一稳定的信号是 ``sys.getwindowsversion().build``：
22000 是 Windows 11 的首个公开发布号，19041~21999 是 Windows 10 的末代。
"""

from __future__ import annotations

import platform
import sys

#: Windows 11 首个公开发布号（21H2 / build 22000），此号及以上即 Win11。
WINDOWS_11_MIN_BUILD = 22000


def windows_build() -> int | None:
    """返回 Windows build 号；非 Windows 平台返回 ``None``。"""
    getter = getattr(sys, 'getwindowsversion', None)
    if getter is None:
        return None
    try:
        return int(getter().build)
    except (AttributeError, OSError, ValueError):
        return None


def is_windows_11() -> bool:
    """是否 Windows 11。非 Windows 平台返回 ``False``。

    注意：这是**按 build 号判定**，不依赖 ``platform.release()``。
    """
    build = windows_build()
    return build is not None and build >= WINDOWS_11_MIN_BUILD


def os_name() -> str:
    """人类可读的操作系统名称，例如 ``'Windows 11'`` / ``'Windows 10'`` / ``'Linux'``。"""
    system = platform.system()
    if system != 'Windows':
        return system or 'unknown'
    build = windows_build()
    if build is None:
        # getwindowsversion 不可用（极老的宿主或被裁剪的解释器），退回 release 但不谎称版本号。
        return 'Windows'
    if build >= WINDOWS_11_MIN_BUILD:
        return 'Windows 11'
    return 'Windows 10'


def os_description() -> str:
    """一行式描述：``'Windows 11 (build 29671) (AMD64)'``。

    与旧的 ``f'{system} {release} ({machine})'`` 相比：
    - 不再输出在 Win11 上具有误导性的 ``10.0.xxxxx``；
    - 附带 build 号，便于使用者自行核对；
    - 非 Windows 平台仍输出 ``release``，因为 Linux/macOS 的 release 有意义。
    """
    machine = platform.machine()
    name = os_name()
    if name.startswith('Windows'):
        build = windows_build()
        detail = f'build {build}' if build is not None else 'build unknown'
    else:
        detail = platform.release()
    tail = f' ({machine})' if machine else ''
    return f'{name} ({detail}){tail}'


def os_facts() -> dict[str, object]:
    """结构化版本事实，供前端展示或问题上报；不含 hostname 等可识别信息。"""
    facts: dict[str, object] = {
        'os_description': os_description(),
        'arch': platform.machine(),
        'python': platform.python_version(),
    }
    build = windows_build()
    if build is not None:
        facts['windows_build'] = build
        facts['windows_11'] = build >= WINDOWS_11_MIN_BUILD
    return facts