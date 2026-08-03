"""Issue #38 platform batch B regression tests (FIX-10/11/12/14/15/20)."""

from __future__ import annotations

import copy
import importlib
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[3]
HEADERS = {'x-api-key': 'test-key'}


def _client(tmp_path: Path) -> TestClient:
    os.environ['WANWEI_API_KEY'] = 'test-key'
    os.environ['WANWEI_MEMORY_DB'] = str(tmp_path / 'memory.db')
    os.environ['WANWEI_PLATFORM_DIR'] = str(tmp_path / 'platform')
    os.environ.pop('WANWEI_PRODUCTION', None)
    os.environ.pop('WANWEI_DEVICE_GEAR_ENABLED', None)

    for path in (str(PROJECT_ROOT / 'backend'), str(PROJECT_ROOT)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


class _RaceStore:
    """Store double that deterministically exposes legacy get/set lost updates."""

    def __init__(self, data: dict):
        self.data = copy.deepcopy(data)
        self._lock = threading.RLock()
        self._read_barrier = threading.Barrier(2)
        self._coordinated_reads = 0

    def get(self, key: str, default=None):
        with self._lock:
            value = copy.deepcopy(self.data.get(key, default))
            coordinate = self._coordinated_reads < 2
            self._coordinated_reads += 1
        if coordinate:
            self._read_barrier.wait(timeout=5)
        return value

    def set(self, key: str, value) -> None:
        with self._lock:
            self.data[key] = copy.deepcopy(value)

    def all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def update(self, mapping: dict) -> None:
        with self._lock:
            self.data.update(copy.deepcopy(mapping))

    def mutate(self, fn):
        with self._lock:
            working = copy.deepcopy(self.data)
            result = fn(working)
            self.data = working
            return copy.deepcopy(result)


def test_provider_probe_connects_to_pinned_ip_with_original_host(monkeypatch):
    from backend.app.platform_api import providers

    captured: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            captured['client'] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, **kwargs):
            captured['url'] = url
            captured['request'] = kwargs
            return SimpleNamespace(status_code=204)

    monkeypatch.setattr(providers.httpx, 'Client', _Client)
    response = providers._probe_pinned_url(
        'https://provider.example:8443/v1/models?q=1',
        '203.0.113.42',
    )

    assert response.status_code == 204
    assert captured['client']['trust_env'] is False
    assert captured['client']['follow_redirects'] is False
    assert captured['url'] == 'https://203.0.113.42:8443/v1/models?q=1'
    assert captured['request']['headers']['Host'] == 'provider.example:8443'
    assert captured['request']['extensions']['sni_hostname'] == 'provider.example'


def test_provider_config_concurrent_partial_updates_are_not_lost(monkeypatch):
    from backend.app.platform_api import providers

    store = _RaceStore({})
    monkeypatch.setattr(providers, '_store', store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(providers.put_config, 'openai', providers.ConfigIn(model='model-a')),
            pool.submit(providers.put_config, 'openai', providers.ConfigIn(enabled=True)),
        ]
        for future in futures:
            future.result(timeout=5)

    assert store.data['openai']['model'] == 'model-a'
    assert store.data['openai']['enabled'] is True


def test_space_updates_and_cascade_delete_use_atomic_store_mutations(monkeypatch):
    from backend.app.platform_api import spaces

    project = {
        'id': 'sp_root', 'name': 'root', 'desc': '', 'kind': 'project_space',
        'kind_label': '项目空间', 'root_path': '', 'default_branch': 'main',
        'parent_id': None, 'created_at': '2026-01-01T00:00:00Z', 'archived': False,
    }
    child = {**project, 'id': 'sp_child', 'name': 'child', 'parent_id': 'sp_root'}
    store = _RaceStore({'sp_root': project, 'sp_child': child})
    monkeypatch.setattr(spaces, '_projects', store)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(spaces.update_project, 'sp_root', spaces.ProjectUpdateIn(name='renamed')),
            pool.submit(spaces.update_project, 'sp_root', spaces.ProjectUpdateIn(desc='kept')),
        ]
        for future in futures:
            future.result(timeout=5)
    assert store.data['sp_root']['name'] == 'renamed'
    assert store.data['sp_root']['desc'] == 'kept'

    result = spaces.delete_project('sp_root')
    assert result['deleted_children'] == ['sp_child']
    assert 'sp_root' not in store.data and 'sp_child' not in store.data


def test_mcp_server_partial_updates_are_atomic(monkeypatch):
    from backend.app.platform_api import mcp_hub

    record = {
        'id': 'srv_test', 'name': 'old', 'note': '', 'transport': 'stdio',
        'command': None, 'args': [], 'env': {}, 'url': None, 'enabled': False,
        'status': 'unknown', 'created_at': '2026-01-01T00:00:00Z',
        'tools_cache': [], 'tools_count': 0,
    }
    store = _RaceStore({'srv_test': record})
    monkeypatch.setattr(mcp_hub, '_store', store)
    monkeypatch.setattr(mcp_hub, '_ensure_seeded', lambda: None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(mcp_hub.update_server, 'srv_test', mcp_hub.ServerPatch(name='new')),
            pool.submit(mcp_hub.update_server, 'srv_test', mcp_hub.ServerPatch(note='preserved')),
        ]
        for future in futures:
            future.result(timeout=5)
    assert store.data['srv_test']['name'] == 'new'
    assert store.data['srv_test']['note'] == 'preserved'

    mcp_hub._delete_key('srv_test')
    assert 'srv_test' not in store.data


@pytest.mark.parametrize(
    ('command', 'args'),
    [
        ('python', ['-c', 'print(1)']),
        ('python.exe', ['-c=print(1)']),
        ('node', ['--eval', 'console.log(1)']),
        ('node', ['-econsole.log(1)']),
        ('npx.cmd', ['-c', 'whoami']),
        ('powershell.exe', ['-c', 'Get-ChildItem']),
        ('powershell.exe', ['-EncodedCommand', 'ZQBjAGgAbwA=']),
        ('cmd.exe', ['/c', 'dir']),
        ('python', ['-I', '-c', 'print(1)']),
        ('node', ['--no-warnings', '--eval', 'console.log(1)']),
        ('cmd.exe', ['/d', '/c', 'dir']),
        ('bash', ['-lc', 'id']),
        ('python', ['-Ic', 'print(1)']),
        ('python', ['-IBc', 'print(1)']),
        ('cmd.exe', ['/d/c', 'dir']),
        ('cmd.exe', ['/q/d/c', 'dir']),
        ('cmd.exe', ['/d/k', 'dir']),
    ],
)
def test_mcp_interpreter_inline_execution_flags_are_rejected(command, args):
    from backend.app.platform_api import mcp_hub

    with pytest.raises(ValueError):
        mcp_hub._validate_stdio_args(command, args)


def test_mcp_interpreter_double_dash_stops_option_scanning():
    from backend.app.platform_api import mcp_hub

    mcp_hub._validate_stdio_args('python', ['--', '-c', 'not-inline-code'])


@pytest.mark.parametrize(
    ('command', 'args'),
    [
        ('python', ['-IB', 'trusted_server.py']),
        ('python', ['-Xdevc', 'trusted_server.py']),
        ('python', ['-Wignore::DeprecationWarning', 'trusted_server.py']),
        ('py', ['-V:PythonCore/3.14c']),
        ('cmd.exe', ['/d', '/q']),
        ('npx.cmd', ['--yes', 'trusted-mcp-package']),
        ('trusted-mcp', ['-c', 'literal-wrapper-argument']),
    ],
)
def test_mcp_stdio_argument_guard_preserves_non_inline_options(command, args):
    from backend.app.platform_api import mcp_hub

    mcp_hub._validate_stdio_args(command, args)


def test_mcp_late_runtime_result_does_not_overwrite_newer_config(monkeypatch):
    from backend.app.platform_api import mcp_hub

    record = {
        'id': 'srv_test', 'name': 'before', 'note': '', 'transport': 'stdio',
        'command': 'trusted-mcp', 'args': [], 'env': {'TOKEN': 'enc:v1:old'},
        'url': None, 'enabled': True, 'status': 'unknown',
        '_config_revision': 4, 'created_at': '2026-01-01T00:00:00Z',
        'tools_cache': [], 'tools_count': 0,
    }
    store = _RaceStore({'srv_test': record})
    monkeypatch.setattr(mcp_hub, '_store', store)
    monkeypatch.setattr(mcp_hub, '_ensure_seeded', lambda: None)

    updated = mcp_hub.update_server(
        'srv_test',
        mcp_hub.ServerPatch(name='after', env={'TOKEN': 'new-secret'}),
    )
    assert updated['name'] == 'after'
    assert mcp_hub._mark_error('srv_test', 4, 'late failure') is False
    assert store.data['srv_test']['name'] == 'after'
    assert store.data['srv_test']['status'] == 'unknown'
    assert store.data['srv_test']['env']['TOKEN'] != 'enc:v1:old'


def test_mcp_lazy_env_migration_preserves_concurrent_record_fields(monkeypatch):
    from backend.app.platform_api import mcp_hub

    stale = {
        'id': 'srv_test', 'name': 'before', 'env': {'TOKEN': 'old-plain'},
    }
    current = {
        **stale,
        'name': 'after',
        'note': 'concurrent update',
        'env': {'TOKEN': 'new-plain'},
    }
    store = _RaceStore({'srv_test': current})
    monkeypatch.setattr(mcp_hub, '_store', store)
    monkeypatch.setattr(mcp_hub.encryption, 'encrypt', lambda value: f'encrypted:{value}')

    assert mcp_hub._decrypt_env(stale) == {'TOKEN': 'old-plain'}
    assert store.data['srv_test']['name'] == 'after'
    assert store.data['srv_test']['note'] == 'concurrent update'
    assert store.data['srv_test']['env']['TOKEN'] == 'enc:v1:encrypted:new-plain'


def test_mcp_transport_url_is_validated_on_create_and_update(monkeypatch):
    from backend.app.platform_api import mcp_hub

    with pytest.raises(HTTPException) as blocked:
        mcp_hub._normalize_server_config({
            'transport': 'sse', 'url': 'http://169.254.169.254/latest/meta-data',
            'command': None, 'args': [],
        })
    assert blocked.value.status_code == 422

    with pytest.raises(HTTPException) as malformed:
        mcp_hub._normalize_server_config({
            'transport': 'sse', 'url': 'http://[::1',
            'command': None, 'args': [],
        })
    assert malformed.value.status_code == 422

    monkeypatch.setattr(mcp_hub, 'validate_external_url', lambda url: url.strip())
    normalized = mcp_hub._normalize_server_config({
        'transport': 'streamable_http', 'url': 'https://mcp.example/sse',
        'command': None, 'args': [],
    })
    assert normalized['url'] == 'https://mcp.example/sse'


@pytest.mark.parametrize(
    ('path', 'payload'),
    [
        ('/platform/system/power', {'prevent_sleep': True}),
        ('/platform/system/settings', {'theme': 'night'}),
        ('/platform/system/browser/launch', {}),
    ],
)
def test_system_mutations_require_explicit_device_gear(tmp_path, path, payload):
    client = _client(tmp_path)
    response = client.request(
        'PUT' if path != '/platform/system/browser/launch' else 'POST',
        path,
        json=payload,
        headers=HEADERS,
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ('path', 'payload', 'method'),
    [
        ('/platform/system/power', {'gear': 'device', 'prevent_sleep': True}, 'PUT'),
        ('/platform/system/settings', {'gear': 'device', 'theme': 'night'}, 'PUT'),
        ('/platform/system/browser/launch', {'gear': 'device'}, 'POST'),
    ],
)
def test_system_mutations_fail_closed_until_device_gear_enabled(tmp_path, path, payload, method, monkeypatch):
    client = _client(tmp_path)
    denied = client.request(method, path, json=payload, headers=HEADERS)
    assert denied.status_code == 403, denied.text

    monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')
    allowed = client.request(method, path, json=payload, headers=HEADERS)
    assert allowed.status_code == 200, allowed.text


def test_background_image_whitelist_rejects_scriptable_values(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')

    rejected = [
        'javascript:alert(1)',
        'http://example.com/background.png',
        'data:image/svg+xml;base64,PHN2Zz48c2NyaXB0Lz48L3N2Zz4=',
        'data:image/png;base64,not-base64',
        'https://example.com/x\");}body{display:none}',
    ]
    for value in rejected:
        response = client.put(
            '/platform/system/settings',
            json={'gear': 'device', 'background_image': value},
            headers=HEADERS,
        )
        assert response.status_code == 422, (value, response.text)

    accepted = client.put(
        '/platform/system/settings',
        json={
            'gear': 'device',
            'background_image': 'data:image/png;base64,iVBORw0KGgo=',
        },
        headers=HEADERS,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['background_image'].startswith('data:image/png;base64,')
