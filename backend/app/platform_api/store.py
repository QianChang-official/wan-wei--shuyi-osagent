"""platform_api 共享：极简 JSON 文件持久化封装。

存储位置：
- 优先取环境变量 ``WANWEI_PLATFORM_DIR``；
- 缺省退到 backend 同级 ``data/platform/``（即项目根下 ``data/platform/``）。

每个 ``JsonStore(name)`` 对应该目录下 ``platform_<name>.json``，
整文件读写 + 线程锁，适合各平台模块的小体量配置/状态持久化。
"""
import json
import os
import threading
from pathlib import Path
from typing import Any

# backend/app/platform_api/store.py → 项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DIR = _PROJECT_ROOT / 'data' / 'platform'


class JsonStore:
    def __init__(self, name: str):
        base = os.environ.get('WANWEI_PLATFORM_DIR', '').strip()
        self._dir = Path(base) if base else _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f'platform_{name}.json'
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        tmp = self._path.with_suffix('.tmp')
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        tmp.replace(self._path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def all(self) -> dict:
        with self._lock:
            return self._read()

    def update(self, mapping: dict) -> None:
        with self._lock:
            data = self._read()
            data.update(mapping)
            self._write(data)
