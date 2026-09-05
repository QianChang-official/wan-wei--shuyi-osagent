"""发布前预检：校验 tag、应用版本、npm 包版本与发布必需文件。"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOCUMENTATION_ANCHORS = [
    "doc-deployment-04615394",
    "doc-operations-fb2c4fc6",
    "doc-release-checklist-6022994b",
]
NPM_PACKAGE_FILES = [
    Path("frontend/console-vue/package.json"),
    Path("frontend/console-vue/package-lock.json"),
    Path("desktop/package.json"),
    Path("desktop/package-lock.json"),
]


def application_version() -> str:
    module = ast.parse((ROOT / "backend" / "app" / "version.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "VERSION":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise RuntimeError("Unable to resolve VERSION from backend/app/version.py.")


def latest_release_status() -> str:
    module = ast.parse((ROOT / "backend" / "app" / "version.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "VERSION_HISTORY":
                    history = ast.literal_eval(node.value)
                    if isinstance(history, list) and history and isinstance(history[0], dict):
                        return str(history[0].get("status", ""))
    raise RuntimeError("Unable to resolve VERSION_HISTORY from backend/app/version.py.")


def npm_version(application_version_value: str) -> str:
    if not application_version_value.startswith("v"):
        raise RuntimeError("Application VERSION must start with 'v'.")
    return application_version_value[1:]


def package_version(path: Path) -> str:
    relative_path = path.relative_to(ROOT)
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read npm package metadata from {relative_path}: {exc}") from exc
    if not isinstance(package, dict):
        raise RuntimeError(f"npm package metadata {relative_path} must be an object.")
    version = package.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"npm package metadata {relative_path} has no string version.")
    if path.name == "package-lock.json":
        packages = package.get("packages")
        root_package = packages.get("") if isinstance(packages, dict) else None
        root_version = root_package.get("version") if isinstance(root_package, dict) else None
        if root_version != version:
            raise RuntimeError(
                f"npm lockfile root version in {relative_path} is {root_version!r}; "
                f"expected {version!r} to match its top-level version."
            )
    return version


def validate(tag: str) -> dict:
    version = application_version()
    expected_npm_version = npm_version(version)
    documentation_hub = ROOT / "文档中心_DOCUMENTATION_HUB.md"
    errors = []
    if tag != version:
        errors.append(f"Release tag {tag!r} must exactly match application version {version!r}.")
    if latest_release_status() != "released":
        errors.append("VERSION_HISTORY[0].status must be 'released' before publishing.")
    for relative_path in NPM_PACKAGE_FILES:
        path = ROOT / relative_path
        try:
            actual_version = package_version(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        if actual_version != expected_npm_version:
            errors.append(
                f"npm version in {relative_path.as_posix()} is {actual_version!r}; "
                f"expected {expected_npm_version!r} from application version {version!r}."
            )
    if not (ROOT / "LICENSE").is_file():
        errors.append("LICENSE is missing; the project owner must choose a license before public release.")
    required = [ROOT / "README.md", ROOT / "CHANGELOG.md", documentation_hub]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        errors.append(f"Required release files are missing: {', '.join(missing)}")
    else:
        hub_text = documentation_hub.read_text(encoding="utf-8")
        missing_anchors = [anchor for anchor in REQUIRED_DOCUMENTATION_ANCHORS if f'<a id="{anchor}"></a>' not in hub_text]
        if missing_anchors:
            errors.append(
                f"Required documentation hub anchors are missing from {documentation_hub.name}: "
                f"{', '.join(missing_anchors)}"
            )
    if errors:
        raise RuntimeError("\n".join(errors))
    return {"status": "ready", "tag": tag, "version": version}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate release metadata and legal prerequisites.")
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.tag), ensure_ascii=False))


if __name__ == "__main__":
    main()
