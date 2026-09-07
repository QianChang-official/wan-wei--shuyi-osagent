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

"""Exercise the code shipped after the desktop release-only cleanup patch."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import tarfile
import threading
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[3]
PATCH_PATH = "desktop/packaging/release-clean.patch"
PATCH = ROOT / PATCH_PATH
SYSTEM_SERVICE = "backend/app/platform_api/_system_svc_runtime.py"
MOBILE_SOURCES = (
    "backend/app/platform_api/mobile_remote.py",
    "frontend/console-vue/src/views/platform/MobileView.vue",
)
SHARED_SECURITY_SOURCES = (
    "backend/app/security/auth.py",
    "backend/app/soul/ownership.py",
)


def _release_paths(patch: bytes) -> set[str]:
    # Git apply uses these attributes to normalize historical CRLF source blobs.
    # Omitting them makes the result depend on the host's core.autocrlf default.
    paths = set(MOBILE_SOURCES + SHARED_SECURITY_SOURCES + (".gitattributes", PATCH_PATH))
    for line in patch.decode("utf-8").splitlines():
        match = re.fullmatch(r"diff --git a/(.+) b/\1", line)
        if match:
            paths.add(match.group(1))
    return paths


def _write_staged_source(stage: Path, relative: str, content: bytes) -> None:
    destination = stage / relative
    destination.resolve().relative_to(stage.resolve())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def _apply_release_cleanup(stage: Path, metadata: Path, autocrlf: str) -> None:
    # Use a separate Git directory: pytest's temporary tree may live inside the
    # checkout, where implicit Git discovery would apply paths at the wrong root.
    subprocess.run(["git", "init", "--bare", "--quiet", str(metadata)], check=True)
    apply = [
        "git", "-c", f"core.autocrlf={autocrlf}",
        "-C", str(stage), f"--git-dir={metadata}",
        f"--work-tree={stage}", "apply",
    ]
    for flags in (["--check"], []):
        result = subprocess.run([*apply, *flags, str(stage / PATCH_PATH)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


@pytest.fixture(params=["false", "true"], ids=["autocrlf-off", "autocrlf-on"])
def git_autocrlf(request):
    return request.param


@pytest.fixture
def staged_release(tmp_path, git_autocrlf):
    stage = tmp_path / "release-stage"
    stage.mkdir()
    originals = {}
    for relative in _release_paths(PATCH.read_bytes()):
        source = ROOT / relative
        source.resolve().relative_to(ROOT)
        originals[relative] = source.read_bytes()
        _write_staged_source(stage, relative, originals[relative])

    _apply_release_cleanup(stage, tmp_path / "git-metadata", git_autocrlf)
    return SimpleNamespace(path=stage, originals=originals)


def test_committed_archive_applies_cleanup_and_preserves_shared_auth(tmp_path, git_autocrlf):
    # git archive exports committed object bytes without checkout EOL conversion.
    # The working-tree fixture separately exercises any uncommitted source edits.
    committed_patch = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{PATCH_PATH}"],
        check=True, capture_output=True,
    ).stdout
    paths = _release_paths(committed_patch)
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD", "--", *sorted(paths)],
        check=True, capture_output=True,
    ).stdout
    stage = tmp_path / "archive-stage"
    stage.mkdir()
    originals = {}
    with tarfile.open(fileobj=BytesIO(archive), mode="r:") as source_archive:
        for relative in paths:
            source = source_archive.extractfile(relative)
            assert source is not None, f"Missing release source: {relative}"
            with source:
                originals[relative] = source.read()
            _write_staged_source(stage, relative, originals[relative])

    _apply_release_cleanup(stage, tmp_path / "archive-git-metadata", git_autocrlf)
    for relative in MOBILE_SOURCES:
        assert not (stage / relative).exists()
    for relative in SHARED_SECURITY_SOURCES:
        assert (stage / relative).read_bytes() == originals[relative]


def test_release_cleanup_is_confined_to_staging_and_preserves_shared_auth(staged_release):
    for relative, original in staged_release.originals.items():
        assert (ROOT / relative).read_bytes() == original
    for relative in MOBILE_SOURCES:
        assert not (staged_release.path / relative).exists()
    for relative in SHARED_SECURITY_SOURCES:
        assert (staged_release.path / relative).read_bytes() == staged_release.originals[relative]


@pytest.fixture
def staged_lan_service(staged_release):
    source = (staged_release.path / SYSTEM_SERVICE).read_text(encoding="utf-8")
    module = ast.parse(source)
    retained_routes = [
        decorator.args[0].value
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
        and isinstance(decorator.args[0].value, str)
        and decorator.args[0].value.startswith("/system/lan/")
    ]
    assert retained_routes == ["/system/lan/disable"]

    # Execute the retained route and its actual router-level dependency without
    # importing the source checkout's platform router or unrelated device I/O.
    selected = [
        node for node in module.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in {"_require_device_owner", "lan_disable"}
        ) or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets)
        )
    ]
    assert len(selected) == 3
    # In-memory persisted-state fixture: the test never opens a listening socket.
    saved = {"lan": {"enabled": True, "token": "old-pairing-token", "bind": "0.0.0.0"}}  # nosec B104
    store = Mock()
    store._lock = threading.RLock()
    store.get.side_effect = lambda key: deepcopy(saved.get(key))
    store.set.side_effect = lambda key, value: saved.__setitem__(key, deepcopy(value))
    revoke = Mock(return_value=2)
    namespace = {
        "APIRouter": APIRouter, "Depends": Depends,
        "HTTPException": HTTPException, "Request": Request,
        "actor_id_for_request": lambda request: request.headers.get("x-test-actor", "anonymous"),
        "configured_actor_id": lambda: "device-owner",
        "_sys_store": store, "revoke_lan_sessions": revoke,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), SYSTEM_SERVICE, "exec"), namespace)
    app = FastAPI()
    app.include_router(namespace["router"], prefix="/platform")
    return SimpleNamespace(app=app, saved=saved, revoke=revoke)


def test_staged_disable_rejects_another_owner_before_revocation(staged_lan_service):
    service = staged_lan_service
    with TestClient(service.app) as client:
        response = client.post("/platform/system/lan/disable", headers={"x-test-actor": "other-owner"})
    assert response.status_code == 404
    service.revoke.assert_not_called()
    assert service.saved["lan"]["enabled"] is True


def test_staged_disable_revokes_sessions_and_clears_persisted_pairing(staged_lan_service):
    service = staged_lan_service
    with TestClient(service.app) as client:
        response = client.post("/platform/system/lan/disable", headers={"x-test-actor": "device-owner"})
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False, "bind": "127.0.0.1", "lan_url": None,
        "token_set": False, "revoked_sessions": 2,
    }
    service.revoke.assert_called_once_with()
    assert service.saved["lan"]["enabled"] is False
    assert service.saved["lan"]["token"] is None
    assert service.saved["lan"]["token_consumed"] is False


def test_staged_disable_does_not_report_success_when_revocation_fails(staged_lan_service):
    service = staged_lan_service
    service.revoke.side_effect = RuntimeError("credential store unavailable")
    with TestClient(service.app, raise_server_exceptions=False) as client:
        response = client.post("/platform/system/lan/disable", headers={"x-test-actor": "device-owner"})
    assert response.status_code == 500
    assert service.saved["lan"]["enabled"] is True


def test_staged_desktop_keeps_cold_start_cleanup_without_mobile_entrypoints(staged_release):
    main = staged_release.path / "desktop/src/main.js"
    source = main.read_text(encoding="utf-8")
    assert "function reconcileLanState()" in source
    assert "/platform/system/lan/disable" in source
    assert re.search(r"await startBackend\(py\);\s+await reconcileLanState\(\);", source)
    assert "desktop:lan-enable" not in source
    assert "/console/#/mobile" not in source
    router = (staged_release.path / "frontend/console-vue/src/router/platform.ts").read_text(encoding="utf-8")
    assert "MobileView" not in router
    assert not re.search(r"path:\s*['\"]/?mobile['\"]", router)
    node = shutil.which("node")
    if node:
        subprocess.run([node, "--check", str(main)], check=True, capture_output=True)
