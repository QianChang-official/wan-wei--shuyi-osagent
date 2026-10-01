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

"""Explicit optional SDK integration; never a transparent legacy DB migration.

Public installations need no private dependency. The SDK has its own schema and
storage namespace, so enabling it does not redirect /memory/v2 or the platform
JSON memory center. A selected but missing/incompatible SDK fails closed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import importlib
import logging
import os
import sqlite3
from pathlib import Path
from types import ModuleType
from typing import Iterator

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ConfigDict, Field

from ..db import database_path
from ..schemas import CapsuleWriteIn
from ..security.input_limits import validate_search_params
from ..security.redaction import redact_capsule_for_output
from ..soul.ownership import (
    SoulAccessDenied,
    SoulScope,
    SoulSelectionRequired,
    resolve_owned_soul,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memory/sdk", tags=["Optional memory SDK"])
_EXPECTED_API = "1"
_EXPECTED_SCHEMA = 1


class SDKConfigurationError(RuntimeError):
    """A deliberately selected SDK cannot be used safely."""


@dataclass(frozen=True)
class SDKConfiguration:
    path: Path
    module: ModuleType


def load_configuration() -> SDKConfiguration | None:
    """Validate explicit opt-in without opening or migrating either database."""
    flag = os.getenv("WANWEI_MEMORY_SDK_ENABLED", "0").strip().lower()
    if flag in {"", "0", "false", "off"}:
        return None
    if flag not in {"1", "true", "on"}:
        raise SDKConfigurationError("WANWEI_MEMORY_SDK_ENABLED must be on or off")
    raw_path = os.getenv("WANWEI_MEMORY_SDK_DB", "").strip()
    path = Path(raw_path).expanduser()
    if not raw_path or not path.is_absolute():
        raise SDKConfigurationError("SDK mode requires a separate absolute WANWEI_MEMORY_SDK_DB")
    path = path.resolve()
    legacy = database_path().resolve()
    if path == legacy or (path.exists() and legacy.exists() and path.samefile(legacy)):
        raise SDKConfigurationError("SDK storage must not be the legacy memory database")
    if path.exists() and not path.is_file():
        raise SDKConfigurationError("SDK database path must name a file")
    try:
        module = importlib.import_module("wanwei_affect_memory")
    except ImportError as exc:
        raise SDKConfigurationError(
            "SDK explicitly enabled but unavailable; install a compatible local wheel or disable SDK mode"
        ) from exc
    if (
        getattr(module, "API_VERSION", None) != _EXPECTED_API
        or getattr(module, "SCHEMA_VERSION", None) != _EXPECTED_SCHEMA
        or not callable(getattr(module, "MemoryEngine", None))
    ):
        raise SDKConfigurationError("SDK API/schema version is incompatible with this adapter")
    return SDKConfiguration(path, module)


def validate_sdk_configuration() -> None:
    """Called before application workers start; disabled mode imports nothing."""
    load_configuration()


def _configuration_or_http_error() -> SDKConfiguration:
    try:
        configuration = load_configuration()
    except SDKConfigurationError as exc:
        raise HTTPException(status_code=503, detail={"error": "memory_sdk_unavailable", "reason": str(exc)}) from exc
    if configuration is None:
        raise HTTPException(status_code=404, detail={"error": "memory_sdk_disabled"})
    return configuration


def _owned_scope(request: Request, soul_id: str) -> SoulScope:
    try:
        return resolve_owned_soul(request, soul_id)
    except SoulSelectionRequired as exc:
        raise HTTPException(status_code=422, detail={"error": "soul_selection_required"}) from exc
    except SoulAccessDenied as exc:
        raise HTTPException(status_code=404, detail={"error": "not_found"}) from exc


@contextmanager
def open_scoped_engine(configuration: SDKConfiguration, scope: SoulScope) -> Iterator:
    """One scoped engine per operation; no cross-request owner or connection cache."""
    # Construction errors are configuration/storage failures, not caller errors.
    try:
        engine = configuration.module.MemoryEngine(
            configuration.path, owner_id=scope.owner_id, soul_id=scope.soul_id,
        )
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        logger.error("Memory SDK initialization failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail={"error": "memory_sdk_storage_unavailable"}) from exc
    try:
        yield engine
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "not_found"}) from exc
    except (ValueError, TypeError) as exc:
        # SDK exceptions may contain user input; do not echo them or SQL details.
        raise HTTPException(status_code=422, detail={"error": "invalid_sdk_operation"}) from exc
    finally:
        engine.close()


def _public_capsule(capsule: dict) -> dict:
    output = redact_capsule_for_output(capsule)
    output.pop("owner_id", None)
    provenance = output.get("provenance")
    if isinstance(provenance, dict):
        provenance.pop("owner_id", None)
    return output


class SDKCapsuleWriteIn(CapsuleWriteIn):
    model_config = ConfigDict(extra="forbid")
    memory_class: str = Field(min_length=1, max_length=64)
    soul_id: str = Field(min_length=1, max_length=128)


@router.get("/status")
def sdk_status():
    try:
        configuration = load_configuration()
    except SDKConfigurationError as exc:
        raise HTTPException(status_code=503, detail={"error": "memory_sdk_unavailable", "reason": str(exc)}) from exc
    return {
        "enabled": configuration is not None,
        "api_version": _EXPECTED_API,
        "schema_version": _EXPECTED_SCHEMA,
        "sdk_version": getattr(configuration.module, "__version__", None) if configuration else None,
        "namespace": "/memory/sdk",
        "isolated_storage": True,
        "legacy_memory_v2": "unchanged",
        "platform_json_memory": "unchanged",
    }


@router.post("/capsules")
def sdk_write_capsule(body: SDKCapsuleWriteIn, request: Request):
    configuration = _configuration_or_http_error()
    scope = _owned_scope(request, body.soul_id)
    payload = body.model_dump(exclude={"soul_id"})
    with open_scoped_engine(configuration, scope) as engine:
        return _public_capsule(engine.remember(**payload))


@router.get("/capsules")
def sdk_list_capsules(
    request: Request,
    soul_id: str = Query(min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
):
    configuration = _configuration_or_http_error()
    scope = _owned_scope(request, soul_id)
    with open_scoped_engine(configuration, scope) as engine:
        return {"items": [_public_capsule(item) for item in engine.list(limit=limit)]}


@router.get("/capsules/{capsule_id}")
def sdk_get_capsule(
    capsule_id: str,
    request: Request,
    soul_id: str = Query(min_length=1, max_length=128),
):
    configuration = _configuration_or_http_error()
    scope = _owned_scope(request, soul_id)
    with open_scoped_engine(configuration, scope) as engine:
        capsule = engine.get(capsule_id)
        if capsule is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        return _public_capsule(capsule)


@router.get("/search")
def sdk_search(
    request: Request,
    q: str,
    soul_id: str = Query(min_length=1, max_length=128),
    top_k: int = Query(default=5, ge=1, le=50),
    high_risk: bool = False,
):
    configuration = _configuration_or_http_error()
    scope = _owned_scope(request, soul_id)
    q, top_k = validate_search_params(q, top_k)
    with open_scoped_engine(configuration, scope) as engine:
        result = engine.search_with_status(q, limit=top_k, high_risk=high_risk)
        return {
            "query": q,
            "retrieval": result["status"],
            "results": [_public_capsule(item) for item in result["hits"]],
            "namespace": "/memory/sdk",
        }
