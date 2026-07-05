"""Redaction utilities for sensitive data in audit logs and responses."""
from __future__ import annotations

import re
from typing import Any


# Patterns for sensitive data detection
_PATTERNS = [
    # Passwords
    (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\'}\s]+)', re.IGNORECASE), r'\1***REDACTED***'),
    # Bearer tokens
    (re.compile(r'(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)', re.IGNORECASE), r'\1***REDACTED***'),
    # OpenAI-style keys (sk-, sess-)
    (re.compile(r'\b(sk-[A-Za-z0-9]{32,})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(sess-[A-Za-z0-9]{32,})', re.IGNORECASE), r'***REDACTED***'),
    # AWS keys
    (re.compile(r'\b(AKIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(ASIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED***'),
    # Chinese mobile phone (11 digits starting with 1)
    (re.compile(r'\b1[3-9]\d{9}\b'), r'***PHONE***'),
    # Chinese ID card (18 digits or 17 digits + X)
    (re.compile(r'\b\d{17}[\dXx]\b'), r'***ID***'),
    # Private key blocks
    (re.compile(r'-----BEGIN [A-Z ]+PRIVATE KEY-----[^-]+-----END [A-Z ]+PRIVATE KEY-----', re.DOTALL),
     r'***PRIVATE_KEY_REDACTED***'),
]


def redact_sensitive_text(text: str) -> str:
    """
    Redact sensitive information from text.

    Args:
        text: Input text that may contain sensitive data

    Returns:
        Text with sensitive data replaced by redaction markers
    """
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(data: dict[str, Any], in_place: bool = False) -> dict[str, Any]:
    """
    Recursively redact sensitive data from dictionary.

    Args:
        data: Dictionary that may contain sensitive data
        in_place: If True, modify dict in place; otherwise create copy

    Returns:
        Dictionary with sensitive data redacted
    """
    if not in_place:
        data = data.copy()

    for key, value in data.items():
        if isinstance(value, str):
            data[key] = redact_sensitive_text(value)
        elif isinstance(value, dict):
            data[key] = redact_dict(value, in_place=False)
        elif isinstance(value, list):
            data[key] = [
                redact_dict(item, in_place=False) if isinstance(item, dict)
                else redact_sensitive_text(item) if isinstance(item, str)
                else item
                for item in value
            ]

    return data


def redact_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Redact sensitive data from audit log payload.

    For rejected events (policy blocks), stores metadata instead of full content:
    - risk_tags: What triggered the block
    - sensitivity_level: S0-S3 classification
    - content_hash: Hash of content for correlation
    - content_preview: First 100 chars (redacted)

    Args:
        payload: Audit payload that may contain sensitive data

    Returns:
        Redacted payload suitable for audit logging
    """
    result = redact_dict(payload, in_place=False)

    # For policy rejections, further reduce stored content
    if result.get('policy_result') == 'reject' or result.get('guard', {}).get('policy_result') == 'reject':
        if 'content' in result:
            content = result['content']
            if isinstance(content, dict):
                content = str(content)
            # Store only preview and metadata, not full content
            result['content'] = '[REDACTED - Policy Block]'
            result['content_preview'] = redact_sensitive_text(content[:100]) if content else ''

    return result
