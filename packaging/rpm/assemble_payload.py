#!/usr/bin/env python3
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

"""Deterministic allowlisted source payload; no build, install or network actions."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

PREFIX = "wanwei-shuyi-1.0.0"
DIST = "frontend/console-vue/dist/"
# "platform" is a real backend code package, not a globally forbidden component.
# Runtime data/platform is excluded by the data rule and allowed source prefixes.
BLOCKED = {"tests", "__pycache__", "node_modules", "venv", "data",
           "secrets", "models", "model", "reports", "evidence", "raw", "uploads"}
STATIC = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp",
          ".ico", ".woff", ".woff2", ".ttf"}
# init_db uses inline SQL. Only these public research fixtures are runtime resources;
# generated reports/metrics and private evaluation data are deliberately absent.
RESOURCES = {
    "backend/app/memory_arena/cases/" + name + ".json" for name in (
        "docs_reference_governance", "git_commit_review", "poisoning_preference_confirm",
        "prompt_injection_false_positive_echo", "self_evolution_loop", "tier_promotion_lifecycle")
} | {
    "backend/app/memoryos/cases/public/" + name + ".json" for name in (
        "conflict_update", "forgetting", "knowledge_recall", "poisoning", "preference_extraction")
}
FIXED = {
    **{f"packaging/rpm/bin/{name}": f"bin/{name}"
       for name in ("install-deps.sh", "run-server", "wanwei-shuyi")},
    **{f"packaging/rpm/{name}": f"packaging/{name}" for name in (
        "desktop/wanwei-shuyi.desktop", "icons/wanwei-shuyi.svg",
        "systemd/wanwei-shuyi.service", "environment")},
    "LICENSE": "doc/LICENSE", "README.md": "doc/README.md",
    "packaging/rpm/INSTALL.md": "doc/INSTALL.md",
}
REQUIRED = set(FIXED.values()) | {"backend/app/main.py", "backend/requirements.txt",
                                "backend/app/platform/service.py",
                                DIST + "index.html"} | RESOURCES


def allowed(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or str(path) != name or "\\" in name
            or any(c in name for c in "\n\r\0:")
            or any(p.startswith(".") or p.lower() in BLOCKED for p in path.parts)):
        return False
    return (name in FIXED.values() or name in RESOURCES
            or (name.startswith("backend/app/") and path.suffix == ".py"
                and not path.name.startswith(("test_", "secret", "credential")))
            or (path.parent == PurePosixPath("backend")
                and path.match("requirements*.txt"))
            or (name.startswith(DIST) and not name.startswith(DIST + "platform/")
                and path.suffix in STATIC))


def safe_path(root, relative):
    current = root
    for part in PurePosixPath(relative).parts:
        if part in ("..", ".") or "\\" in part:
            raise ValueError(f"Unsafe path: {relative}")
        current /= part
        if current.is_symlink():
            raise ValueError(f"Symlink not allowed: {relative}")
    if not current.resolve().is_relative_to(root):
        raise ValueError(f"Path escapes source root: {relative}")
    return current


def collect(root):
    if root.is_symlink():
        raise ValueError("Source root must not be a symlink")
    root = root.resolve(strict=True)
    files = {}

    def add(source, target):
        path = safe_path(root, source)
        if not path.is_file() or not allowed(target):
            raise ValueError(f"Missing or disallowed source: {source}")
        data = path.read_bytes()
        # Extensionless launchers may be checked out as CRLF on Windows.
        files[target] = data.replace(b"\r\n", b"\n") if target in FIXED.values() else data

    for source, target in FIXED.items():
        add(source, target)
    for resource in sorted(RESOURCES):
        add(resource, resource)
    for base in ("backend/app", DIST.rstrip("/")):
        directory = safe_path(root, base)
        if not directory.is_dir():
            raise ValueError(f"Missing source directory: {base}")
        for parent, dirs, names in os.walk(directory, followlinks=False):
            for name in dirs + names:
                safe_path(root, (Path(parent) / name).relative_to(root).as_posix())
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in BLOCKED)
            for name in sorted(names):
                relative = (Path(parent) / name).relative_to(root).as_posix()
                if allowed(relative):
                    add(relative, relative)
    for path in safe_path(root, "backend").glob("requirements*.txt"):
        add(path.relative_to(root).as_posix(), path.relative_to(root).as_posix())
    check_required(files)
    return files


def check_required(files):
    missing = REQUIRED - files.keys()
    if missing:
        raise ValueError(f"Missing required payload files: {sorted(missing)}")
    if not files[DIST + "index.html"].strip() or not any(
            name.startswith(DIST) and name.endswith(".js") and data.strip()
            for name, data in files.items()):
        raise ValueError("Build frontend dist first: nonempty index.html and JavaScript required")


def manifest(files):
    return (json.dumps({name: {"sha256": hashlib.sha256(data).hexdigest(),
                              "size": len(data), "mode": 0o755 if name.startswith("bin/") else 0o644}
                       for name, data in sorted(files.items())},
                      sort_keys=True, indent=2) + "\n").encode("utf-8")


def assemble(root, output):
    files = collect(root)
    files["MANIFEST.json"] = manifest(files)
    # Exclusive creation: never overwrite a user's old payload, even on failure.
    with output.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name, data in sorted(files.items()):
                    info = tarfile.TarInfo(f"{PREFIX}/{name}")
                    info.size = len(data)
                    info.mode = 0o755 if name.startswith("bin/") else 0o644
                    info.mtime = info.uid = info.gid = 0
                    archive.addfile(info, io.BytesIO(data))


def validate(archive_path):
    files = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            name = member.name.removeprefix(PREFIX + "/")
            if (not member.name.startswith(PREFIX + "/") or not member.isfile()
                    or name in files or (name != "MANIFEST.json" and not allowed(name))
                    or member.mode != (0o755 if name.startswith("bin/") else 0o644)):
                raise ValueError(f"Unsafe payload member: {member.name}")
            files[name] = archive.extractfile(member).read()
    recorded = files.pop("MANIFEST.json", None)
    check_required(files)
    if recorded != manifest(files):
        raise ValueError("Missing or mismatched payload manifest")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--validate", type=Path)
    args = parser.parse_args()
    try:
        if args.validate:
            validate(args.validate)
        else:
            assemble(args.repo, args.output)
    except (OSError, ValueError, tarfile.TarError) as exc:
        parser.exit(1, f"payload: {exc}\n")


if __name__ == "__main__":
    main()
