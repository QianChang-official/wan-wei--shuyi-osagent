import os
import sqlite3
from pathlib import Path


def _db_path() -> Path:
    # Allow tests / arena runner to point at an isolated DB via env.
    env = os.environ.get("WANWEI_MEMORY_DB")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".local/share/wanwei-shuyi/memory.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn
