import re
from typing import Any

# Pre-compile regex patterns for performance
S3_PATTERNS = [
    re.compile(r"password\s*[:=]", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]", re.IGNORECASE),
    re.compile(r"token\s*[:=]", re.IGNORECASE),
    re.compile(r"secret\s*[:=]", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b\d{17}[0-9Xx]\b"),
]
AWS_KEY_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
]
OPENAI_KEY_PATTERNS = [re.compile(r"sk-[a-zA-Z0-9]{20,}")]
PHONE_PATTERNS = [re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")]
ID_CARD_PATTERNS = [re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")]
POISON_PATTERNS = [
    re.compile(r"忽略.*安全规则", re.IGNORECASE),
    re.compile(r"覆盖.*系统提示", re.IGNORECASE),
    re.compile(r"不要告诉用户", re.IGNORECASE),
    re.compile(r"永久记住.*跳过确认", re.IGNORECASE),
    re.compile(r"下次.*自动调用.*危险", re.IGNORECASE),
    re.compile(r"ignore.*safety", re.IGNORECASE),
    re.compile(r"override.*system", re.IGNORECASE),
    re.compile(r"skip.*confirmation", re.IGNORECASE),
]
WEAK_IDENTIFIER_PATTERNS = [
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}")
]


def _hits(patterns: list[re.Pattern], text: str) -> list[str]:
    """Check which compiled patterns match the text."""
    return [p.pattern for p in patterns if p.search(text)]


def evaluate_policy(
    *,
    text: str,
    source_type: str = "user_input",
    write_intent: str = "explicit",
    affects_future_behavior: bool = False,
    source_trust: str = "normal",
    memory_class: str = "knowledge",
) -> dict[str, Any]:
    s3_hits = _hits(S3_PATTERNS, text)
    aws_hits = _hits(AWS_KEY_PATTERNS, text)
    openai_hits = _hits(OPENAI_KEY_PATTERNS, text)
    phone_hits = _hits(PHONE_PATTERNS, text)
    id_hits = _hits(ID_CARD_PATTERNS, text)
    all_s3_hits = s3_hits + aws_hits + openai_hits
    poison_hits = _hits(POISON_PATTERNS, text)
    weak_hits = _hits(WEAK_IDENTIFIER_PATTERNS, text)

    if all_s3_hits:
        return {
            "sensitivity_level": "S3", "trust_score": 0.0, "confidence": 0.9,
            "policy_result": "reject", "risk_tags": ["s3_secret", "block_from_memory"],
            "retention_policy": "read_only", "requires_confirmation": False,
            "hits": all_s3_hits,
        }
    if phone_hits or id_hits:
        return {
            "sensitivity_level": "S3", "trust_score": 0.0, "confidence": 0.9,
            "policy_result": "reject", "risk_tags": ["s3_secret", "pii"],
            "retention_policy": "read_only", "requires_confirmation": False,
            "hits": phone_hits + id_hits,
        }
    if poison_hits:
        return {
            "sensitivity_level": "S2", "trust_score": 0.1, "confidence": 0.85,
            "policy_result": "quarantine", "risk_tags": ["memory_poisoning", "prompt_injection"],
            "retention_policy": "short_term", "requires_confirmation": False,
            "hits": poison_hits,
        }
    if source_trust == "low" and write_intent == "autonomous":
        return {
            "sensitivity_level": "S1", "trust_score": 0.25, "confidence": 0.7,
            "policy_result": "quarantine", "risk_tags": ["low_trust_autonomous_write"],
            "retention_policy": "short_term", "requires_confirmation": False,
            "hits": [],
        }
    if write_intent == "inferred" and affects_future_behavior:
        return {
            "sensitivity_level": "S1", "trust_score": 0.65, "confidence": 0.65,
            "policy_result": "require_confirmation", "risk_tags": ["inferred_preference"],
            "retention_policy": "medium_term", "requires_confirmation": True,
            "hits": [],
        }
    if weak_hits:
        return {
            "sensitivity_level": "S1", "trust_score": 0.75, "confidence": 0.75,
            "policy_result": "redact", "risk_tags": ["weak_identifier"],
            "retention_policy": "medium_term", "requires_confirmation": False,
            "hits": weak_hits,
        }
    return {
        "sensitivity_level": "S0", "trust_score": 0.9, "confidence": 0.85,
        "policy_result": "allow", "risk_tags": [], "retention_policy": "long_term",
        "requires_confirmation": False, "hits": [],
    }
