"""Soul ownership and request-principal helpers.

The public API authenticates with ``X-API-Key``.  Persisting a one-way actor
identifier derived from that key lets Soul and memory rows enforce the same
principal boundary without storing or returning the credential itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..db import get_conn
from ..security.auth import actor_id_from_api_key, get_api_key


class SoulAccessDenied(LookupError):
    """The requested Soul does not exist for the current API principal."""


class SoulSelectionRequired(ValueError):
    """The principal owns multiple Souls and must choose one explicitly."""


@dataclass(frozen=True)
class SoulScope:
    soul_id: str
    owner_id: str


def configured_actor_id() -> str:
    """Return the actor used for internal calls and legacy migration."""
    return actor_id_from_api_key(get_api_key())


def actor_id_for_request(request: Any | None) -> str:
    """Resolve the authenticated request actor without exposing the API key."""
    if request is None:
        return configured_actor_id()
    provided = (request.headers.get("x-api-key") or "").strip()
    if not provided:
        # Middleware rejects missing credentials before handlers run.  Keeping
        # this fallback makes direct/internal handler calls deterministic.
        return configured_actor_id()
    return actor_id_from_api_key(provided)


def owner_id_for_soul(soul_id: str) -> str | None:
    row = get_conn().execute(
        "SELECT owner_id FROM soul_persona WHERE soul_id=?",
        (soul_id,),
    ).fetchone()
    if row is None:
        return None
    owner_id = row["owner_id"]
    return str(owner_id) if owner_id else None


def require_soul_owner(soul_id: str, owner_id: str) -> SoulScope:
    """Return a scoped identity or fail without revealing cross-owner rows."""
    row = get_conn().execute(
        "SELECT soul_id FROM soul_persona WHERE soul_id=? AND owner_id=?",
        (soul_id, owner_id),
    ).fetchone()
    if row is None:
        raise SoulAccessDenied(soul_id)
    return SoulScope(soul_id=str(row["soul_id"]), owner_id=owner_id)


def resolve_owned_soul(request: Any | None, requested_soul_id: str | None) -> SoulScope:
    """Resolve an explicit Soul or an unambiguous backwards-compatible default."""
    # Several legacy callers construct TestClient without entering its lifespan;
    # ownership is now the first DB read, so preserve the existing lazy-schema
    # contract that write_capsule previously provided for those callers.
    from ..memory_runtime.capsule_store import init_runtime_schema

    init_runtime_schema()
    owner_id = actor_id_for_request(request)
    if requested_soul_id is not None:
        soul_id = requested_soul_id.strip()
        if not soul_id:
            raise SoulAccessDenied(requested_soul_id)
        return require_soul_owner(soul_id, owner_id)

    default = get_conn().execute(
        "SELECT soul_id FROM soul_persona WHERE soul_id='soul_default' AND owner_id=?",
        (owner_id,),
    ).fetchone()
    if default is not None:
        return SoulScope(soul_id=str(default["soul_id"]), owner_id=owner_id)

    rows = get_conn().execute(
        "SELECT soul_id FROM soul_persona WHERE owner_id=? ORDER BY created_at, soul_id LIMIT 2",
        (owner_id,),
    ).fetchall()
    if len(rows) == 1:
        return SoulScope(soul_id=str(rows[0]["soul_id"]), owner_id=owner_id)
    if not rows:
        # Memory APIs historically worked before an explicit /soul/connect.
        # Create one deterministic, owner-private Soul to retain that contract
        # without falling back to another principal's soul_default.
        from .persona import create_persona

        automatic_soul_id = "soul_auto_" + owner_id.removeprefix("api_")[:12]
        create_persona(automatic_soul_id, owner_id=owner_id)
        return SoulScope(soul_id=automatic_soul_id, owner_id=owner_id)
    raise SoulSelectionRequired("soul_id is required when an owner has multiple Souls")
