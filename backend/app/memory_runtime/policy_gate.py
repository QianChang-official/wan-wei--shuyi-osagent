import re
from typing import Any

# Pre-compile regex patterns for performance
S3_PATTERNS = [
    re.compile(r"password\s*[:=：]", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=：]", re.IGNORECASE),
    re.compile(r"token\s*[:=：]", re.IGNORECASE),
    re.compile(r"secret\s*[:=：]", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b\d{17}[0-9Xx]\b"),
]

# 第四批 P1：自然语言敏感表述（中文同义词 + 赋值动词），堵住
# 「我的口令是 xxx」「把密钥记成 xxx」这类绕过 regex 直写的写法。
# 仅匹配「敏感词 + 赋值动词 + 值」结构，避免「请修改密码策略」之类误伤。
S3_NL_PATTERNS = [
    re.compile(
        r"(?:密码|口令|密钥|私钥|令牌|凭据|访问码)\s*(?:是|为|：|:|=|设为|设置成|设置成|改成|记成|记为|写成|更新为)\s*\S{4,}",
        re.IGNORECASE,
    ),
    re.compile(
        r"我(?:们)?的(?:密码|口令|密钥|私钥|令牌|凭据)\s*(?:是|：|:)?\s*\S{4,}",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:password|passwd|api[_-]?key|secret|token|credential)\s+is\s+\S{4,}",
        re.IGNORECASE,
    ),
    # 复测补充（原规则只认 password[:=] 形态，以下自然语言表述曾实机绕过）：
    # 中文「敏感词.{0,8}是/为/：/: + 值」——覆盖「我的银行卡密码是 123456」
    # 「身份证号为 xxx」这类在敏感词与赋值动词间夹带修饰语的写法。
    # 注意：.{0,8} 窗口 + 必须有后续值字符，避免「请修改密码策略」「密钥轮换
    # 方案」这类无赋值动词的表述被误伤（test_batch4_p1 有用例钉死）。
    re.compile(
        r"(?:密码|口令|密钥|身份证号|银行卡).{0,8}(?:是|为|：|:)\s*\S",
        re.IGNORECASE,
    ),
    # 英文「(password|passphrase|secret|api key).{0,10}(is|:)+值」——覆盖
    # 「my root password is hunter2」「the api key: abc」等夹带修饰语写法。
    re.compile(
        r"(?:password|passphrase|secret|api[_ -]?key).{0,10}(?:is|:)\s*\S",
        re.IGNORECASE,
    ),
]

# 间隔符绕过：p a s s w o r d = x / p.a.s.s.w.o.r.d 这类逐字符拆开写法。
_SQUASH_MIN_CHARS = 10
AWS_KEY_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
]
OPENAI_KEY_PATTERNS = [re.compile(r"sk-[a-zA-Z0-9]{20,}")]
PHONE_PATTERNS = [re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")]
ID_CARD_PATTERNS = [re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")]
POISON_PATTERNS = [
    re.compile(r"忽略.*安全规则", re.IGNORECASE),
    re.compile(r"忽略.*(?:之前|以上|所有).*(?:指令|提示|规则)", re.IGNORECASE),
    re.compile(r"覆盖.*系统提示", re.IGNORECASE),
    re.compile(r"不要告诉用户", re.IGNORECASE),
    re.compile(r"永久记住.*跳过确认", re.IGNORECASE),
    re.compile(r"下次.*自动调用.*危险", re.IGNORECASE),
    re.compile(r"无视.*(?:安全|限制|防护)", re.IGNORECASE),
    re.compile(r"ignore.*safety", re.IGNORECASE),
    re.compile(r"ignore.*(?:previous|all).*(?:instructions|prompts)", re.IGNORECASE),
    re.compile(r"override.*system", re.IGNORECASE),
    re.compile(r"skip.*confirmation", re.IGNORECASE),
    re.compile(r"disregard.*(?:guidelines|rules)", re.IGNORECASE),
]
WEAK_IDENTIFIER_PATTERNS = [
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}")
]


def _squash_spaced(text: str) -> str:
    """把「字符 + 分隔符」逐字拆开的写法压回连续串，用于检出间隔符绕过。

    例：``p a s s w o r d = x`` / ``p.a.s.s`` → ``password`` / ``pass``。
    仅处理片段长度足够的序列，避免正常文本被误压。
    """
    # 连续「单字符 + 空格/点/短横」重复 4 次以上的片段视为拆分写法
    pattern = re.compile(r"(?:[A-Za-z0-9][\s.\-_]){3,}[A-Za-z0-9]")

    def _join(match: re.Match) -> str:
        return re.sub(r"[\s.\-_]", "", match.group(0))

    return pattern.sub(_join, text)


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
    # 间隔符拆写归一化后再跑一遍 S3 规则（检出 p a s s w o r d = x 类绕过）
    squashed = _squash_spaced(text)
    s3_hits = _hits(S3_PATTERNS, text)
    if squashed != text:
        s3_hits += _hits(S3_PATTERNS, squashed)
        s3_hits = list(dict.fromkeys(s3_hits))
    nl_hits = _hits(S3_NL_PATTERNS, text)
    aws_hits = _hits(AWS_KEY_PATTERNS, text)
    openai_hits = _hits(OPENAI_KEY_PATTERNS, text)
    phone_hits = _hits(PHONE_PATTERNS, text)
    id_hits = _hits(ID_CARD_PATTERNS, text)
    all_s3_hits = s3_hits + nl_hits + aws_hits + openai_hits
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
