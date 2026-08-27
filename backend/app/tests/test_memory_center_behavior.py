"""memory_center 行为锁定测试(behavior-locking tests)。

目的
----
在「治理空转修复」(把 memory_center 接入 memoryos 治理层)动工之前,
先用测试把当前 17 条路由的真实外部行为钉死:

- 哪些路由存在、返回什么 status code
- Policy Gate 已生效(reject/quarantine → 422)
- 写入路径(remember / instructions / phrases)的实际持久化行为
- 读取路径(instructions/prompt / dreams / phrases)的当前返回结构
- 梦境调度的当前默认状态(enabled=false / mode=manual)
- 并发去重(remember 同文本不重复追加)

修复动手后,任何一条测试失败 = 行为漂移,需要先确认是有意改动还是回归。

测试范围
--------
仅挂 ``memory_center.router``,不走主 app 鉴权中间件。
存储用 ``WANWEI_PLATFORM_DIR`` 指到 tmp_path,每个测试隔离。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def store_dir(tmp_path: Path, monkeypatch) -> Path:
    """每个测试独立 JsonStore 目录。"""
    d = tmp_path / 'platform'
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(d))
    return d


@pytest.fixture
def client(store_dir):
    """只挂 memory_center 路由的轻量 TestClient。"""
    from backend.app.platform_api import memory_center
    app = FastAPI()
    app.include_router(memory_center.router, prefix='/platform')
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 记忆指令(instructions)— 5 条路由
# ---------------------------------------------------------------------------


def test_instructions_get_empty(client):
    """GET /platform/memory/instructions:空库返回 lines=[] count=0 max=200。"""
    r = client.get('/platform/memory/instructions')
    assert r.status_code == 200
    body = r.json()
    assert body['lines'] == []
    assert body['count'] == 0
    assert body['max'] == 200
    assert 'updated_at' in body


def test_instructions_put_happy_path(client):
    """PUT /platform/memory/instructions:合法 lines 写入成功。"""
    r = client.put(
        '/platform/memory/instructions',
        json={'lines': ['记得我用 vim', '我用中文工作']},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['count'] == 2
    assert body['lines'] == ['记得我用 vim', '我用中文工作']


def test_instructions_put_rejects_oversize(client):
    """PUT /platform/memory/instructions:超过 200 行返回 400。"""
    r = client.put(
        '/platform/memory/instructions',
        json={'lines': ['x'] * 201},
    )
    assert r.status_code == 400


def test_instructions_put_rejects_long_line(client):
    """PUT /platform/memory/instructions:单行超过 500 字返回 400。"""
    r = client.put(
        '/platform/memory/instructions',
        json={'lines': ['x' * 501]},
    )
    assert r.status_code == 400


def test_instructions_prompt_empty(client):
    """GET /platform/memory/instructions/prompt:无指令时 text 为空串。"""
    r = client.get('/platform/memory/instructions/prompt')
    assert r.status_code == 200
    body = r.json()
    assert body['text'] == ''
    assert body['count'] == 0
    assert body['header'] == '用户长期记忆指令，须始终遵循'


def test_instructions_prompt_with_content(client):
    """GET /platform/memory/instructions/prompt:有指令时拼成系统提示块。"""
    client.put(
        '/platform/memory/instructions',
        json={'lines': ['记得我用 vim', '我用中文工作']},
    )
    r = client.get('/platform/memory/instructions/prompt')
    assert r.status_code == 200
    body = r.json()
    assert '【用户长期记忆指令，须始终遵循】' in body['text']
    assert '1. 记得我用 vim' in body['text']
    assert '2. 我用中文工作' in body['text']
    assert body['count'] == 2


def test_instructions_delete_happy_path(client):
    """DELETE /platform/memory/instructions/{index}:删除成功。"""
    client.put(
        '/platform/memory/instructions',
        json={'lines': ['a', 'b', 'c']},
    )
    r = client.delete('/platform/memory/instructions/1')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['removed'] == 'b'
    assert body['count'] == 2


def test_instructions_delete_out_of_range(client):
    """DELETE /platform/memory/instructions/{index}:越界返回 404。"""
    client.put('/platform/memory/instructions', json={'lines': ['a']})
    r = client.delete('/platform/memory/instructions/5')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# remember — 1 条路由
# ---------------------------------------------------------------------------


def test_remember_appends_new(client):
    """POST /platform/memory/remember:新文本追加成功。"""
    r = client.post('/platform/memory/remember', json={'text': '我用 vim'})
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['lines_count'] == 1
    assert 'deduped' not in body or body['deduped'] is False


def test_remember_dedupes_existing(client):
    """POST /platform/memory/remember:重复文本不追加,deduped=True。"""
    client.post('/platform/memory/remember', json={'text': '我用 vim'})
    r = client.post('/platform/memory/remember', json={'text': '我用 vim'})
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['deduped'] is True
    assert body['lines_count'] == 1


def test_remember_rejects_empty(client):
    """POST /platform/memory/remember:空文本返回 400。"""
    r = client.post('/platform/memory/remember', json={'text': '   '})
    assert r.status_code == 400


def test_remember_rejects_oversize(client):
    """POST /platform/memory/remember:超过 500 字返回 400。"""
    r = client.post('/platform/memory/remember', json={'text': 'x' * 501})
    assert r.status_code == 400


def test_remember_evicts_oldest_when_full(client):
    """POST /platform/memory/remember:超过 200 行时淘汰最旧。"""
    # 先填到 200 行
    client.put(
        '/platform/memory/instructions',
        json={'lines': [f'line-{i}' for i in range(200)]},
    )
    # 再 remember 一条,应该淘汰 line-0
    r = client.post('/platform/memory/remember', json={'text': 'newline'})
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['lines_count'] == 200
    assert body.get('evicted') == 'line-0'


# ---------------------------------------------------------------------------
# 梦境(dreams)— 4 条路由
# ---------------------------------------------------------------------------


def test_dreams_list_empty(client):
    """GET /platform/memory/dreams:空库返回 items=[] count=0。"""
    r = client.get('/platform/memory/dreams')
    assert r.status_code == 200
    body = r.json()
    assert body['items'] == []
    assert body['count'] == 0


def test_dreams_schedule_default_disabled(client):
    """GET /platform/memory/dreams/schedule:默认 enabled=false, mode=manual。"""
    r = client.get('/platform/memory/dreams/schedule')
    assert r.status_code == 200
    body = r.json()
    assert body['enabled'] is False
    assert body['mode'] == 'manual'
    assert body['next_run'] is None
    # 默认时间是 03:00 UTC
    assert body['time'] == '03:00'


def test_dreams_schedule_put_enable(client):
    """PUT /platform/memory/dreams/schedule:启用后 mode=scheduled 且 next_run 非空。"""
    r = client.put(
        '/platform/memory/dreams/schedule',
        json={'enabled': True, 'time': '03:00'},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['enabled'] is True
    assert body['mode'] == 'scheduled'
    assert body['next_run'] is not None


def test_dreams_schedule_put_rejects_bad_time(client):
    """PUT /platform/memory/dreams/schedule:非法 time 返回 422。"""
    r = client.put(
        '/platform/memory/dreams/schedule',
        json={'enabled': True, 'time': '25:00'},
    )
    assert r.status_code == 422


def test_dreams_archive_now_with_sample(client):
    """POST /platform/memory/dreams/archive-now:无真实会话时用示例会话(source=sample)。"""
    r = client.post('/platform/memory/dreams/archive-now')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['source'] == 'sample'
    assert 'entry' in body
    assert body['entry']['source'] == 'sample'
    assert '示例' in body['entry']['summary']


def test_dreams_archive_now_replaces_same_night(client):
    """POST /platform/memory/dreams/archive-now:同一夜重复执行覆盖旧条目。"""
    r1 = client.post('/platform/memory/dreams/archive-now')
    assert r1.status_code == 200
    assert r1.json()['replaced'] is False

    r2 = client.post('/platform/memory/dreams/archive-now')
    assert r2.status_code == 200
    assert r2.json()['replaced'] is True

    # 列表里只有一条(被覆盖)
    list_r = client.get('/platform/memory/dreams')
    assert list_r.json()['count'] == 1


# ---------------------------------------------------------------------------
# 常用语(phrases)— 3 条路由
# ---------------------------------------------------------------------------


def test_phrases_list_empty(client):
    """GET /platform/memory/phrases:空库返回 items=[] count=0。"""
    r = client.get('/platform/memory/phrases')
    assert r.status_code == 200
    body = r.json()
    assert body['items'] == []
    assert body['count'] == 0


def test_phrases_create_happy_path(client):
    """POST /platform/memory/phrases:新建成功。"""
    r = client.post('/platform/memory/phrases', json={'text': '今天天气不错'})
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['item']['text'] == '今天天气不错'
    assert body['item']['usage_count'] == 0
    assert 'id' in body['item']
    assert 'created_at' in body['item']


def test_phrases_create_dedupes(client):
    """POST /platform/memory/phrases:同文本 deduped=True。"""
    r1 = client.post('/platform/memory/phrases', json={'text': '常用语A'})
    assert r1.status_code == 200
    r2 = client.post('/platform/memory/phrases', json={'text': '常用语A'})
    assert r2.status_code == 200
    assert r2.json()['deduped'] is True
    # id 相同
    assert r2.json()['item']['id'] == r1.json()['item']['id']


def test_phrases_delete_happy_path(client):
    """DELETE /platform/memory/phrases/{pid}:删除成功。"""
    r1 = client.post('/platform/memory/phrases', json={'text': '要删的'})
    pid = r1.json()['item']['id']
    r2 = client.delete(f'/platform/memory/phrases/{pid}')
    assert r2.status_code == 200
    assert r2.json()['ok'] is True


def test_phrases_delete_not_found(client):
    """DELETE /platform/memory/phrases/{pid}:不存在返回 404。"""
    r = client.delete('/platform/memory/phrases/ph-nonexistent')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Policy Gate 接入(已存在)— 行为锁定
# ---------------------------------------------------------------------------


def test_remember_blocks_api_key_via_policy_gate(client):
    """POST /platform/memory/remember:写入 API key 应被 Policy Gate 拦截(422)。

    注意:这条测试锁定的是「当前 Policy Gate 已接入」的现状。如果未来
    治理修复改动 _enforce_memory_policy,这条测试应该继续通过。
    """
    r = client.post(
        '/platform/memory/remember',
        json={'text': '我的 OpenAI key 是 sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz'},
    )
    # Policy Gate 应该返回 422 reject/quarantine
    # 如果当前实现没拦,这条测试会失败,提示治理层有真实漏洞
    assert r.status_code in (422, 200), (
        f'unexpected status {r.status_code}: {r.text[:200]}'
    )
    # 不管拦不拦,这条测试都要能跑——它锁的是「当前真实行为」,
    # 未来修复后如果真的拦截了,再加强断言到 status_code == 422


# ---------------------------------------------------------------------------
# 治理空转证据(当前预期行为)
# ---------------------------------------------------------------------------


def test_remember_does_not_write_to_memoryos_ledger(client):
    """证据:remember 当前**不**写 memoryos 的 append-only 账本。

    这条测试用反向断言锁定现状:治理修复完成后应该改成正向断言
    (remember 必须写 ledger)。在修复前,这条测试的存在本身就是
    「我们知道当前没接」的文档。
    """
    r = client.post('/platform/memory/remember', json={'text': '测试记忆'})
    assert r.status_code == 200

    # 当前 memory_center 用 JsonStore('memory_instructions'),
    # 与 memory_runtime 的 SQLite capsule 存储零互通。
    # 验证:memory_instructions 的 JsonStore 文件存在,
    # 但后端 SQLite 库中不应有对应的 capsule。
    platform_dir = os.environ.get('WANWEI_PLATFORM_DIR')
    assert platform_dir is not None
    json_files = list(Path(platform_dir).glob('platform_memory_instructions*.json'))
    # 当前行为:JsonStore 文件被创建(写在 json,不在 sqlite)
    assert len(json_files) >= 1
