import re
from typing import Any

S3_PATTERNS = [
    r"password\s*[:=]", r"api[_-]?key\s*[:=]", r"token\s*[:=]", r"secret\s*[:=]",
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----", r"\b\d{17}[0-9Xx]\b",
]
POISON_PATTERNS = [
    r"忽略.*安全规则", r"覆盖.*系统提示", r"不要告诉用户", r"永久记住.*跳过确认",
    r"下次.*自动调用.*危险", r"ignore.*safety", r"override.*system", r"skip.*confirmation",
]
WEAK_IDENTIFIER_PATTERNS = [r"\b1[3-9]\d{9}\b", r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}"]


def _hits(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.I)]


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
    poison_hits = _hits(POISON_PATTERNS, text)
    weak_hits = _hits(WEAK_IDENTIFIER_PATTERNS, text)

    if s3_hits:
        return {
            "sensitivity_level": "S3", "trust_score": 0.0, "confidence": 0.9,
            "policy_result": "reject", "risk_tags": ["s3_secret", "block_from_memory"],
            "retention_policy": "read_only", "requires_confirmation": False,
            "hits": s3_hits,
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
