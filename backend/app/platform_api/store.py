"""platform_api 共享：极简 JSON 文件持久化封装。

存储位置：
- 优先取环境变量 ``WANWEI_PLATFORM_DIR``；
- 缺省退到 backend 同级 ``data/platform/``（即项目根下 ``data/platform/``）。

每个 ``JsonStore(name)`` 对应该目录下 ``platform_<name>.json``，
整文件读写 + 模块级共享锁，适合各平台模块的小体量配置/状态持久化。

安全与并发口径（审计 02-#14 / 03-#22 / 06-#9 收口）：
- 落盘后尽力 ``chmod 0600``，与 ``app.db`` 对 ``memory.db`` 的口径对齐。
  Windows 上 ``os.chmod`` 仅只读位有效，0600 实际效果是「非只读」，
  故此处为尽力而为的加固，不构成权限保证；
- 锁为**模块级共享 RLock**：同一进程内所有 JsonStore 实例（含指向同名
  文件的不同实例）串行化读写；外部模块经 ``store._lock`` 自取锁
  （mcp_hub / providers / automation / spaces 的删除兜底）用的也是
  同一把锁。跨进程并发写不在防护范围（桌面单进程场景）；
- 写入走 ``<pid>.<uuid>.tmp`` 唯一临时名 + ``os.replace`` 原子替换，
  多实例/多进程并发写不再共享 ``.tmp`` 文件名互相覆盖；
- 读取遇 JSON 损坏或顶层非 dict 时，先把原文件备份为
  ``<name>.json.corrupt-<UTC时间戳>-<uuid>`` 再按空数据继续，
  绝不静默覆盖丢数据；
- ``mutate(fn)`` 提供锁内「读-改-写一次落盘」原子原语，
  读改写调用点应优先使用它，替代 get/set 组合的锁外读改写。
"""
import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# backend/app/platform_api/store.py → 项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DIR = _PROJECT_ROOT / 'data' / 'platform'

# 模块级共享锁：防护同一进程内跨实例并发（含同名文件的多个 JsonStore 实例）。
# 用 RLock 而非 Lock：mutate(fn) 的 fn 与外部「with store._lock」兜底代码
# 可能回调本 store 的公开方法，可重入避免自死锁。
_STORE_LOCK = threading.RLock()


class JsonStore:
    def __init__(self, name: str):
        self._name = name
        # 实例属性沿用旧名 ``_lock`` 以兼容外部自取锁的调用方
        # （mcp_hub/providers/automation/spaces），但指向模块级共享锁。
        self._lock = _STORE_LOCK

    @property
    def _path(self) -> Path:
        """按当前环境变量惰性解析存储路径。

        测试与多环境切换场景下，``WANWEI_PLATFORM_DIR`` 可能在模块
        import 之后被替换；惰性解析保证 store 始终跟随当前配置，
        避免写入已失效的旧目录。
        """
        base = os.environ.get('WANWEI_PLATFORM_DIR', '').strip()
        target = Path(base) if base else _DEFAULT_DIR
        target.mkdir(parents=True, exist_ok=True)
        return target / f'platform_{self._name}.json'

    def _quarantine_corrupt(self) -> None:
        """把损坏的存储文件备份为 ``.corrupt-<时间戳>`` 副本，绝不静默丢数据。

        优先 move（损坏文件移出主路径，避免后续每次读取都重复备份）；
        move 失败（占用/跨设备）退化为 copy，原文件保留。
        """
        path = self._path
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = path.with_name(
            f'{path.name}.corrupt-{stamp}-{uuid.uuid4().hex[:8]}'
        )
        try:
            path.replace(backup)
        except OSError:
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        print(f'[store] {path.name} 内容损坏，已备份为 {backup.name}，按空数据继续')

    def _read(self) -> dict:
        path = self._path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            self._quarantine_corrupt()
            return {}
        if not isinstance(data, dict):
            # 顶层必须是 dict（本店按 key/value 组织）；其他形态同样按损坏处理
            self._quarantine_corrupt()
            return {}
        return data

    def _write(self, data: dict) -> None:
        path = self._path
        # pid+uuid 唯一临时名：多实例/多进程并发写不再共享 .tmp 文件名互相覆盖
        tmp = path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
        try:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            tmp.replace(path)
        finally:
            # replace 成功后 tmp 已不存在；失败时尽力清理残留临时文件
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        # 权限收紧 0600，与 app.db 的 memory.db 对齐；replace 生成的是新文件，
        # 权限不继承旧文件，故每次落盘都需重设。Windows 上 chmod 仅只读位
        # 有效，0600 为尽力而为（见模块 docstring），失败不阻断写入。
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

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

    def mutate(self, fn: Callable[[dict], Any]) -> Any:
        """原子「读-改-写」原语：模块级共享锁内一次完成读取 → fn(data) → 落盘。

        - fn 收到整店 dict，原地修改；其返回值原样透传给调用方；
        - fn 抛异常时不落盘，保证不会写入半成品；
        - 相比 get/set 组合的锁外读改写，杜绝并发下相互覆盖丢更新。
        """
        with self._lock:
            data = self._read()
            result = fn(data)
            self._write(data)
            return result
