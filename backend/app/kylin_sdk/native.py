"""Process boundary for the official Kylin embedding and vector SDKs.

The vector SDK is a C++ API while the application runtime is Python.  A small
native bridge keeps the vendor ABI out of Python and communicates only through
one JSON request on stdin and one JSON response on stdout.

延迟模式（全链路 ≤200ms 优化的核心）:
- **常驻模式（默认）**: bridge 进程 spawn 一次后按行循环处理请求——embedding
  模型只在首个请求加载一次,后续查询只付 embed + search 的真实成本。进程
  死亡/超时/协议错误自动回落 one-shot 模式,行为不劣于旧版。
- **one-shot 模式**: 每次请求 spawn 一个 bridge（旧版行为,``WANWEI_KYLIN_SDK_PERSISTENT=0``
  强制使用）。实测 V11 上模型重复加载占单次查询 ~200ms 中的绝大部分。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db import database_path
from ..security.auth import is_production_mode


DEFAULT_BRIDGE_NAME = "wanwei-kylin-sdk-bridge"
DEFAULT_COLLECTION = "wanwei_memory_capsules"
DEFAULT_APP_ID = "wanwei-shuyi-osagent"
RESPONSE_PREFIX = "WANWEI_KYLIN_RESPONSE:"
MAX_BRIDGE_TIMEOUT_SECONDS = 60.0
PERSISTENT_ENV = "WANWEI_KYLIN_SDK_PERSISTENT"
_TRUE_VALUES = {"1", "true", "yes", "on"}


class KylinNativeSdkError(RuntimeError):
    """A native SDK operation was unavailable or returned an invalid response."""


def _native_mode() -> str:
    mode = os.environ.get("WANWEI_KYLIN_NATIVE_MODE", "auto").strip().lower()
    return mode if mode in {"auto", "off"} else "auto"


def _timeout_seconds() -> float:
    try:
        return max(
            1.0,
            min(
                float(os.environ.get("WANWEI_KYLIN_SDK_TIMEOUT_SECONDS", "10")),
                MAX_BRIDGE_TIMEOUT_SECONDS,
            ),
        )
    except ValueError:
        return 10.0


def _resolve_bridge_path() -> Path | None:
    explicit = os.environ.get("WANWEI_KYLIN_SDK_BRIDGE")
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_absolute() and candidate.is_file() else None

    # The bridge receives governed memory content.  Production deployments must
    # pin the trusted executable explicitly instead of inheriting PATH order.
    if is_production_mode():
        return None

    installed = Path("/usr/local/bin") / DEFAULT_BRIDGE_NAME
    return installed if installed.is_file() else None


@dataclass(frozen=True)
class NativeSdkConfig:
    bridge_path: Path | None
    collection: str
    app_id: str
    embedding_model: str | None
    vector_db_path: Path
    timeout_seconds: float
    mode: str


def load_config() -> NativeSdkConfig:
    configured_db = os.environ.get("WANWEI_KYLIN_VECTOR_DB")
    vector_db_path = Path(configured_db).expanduser() if configured_db else database_path().with_name("kylin-vector.db")
    model = os.environ.get("WANWEI_KYLIN_EMBEDDING_MODEL", "").strip() or None
    return NativeSdkConfig(
        bridge_path=_resolve_bridge_path(),
        collection=os.environ.get("WANWEI_KYLIN_VECTOR_COLLECTION", DEFAULT_COLLECTION).strip() or DEFAULT_COLLECTION,
        app_id=os.environ.get("WANWEI_KYLIN_VECTOR_APP_ID", DEFAULT_APP_ID).strip() or DEFAULT_APP_ID,
        embedding_model=model,
        vector_db_path=vector_db_path,
        timeout_seconds=_timeout_seconds(),
        mode=_native_mode(),
    )


class KylinNativeSdk:
    """Native-first adapter with an explicit, observable fallback state."""

    def __init__(self, config: NativeSdkConfig | None = None):
        self.config = config or load_config()

    @property
    def collection(self) -> str:
        return self.config.collection

    def availability(self) -> dict[str, Any]:
        if self.config.mode == "off":
            return {"available": False, "reason": "disabled_by_configuration"}
        if not self.config.bridge_path:
            if is_production_mode() and not os.environ.get("WANWEI_KYLIN_SDK_BRIDGE"):
                return {"available": False, "reason": "bridge_path_required_in_production"}
            return {"available": False, "reason": "bridge_not_installed"}
        return {"available": True, "reason": None, "bridge_path": str(self.config.bridge_path)}

    def status(self) -> dict[str, Any]:
        availability = self.availability()
        if not availability["available"]:
            return {"backend": "fts_fallback", **availability}
        try:
            response = self._request("probe", {})
        except KylinNativeSdkError:
            return {"backend": "fts_fallback", "available": False, "reason": "bridge_probe_failed"}
        return {
            "backend": "kylin_native",
            "available": True,
            "reason": None,
            "bridge_path": str(self.config.bridge_path),
            "capabilities": response.get("capabilities", {}),
            "model": response.get("model") if isinstance(response.get("model"), str) else None,
            "dimension": response.get("dimension") if isinstance(response.get("dimension"), int) else None,
        }

    def upsert(self, *, vector_id: int, capsule_id: str, text: str) -> dict[str, Any]:
        return self._request(
            "upsert",
            {"vector_id": vector_id, "capsule_id": capsule_id, "text": text},
        )

    def search(self, *, text: str, top_k: int) -> dict[str, Any]:
        return self._request("search", {"text": text, "top_k": top_k})

    def delete(self, *, vector_id: int) -> dict[str, Any]:
        return self._request("delete", {"vector_id": vector_id})

    def _request(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        availability = self.availability()
        if not availability["available"]:
            raise KylinNativeSdkError(str(availability["reason"]))

        request = {
            "action": action,
            "collection": self.config.collection,
            "app_id": self.config.app_id,
            "db_file": str(self.config.vector_db_path),
            "embedding_model": self.config.embedding_model,
            **payload,
        }
        # 常驻模式优先:模型只加载一次。进程死亡/超时/协议错误返回 None,
        # 调用方回落 one-shot——任何路径的行为都不劣于旧版。
        if _persistent_enabled():
            response = _persistent_bridge(self.config).request(request, self.config.timeout_seconds)
            if response is not None:
                if not response.get("ok"):
                    raise KylinNativeSdkError("bridge_operation_failed")
                return response

        try:
            completed = subprocess.run(
                [str(self.config.bridge_path)],
                input=json.dumps(request, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise KylinNativeSdkError("bridge_execution_failed") from exc

        if completed.returncode != 0:
            raise KylinNativeSdkError("bridge_operation_failed")

        response = _protocol_response(completed.stdout)
        if not isinstance(response, dict) or not response.get("ok"):
            raise KylinNativeSdkError("bridge_invalid_response")
        return response


def _persistent_enabled() -> bool:
    """常驻 bridge 开关(默认开;``WANWEI_KYLIN_SDK_PERSISTENT=0`` 关闭)。

    关闭时回到旧的 one-shot 行为——保留这条退路供现场排障对比。
    """
    return os.environ.get(PERSISTENT_ENV, "1").strip().lower() in _TRUE_VALUES


class _PersistentBridge:
    """常驻 bridge 进程:spawn 一次,按行循环收发请求。

    - 协议与 one-shot 逐字节兼容:一行 JSON 请求 → 一行
      ``WANWEI_KYLIN_RESPONSE:`` 前缀响应;旧版 bridge(单请求退出)在这里
      表现为首个请求后 EOF,自动判死重建。
    - 线程安全:FastAPI 同步端点跑在线程池,锁串行化跨线程请求。
    - 自愈:进程死亡/超时杀进程后,下一个请求自动 respawn(模型重加载
      一次),期间调用方拿到 None 回落 one-shot,不阻塞服务。
    """

    def __init__(self, bridge_path: Path, warmup_request: dict[str, Any]):
        self._bridge_path = str(bridge_path)
        self._warmup_request = warmup_request
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _spawn(self) -> subprocess.Popen:
        proc = subprocess.Popen(
            [self._bridge_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        # 预热:首个请求(探针)把模型加载从第一次真实查询挪到 spawn 期。
        self._exchange(proc, self._warmup_request, timeout=60.0)
        return proc

    def _kill(self, proc: subprocess.Popen | None) -> None:
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _exchange(proc: subprocess.Popen, request: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
        """一次请求-响应交换;任何异常返回 None(由调用方决定回落)。"""
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            # 超时看门狗:管道 readline 无原生超时,到点杀进程让其返回 EOF。
            watchdog = threading.Timer(timeout, proc.kill)
            watchdog.start()
            try:
                line = proc.stdout.readline()
            finally:
                watchdog.cancel()
        except (OSError, ValueError):
            return None
        if not line:
            return None
        response = _protocol_response(line)
        if not isinstance(response, dict):
            return None
        return response

    def close(self) -> None:
        """关闭常驻进程(服务停机钩子调用;调用方负责不在请求进行中停机)。"""
        with self._lock:
            self._kill(self._proc)
            self._proc = None

    def request(self, request: dict[str, Any], timeout: float) -> dict[str, Any] | None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is not None:
                self._kill(self._proc)  # 回收僵尸句柄
                self._proc = None
            if self._proc is None:
                try:
                    self._proc = self._spawn()
                except (OSError, subprocess.SubprocessError):
                    self._proc = None
                    return None
            response = self._exchange(self._proc, request, timeout=timeout)
            if response is None:
                # 进程不可用(死亡/超时/协议坏):杀掉,本轮回落 one-shot,
                # 下一轮自动 respawn。
                self._kill(self._proc)
                self._proc = None
            return response


#: 常驻 bridge 进程注册表:按配置指纹缓存(bridge/集合/app/库文件/模型)。
_PERSISTENT_BRIDGES: dict[tuple, _PersistentBridge] = {}
_PERSISTENT_BRIDGES_LOCK = threading.Lock()


def _persistent_bridge(config: NativeSdkConfig) -> _PersistentBridge:
    assert config.bridge_path is not None
    key = (
        str(config.bridge_path),
        config.collection,
        config.app_id,
        str(config.vector_db_path),
        config.embedding_model or "",
    )
    with _PERSISTENT_BRIDGES_LOCK:
        bridge = _PERSISTENT_BRIDGES.get(key)
        if bridge is None:
            warmup = {
                "action": "probe",
                "collection": config.collection,
                "app_id": config.app_id,
                "db_file": str(config.vector_db_path),
                "embedding_model": config.embedding_model,
            }
            bridge = _PersistentBridge(config.bridge_path, warmup)
            _PERSISTENT_BRIDGES[key] = bridge
        return bridge


def shutdown_persistent_bridges() -> None:
    """进程退出钩子:关闭全部常驻 bridge(FastAPI lifespan 停机时调用)。"""
    with _PERSISTENT_BRIDGES_LOCK:
        for bridge in _PERSISTENT_BRIDGES.values():
            bridge.close()
        _PERSISTENT_BRIDGES.clear()


def _protocol_response(stdout: str) -> dict[str, Any] | None:
    """Parse exactly one bridge response without trusting incidental SDK logs."""
    responses: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith(RESPONSE_PREFIX):
            continue
        try:
            parsed = json.loads(line[len(RESPONSE_PREFIX):])
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        responses.append(parsed)
    return responses[0] if len(responses) == 1 else None


def get_native_sdk() -> KylinNativeSdk:
    """Construct from current environment so operators can change config safely."""
    return KylinNativeSdk()
