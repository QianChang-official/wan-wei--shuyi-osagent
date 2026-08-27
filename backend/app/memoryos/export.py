"""Auditable, owner-scoped memory evidence exports.

The export is deliberately generated from the same capsule and ledger stores as
the runtime. It is a portable evidence artifact, not a second persistence
format: content is redacted before serialization, internal owner identifiers
are removed, and an integrity digest covers the exported body.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..memory_runtime.capsule_store import list_capsules
from ..security.redaction import redact_capsule_for_output, redact_dict
from ..utils.datetime_utils import utc_now_iso_compact
from .governance import ledger_history, provenance_card

EXPORT_FORMAT = "memory-evidence-v1"
MAX_CAPSULES = 200
MAX_LEDGER_ITEMS = 50
MAX_RECORD_CHARS = 12000


def _strip_internal_keys(value: Any) -> Any:
    """Remove internal ownership fields at every nesting level."""
    if isinstance(value, dict):
        return {
            key: _strip_internal_keys(item)
            for key, item in value.items()
            if key != "owner_id"
        }
    if isinstance(value, list):
        return [_strip_internal_keys(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_internal_keys(item) for item in value)
    return value


def _safe_capsule(capsule: dict[str, Any]) -> dict[str, Any]:
    """Return a recursively redacted capsule without internal ownership data."""
    return _strip_internal_keys(redact_dict(redact_capsule_for_output(capsule)))


def _safe_card(capsule: dict[str, Any]) -> dict[str, Any]:
    card = _strip_internal_keys(redact_dict(provenance_card(capsule)))
    card.pop("owner", None)
    return card


def _safe_ledger(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        output.append(_strip_internal_keys(redact_dict(dict(item))))
    return output


def _json_block(value: Any, *, max_chars: int = MAX_RECORD_CHARS) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    if len(encoded) <= max_chars:
        return encoded
    return encoded[:max_chars] + "\n... [truncated by export policy]"


def build_memory_evidence_export(
    *,
    owner_id: str | None,
    soul_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Build a bounded Markdown/JSON evidence package for one owner scope."""
    capped = max(1, min(int(limit), MAX_CAPSULES))
    capsules = list_capsules(capped, owner_id=owner_id, soul_id=soul_id)
    records: list[dict[str, Any]] = []
    for capsule in capsules:
        capsule_id = str(capsule.get("capsule_id"))
        records.append({
            "capsule": _safe_capsule(capsule),
            "provenance_card": _safe_card(capsule),
            "ledger": _safe_ledger(
                ledger_history(
                    capsule_id,
                    limit=MAX_LEDGER_ITEMS,
                    owner_id=owner_id,
                    soul_id=soul_id,
                )
            ),
        })

    generated_at = utc_now_iso_compact()
    body_lines = [
        "# Wanwei Memory Evidence Export",
        "",
        f"- format: `{EXPORT_FORMAT}`",
        f"- generated_at: `{generated_at}`",
        "- scope: `owner-scoped`",
        f"- soul_id: `{soul_id or 'all-owned-souls'}`",
        f"- capsule_count: `{len(records)}`",
        "- redaction: `sensitive strings are redacted before serialization`",
        "",
    ]
    for index, record in enumerate(records, start=1):
        capsule = record["capsule"]
        card = record["provenance_card"]
        capsule_id = capsule.get("capsule_id", f"record-{index}")
        body_lines.extend([
            f"## {index}. Capsule `{capsule_id}`",
            "",
            f"- memory_class: `{capsule.get('memory_class', 'unknown')}`",
            f"- created_at: `{capsule.get('created_at', 'unknown')}`",
            f"- lifecycle: `{card.get('lifecycle', 'unknown')}`",
            "",
            "### Provenance Card",
            "",
            "```json",
            _json_block(card),
            "```",
            "",
            "### Capsule Content (redacted)",
            "",
            "```json",
            _json_block(capsule.get("content") or {}),
            "```",
            "",
            "### Ledger",
            "",
            "```json",
            _json_block(record["ledger"]),
            "```",
            "",
        ])

    body = "\n".join(body_lines).rstrip() + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    markdown = body + f"\n<!-- integrity_sha256: {digest} -->\n"
    return {
        "format": EXPORT_FORMAT,
        "generated_at": generated_at,
        "scope": "owner-scoped",
        "soul_id": soul_id,
        "item_count": len(records),
        "integrity_sha256": digest,
        "records": records,
        "markdown": markdown,
    }


__all__ = ["EXPORT_FORMAT", "build_memory_evidence_export"]
