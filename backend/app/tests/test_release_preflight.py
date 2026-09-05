from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "release_preflight.py"
SPEC = importlib.util.spec_from_file_location("release_preflight", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
release_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_preflight)


REQUIRED_ANCHORS = [
    "doc-deployment-04615394",
    "doc-operations-fb2c4fc6",
    "doc-release-checklist-6022994b",
]


def _write_release_project(
    root: Path,
    anchors: list[str],
    *,
    release_status: str = "released",
    include_license: bool = True,
) -> None:
    (root / "README.md").write_text("# README\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    if include_license:
        (root / "LICENSE").write_text("test license\n", encoding="utf-8")
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "version.py").write_text(
        f'VERSION = "v1.0.0"\nVERSION_HISTORY = [{{"status": "{release_status}"}}]\n',
        encoding="utf-8",
    )
    for project in (root / "desktop", root / "frontend" / "console-vue"):
        project.mkdir(parents=True)
        (project / "package.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
        (project / "package-lock.json").write_text(
            json.dumps({"version": "1.0.0", "packages": {"": {"version": "1.0.0"}}}),
            encoding="utf-8",
        )
    (root / "文档中心_DOCUMENTATION_HUB.md").write_text(
        "\n".join(f'<a id="{anchor}"></a>' for anchor in anchors),
        encoding="utf-8",
    )


def test_validate_accepts_documentation_hub_instead_of_removed_docs_directory(tmp_path, monkeypatch):
    _write_release_project(tmp_path, REQUIRED_ANCHORS)
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)

    assert release_preflight.validate("v1.0.0") == {
        "status": "ready",
        "tag": "v1.0.0",
        "version": "v1.0.0",
    }


@pytest.mark.parametrize("missing_anchor", REQUIRED_ANCHORS)
def test_validate_rejects_each_missing_required_documentation_hub_anchor(tmp_path, monkeypatch, missing_anchor):
    _write_release_project(tmp_path, [anchor for anchor in REQUIRED_ANCHORS if anchor != missing_anchor])
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match=f"文档中心_DOCUMENTATION_HUB.md.*{missing_anchor}"):
        release_preflight.validate("v1.0.0")


def test_validate_rejects_an_empty_documentation_hub(tmp_path, monkeypatch):
    _write_release_project(tmp_path, [])
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="文档中心_DOCUMENTATION_HUB.md.*doc-deployment-04615394"):
        release_preflight.validate("v1.0.0")


def test_validate_retains_released_status_gate(tmp_path, monkeypatch):
    _write_release_project(tmp_path, REQUIRED_ANCHORS, release_status="in_progress")
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="VERSION_HISTORY\\[0\\]\\.status"):
        release_preflight.validate("v1.0.0")


@pytest.mark.parametrize("project", ["desktop", "frontend/console-vue"])
@pytest.mark.parametrize("target", ["package", "lock", "lock_root"])
def test_validate_rejects_npm_version_drift(tmp_path, monkeypatch, project, target):
    _write_release_project(tmp_path, REQUIRED_ANCHORS)
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)
    filename = "package.json" if target == "package" else "package-lock.json"
    path = tmp_path / project / filename
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if target == "lock_root":
        metadata["packages"][""]["version"] = "0.11.0-wanshu"
    else:
        metadata["version"] = "0.11.0-wanshu"
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(RuntimeError):
        release_preflight.validate("v1.0.0")


def test_validate_retains_license_gate(tmp_path, monkeypatch):
    _write_release_project(tmp_path, REQUIRED_ANCHORS, include_license=False)
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="LICENSE is missing"):
        release_preflight.validate("v1.0.0")
