"""Integration test for tier management API routes.

鉴权说明（04-#08）：APIKeyMiddleware 对写方法强制校验 X-API-Key，
TestClient 的对端 host 不是回环地址，回环免密不生效——必须显式带 key。
key 取自 get_api_key()（与被测进程同一解析链），避免测试内自造常量。

数据库隔离（Kilo review #140）：client fixture 依赖 isolated_db，
将 WANWEI_MEMORY_DB 指向临时文件，避免胶囊写入默认库造成跨次运行污染、
结果不可复现、以及干扰本地开发数据。

路由契约（app_runtime.py 实测）：
- GET  /memory/tier/stats          层级分布
- POST /memory/tier/promote        body=TierTransitionIn
- POST /memory/tier/demote         body=TierTransitionIn
- POST /memory/tier/auto-flow      body=TierAutoFlowIn（手动触发一轮自动流转）
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.app_runtime import app
from backend.app.memory_runtime.capsule_store import write_capsule
from backend.app.security.auth import get_api_key


@pytest.fixture()
def client(isolated_db):
    """带隔离数据库的测试客户端。

    依赖 isolated_db 提供独立的临时 WANWEI_MEMORY_DB，
    防止胶囊写入共享默认库导致的状态污染。
    """
    headers = {"X-API-Key": get_api_key()}
    with TestClient(app) as c:
        c.headers.update(headers)
        yield c


def test_memory_tier_stats(client):
    """GET /memory/tier/stats 返回层级分布。"""
    response = client.get("/memory/tier/stats")
    assert response.status_code == 200
    data = response.json()
    assert "tiers" in data
    assert isinstance(data["tiers"], dict)


def test_tier_promote_api(client):
    """POST /memory/tier/promote 将 working 胶囊升层。"""
    capsule = write_capsule(
        memory_class="episodic",
        content={"kind": "memory_note", "summary": "test tier API promote"},
        source_type="user_input",
    )
    response = client.post(
        "/memory/tier/promote",
        json={
            "capsule_id": capsule["capsule_id"],
            "to_tier": "short_term",
            "reason": "test_api",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["changed"] is True


def test_tier_demote_api(client):
    """POST /memory/tier/demote 将胶囊降回 working。"""
    capsule = write_capsule(
        memory_class="episodic",
        content={"kind": "memory_note", "summary": "test tier API demote"},
        source_type="user_input",
    )
    # 先升到 short_term 才有降层空间。
    # Kilo review #140：先验证 promote 响应，避免 promote 失败时 demote 变成
    # no-op 并把错误误导到 demote 的断言上。
    promote = client.post(
        "/memory/tier/promote",
        json={"capsule_id": capsule["capsule_id"], "to_tier": "short_term"},
    )
    assert promote.status_code == 200
    assert promote.json()["changed"] is True

    response = client.post(
        "/memory/tier/demote",
        json={
            "capsule_id": capsule["capsule_id"],
            "to_tier": "working",
            "reason": "test_api",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["changed"] is True


def test_auto_flow_api(client):
    """POST /memory/tier/auto-flow 手动触发一轮自动流转。"""
    response = client.post(
        "/memory/tier/auto-flow",
        json={"limit": 100},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
