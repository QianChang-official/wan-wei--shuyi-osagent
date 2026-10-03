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

"""Offline approval, transport and chat lifecycle regression tests.

No test executes host commands, opens desktop applications, or calls a live LLM.
All file effects are confined to pytest temporary directories.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.app.model_gateway import service as gateway
from backend.app.platform_api import agent_bridge as bridge
from backend.app.platform_api import agents

ALL_GRANTS = {key: True for key in ('fs_read', 'fs_write', 'shell', 'network', 'git')}
TARGET = ('https://api.example.test/v1', 'secret-key', 'bound-model', 'deepseek')


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(tmp_path / 'platform'))
    monkeypatch.setenv('WANWEI_MEMORY_DB', str(tmp_path / 'memory.db'))
    monkeypatch.delenv('WANWEI_DEVICE_GEAR_ENABLED', raising=False)
    monkeypatch.setattr(agents, '_runs_agent_index', None)
    monkeypatch.setattr(agents, '_actor_id', lambda request: request.scope.get('test_owner', 'owner-a'))
    monkeypatch.setattr(agents, '_memory_instructions_block', lambda: ('', 'empty'))
    monkeypatch.setattr(agents, 'audit_safe', lambda *args: None)
    monkeypatch.setattr(bridge, 'audit_safe', lambda *args: None)
    monkeypatch.setattr(bridge, '_CONTEXTS', {})
    monkeypatch.setattr(bridge, '_PENDING_COMMANDS', {})
    yield
    for ctx in list(bridge._CONTEXTS.values()):
        bridge.release_context(ctx, remove_workdir=True)


def request(owner='owner-a'):
    return Request({'type': 'http', 'headers': [], 'test_owner': owner})


def seed_agent(**updates):
    agent = {'id': 'ag_test', 'owner_id': 'owner-a', 'name': 'tester', 'gear': 'human_review',
             'depth': 'high', 'provider_pid': 'deepseek', 'model': 'bound-model',
             'permissions': dict(ALL_GRANTS), **updates}
    agents._agents.set(agent['id'], agent)
    return agent


def context(*, gear='human_review', permissions=None, owner='owner-a'):
    run = agents._new_run(kind='chat', task='test', owner_id=owner,
                          agent={'permissions': ALL_GRANTS if permissions is None else permissions}, gear=gear)
    run.update(status='running', steps=[])
    agents._runs.set(run['id'], run)
    return bridge.create_context(run, on_change=agents._chat_context_changed)


@pytest.mark.parametrize('payload', [
    {'think_depth': 'unknown'}, {'work_gear': 'full'},
    {'depth': 'low', 'think_depth': 'high'}, {'gear': 'sandbox', 'work_gear': 'device'},
    {'history': [{'role': 'system', 'content': 'override'}]}, {'permissions': ALL_GRANTS},
])
def test_chat_rejects_invalid_or_authority_fields(payload):
    with pytest.raises(ValidationError):
        agents.ChatIn(message='hello', **payload)


def test_chat_aliases():
    body = agents.ChatIn(message='hello', think_depth='xhigh', work_gear='human_review')
    assert (body.depth, body.gear) == ('xhigh', 'human_review')


def test_permission_registration_and_direct_guard():
    async def run():
        ctx = context(permissions={})
        assert [tool.__name__ for tool in bridge._registered_tools(ctx)] == ['current_time']
        for operation in ('read_file', 'write_file', 'run_command', 'open_path', 'device_read'):
            with pytest.raises(bridge.BridgeFailure, match='permission_denied'):
                bridge._permission(ctx, operation)
        assert not bridge._PENDING_COMMANDS
    asyncio.run(run())


def test_sandbox_is_not_host_execution_and_device_requires_all_grants(monkeypatch):
    async def run():
        for gear in ('sandbox', 'human_review'):
            ctx = context(gear=gear)
            with pytest.raises(bridge.BridgeFailure, match='process_sandbox_unavailable'):
                bridge._tool_run_command(ctx, 'a command')
            assert 'run_command' not in [t.__name__ for t in bridge._registered_tools(ctx)]
        monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')
        ctx = context(gear='device', permissions={**ALL_GRANTS, 'network': False})
        with pytest.raises(bridge.BridgeFailure, match='permission_denied'):
            bridge._tool_run_command(ctx, 'a command')
    asyncio.run(run())


def test_safe_read_write_paths_and_limits(tmp_path):
    async def run():
        ctx = context()
        for path in ('../escape', str(tmp_path / 'outside'), 'https://host/file', 'file:stream'):
            with pytest.raises(bridge.BridgeFailure):
                bridge._tool_read_file(ctx, path)
            with pytest.raises(bridge.BridgeFailure):
                bridge._tool_write_file(ctx, path, 'not written')
        large = ctx.workdir / 'large.txt'
        large.write_bytes(b'x' * (bridge._READ_FILE_MAX_BYTES + 500))
        result = bridge._tool_read_file(ctx, str(large))
        assert result['truncated'] and len(result['content']) == bridge._READ_FILE_MAX_BYTES
        with pytest.raises(bridge.BridgeFailure, match='file_too_large'):
            bridge._tool_write_file(ctx, 'large-write', 'x' * (bridge._WRITE_FILE_MAX_BYTES + 1))
    asyncio.run(run())


def test_symlink_and_hardlink_escape_rejected(tmp_path):
    async def run():
        ctx = context()
        outside = tmp_path / 'outside.txt'
        outside.write_text('private', encoding='utf-8')
        hard = ctx.workdir / 'hard.txt'
        try:
            hard.hardlink_to(outside)
        except OSError:
            pytest.skip('filesystem does not support hardlinks')
        with pytest.raises(bridge.BridgeFailure):
            bridge._tool_read_file(ctx, str(hard))
        link = ctx.workdir / 'link.txt'
        try:
            link.symlink_to(outside)
        except OSError:
            return  # Windows may disallow symlink creation; hardlink boundary still tested
        with pytest.raises(bridge.BridgeFailure):
            bridge._tool_read_file(ctx, str(link))
        with pytest.raises(bridge.BridgeFailure):
            bridge._tool_write_file(ctx, str(link), 'bad')
    asyncio.run(run())


def test_owner_scoped_one_use_multiple_approvals_and_real_file_result():
    async def run():
        ctx = context()
        one = bridge._tool_write_file(ctx, 'one.txt', 'one')
        duplicate = bridge._tool_write_file(ctx, 'one.txt', 'one')
        two = bridge._tool_write_file(ctx, 'two.txt', 'two')
        assert duplicate['confirm_token'] == one['confirm_token']
        assert len(ctx.pending()) == 2 and not (ctx.workdir / 'one.txt').exists()
        ctx.generating = False
        assert ctx.status() == 'awaiting_review'
        assert bridge.pending_confirmation(one['confirm_token'], 'owner-b') is None
        assert await bridge.resolve_pending_command(one['confirm_token'], True, 'owner-b') is None
        first = await bridge.resolve_pending_command(one['confirm_token'], True, 'owner-a')
        assert first['ok'] and first['status'] == 'awaiting_review'
        assert len(first['pending_confirmations']) == 1
        assert (ctx.workdir / 'one.txt').read_text() == 'one'
        assert await bridge.resolve_pending_command(one['confirm_token'], True, 'owner-a') is None
        second = await bridge.resolve_pending_command(two['confirm_token'], True, 'owner-a')
        assert second['ok'] and second['status'] == 'done' and not second['pending_confirmations']
        assert agents._runs.get(ctx.run_id)['status'] == 'done'
    asyncio.run(run())


def test_approval_denial_ttl_cancel_and_audit_never_leak_ticket(monkeypatch):
    audits = []
    monkeypatch.setattr(bridge, 'audit_safe', lambda event, data: audits.append((event, data)))
    async def run():
        ctx = context()
        denied = bridge._tool_write_file(ctx, 'denied', 'secret content')
        result = await bridge.resolve_pending_command(denied['confirm_token'], False, 'owner-a')
        assert result['denied'] and not result['ok'] and not (ctx.workdir / 'denied').exists()
        assert denied['confirm_token'] not in json.dumps(audits)
        assert 'secret content' not in json.dumps(audits)
        expired_ctx = context()
        expired_ctx.generating = False
        expired = bridge._tool_write_file(expired_ctx, 'expired', 'no')
        bridge._PENDING_COMMANDS[expired['confirm_token']].expires = 0
        assert bridge.pending_confirmation(expired['confirm_token'], 'owner-a') is None
        assert agents._runs.get(expired_ctx.run_id)['status'] == 'failed'
        cancelled_ctx = context()
        ticket = bridge._tool_write_file(cancelled_ctx, 'cancelled', 'no')
        await bridge.cancel_context(cancelled_ctx.run_id)
        assert not cancelled_ctx.workdir.exists()
        assert await bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a') is None
    asyncio.run(run())


def test_concurrent_confirmation_claim_executes_once(monkeypatch):
    calls = []
    async def execute(ticket):
        calls.append(ticket.fingerprint)
        await asyncio.sleep(0)
        return {'ok': True, 'exit_code': 7, 'stdout': 'actual output', 'stderr': 'actual stderr'}
    monkeypatch.setattr(bridge, '_execute_operation', execute)
    async def run():
        ctx = context()
        ticket = bridge._tool_write_file(ctx, 'once', 'yes')
        results = await asyncio.gather(*[bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a')
                                         for _ in range(2)])
        assert len(calls) == 1
        assert sum(r is None for r in results) == 1
        actual = next(r for r in results if r)
        assert actual['exit_code'] == 7 and actual['stdout'] == 'actual output'
    asyncio.run(run())


def test_operation_integrity_and_gate_rechecked(monkeypatch):
    async def run():
        ctx = context()
        ticket = bridge._tool_write_file(ctx, 'bound', 'original')
        bridge._PENDING_COMMANDS[ticket['confirm_token']].payload['content'] = 'tampered'
        result = await bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a')
        assert not result['ok'] and result['error'] == 'approval_operation_changed'
        assert not (ctx.workdir / 'bound').exists()
        monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')
        ctx = context(gear='device')
        ticket = bridge._tool_write_file(ctx, 'revoked-device', 'no')
        monkeypatch.delenv('WANWEI_DEVICE_GEAR_ENABLED')
        result = await bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a')
        assert not result['ok'] and result['error'] == 'device_gear_disabled'
    asyncio.run(run())


def test_run_created_and_bound_provider_depth_before_tool_execution(monkeypatch):
    agent = seed_agent()
    seen = []
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    def target(run, owner_id=None):
        assert run['provider_pid'] == agent['provider_pid'] and owner_id == 'owner-a'
        assert agents._runs.get(run['id'])['status'] == 'running'
        return TARGET
    async def fake_run(system, message, target, *, context, history):
        assert context.depth == 'xhigh' and context.owner_id == 'owner-a'
        assert context.gear == 'human_review' and dict(context.permissions) == ALL_GRANTS
        assert context.run_id == seen[0]['run_id']
        assert not history
        return 'real mocked model response'
    monkeypatch.setattr(agents, '_resolve_gateway_target', target)
    monkeypatch.setattr(bridge, 'run_agent_chat', fake_run)
    # A wrapper records the earliest externally published run_started event.
    async def run_with_step():
        result = await agents._run_chat_pipeline(
            agents.ChatIn(message='hello', agent_id=agent['id'], think_depth='xhigh'), request(), on_step=seen.append)
        assert result['status'] == 'done' and result['provider_used'] == 'deepseek'
        assert agents._runs.get(result['run_id'])['steps'] == []
    asyncio.run(run_with_step())


def test_no_fallback_after_tool_effect_and_failure_preserves_evidence(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    async def forbidden_fallback(*args, **kwargs):
        pytest.fail('a second model request must not conceal effects')
    async def fail_after_effect(system, message, target, *, context, history):
        ticket = bridge._tool_write_file(context, 'artifact', 'actual')
        result = await bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a')
        assert result['ok']
        raise bridge.BridgeFailure('upstream_failed_after_effect')
    monkeypatch.setattr(agents, '_try_gateway', forbidden_fallback)
    monkeypatch.setattr(bridge, 'run_agent_chat', fail_after_effect)
    async def run():
        with pytest.raises(HTTPException) as error:
            await agents.chat(agents.ChatIn(message='write', agent_id=agent['id'], supports_approvals=True), request())
        saved = agents._runs.get(error.value.detail['run_id'])
        assert saved['status'] == 'failed' and saved['operation_results'][0]['ok']
        assert error.value.detail['process_steps'] and not bridge._PENDING_COMMANDS
    asyncio.run(run())


def test_unavailable_bridge_is_explicit_text_only_gateway(monkeypatch):
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', False)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    async def fake_gateway(prompt, run, owner_id):
        assert run['id'] in agents._runs.all() and owner_id == 'owner-a'
        assert '未提供本机操作工具' in prompt
        return 'text only', 'deepseek'
    monkeypatch.setattr(agents, '_try_gateway', fake_gateway)
    result = asyncio.run(agents.chat(agents.ChatIn(message='hello'), request()))
    assert result['capabilities']['reason'] == 'optional_dependencies_missing'
    assert result['process_steps'] == []


def test_history_owner_agent_scope_and_bounds():
    prior = None
    for index in range(10):
        rid = f'history-{index}'
        agents._runs.set(rid, {'id': rid, 'owner_id': 'owner-a', 'agent_id': 'a', 'kind': 'chat',
                              'status': 'done', 'message': 'm' * 2000, 'result': 'r' * 2000,
                              'previous_run_id': prior})
        prior = rid
    body = agents.ChatIn(message='continue', agent_id='a', previous_run_id=prior)
    history = agents._chat_history(body, 'owner-a')
    assert len(history) == 12 and sum(len(m['content']) for m in history) == 24000
    for owner, agent in [('owner-b', 'a'), ('owner-a', 'other-agent')]:
        with pytest.raises(HTTPException) as error:
            agents._chat_history(agents.ChatIn(message='bad', agent_id=agent, previous_run_id=prior), owner)
        assert error.value.status_code == 404


def test_sse_disconnect_cancels_task_and_invalidates_tickets(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    created = []
    async def fake_run(system, message, target, *, context, history):
        created.append(context)
        bridge._tool_write_file(context, 'pending', 'no')
        await context.emit({'kind': 'test_ready'})
        await asyncio.Event().wait()
    monkeypatch.setattr(bridge, 'run_agent_chat', fake_run)
    class Connected:
        scope = {'test_owner': 'owner-a'}
        async def is_disconnected(self):
            return False
    async def run():
        response = await agents.chat_stream(agents.ChatIn(message='start', agent_id=agent['id']), Connected())
        iterator = response.body_iterator
        assert 'run_started' in await anext(iterator)
        assert 'test_ready' in await anext(iterator)
        await iterator.aclose()
        assert not bridge._PENDING_COMMANDS and not agents._CHAT_TASKS
        assert agents._runs.get(created[0].run_id)['status'] == 'cancelled'
        assert not created[0].workdir.exists()
    asyncio.run(run())


def test_sse_normal_final_retains_pending_approvals(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    async def fake_run(system, message, target, *, context, history):
        bridge._tool_write_file(context, 'pending', 'not yet')
        return 'proposed file'
    monkeypatch.setattr(bridge, 'run_agent_chat', fake_run)
    class Connected:
        scope = {'test_owner': 'owner-a'}
        async def is_disconnected(self):
            return False
    async def run():
        response = await agents.chat_stream(agents.ChatIn(message='start', agent_id=agent['id']), Connected())
        frames = [frame async for frame in response.body_iterator]
        final = json.loads(next(frame.split('data: ', 1)[1] for frame in frames if 'event: final' in frame))
        assert final['status'] == 'awaiting_review' and len(final['pending_confirmations']) == 1
        assert bridge.pending_confirmation(final['pending_confirmations'][0]['confirm_token'], 'owner-a')
        assert not agents._CHAT_TASKS
    asyncio.run(run())


def test_native_protocol_never_passes_through_openai_bridge(monkeypatch):
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    for provider in ('anthropic', 'gemini', 'google_ai_studio', 'aws_bedrock',
                     'google_vertex', 'github_copilot', 'qwen_oauth'):
        assert not bridge.bridge_capabilities((*TARGET[:3], provider))['tools_available']
    from backend.app.platform_api.providers import _CATALOG_BY_ID
    assert {'anthropic', 'google_ai_studio', 'aws_bedrock'} <= set(_CATALOG_BY_ID)


def test_gateway_transport_pins_dns_preserves_host_sni_and_rejects_redirects(monkeypatch):
    seen = []
    resolutions = []
    def resolve(url, allowlist=None):
        resolutions.append(url)
        return url, '203.0.113.17'
    monkeypatch.setattr(gateway, 'resolve_external_url', resolve)
    async def run():
        transport = bridge.GatewayTransport(TARGET[0])
        async def respond(request):
            seen.append(request)
            return httpx.Response(200, json={'ok': True})
        await transport.transport.aclose()
        transport.transport = httpx.MockTransport(respond)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(TARGET[0] + '/chat/completions', json={})
            assert response.status_code == 200
            with pytest.raises(bridge.BridgeFailure, match='origin_changed'):
                await client.post('https://another.test/v1/chat/completions', json={})
            with pytest.raises(bridge.BridgeFailure, match='path_not_allowed'):
                await client.post(TARGET[0] + '/files', json={})
        assert seen[0].url.host == '203.0.113.17'
        assert seen[0].headers['host'] == 'api.example.test'
        assert seen[0].extensions['sni_hostname'] == 'api.example.test'
        assert len(resolutions) == 1
        transport = bridge.GatewayTransport(TARGET[0])
        await transport.transport.aclose()
        transport.transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={'location': 'http://127.0.0.1'}))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(bridge.BridgeFailure, match='redirect_denied'):
                await client.post(TARGET[0] + '/chat/completions', json={})
    asyncio.run(run())


@pytest.mark.parametrize('base', ['http://127.0.0.1/v1', 'http://169.254.169.254/v1', 'http://10.0.0.1/v1'])
def test_gateway_transport_forbidden_egress_never_connects(base, monkeypatch):
    monkeypatch.setattr(gateway, 'local_llama_allowlist', lambda: None)
    async def run():
        transport = bridge.GatewayTransport(base)
        await transport.transport.aclose()
        transport.transport = httpx.MockTransport(lambda req: pytest.fail('forbidden network request'))
        async with httpx.AsyncClient(transport=transport) as client:
            from backend.app.security.ssrf import SSRFError
            with pytest.raises(SSRFError):
                await client.post(base + '/chat/completions', json={})
    asyncio.run(run())


@pytest.mark.parametrize('platform,command', [('linux', 'xdg-open'), ('darwin', 'open'), ('win32', None)])
def test_os_opener_selection_is_mocked(monkeypatch, platform, command, tmp_path):
    monkeypatch.setattr(bridge.sys, 'platform', platform)
    monkeypatch.setattr(bridge.shutil, 'which', lambda name: '/mock/' + name)
    expected = None if command is None else ['/mock/' + command, str(tmp_path / 'file.html')]
    assert bridge._opener_args(tmp_path / 'file.html') == expected


@pytest.mark.parametrize('platform', ['linux', 'darwin', 'win32'])
def test_opener_execution_requires_approval_and_uses_mock_os(monkeypatch, platform):
    monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')
    monkeypatch.setattr(bridge.sys, 'platform', platform)
    monkeypatch.setattr(bridge.shutil, 'which', lambda name: '/mock/' + name)
    opened = []
    monkeypatch.setattr(bridge.os, 'startfile', lambda path: opened.append(['startfile', path]), raising=False)
    async def fake_process(args, cwd, timeout_s):
        opened.append(args)
        return {'ok': True, 'exit_code': 0, 'stdout': 'launched', 'stderr': ''}
    monkeypatch.setattr(bridge, '_run_process', fake_process)
    async def run():
        ctx = context(gear='device')
        path = ctx.workdir / 'page.html'
        path.write_text('<p>test</p>', encoding='utf-8')
        ticket = bridge._tool_open_path(ctx, str(path))
        assert not opened and ticket['needs_confirm']
        result = await bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a')
        assert result['ok'] and result['launched'] and len(opened) == 1
        assert opened[0][-1] == str(path)
    asyncio.run(run())


def test_confirmation_endpoint_checks_owner_and_revocation(monkeypatch):
    agent = seed_agent()
    async def fake_run(system, message, target, *, context, history):
        bridge._tool_write_file(context, 'pending', 'no')
        return 'pending'
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    monkeypatch.setattr(bridge, 'run_agent_chat', fake_run)
    async def run():
        response = await agents.chat(agents.ChatIn(message='write', agent_id=agent['id'], supports_approvals=True), request())
        token = response['pending_confirmations'][0]['confirm_token']
        with pytest.raises(HTTPException) as error:
            await agents.chat_confirm(agents.ChatConfirmIn(token=token, approved=True), request('owner-b'))
        assert error.value.status_code == 404
        agent['permissions']['fs_write'] = False
        agents._agents.set(agent['id'], agent)
        with pytest.raises(HTTPException) as error:
            await agents.chat_confirm(agents.ChatConfirmIn(token=token, approved=True), request())
        assert error.value.status_code == 403
        assert not bridge._PENDING_COMMANDS
    asyncio.run(run())


def test_real_optional_library_loop_uses_safe_transport_and_proposes_write(monkeypatch):
    pytest.importorskip('pydantic_ai')
    agent = seed_agent()
    requests = []
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    monkeypatch.setattr(gateway, 'resolve_external_url', lambda url, **kwargs: (url, '203.0.113.17'))

    async def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.host == '203.0.113.17'
        assert request.extensions['sni_hostname'] == 'api.example.test'
        if len(requests) == 1:
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': 'call-write', 'type': 'function', 'function': {
                    'name': 'write_file', 'arguments': json.dumps({'path': 'real-library.txt', 'content': 'real tool result'})},
            }]}
            finish = 'tool_calls'
        else:
            assert payload['messages'][-1]['role'] == 'tool'
            assert 'needs_confirm' in payload['messages'][-1]['content']
            message = {'role': 'assistant', 'content': 'File proposed; awaiting approval.'}
            finish = 'stop'
        return httpx.Response(200, json={
            'id': 'offline-response', 'object': 'chat.completion', 'created': 1, 'model': 'bound-model',
            'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20},
        })

    class OfflineTransport(bridge.GatewayTransport):
        def __init__(self, base_url):
            self.base = httpx.URL(base_url.rstrip('/') + '/')
            self.transport = httpx.MockTransport(respond)
    monkeypatch.setattr(bridge, 'GatewayTransport', OfflineTransport)

    async def run():
        response = await agents.chat(agents.ChatIn(message='write an artifact', agent_id=agent['id'], supports_approvals=True), request())
        assert len(requests) == 2 and requests[0]['model'] == 'bound-model'
        names = {t['function']['name'] for t in requests[0]['tools']}
        assert 'write_file' in names and 'run_command' not in names
        assert response['status'] == 'awaiting_review'
        ticket = response['pending_confirmations'][0]
        assert not Path(ticket['path']).exists()
        result = await agents.chat_confirm(agents.ChatConfirmIn(token=ticket['confirm_token'], approved=True), request())
        assert result['ok'] and result['status'] == 'done'
        assert Path(ticket['path']).read_text() == 'real tool result'
    asyncio.run(run())


def test_cancel_during_claimed_approval_cleans_task(monkeypatch):
    started = None
    async def execute(ticket):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(bridge, '_execute_operation', execute)
    async def run():
        nonlocal started
        started = asyncio.Event()
        ctx = context()
        ctx.generating = False
        ticket = bridge._tool_write_file(ctx, 'cancel-inflight', 'no')
        resolver = asyncio.create_task(bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a'))
        await started.wait()
        await bridge.cancel_context(ctx.run_id)
        assert resolver.cancelled() and not ctx.tasks
        assert not ctx.workdir.exists() and not bridge._PENDING_COMMANDS
        assert not bridge._CONTEXTS
    asyncio.run(run())


def test_denial_cancels_other_inflight_approvals(monkeypatch):
    async def execute(ticket):
        await asyncio.Event().wait()
    monkeypatch.setattr(bridge, '_execute_operation', execute)
    async def run():
        ctx = context()
        ctx.generating = False
        one = bridge._tool_write_file(ctx, 'one', 'one')
        two = bridge._tool_write_file(ctx, 'two', 'two')
        active = asyncio.create_task(bridge.resolve_pending_command(one['confirm_token'], True, 'owner-a'))
        await asyncio.sleep(0)
        with anyio.fail_after(2):
            denied = await bridge.resolve_pending_command(two['confirm_token'], False, 'owner-a')
        assert denied['denied'] and denied['status'] == 'failed'
        assert active.cancelled() and not ctx.tasks and not bridge._PENDING_COMMANDS
    asyncio.run(run())


def test_fake_subprocess_is_async_bounded_and_cancellable(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-inherit')
    calls = []
    processes = []
    class Reader:
        def __init__(self):
            self.left = 5
        async def read(self, size):
            await asyncio.sleep(0)
            self.left -= 1
            return b'x' * 4096 if self.left >= 0 else b''
    class Process:
        returncode = None
        def __init__(self):
            self.stdout, self.stderr = Reader(), Reader()
            self.killed = asyncio.Event()
        async def wait(self):
            await self.killed.wait()
            self.returncode = -9
        def kill(self):
            self.killed.set()
    async def create(*args, **kwargs):
        calls.append(kwargs)
        proc = Process()
        processes.append(proc)
        return proc
    monkeypatch.setattr(bridge.asyncio, 'create_subprocess_exec', create)
    monkeypatch.setattr(bridge, '_terminate_process', lambda proc: proc.kill())
    async def run():
        task = asyncio.create_task(bridge._run_process(['/fake'], tmp_path, 30))
        await asyncio.sleep(0.02)
        assert not task.done() and 'OPENAI_API_KEY' not in calls[0]['env']
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].killed.is_set()
        # Exercise bounded stdout/stderr while the fake process exits normally.
        async def complete(*args, **kwargs):
            proc = Process()
            proc.killed.set()
            return proc
        monkeypatch.setattr(bridge.asyncio, 'create_subprocess_exec', complete)
        result = await bridge._run_process(['/fake'], tmp_path, 30)
        assert result['exit_code'] == -9 and not result['ok']
        assert len(result['stdout']) == bridge._RUN_OUTPUT_TRUNCATE
        assert len(result['stderr']) == bridge._RUN_OUTPUT_TRUNCATE
    asyncio.run(run())


def test_sse_late_eof_invalidates_finished_pipeline_approvals(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    async def fake_run(system, message, target, *, context, history):
        bridge._tool_write_file(context, 'unreceived-final', 'no')
        return 'waiting'
    monkeypatch.setattr(bridge, 'run_agent_chat', fake_run)
    class Connected:
        scope = {'test_owner': 'owner-a'}
        async def is_disconnected(self):
            return False
    async def run():
        response = await agents.chat_stream(agents.ChatIn(message='write', agent_id=agent['id'], supports_approvals=True), Connected())
        frame = await anext(response.body_iterator)
        run_id = json.loads(frame.split('data: ')[1])['run_id']
        with anyio.fail_after(2):
            while agents._CHAT_TASKS:
                await asyncio.sleep(0.01)
        assert bridge._PENDING_COMMANDS
        await response.body_iterator.aclose()
        assert not bridge._PENDING_COMMANDS
        assert agents._runs.get(run_id)['status'] == 'cancelled'
    asyncio.run(run())


def test_sse_queue_backpressure_bounds_producer(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *args, **kwargs: TARGET)
    progress = []
    async def fake_run(system, message, target, *, context, history):
        for index in range(100):
            await context.emit({'kind': 'progress', 'index': index})
            progress.append(index)
        return 'done'
    monkeypatch.setattr(bridge, 'run_agent_chat', fake_run)
    class Connected:
        scope = {'test_owner': 'owner-a'}
        async def is_disconnected(self):
            return False
    async def run():
        response = await agents.chat_stream(agents.ChatIn(message='progress', agent_id=agent['id']), Connected())
        await anext(response.body_iterator)
        await asyncio.sleep(0.05)
        assert len(progress) <= 32
        with anyio.fail_after(2):
            await response.body_iterator.aclose()
        assert not agents._CHAT_TASKS
    asyncio.run(run())


def test_gateway_target_keeps_agent_model_and_owner(monkeypatch):
    from backend.app.platform_api import providers
    owners = []
    def record(pid, owner_id, **kwargs):
        owners.append(owner_id)
        return {'enabled': True, 'model': 'provider-default', 'base_url': TARGET[0]}
    monkeypatch.setattr(providers, '_provider_record_for_owner', record)
    monkeypatch.setattr(providers, '_decrypt_key', lambda rec: 'key')
    result = agents._resolve_gateway_target({'owner_id': 'owner-a', 'provider_pid': 'deepseek', 'model': 'agent-model'})
    assert result == (TARGET[0], 'key', 'agent-model', 'deepseek')
    assert owners == ['owner-a']


@pytest.mark.parametrize('provider,model,base,key', [
    ('deepseek', 'deepseek-chat', 'https://example.test/v1', 'key'),
    ('anthropic', 'native-model', 'https://example.test', 'key'),
    ('gemini', 'gemini-model', 'https://example.test/v1beta', 'key'),
    ('google_ai_studio', 'gemini-model', 'https://example.test/v1beta', 'key'),
    ('aws_bedrock', 'amazon.nova-pro-v1:0', 'https://bedrock-runtime.us-east-1.amazonaws.com', 'ACCESS|SECRET'),
])
def test_chat_native_ids_and_full_current_message_reach_provider(
    monkeypatch, provider, model, base, key,
):
    agent = seed_agent(provider_pid=provider, model=model)
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', provider != 'deepseek')
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *a, **kw: (base, key, model, provider))
    monkeypatch.setattr(gateway, 'resolve_external_url', lambda url, **kw: (url, '203.0.113.17'))
    payloads = []
    def post(url, ip, payload, headers, timeout):
        payloads.append((url, payload))
        text = 'response-' * 150
        return {'choices': [{'message': {'content': text}}],
                'content': [{'type': 'text', 'text': text}],
                'candidates': [{'content': {'parts': [{'text': text}]}}],
                'output': {'message': {'content': [{'text': text}]}}}
    monkeypatch.setattr(gateway, '_pinned_json_post', post)
    async def forbidden_bridge(*args, **kwargs):
        pytest.fail('native catalog provider entered OpenAI tool loop')
    monkeypatch.setattr(bridge, 'run_agent_chat', forbidden_bridge)
    agents._runs.set('prior', {'id': 'prior', 'kind': 'chat', 'status': 'done',
                              'owner_id': 'owner-a', 'agent_id': agent['id'],
                              'message': 'old-user-' * 200, 'result': 'old-answer-' * 200})
    current = 'DISTINCT-CURRENT-MESSAGE-' + 'new content ' * 200
    response = asyncio.run(agents.chat(agents.ChatIn(
        message=current, agent_id=agent['id'], previous_run_id='prior'), request()))
    sent = json.dumps(payloads[0][1], ensure_ascii=False)
    assert current in sent and 'old-user-' in sent and len(response['reply']) > 600
    if provider in {'gemini', 'google_ai_studio'}:
        assert ':generateContent' in payloads[0][0] and '/chat/completions' not in payloads[0][0]
    # Subsequent connectivity probes retain their original 500/256/600 limits.
    _status, _latency, smoke_text = gateway._provider_dispatch(provider, base, key, model, current, 1024)
    smoke_payload = payloads[1][1]
    assert current not in json.dumps(smoke_payload) and len(smoke_text) == 600
    assert gateway._GENERATION_PROFILE.get().prompt_chars == 500
    if provider in {'deepseek', 'anthropic'}:
        assert len(smoke_payload['messages'][-1]['content']) == 500
        assert smoke_payload['max_tokens'] == 256


def test_chat_profile_resets_on_failure_and_refuses_oversize(monkeypatch):
    def fail(*args):
        assert gateway._GENERATION_PROFILE.get().prompt_chars == gateway.CHAT_PROMPT_MAX_CHARS
        raise RuntimeError('offline failure')
    monkeypatch.setattr(gateway, '_provider_dispatch', fail)
    with pytest.raises(RuntimeError):
        gateway._provider_chat_dispatch('deepseek', 'base', 'key', 'model', 'message', 1024)
    assert gateway._GENERATION_PROFILE.get().prompt_chars == 500
    with pytest.raises(ValueError, match='chat_prompt_too_large'):
        gateway._provider_chat_dispatch('deepseek', 'base', 'key', 'model', 'x' * 48001, 1024)


def test_legacy_nonstream_chat_has_no_approval_tools(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *a, **kw: TARGET)
    async def model(system, message, target, *, context, history):
        names = {tool.__name__ for tool in bridge._registered_tools(context)}
        assert 'read_file' in names and not {'write_file', 'run_command', 'open_path'} & names
        with pytest.raises(bridge.BridgeFailure, match='approval_ui_unavailable'):
            bridge._tool_write_file(context, 'not-created', 'no')
        return 'read-only answer'
    monkeypatch.setattr(bridge, 'run_agent_chat', model)
    result = asyncio.run(agents.chat(agents.ChatIn(message='hello', agent_id=agent['id']), request()))
    assert not result['pending_confirmations']
    assert result['capabilities']['side_effects_reason'] == 'approval_ui_unavailable'


def test_continuation_reuses_authorized_workspace_and_cancel_retains_artifacts(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *a, **kw: TARGET)
    seen = []
    ready = None
    async def model(system, message, target, *, context, history):
        seen.append(context)
        if not history:
            ticket = bridge._tool_write_file(context, 'artifact.txt', 'keep me')
            await bridge.resolve_pending_command(ticket['confirm_token'], True, 'owner-a')
            return 'created artifact'
        assert not context.owns_workdir
        assert bridge._tool_read_file(context, 'artifact.txt')['content'] == 'keep me'
        ready.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(bridge, 'run_agent_chat', model)
    async def run():
        nonlocal ready
        ready = asyncio.Event()
        first = await agents.chat(agents.ChatIn(message='create', agent_id=agent['id'], supports_approvals=True), request())
        assert first['status'] == 'done'
        for owner, aid in [('owner-b', agent['id']), ('owner-a', None)]:
            with pytest.raises(HTTPException) as denied:
                await agents.chat(agents.ChatIn(message='bad', agent_id=aid, previous_run_id=first['run_id']), request(owner))
            assert denied.value.status_code == 404
        second = asyncio.create_task(agents.chat(agents.ChatIn(
            message='read artifact', agent_id=agent['id'], previous_run_id=first['run_id']), request()))
        await ready.wait()
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        assert len(seen) == 2 and seen[0].workdir == seen[1].workdir
        assert (seen[0].workdir / 'artifact.txt').read_text() == 'keep me'
        assert agents._runs.get(seen[1].run_id)['status'] == 'cancelled'
    asyncio.run(run())


def test_sse_cleanup_survives_already_cancelled_anyio_scope(monkeypatch):
    agent = seed_agent()
    monkeypatch.setattr(bridge, '_PAI_AVAILABLE', True)
    monkeypatch.setattr(agents, '_resolve_gateway_target', lambda *a, **kw: TARGET)
    seen = []
    async def model(system, message, target, *, context, history):
        seen.append(context)
        bridge._tool_write_file(context, 'pending', 'no')
        await context.emit({'kind': 'ready'})
        await asyncio.Event().wait()
    monkeypatch.setattr(bridge, 'run_agent_chat', model)
    class Connected:
        scope = {'test_owner': 'owner-a'}
        async def is_disconnected(self):
            return False
    async def run():
        response = await agents.chat_stream(agents.ChatIn(message='start', agent_id=agent['id']), Connected())
        with anyio.CancelScope() as response_scope:
            await anext(response.body_iterator)
            await anext(response.body_iterator)
            response_scope.cancel()
            await response.body_iterator.aclose()
        assert not bridge._PENDING_COMMANDS and not agents._CHAT_TASKS
        assert agents._runs.get(seen[0].run_id)['status'] == 'cancelled'
        assert not seen[0].workdir.exists()
    asyncio.run(run())


def test_step_persistence_is_coalesced_off_loop_and_terminal_is_durable():
    import threading
    import time
    writes = []
    main_thread = threading.get_ident()
    ticks = []
    def persist(ctx):
        writes.append(threading.get_ident())
        time.sleep(0.005)
        agents._chat_context_changed(ctx)
    async def run():
        ctx = context()
        ctx.on_change = persist
        async def heartbeat():
            while True:
                ticks.append(1)
                await asyncio.sleep(0.001)
        heartbeat_task = asyncio.create_task(heartbeat())
        for index in range(100):
            await ctx.emit({'kind': 'progress', 'index': index})
        ctx.generating = False
        ctx.changed()
        await ctx.flush()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        saved = agents._runs.get(ctx.run_id)
        assert saved['status'] == 'done' and len(saved['process_steps']) == 100
        assert saved['steps'] == []
        assert len(writes) < 20 and all(thread != main_thread for thread in writes)
        assert len(ticks) > 2
    asyncio.run(run())


def test_posix_command_literal_quotes_are_not_stripped_twice(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(bridge, 'os', SimpleNamespace(name='posix'))
    assert bridge._split_command("printf '%s' '\"quoted\"'") == ['printf', '%s', '"quoted"']


def test_agent_filter_precedes_run_pagination_and_owner_scope():
    agents._runs.set('wanted', {'id': 'wanted', 'owner_id': 'owner-a', 'agent_id': 'wanted-agent', 'created_at': '1'})
    for index in range(60):
        agents._runs.set(f'other-{index}', {'id': f'other-{index}', 'owner_id': 'owner-a',
                                          'agent_id': 'other-agent', 'created_at': '9'})
    agents._runs.set('private', {'id': 'private', 'owner_id': 'owner-b', 'agent_id': 'wanted-agent', 'created_at': '9'})
    result = agents.list_runs(request(), agent_id='wanted-agent', status=None, limit=1, offset=0)
    assert result['total'] == 1 and result['items'][0]['id'] == 'wanted'


def test_restart_does_not_replay_chat_as_mock_or_keep_approvals(monkeypatch):
    agents._runs.set('interrupted', {'id': 'interrupted', 'kind': 'chat', 'status': 'awaiting_review'})
    monkeypatch.setattr(agents, '_spawn', lambda coro: pytest.fail('must not replay chat tools'))
    agents.resume_runs()
    assert agents._runs.get('interrupted')['status'] == 'failed'
    assert agents._runs.get('interrupted')['error'] == 'agent_process_restarted'
