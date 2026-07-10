from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ..db import close_all, database_path
from ..version import VERSION


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_database(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Database file does not exist: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        }
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite quick_check failed for {path}")
    required = {"memory_events", "memory_capsules_v2", "audit_logs"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"Database is missing required tables: {', '.join(missing)}")
    return {"quick_check": "ok", "tables": len(tables)}


def verify_backup(path: Path, *, require_manifest: bool = False) -> dict:
    path = path.resolve()
    validation = validate_database(path)
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    if not manifest_path.is_file():
        if require_manifest:
            raise RuntimeError("Backup manifest is required for restore.")
        return {**validation, "manifest": "absent", "sha256": _sha256(path)}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "wanwei-sqlite-backup-v1":
        raise RuntimeError("Unsupported backup manifest format.")
    if manifest.get("backup_file") != path.name:
        raise RuntimeError("Backup manifest filename does not match the database file.")
    digest = _sha256(path)
    if manifest.get("sha256") != digest:
        raise RuntimeError("Backup checksum does not match its manifest.")
    if manifest.get("size_bytes") != path.stat().st_size:
        raise RuntimeError("Backup size does not match its manifest.")
    return {**validation, "manifest": "verified", "sha256": digest}


def _destination(output: Path | None) -> Path:
    if output is None:
        output = database_path().parent / "backups"
    if output.suffix.lower() == ".db":
        return output
    return output / f"wanwei-{_timestamp()}.db"


def _preserve_raw_database(path: Path, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"wanwei-pre-restore-{_timestamp()}-raw.db"
    shutil.copy2(path, destination)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, Path(str(destination) + suffix))
    return str(destination)


def create_backup(
    output: Path | None = None,
    *,
    source: Path | None = None,
    overwrite: bool = False,
) -> dict:
    source_path = (source or database_path()).resolve()
    destination = _destination(output).resolve()
    validate_database(source_path)
    if source_path == destination:
        raise ValueError("Backup destination must differ from the live database.")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Backup already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(str(source_path))) as source_conn:
            with closing(sqlite3.connect(str(temp_path))) as destination_conn:
                source_conn.backup(destination_conn)
        validation = validate_database(temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    try:
        destination.chmod(0o600)
    except PermissionError:
        pass
    manifest = {
        "format": "wanwei-sqlite-backup-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "application_version": VERSION,
        "backup_file": destination.name,
        "size_bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
        **validation,
    }
    manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
    manifest_temp = manifest_path.with_name(f".{manifest_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        manifest_temp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(manifest_temp, manifest_path)
    finally:
        if manifest_temp.exists():
            manifest_temp.unlink()
    return {"backup": str(destination), "manifest": str(manifest_path), **manifest}


def restore_backup(source: Path, *, target: Path | None = None, force: bool = False) -> dict:
    if not force:
        raise RuntimeError("Restore requires force=True after the application has been stopped.")
    source_path = source.resolve()
    target_path = (target or database_path()).resolve()
    if source_path == target_path:
        raise ValueError("Restore source must differ from the live database.")
    validation = verify_backup(source_path, require_manifest=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    close_all()
    safety_backup = None
    safety_backup_kind = None
    if target_path.exists() and target_path.stat().st_size:
        safety_dir = target_path.parent / "backups" / "pre-restore"
        try:
            safety_backup = create_backup(safety_dir, source=target_path)["backup"]
            safety_backup_kind = "verified"
        except (OSError, RuntimeError, sqlite3.Error):
            safety_backup = _preserve_raw_database(target_path, safety_dir)
            safety_backup_kind = "raw"
    temp_path = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.restore")
    try:
        with closing(sqlite3.connect(str(source_path))) as source_conn:
            with closing(sqlite3.connect(str(temp_path))) as target_conn:
                source_conn.backup(target_conn)
        validate_database(temp_path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(target_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(temp_path, target_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    try:
        target_path.chmod(0o600)
    except PermissionError:
        pass
    return {
        "status": "restored",
        "target": str(target_path),
        "source": str(source_path),
        "safety_backup": safety_backup,
        "safety_backup_kind": safety_backup_kind,
        **validation,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or restore verified SQLite backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--output", type=Path)
    create.add_argument("--source", type=Path)
    create.add_argument("--overwrite", action="store_true")
    restore = subparsers.add_parser("restore")
    restore.add_argument("--input", type=Path, required=True)
    restore.add_argument("--target", type=Path)
    restore.add_argument("--force", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--input", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "create":
        result = create_backup(args.output, source=args.source, overwrite=args.overwrite)
    elif args.command == "restore":
        result = restore_backup(args.input, target=args.target, force=args.force)
    else:
        result = verify_backup(args.input)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
