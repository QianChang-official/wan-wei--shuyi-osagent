"""发布前预检：校验 tag 与应用版本一致、VERSION_HISTORY 已发布、LICENSE/CHANGELOG/使用说明书齐备，未通过则阻止发版。"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
#: v1.0 起交付文档为使用说明书(文档中心已随发布精简移除)。
REQUIRED_DOCUMENTATION_FILES = ["使用说明书.md"]


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


def validate(tag: str) -> dict:
    version = application_version()
    errors = []
    if tag != version:
        errors.append(f"Release tag {tag!r} must exactly match application version {version!r}.")
    if latest_release_status() != "released":
        errors.append("VERSION_HISTORY[0].status must be 'released' before publishing.")
    if not (ROOT / "LICENSE").is_file():
        errors.append("LICENSE is missing; the project owner must choose a license before public release.")
    required = [ROOT / "README.md", ROOT / "CHANGELOG.md"] + [ROOT / f for f in REQUIRED_DOCUMENTATION_FILES]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        errors.append(f"Required release files are missing: {', '.join(missing)}")
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
