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

"""RPM contracts and tiny source payloads only; never install or start a service."""
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile

import pytest

RPM = Path(__file__).resolve().parents[3] / "packaging" / "rpm"
PACK = runpy.run_path(str(RPM / "assemble_payload.py"))
SERVER = runpy.run_path(str(RPM / "bin" / "run-server"))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    sources = {source: "fixture\n" for source in PACK["FIXED"]}
    sources.update({name: '{"case_id":"public-fixture"}\n' for name in PACK["RESOURCES"]})
    sources.update({"backend/app/main.py": "from .platform.service import marker\napp = None\n",
                    "backend/app/platform/__init__.py": "",
                    "backend/app/platform/service.py": "def marker(): return 'fixture'\n",
                    "backend/requirements.txt": "fastapi==0.139.0\n",
                    "frontend/console-vue/dist/index.html": '<script src="./assets/app.js"></script>',
                    "frontend/console-vue/dist/assets/app.js": "console.log('fixture');\n"})
    for name, data in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
    return root


def test_actual_payload_cli_is_deterministic(repo, tmp_path):
    outputs = [tmp_path / "one.tar.gz", tmp_path / "two.tar.gz"]
    for output in outputs:
        result = subprocess.run([sys.executable, str(RPM / "assemble_payload.py"),
                                 "--repo", str(repo), "--output", str(output)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        os.utime(repo / "backend/app/main.py", (12345, 12345))
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    PACK["validate"](outputs[0])
    with tarfile.open(outputs[0]) as archive:
        members = archive.getmembers()
        assert [m.name for m in members] == sorted(m.name for m in members)
        assert all(m.isfile() and m.uid == m.gid == m.mtime == 0 for m in members)
        prefix = PACK["PREFIX"] + "/"
        manifest = json.load(archive.extractfile(prefix + "MANIFEST.json"))
        assert PACK["REQUIRED"] <= manifest.keys()
        assert {"backend/app/platform/__init__.py", "backend/app/platform/service.py"} <= manifest.keys()
        for name, record in manifest.items():
            data = archive.extractfile(prefix + name).read()
            assert record["sha256"] == hashlib.sha256(data).hexdigest()
            assert record["size"] == len(data)
    before = outputs[0].read_bytes()
    with pytest.raises(FileExistsError):
        PACK["assemble"](repo, outputs[0])
    assert outputs[0].read_bytes() == before


def test_actual_source_payload_import_and_start(tmp_path):
    source = RPM.parents[1]
    if not (source / "frontend/console-vue/dist/index.html").is_file():
        pytest.skip("Build the real frontend dist before the source-payload startup smoke")
    payload = tmp_path / "source.tar.gz"
    PACK["assemble"](source, payload)
    PACK["validate"](payload)
    with tarfile.open(payload) as archive:
        manifest = json.load(archive.extractfile(PACK["PREFIX"] + "/MANIFEST.json"))
        # All real runtime Python modules must survive, not merely the tiny fixture.
        expected = {path.relative_to(source).as_posix()
                    for path in (source / "backend/app").rglob("*.py")
                    if "tests" not in path.relative_to(source / "backend/app").parts
                    and not path.name.startswith("test_")}
        assert expected <= manifest.keys(), sorted(expected - manifest.keys())
        for member in archive:
            path = tmp_path / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    app_root = tmp_path / PACK["PREFIX"]
    state = tmp_path / "isolated-state"
    state.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("WANWEI_") and key != "PYTHONPATH"}
    env.update({key: str(state) for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                          "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")})
    env.update(PYTHONDONTWRITEBYTECODE="1", WANWEI_DATA_DIR=str(state),
               WANWEI_MEMORY_DB=str(state / "memory.db"), WANWEI_PLATFORM_DIR=str(state / "platform"),
               WANWEI_API_KEY_FILE=str(state / "api-key"), WANWEI_DEVICE_GEAR_ENABLED="0",
               WANWEI_KYLIN_NATIVE_MODE="off")
    smoke = r'''
import os, runpy, sys
from pathlib import Path
root = Path.cwd().parent.resolve()
runpy.run_path(str(root / "bin/run-server"))["prepare_state"]()
import app.main as entry
import app.platform.service
from fastapi.testclient import TestClient
from app.reproduction.memoryarena_workbench import workbench
assert Path(entry.__file__).resolve() == root / "backend/app/main.py"
with TestClient(entry.app, base_url="http://127.0.0.1") as client:
    assert client.get("/health").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 200, ready.text
    console = client.get("/console/")
    assert console.status_code == 200 and "<html" in console.text.lower()
    assert len(workbench()["cases"]) == 6
assert (Path(os.environ["WANWEI_DATA_DIR"]) / "memory.db").is_file()
for name, module in tuple(sys.modules.items()):
    if name.startswith("app.") and getattr(module, "__file__", None):
        assert Path(module.__file__).resolve().is_relative_to(root / "backend/app"), name
print("assembled-source lifespan, readiness, console and resources: OK")
'''
    result = subprocess.run([sys.executable, "-c", smoke], cwd=app_root / "backend",
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "assembled-source lifespan, readiness, console and resources: OK" in result.stdout


def test_payload_normalizes_launcher_and_rejects_path_escape(repo):
    (repo / "packaging/rpm/bin/run-server").write_bytes(b"#!/usr/bin/python3\r\n")
    assert PACK["collect"](repo)["bin/run-server"] == b"#!/usr/bin/python3\n"
    with pytest.raises(ValueError, match="Unsafe path"):
        PACK["safe_path"](repo.resolve(), "../outside.py")


def test_detected_source_symlink_fails_closed(repo, monkeypatch):
    original = Path.is_symlink
    linked = repo / "backend/app/main.py"
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == linked or original(path))
    with pytest.raises(ValueError, match="Symlink"):
        PACK["collect"](repo)


@pytest.mark.parametrize("name", [
    "backend/app/tests/private.py", "backend/app/data/stolen.py",
    "backend/app/secrets/keys.py", "backend/app/secret_local.py",
    "backend/app/native.so", "backend/app/memory_arena/cases/private.json",
    "backend/app/.env", "backend/app/uploads/private.py",
    "frontend/console-vue/dist/.env", "frontend/console-vue/dist/node_modules/lib.js",
    "frontend/console-vue/dist/data/private.js", "frontend/console-vue/dist/native.whl",
    "frontend/console-vue/dist/platform/private.js", "backend/app/data/platform/private.py",
    "venv/lib/package.py", "data/memory.db", "platform/platform_system.json",
    "secrets/api-key", "models/weights.bin", "reports/raw-evidence.json",
])
def test_security_exclusions(repo, name):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("DO NOT PACKAGE", encoding="utf-8")
    assert name not in PACK["collect"](repo)


@pytest.mark.parametrize("missing", ["index.html", "assets/app.js", "all"])
def test_missing_dist_fails_before_output(repo, tmp_path, missing):
    dist = repo / "frontend/console-vue/dist"
    if missing == "all":
        shutil.rmtree(dist)
    else:
        (dist / missing).unlink()
    output = tmp_path / "missing.tar.gz"
    with pytest.raises(ValueError, match="Missing|dist"):
        PACK["assemble"](repo, output)
    assert not output.exists()


@pytest.mark.parametrize("directory", [False, True])
def test_symlink_source_rejected(repo, tmp_path, directory):
    target = tmp_path / ("outside" if directory else "outside.py")
    target.mkdir() if directory else target.write_text("secret", encoding="utf-8")
    link = repo / "backend/app" / ("escape" if directory else "escape.py")
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"OS does not permit symlinks: {exc}")
    with pytest.raises(ValueError, match="Symlink|escapes"):
        PACK["assemble"](repo, tmp_path / "unsafe.tar.gz")


@pytest.mark.parametrize("name,kind", [("../escape.py", "file"),
    ("backend/app/linked.py", "link"), ("frontend/console-vue/dist/.env", "file")])
def test_supplied_archive_rejects_unsafe_members(tmp_path, name, kind):
    payload = tmp_path / "unsafe.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        info = tarfile.TarInfo(PACK["PREFIX"] + "/" + name)
        info.mode = 0o644
        if kind == "link":
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        archive.addfile(info, io.BytesIO())
    with pytest.raises(ValueError, match="Unsafe payload"):
        PACK["validate"](payload)


@pytest.mark.parametrize("port", ["", "0", "00080", "65536", "-1", "8010;id", " 8010", "1\n"])
def test_server_rejects_invalid_port(port):
    with pytest.raises(ValueError):
        SERVER["validate_port"](port)


def test_server_state_and_key_survive_restart(tmp_path, monkeypatch):
    for name, path in {"WANWEI_DATA_DIR": tmp_path / "state",
                       "WANWEI_PLATFORM_DIR": tmp_path / "state/platform",
                       "WANWEI_API_KEY_FILE": tmp_path / "state/api-key"}.items():
        monkeypatch.setenv(name, str(path))
    monkeypatch.setattr(os, "umask", lambda _: 0)
    SERVER["prepare_state"]()
    key = tmp_path / "state/api-key"
    first = key.read_bytes()
    assert len(first.strip()) == 48
    SERVER["prepare_state"]()
    assert key.read_bytes() == first
    assert SERVER["validate_port"]("8011") == "8011"
    key.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to replace"):
        SERVER["prepare_state"]()


def test_server_exec_honors_port_and_forces_device_off(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 1234, raising=False)
    monkeypatch.setattr(os, "chdir", lambda _: None)
    monkeypatch.setattr(os, "execv", lambda exe, argv: calls.append((exe, argv)))
    monkeypatch.setitem(SERVER["main"].__globals__, "prepare_state", lambda: None)
    monkeypatch.setenv("WANWEI_PORT", "8011")
    monkeypatch.setenv("WANWEI_DEVICE_GEAR_ENABLED", "1")
    monkeypatch.setenv("WANWEI_HOST", "0.0.0.0")
    SERVER["main"]()
    assert calls[0][1][-4:] == ["--host", "127.0.0.1", "--port", "8011"]
    assert os.environ["WANWEI_DEVICE_GEAR_ENABLED"] == "0"
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(ValueError, match="not root"):
        SERVER["main"]()


@pytest.fixture
def bash():
    git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    executable = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("bash is not installed")
    return executable


def test_shell_syntax_and_install_contracts(bash):
    for name in ("build-rpm.sh", "bin/install-deps.sh", "bin/wanwei-shuyi"):
        result = subprocess.run([bash, "-n", (RPM / name).as_posix()], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    spec = (RPM / "wanwei-shuyi.spec").read_text(encoding="utf-8")
    post = spec.split("\n%post\n")[1].split("\n%preun\n")[0]
    assert "pip install" not in post and "bash /opt" not in post
    assert "systemctl enable" not in post and "systemctl start" not in post
    assert "%config(noreplace) %attr(0600,root,root)" in spec
    assert "userdel" not in spec and "rm -rf" not in spec
    installer = (RPM / "bin/install-deps.sh").read_text(encoding="utf-8")
    assert "runuser -u wanwei-shuyi -- env -i" in installer
    assert "--no-index" in installer and "--only-binary=:all:" in installer
    assert "--without-pip" not in installer and "rm -rf" not in installer
    build = (RPM / "build-rpm.sh").read_text(encoding="utf-8")
    assert "mktemp -d" in build and "--validate" in build
    assert not any(word in build for word in ("RPM_CONFIGDIR", "LD_LIBRARY_PATH", "rm -rf"))


def test_service_is_unprivileged_and_state_paths_agree():
    service = (RPM / "systemd/wanwei-shuyi.service").read_text(encoding="utf-8")
    for line in ("User=wanwei-shuyi", "Group=wanwei-shuyi", "StateDirectory=wanwei-shuyi",
                 "StateDirectoryMode=0700", "UMask=0077", "NoNewPrivileges=true",
                 "ProtectSystem=strict", "ProtectHome=true", "PrivateDevices=true",
                 "Environment=WANWEI_DEVICE_GEAR_ENABLED=0",
                 "Environment=HOME=/var/lib/wanwei-shuyi",
                 "Environment=WANWEI_DATA_DIR=/var/lib/wanwei-shuyi",
                 "Environment=WANWEI_PLATFORM_DIR=/var/lib/wanwei-shuyi/platform",
                 "Environment=WANWEI_API_KEY_FILE=/var/lib/wanwei-shuyi/api-key"):
        assert line in service.splitlines()
    assert "/bin/run-server" in service and "--port 8010" not in service


@pytest.mark.parametrize("health,port,expected", [(0, "8011", 0), (22, "8011", 1), (0, "bad", 1)])
def test_launcher_only_opens_healthy_port(bash, tmp_path, health, port, expected):
    for name, script in {"curl": 'printf "%s\\n" "$*" >> "$LOG"; exit "$HEALTH"',
                         "xdg-open": 'printf "OPEN %s\\n" "$*" >> "$LOG"'}.items():
        path = tmp_path / name
        path.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
        path.chmod(0o755)
    log = tmp_path / "calls"
    result = subprocess.run([bash, "-c", 'cd "$STUBS" && export PATH="$PWD:$PATH"; sh "$LAUNCHER"'],
        env={**os.environ, "STUBS": tmp_path.as_posix(), "LOG": log.as_posix(),
             "HEALTH": str(health), "WANWEI_PORT": port,
             "LAUNCHER": (RPM / "bin/wanwei-shuyi").as_posix()}, capture_output=True, text=True)
    assert result.returncode == expected, result.stderr
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    assert ("OPEN" in calls) == (expected == 0)
    if expected == 0:
        assert "http://127.0.0.1:8011/health/ready" in calls
        assert "OPEN http://127.0.0.1:8011/console/" in calls
