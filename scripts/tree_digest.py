from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest_tree(root: Path) -> str:
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Directory does not exist: {root}")
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a deterministic SHA-256 digest for a file tree.")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(digest_tree(args.directory))


if __name__ == "__main__":
    main()
