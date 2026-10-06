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

"""Windows 10/11 判定：必须依据 build 号，而非 platform.release()。"""

from __future__ import annotations

import sys

import pytest

from app.platform_api.os_description import (
    WINDOWS_11_MIN_BUILD,
    is_windows_11,
    os_description,
    os_facts,
    os_name,
    windows_build,
)


class _FakeVersion:
    def __init__(self, build: int) -> None:
        self.build = build


@pytest.mark.parametrize(
    ('build', 'expected'),
    [
        (19041, 'Windows 10'),# 20H1
        (19042, 'Windows 10'),
        (19043, 'Windows 10'),
        (19045, 'Windows 10'),      # 22H2 —— Win10 末代
        (19999, 'Windows 10'),
        (21999, 'Windows 10'),      # 边界之下
        (22000, 'Windows 11'),      # 边界
        (22621, 'Windows 11'),      # 22H2
        (26100, 'Windows 11'),      # 24H2
        (29671, 'Windows 11'),      # 本机实测 build
        (34500, 'Windows 11'),      # 未来版本仍判Win11
    ],
)
def test_windows_generation_follows_build_not_release(monkeypatch, build, expected):
    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Windows')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: _FakeVersion(build), raising=False)
    assert os_name() == expected
    assert is_windows_11() == (expected == 'Windows 11')


def test_win11_never_reported_as_win10_even_when_release_says_10(monkeypatch):
    """回归：Python 3.11 在 Win11 上 platform.release() 返回 '10'，曾导致误报 Windows 10。"""
    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Windows')
    monkeypatch.setattr('app.platform_api.os_description.platform.release', lambda: '10')
    monkeypatch.setattr('app.platform_api.os_description.platform.version', lambda: '10.0.29671')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: _FakeVersion(29671), raising=False)
    assert os_name() == 'Windows 11'
    description = os_description()
    assert description.startswith('Windows 11')
    assert '10.0' not in description


def test_build_22000_boundary_is_inclusive():
    assert WINDOWS_11_MIN_BUILD == 22000


def test_non_windows_reports_release(monkeypatch):
    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Linux')
    monkeypatch.setattr('app.platform_api.os_description.platform.release', lambda: '6.8.0-generic')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: None, raising=False)
    assert os_name() == 'Linux'
    assert is_windows_11() is False
    assert windows_build() is None
    assert '6.8.0-generic' in os_description()


def test_windows_without_getwindowsversion_degrades_honestly(monkeypatch):
    """拿不到 build 号时不猜版本，只说 Windows。"""
    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Windows')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: None, raising=False)
    assert os_name() == 'Windows'
    assert windows_build() is None
    assert is_windows_11() is False
    assert 'build unknown' in os_description()


def test_getwindowsversion_raising_is_absorbed(monkeypatch):
    def boom():
        raise OSError('no api')

    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Windows')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: boom(), raising=False)
    assert windows_build() is None
    assert os_name() == 'Windows'


def test_os_facts_shape_and_content(monkeypatch):
    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Windows')
    monkeypatch.setattr('app.platform_api.os_description.platform.machine', lambda: 'AMD64')
    monkeypatch.setattr(
        'app.platform_api.os_description.platform.python_version', lambda: '3.11.0')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: _FakeVersion(29671), raising=False)
    facts = os_facts()
    assert facts['windows_build'] == 29671
    assert facts['windows_11'] is True
    assert facts['arch'] == 'AMD64'
    assert facts['python'] == '3.11.0'
    assert facts['os_description'].startswith('Windows 11')
    # 不得泄漏可识别信息
    assert 'hostname' not in facts
    assert set(facts) == {'os_description', 'arch', 'python', 'windows_build', 'windows_11'}


def test_os_facts_on_non_windows_omits_windows_keys(monkeypatch):
    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Darwin')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: None, raising=False)
    facts = os_facts()
    assert 'windows_build' not in facts
    assert 'windows_11' not in facts
    assert facts['os_description'].startswith('Darwin')


def test_device_info_system_uses_new_description(monkeypatch):
    """device_metrics('system') 必须走新判定，而不是旧的 platform.release()。"""
    psutil = pytest.importorskip('psutil')
    from app.platform_api import agent_bridge

    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Windows')
    monkeypatch.setattr('app.platform_api.os_description.platform.machine', lambda: 'AMD64')
    monkeypatch.setattr('app.platform_api.os_description.platform.release', lambda: '10')
    monkeypatch.setattr('app.platform_api.os_description.platform.node', lambda: 'test-host')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: _FakeVersion(29671), raising=False)
    monkeypatch.setattr(psutil, 'cpu_count', lambda: 8)
    # agent_bridge.time 与 psutil 内部共享 time 模块，故boot_time 一并打桩，
    # 否则 psutil 自身的 time.time() 也会被替换成递归lambda。
    monkeypatch.setattr(psutil, 'boot_time', lambda: 1000.0)
    monkeypatch.setattr(agent_bridge.time, 'time', lambda: 1100.0)

    info = agent_bridge._device_info('system')
    assert info['os'].startswith('Windows 11')
    assert info['windows_11'] is True
    assert info['windows_build'] == 29671
    assert info['uptime_s'] == 100
    assert info['hostname'] == 'test-host'


def test_arch_suffix_omitted_when_machine_empty(monkeypatch):
    monkeypatch.setattr('app.platform_api.os_description.platform.system', lambda: 'Linux')
    monkeypatch.setattr('app.platform_api.os_description.platform.release', lambda: '6.8.0')
    monkeypatch.setattr('app.platform_api.os_description.platform.machine', lambda: '')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: None, raising=False)
    assert os_description() == 'Linux (6.8.0)'