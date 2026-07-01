import sqlite3
from pathlib import Path
DB_PATH = Path.home() / '.local/share/wanwei-shuyi/memory.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
def get_conn():
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; return conn
