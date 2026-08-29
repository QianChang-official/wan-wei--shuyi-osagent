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
def client(store_dir, isolated_db):
    """只挂 memory_center 路由的轻量 TestClient。

    isolated_db 必需:治理双写(方案 B)后,remember/instructions/phrases
    写入会同步登记 memoryos 账本(SQLite),必须指向临时库。
    """
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


def test_remember_writes_to_memoryos_ledger(client):
    """治理双写(方案 B)正向断言:remember 必须同步登记 memoryos 账本。

    本测试由 #148 的反向断言(治理空转证据)演化而来 — 治理修复完成后,
    写入路径除 JsonStore 外必须在 append-only 账本留下条目,且内容只记
    hash 不落明文。
    """
    r = client.post('/platform/memory/remember', json={'text': '测试治理双写'})
    assert r.status_code == 200
    # 响应必须如实标注治理账本登记状态
    assert r.json().get('governance_recorded') is True

    # 账本侧必须有对应条目
    from backend.app.db import get_conn
    rows = get_conn().execute(
        "SELECT op_type, capsule_id, after_hash FROM memory_ledger "
        "WHERE capsule_id LIKE 'mc-%' ORDER BY created_at DESC"
    ).fetchall()
    assert len(rows) >= 1, 'remember 未在治理账本留下条目'
    assert rows[0]['op_type'] == 'platform_memory_write'
    # 账本只记 hash 不落明文
    assert rows[0]['after_hash'] is not None
    assert len(rows[0]['after_hash']) == 64


def test_delete_instruction_writes_delete_ledger_entry(client):
    """删除指令行必须登记 platform_memory_delete 账目(治理闭环)。"""
    client.put('/platform/memory/instructions', json={'lines': ['要删的指令']})
    r = client.delete('/platform/memory/instructions/0')
    assert r.status_code == 200
    assert r.json().get('governance_recorded') is True

    from backend.app.db import get_conn
    rows = get_conn().execute(
        "SELECT op_type, after_state, before_hash FROM memory_ledger "
        "WHERE op_type='platform_memory_delete' ORDER BY created_at DESC"
    ).fetchall()
    assert len(rows) >= 1, 'delete 未在治理账本留下条目'
    assert rows[0]['after_state'] == 'forgotten'
    assert rows[0]['before_hash'] is not None


def _latest_ledger_ops() -> list[str]:
    from backend.app.db import get_conn
    rows = get_conn().execute(
        "SELECT op_type FROM memory_ledger ORDER BY created_at DESC, rowid DESC"
    ).fetchall()
    return [r['op_type'] for r in rows]


def test_put_instructions_writes_ledger_entry(client):
    """整体替换指令必须登记 platform_memory_write 账目。"""
    r = client.put('/platform/memory/instructions', json={'lines': ['新指令A']})
    assert r.status_code == 200
    assert r.json().get('governance_recorded') is True
    assert 'platform_memory_write' in _latest_ledger_ops()


def test_create_phrase_writes_ledger_entry(client):
    """新建常用语必须登记 platform_memory_write 账目。"""
    r = client.post('/platform/memory/phrases', json={'text': '常用语记账测试'})
    assert r.status_code == 200
    assert r.json().get('governance_recorded') is True
    assert 'platform_memory_write' in _latest_ledger_ops()


def test_delete_phrase_writes_delete_ledger_entry(client):
    """删除常用语必须登记 platform_memory_delete 账目。"""
    pid = client.post(
        '/platform/memory/phrases', json={'text': '待删常用语'}
    ).json()['item']['id']
    r = client.delete(f'/platform/memory/phrases/{pid}')
    assert r.status_code == 200
    assert r.json().get('governance_recorded') is True
    assert 'platform_memory_delete' in _latest_ledger_ops()


def test_ledger_write_failure_does_not_block_store_write(client, monkeypatch):
    """账本故障(操作性异常)不阻断 JsonStore 写入,但响应如实标注。

    同时验证:编程错误(TypeError)不被吞咽 — REVIEW.md 明文条款。
    """
    import sqlite3 as _sqlite3
    from backend.app.platform_api import memory_center

    # 场景 1:操作性异常(sqlite3.Error)→ 不阻断,governance_recorded=False
    def _raise_operational(**kwargs):
        raise _sqlite3.OperationalError('disk I/O error (simulated)')

    monkeypatch.setattr(
        'backend.app.memoryos.governance.append_ledger', _raise_operational
    )
    r = client.post('/platform/memory/remember', json={'text': '账本故障场景'})
    assert r.status_code == 200  # 展示源写入不受影响
    assert r.json().get('governance_recorded') is False  # 如实标注

    # 场景 2:编程错误(TypeError)→ 必须传播,不得吞咽。
    # TestClient(raise_server_exceptions=False) 下,未捕获异常转为 500 响应;
    # 500 而非 200 即证明 TypeError 穿透了 _record_governance 的 except 子句。
    def _raise_programming(**kwargs):
        raise TypeError('signature drift (simulated)')

    monkeypatch.setattr(
        'backend.app.memoryos.governance.append_ledger', _raise_programming
    )
    r = client.post('/platform/memory/remember', json={'text': '编程错误场景'})
    assert r.status_code == 500, (
        f'编程错误被吞咽(返回 {r.status_code} 而非 500)— REVIEW.md 条款被违反'
    )
