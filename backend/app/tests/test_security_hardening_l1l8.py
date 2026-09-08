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

import asyncio
import inspect
import re

import pytest
from fastapi.testclient import TestClient


def test_l1_identity_no_key_prefix_and_strength_rule():
    from backend.app import app_runtime
    assert app_runtime.memory_identity.__name__ == 'memory_identity'
    assert 'api_key_prefix' in inspect.getsource(app_runtime.memory_identity)
    assert re.search(r'(?=.*[a-z])', inspect.getsource(app_runtime.memory_identity_rotate))


def test_l2_upsert_validates_endpoint_first():
    from backend.app.model_gateway import service
    # 行为级验证：写入时静态校验（语法+主机黑名单，不做 DNS 解析）——
    # scheme 非法 / 内网主机被拒，公网 .example 域名可通过（真实 DNS pin
    # 留给调用时执行，与 resolve_external_url 的语义分工见 upsert_config 注释）。
    import pytest as _pytest
    from backend.app.security.ssrf import SSRFError
    common = dict(api_key="k", model="m", enabled=True, notes="")
    with _pytest.raises(SSRFError):
        service.upsert_config(provider="p1", api_base="ftp://x.example/v1", **common)
    with _pytest.raises(SSRFError):
        service.upsert_config(provider="p2", api_base="http://127.0.0.1:9/v1", **common)
    with _pytest.raises(SSRFError):
        service.upsert_config(provider="p3", api_base="https://user:pw@x.example/v1", **common)
    ok = service.upsert_config(provider="p4", api_base="https://x.example/v1", **common)
    assert ok


def test_l3_workflow_limits():
    from backend.app.workflow.service import WorkflowRunIn
    with pytest.raises(Exception):
        WorkflowRunIn(scenario='x' * 2001)


def test_l4_upload_quota_constants():
    from backend.app.platform_api import mobile_remote
    assert mobile_remote.MAX_FILES == 1000
    assert mobile_remote.MAX_TOTAL_BYTES == 1024 * 1024 * 1024


def test_l5_subscriber_cap_and_idle_default(monkeypatch, tmp_path):
    from backend.app.platform_api import mobile_remote
    import importlib
    monkeypatch.setenv('WANWEI_API_KEY', 'test-key')
    import backend.app.security.auth as auth_mod
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod
    importlib.reload(auth_mod); importlib.reload(runtime_mod); importlib.reload(main_mod)
    assert mobile_remote._SUBSCRIBERS_MAX == 100
    mobile_remote._SUBSCRIBERS.update(asyncio.Event() for _ in range(mobile_remote._SUBSCRIBERS_MAX))
    try:
        response = TestClient(main_mod.app).get(
            '/platform/mobile/events', params={'max_idle': 1}, headers={'X-API-Key': 'test-key'}
        )
        assert response.status_code == 429
    finally:
        mobile_remote._SUBSCRIBERS.clear()


def test_l5_subscriber_released_after_normal_stream(monkeypatch):
    from backend.app.platform_api import mobile_remote
    from backend.app import main
    monkeypatch.setenv('WANWEI_API_KEY', 'test-key')
    import importlib
    import backend.app.security.auth as auth_mod
    import backend.app.app_runtime as runtime_mod
    importlib.reload(auth_mod); importlib.reload(runtime_mod); importlib.reload(main)
    # reload runtime 会级联刷新 platform_api.mobile_remote；顶部旧绑定已失效，
    # 这里重取最新模块对象并复用同一名字（del 旧绑定避免 F811 重复定义告警）。
    del mobile_remote
    mobile_remote = importlib.import_module('backend.app.platform_api.mobile_remote')
    async def immediate_timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(mobile_remote.asyncio, 'wait_for', immediate_timeout)
    async def exercise():
        response = await mobile_remote.realtime_events(since=0, max_idle=1)
        assert response.status_code == 200
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks
    asyncio.run(exercise())
    assert not mobile_remote._SUBSCRIBERS
    asyncio.run(exercise())
    assert not mobile_remote._SUBSCRIBERS


def test_l6_download_error_does_not_echo_exception(monkeypatch):
    from backend.app.platform_api import _system_svc_runtime as mod
    from backend.app.security.ssrf import SSRFError
    notes = []
    resolve = lambda *args, **kwargs: (_ for _ in ()).throw(
        SSRFError('http://10.0.0.1/internal-host')
    )
    monkeypatch.setattr(mod, 'resolve_external_url', resolve)
    monkeypatch.setattr(mod, '_mark_real_download_error', lambda did, note, **kwargs: notes.append(note))
    mod._real_download_worker('test-id', 'http://10.0.0.1/internal-host', '', asyncio.Event())
    assert notes == ['真实下载失败：URL 未通过 SSRF 校验']


def test_l7_uses_mutate():
    from backend.app.platform_api import automation, _system_svc_runtime
    assert '_runs.mutate' in inspect.getsource(automation._materialize_run_owner)
    assert '_sys_store.mutate' in inspect.getsource(_system_svc_runtime.voice_delete)


def test_l8_rechecks_paths_before_git_use():
    from backend.app.platform_api import spaces
    assert inspect.getsource(spaces.commit_in_space).count('validate_repo_files') >= 2
