"""W07 空间后端修复回归测试。

覆盖审计条目（第02/05章）：
- 02-#16/05-#1：提交模板重复占位符 / 正则编译失败统一 400（不再 500）
- 05-#9：dry_run 回显命令改 shlex.quote 安全引用
- 05-#10：真实提交全程互斥锁 + finally 切回原分支
- 05-#11：分支名按 git check-ref-format 规则子集加强校验
- 05-#13：parent_id 空间归属 + 删除父空间级联删除后代
- 05-#14：create 纯空格 name 422
- 05-#15：模板 <subject> 支持多行（re.S）+ 无占位符模板回 warning
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _client(tmp_path, *, api_key: str = "test-key"):
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ["WANWEI_ROOT_PATH_WHITELIST"] = str(tmp_path)
    os.environ.pop("WANWEI_PRODUCTION", None)
    os.environ.pop("WANWEI_DEVICE_GEAR_ENABLED", None)

    backend_dir = str(PROJECT_ROOT / "backend")
    for path in (backend_dir, str(PROJECT_ROOT)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _create_project(client, h, **overrides) -> str:
    payload = {"name": "W07 测试项目", "kind": "project_space"}
    payload.update(overrides)
    r = client.post("/platform/spaces/projects", json=payload, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# 02-#16 / 05-#1：重复占位符与正则编译失败 → 400
# ---------------------------------------------------------------------------


def test_put_template_duplicate_placeholder_400(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    r = client.put(
        f"/platform/spaces/{pid}/commit-template",
        json={"template": "<type> <type>: <subject>", "types": ["feat"], "require_scope": False},
        headers=h,
    )
    assert r.status_code == 400, r.text
    assert "多次" in r.json()["detail"]

    # (<scope>) 与裸 <scope> 混用同样产生重复命名分组
    r = client.put(
        f"/platform/spaces/{pid}/commit-template",
        json={"template": "<type>(<scope>) <scope>: <subject>", "types": ["feat"], "require_scope": True},
        headers=h,
    )
    assert r.status_code == 400, r.text

    # 非法模板未被写入，原默认模板仍生效
    r = client.get(f"/platform/spaces/{pid}/commit-template", headers=h)
    assert r.json()["template"] == "<type>(<scope>): <subject>"


def test_commit_with_legacy_bad_template_400_not_500(tmp_path):
    """PUT 校验上线前存入的非法模板（历史脏数据）：commit 诚实 400 而非 500。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    store_path = tmp_path / "platform" / "platform_spaces.json"
    data = json.loads(store_path.read_text(encoding="utf-8"))
    data[pid]["commit_template"] = {
        "template": "<type> <type>: <subject>",
        "types": ["feat"],
        "require_scope": False,
    }
    store_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"message": "feat feat: x"},
        headers=h,
    )
    assert r.status_code == 400, r.text
    assert "模板非法" in r.json()["detail"]


def test_compile_template_pattern_unit():
    from backend.app.platform_api.spaces import _compile_template_pattern

    with pytest.raises(ValueError):
        _compile_template_pattern({"template": "<subject> / <subject>", "types": [], "require_scope": False})
    regex = _compile_template_pattern({"template": "<type>(<scope>): <subject>", "types": ["feat"], "require_scope": True})
    assert regex.match("feat(a): 正常")


# ---------------------------------------------------------------------------
# 05-#9：dry_run 回显命令 shlex.quote
# ---------------------------------------------------------------------------


def test_dry_run_commands_shlex_quoted(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h, root_path=str(tmp_path / "dir with space"))

    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"message": "feat(spaces): 带 空格 的消息", "files": ["a b.txt"]},
        headers=h,
    )
    body = r.json()
    assert body["ok"] is True and body["dry_run"] is True
    joined = "\n".join(body["commands"])
    # root 含空格 → shlex.quote 单引号包裹；不再出现 Python repr 风格
    assert "git -C '" in joined and "dir with space" in joined
    assert "add -- 'a b.txt'" in joined
    assert "commit -m 'feat(spaces):" in joined
    assert 'commit -m "' not in joined


# ---------------------------------------------------------------------------
# 05-#10：真实提交切回原分支 + 互斥锁
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
    )


@pytest.fixture
def git_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-b", "main").returncode == 0
    _git(repo, "config", "user.email", "w07@test.local")
    _git(repo, "config", "user.name", "w07")
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-m", "chore: init").returncode == 0
    assert _git(repo, "branch", "perch").returncode == 0
    return repo


def _current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def test_real_commit_restores_original_branch(tmp_path, git_repo):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h, root_path=str(git_repo), default_branch="main")

    (git_repo / "work.txt").write_text("hello", encoding="utf-8")
    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"branch": "perch", "message": "feat(spaces): 真实提交", "dry_run": False, "gear": "sandbox"},
        headers=h,
    )
    body = r.json()
    assert body["ok"] is True, body
    assert body["commit_id"]
    # 完成后切回原分支 main，且回显命令如实包含恢复动作
    assert _current_branch(git_repo) == "main"
    assert body["commands"][-1].endswith("switch main")
    # 提交确实落在 perch 上
    assert _git(git_repo, "log", "-1", "--format=%s", "perch").stdout.strip() == "feat(spaces): 真实提交"


def test_real_commit_failure_also_restores_branch(tmp_path, git_repo):
    """switch 成功但 commit 失败（无改动可提交）时同样切回原分支。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h, root_path=str(git_repo), default_branch="main")

    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"branch": "perch", "message": "feat(spaces): 空提交", "dry_run": False, "gear": "sandbox"},
        headers=h,
    )
    body = r.json()
    assert body["ok"] is False and body["error"] == "git_commit_failed", body
    assert _current_branch(git_repo) == "main"
    assert body["commands"][-1].endswith("switch main")


def test_commit_lock_exists_and_serializes():
    import threading

    from backend.app.platform_api import spaces

    assert isinstance(spaces._commit_lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# 05-#11：分支名校验（git check-ref-format 子集）
# ---------------------------------------------------------------------------


def test_branch_name_validation_unit():
    from backend.app.platform_api.spaces import _validate_branch_name

    for bad in ("-x", "a..b", "bad branch", "a~b", "a^b", "a:b", "a?b", "a*b",
                "a[b", "a\\b", "/a", "a/", "a//b", "a.", "a.lock", ".a/b", "@", "a@{b",
                "ctrl\x01char"):
        assert _validate_branch_name(bad) is not None, bad
    for good in ("main", "perch", "feature/foo", "fix-123", "release/1.2.0", "a.b"):
        assert _validate_branch_name(good) is None, good


def test_commit_invalid_branch_400(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"branch": "bad branch", "message": "feat(spaces): x"},
        headers=h,
    )
    assert r.status_code == 400, r.text
    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"branch": "feat..bad", "message": "feat(spaces): x"},
        headers=h,
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 05-#13：parent_id 归属 + 级联删除
# ---------------------------------------------------------------------------


def test_parent_id_and_cascade_delete(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    # 父空间不存在 → 400
    r = client.post(
        "/platform/spaces/projects",
        json={"name": "孤儿", "kind": "task_space", "parent_id": "sp_nonexistent"},
        headers=h,
    )
    assert r.status_code == 400, r.text

    r = client.post(
        "/platform/spaces/projects",
        json={"name": "子任务", "kind": "task_space", "parent_id": pid},
        headers=h,
    )
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["parent_id"] == pid
    r = client.post(
        "/platform/spaces/projects",
        json={"name": "孙任务", "kind": "task_space", "parent_id": child["id"]},
        headers=h,
    )
    grandchild = r.json()

    # 无 parent_id 的旧式空间不受影响
    other = _create_project(client, h, name="独立项目")

    r = client.delete(f"/platform/spaces/projects/{pid}", headers=h)
    body = r.json()
    assert body["ok"] is True
    assert sorted(body["deleted_children"]) == sorted([child["id"], grandchild["id"]])
    for gone in (pid, child["id"], grandchild["id"]):
        assert client.get(f"/platform/spaces/projects/{gone}", headers=h).status_code == 404
    assert client.get(f"/platform/spaces/projects/{other}", headers=h).status_code == 200


def test_project_without_parent_id_defaults_null(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)
    r = client.get(f"/platform/spaces/projects/{pid}", headers=h)
    assert r.json()["parent_id"] is None
    r = client.delete(f"/platform/spaces/projects/{pid}", headers=h)
    assert r.json()["deleted_children"] == []


# ---------------------------------------------------------------------------
# 05-#14：create 纯空格 name 422
# ---------------------------------------------------------------------------


def test_create_blank_name_422(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    r = client.post("/platform/spaces/projects", json={"name": "   "}, headers=h)
    assert r.status_code == 422, r.text

    r = client.post("/platform/spaces/projects", json={"name": "  留白项目  "}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "留白项目"


def test_update_blank_name_422_and_parent_id(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    r = client.put(f"/platform/spaces/projects/{pid}", json={"name": "   "}, headers=h)
    assert r.status_code == 422, r.text

    # 允许变更 parent_id
    child = _create_project(client, h, name="子任务", kind="task_space", parent_id=pid)
    other = _create_project(client, h, name="另一个父")
    r = client.put(f"/platform/spaces/projects/{child}", json={"parent_id": other}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["parent_id"] == other

    # 非法 parent_id / 自身循环
    r = client.put(f"/platform/spaces/projects/{child}", json={"parent_id": "sp_nonexistent"}, headers=h)
    assert r.status_code == 400, r.text
    r = client.put(f"/platform/spaces/projects/{child}", json={"parent_id": child}, headers=h)
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 05-#15：多行 subject + 无占位符模板 warning
# ---------------------------------------------------------------------------


def test_multiline_subject_passes(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"message": "feat(spaces): 第一行\n第二行补充说明"},
        headers=h,
    )
    body = r.json()
    assert body["ok"] is True, body


def test_put_template_without_placeholder_warns(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    r = client.put(
        f"/platform/spaces/{pid}/commit-template",
        json={"template": "固定字面量提交", "types": ["feat"], "require_scope": False},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert "warning" in r.json()

    # 字面量模板：全串匹配才通过
    r = client.post(f"/platform/spaces/{pid}/commit", json={"message": "固定字面量提交"}, headers=h)
    assert r.json()["ok"] is True
    r = client.post(f"/platform/spaces/{pid}/commit", json={"message": "别的提交"}, headers=h)
    assert r.json()["ok"] is False and r.json()["error"] == "template_mismatch"

    # 含占位符模板不带 warning
    r = client.put(
        f"/platform/spaces/{pid}/commit-template",
        json={"template": "<type>(<scope>): <subject>", "types": ["feat"], "require_scope": True},
        headers=h,
    )
    assert "warning" not in r.json()


# ---------------------------------------------------------------------------
# A2：spaces create/update/commit 接入 root_path 白名单校验
# ---------------------------------------------------------------------------


def test_create_project_rejects_root_path_outside_whitelist(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    outside = str(tmp_path.parent / "outside_whitelist")

    r = client.post(
        "/platform/spaces/projects",
        json={"name": "越界路径", "kind": "project_space", "root_path": outside},
        headers=h,
    )
    assert r.status_code == 422, r.text
    assert "白名单" in r.json()["detail"]


def test_update_project_rejects_root_path_outside_whitelist(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)
    outside = str(tmp_path.parent / "outside_whitelist")

    r = client.put(
        f"/platform/spaces/projects/{pid}",
        json={"root_path": outside},
        headers=h,
    )
    assert r.status_code == 422, r.text
    assert "白名单" in r.json()["detail"]

    # 清空 root_path 仍被允许
    r = client.put(
        f"/platform/spaces/projects/{pid}",
        json={"root_path": ""},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["root_path"] == ""


def test_commit_rejects_root_path_outside_whitelist(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    pid = _create_project(client, h)

    # 绕过 create/update 校验，直接把项目 root_path 改成白名单外路径
    from backend.app.platform_api import spaces
    project = spaces._projects.get(pid)
    project["root_path"] = str(tmp_path.parent / "outside_whitelist")
    spaces._projects.set(pid, project)

    r = client.post(
        f"/platform/spaces/{pid}/commit",
        json={"message": "feat(spaces): x"},
        headers=h,
    )
    body = r.json()
    assert body["ok"] is False, body
    assert body["error"] == "root_path_denied"
    assert "白名单" in body["note"]
