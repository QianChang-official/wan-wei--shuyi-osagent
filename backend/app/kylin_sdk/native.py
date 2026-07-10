"""Process boundary for the official Kylin embedding and vector SDKs.

The vector SDK is a C++ API while the application runtime is Python.  A small
native bridge keeps the vendor ABI out of Python and communicates only through
one JSON request on stdin and one JSON response on stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db import database_path
from ..security.auth import is_production_mode


DEFAULT_BRIDGE_NAME = "wanwei-kylin-sdk-bridge"
DEFAULT_COLLECTION = "wanwei_memory_capsules"
DEFAULT_APP_ID = "wanwei-shuyi-osagent"
RESPONSE_PREFIX = "WANWEI_KYLIN_RESPONSE:"


class KylinNativeSdkError(RuntimeError):
    """A native SDK operation was unavailable or returned an invalid response."""


def _native_mode() -> str:
    mode = os.environ.get("WANWEI_KYLIN_NATIVE_MODE", "auto").strip().lower()
    return mode if mode in {"auto", "off"} else "auto"


def _timeout_seconds() -> float:
    try:
        return max(1.0, min(float(os.environ.get("WANWEI_KYLIN_SDK_TIMEOUT_SECONDS", "10")), 60.0))
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
