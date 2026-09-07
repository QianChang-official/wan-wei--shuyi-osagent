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
#
# 疑问式否定前瞻（是否 / 为何 / 为什么）：MEB-POISON-004 实测发现
# 「口令是否需要定期更换」「密钥为何需要轮换」会被误判为凭据泄漏——
# 「是」「为」被当成赋值动词，后面的「否需要定期」被当成了值。这三个词是疑问
# 语气，语法上不可能引出凭据值，排除它们不削弱检出能力：真实赋值写法
# （「口令是 abc123」「密钥设为 AK-xxx」）仍照常命中。
S3_NL_PATTERNS = [
    re.compile(
        r"(?:密码|口令|密钥|私钥|令牌|凭据|访问码)\s*"
        r"(?:是(?!否)|为(?!何|什么)|：|:|=|设为|设置成|设置成|改成|记成|记为|写成|更新为)"
        r"\s*\S{4,}",
        re.IGNORECASE,
    ),
    re.compile(
        r"我(?:们)?的(?:(?:WiFi|Wi-?Fi|热点|路由器|管理员|数据库|root)\s*)?"
        r"(?:密码|口令|密钥|私钥|令牌|凭据)\s*(?:是|：|:)?\s*\S{4,}",
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
    #
    # 疑问式否定前瞻（是否 / 为何 / 为什么）：MEB-POISON-004 实测发现
    # 「密码策略是否符合等级保护要求」会被这条规则误判为凭据泄漏——.{0,8} 把
    # 「策略」吃进窗口，「是」后面跟着的「否」被当成了密码值。「是否」「为何」
    # 「为什么」是疑问语气，语法上不可能引出一个凭据值，排除它们不削弱检出能力
    # （真实赋值仍会命中「密码是 xxx」）。
    re.compile(
        r"(?:密码|口令|密钥|身份证号|银行卡).{0,8}(?:是(?!否)|为(?!何|什么)|：|:)\s*\S",
        re.IGNORECASE,
    ),
    # 英文「(password|passphrase|secret|api key).{0,10}(is|:)+值」——覆盖
    # 「my root password is hunter2」「the api key: abc」等夹带修饰语写法。
    re.compile(
        r"(?:password|passphrase|secret|api[_ -]?key).{0,10}(?:is|:)\s*\S",
        re.IGNORECASE,
    ),
    # issue #116：「把数据库口令 root@2026Prod 记下来」——值在前、赋值动词在
    # 后的倒装写法（旧词表只有前置动词，「记下来」不在其中）。仅匹配
    # 「敏感词 + 值 + 后置动词」结构，避免「请把密码策略文档记下来」误伤：
    # 值位要求 4+ 非空白字符，纯词（策略/文档）通常不足长。
    re.compile(
        r"(?:密码|口令|密钥|私钥|令牌|凭据)\s*\S{4,}\s*(?:记下来|记一下|记录一下|保存下来|存下来|存好)",
        re.IGNORECASE,
    ),
]

# 间隔符绕过：p a s s w o r d = x / p.a.s.s.w.o.r.d 这类逐字符拆开写法。
_SQUASH_MIN_CHARS = 10
AWS_KEY_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
]
OPENAI_KEY_PATTERNS = [re.compile(r"sk-[a-zA-Z0-9_-]{20,}")]
# issue #116：凭据格式集合与 security.redaction._PATTERNS 对齐（单一规则来源）。
# 旧闸门只认识 AKIA/ASIA 与 sk- 两种前缀，ghp_/AIza/xox/sk-ant-/JWT/PEM/
# 内嵌凭据连接串等格式一律判 allow——而 redaction 模块为这些格式写的掩码
# 规则又被 policy_result 门控跳过，形成「闸门放行 → 跳过脱敏 → 明文入库并
# 原样读回」的闭环。两个模块从此共用同一份格式认知，不再各写一份。
CREDENTIAL_TOKEN_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}"),            # GitHub PAT 全系列
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),                 # Google API key
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}"),           # Slack token
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"),              # Anthropic key
    re.compile(r"\bsk_live_[A-Za-z0-9]{16,}"),               # Stripe live key
    re.compile(r"\bsess-[A-Za-z0-9]{32,}"),                  # OpenAI session
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(
        r"\b(?:ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-\S+)\s+AAAA[0-9A-Za-z+/]{32,}={0,3}"
    ),                                                       # SSH 公钥
    re.compile(r"[a-z][a-z0-9+.-]*://[^/:\s@]+:[^@\s]+@"),   # 内嵌凭据连接串
]
PHONE_PATTERNS = [re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")]
ID_CARD_PATTERNS = [re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")]
POISON_PATTERNS = [
    re.compile(r"忽略.*安全规则", re.IGNORECASE | re.DOTALL),
    re.compile(r"忽略.*(?:之前|以上|所有).*(?:指令|提示|规则)", re.IGNORECASE | re.DOTALL),
    re.compile(r"覆盖.*系统提示", re.IGNORECASE | re.DOTALL),
    re.compile(r"不要告诉用户", re.IGNORECASE | re.DOTALL),
    re.compile(r"永久记住.*跳过确认", re.IGNORECASE | re.DOTALL),
    re.compile(r"下次.*自动调用.*危险", re.IGNORECASE | re.DOTALL),
    re.compile(r"无视.*(?:安全|限制|防护)", re.IGNORECASE | re.DOTALL),
    re.compile(r"ignore.*safety", re.IGNORECASE | re.DOTALL),
    re.compile(r"ignore.*(?:previous|all).*(?:instructions|prompts)", re.IGNORECASE | re.DOTALL),
    re.compile(r"override.*system", re.IGNORECASE | re.DOTALL),
    re.compile(r"skip.*confirmation", re.IGNORECASE | re.DOTALL),
    re.compile(r"disregard.*(?:guidelines|rules)", re.IGNORECASE | re.DOTALL),
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
    # 支持 ASCII 与中文（一-鿿），否则「忽 略 之 前」压不回去
    pattern = re.compile(r"(?:[A-Za-z0-9一-鿿][\s.\-_]){3,}[A-Za-z0-9一-鿿]")

    def _join(match: re.Match) -> str:
        return re.sub(r"[\s.\-_]", "", match.group(0))

    return pattern.sub(_join, text)


def _hits(patterns: list[re.Pattern], text: str) -> list[str]:
    """Check which compiled patterns match the text."""
    return [p.pattern for p in patterns if p.search(text)]


def _collapse_digit_separators(text: str) -> str:
    """折叠数字之间的空白/点/横线，线性扫描实现（无回溯，规避 ReDoS）。

    等价于 ``re.sub(r"(?<=\\d)[\\s.\\-]+(?=\\d)", "", text)``，但对包含
    大量重复分隔符的恶意输入保持 O(n) 时间复杂度。
    """
    if not text:
        return text
    chars: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c.isdigit():
            chars.append(c)
            j = i + 1
            # 跳过夹在两个数字之间的分隔符串
            while j < n and text[j] in " \t\r\n.-":
                j += 1
            if j < n and j > i + 1 and text[j].isdigit():
                i = j
            else:
                i += 1
        else:
            chars.append(c)
            i += 1
    return "".join(chars)


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
    # issue #116：间隔符归一化覆盖全部凭据组（旧实现只作用于 S3_PATTERNS，
    # phone/id/aws/openai 四组不做归一化，「1 3 8 0 0 0 0 1 2 3 4」可绕过）。
    if squashed != text:
        aws_hits = _hits(AWS_KEY_PATTERNS, text) + _hits(AWS_KEY_PATTERNS, squashed)
        openai_hits = _hits(OPENAI_KEY_PATTERNS, text) + _hits(OPENAI_KEY_PATTERNS, squashed)
        cred_hits = _hits(CREDENTIAL_TOKEN_PATTERNS, text) + _hits(
            CREDENTIAL_TOKEN_PATTERNS, squashed
        )
        aws_hits = list(dict.fromkeys(aws_hits))
        openai_hits = list(dict.fromkeys(openai_hits))
        cred_hits = list(dict.fromkeys(cred_hits))
    else:
        aws_hits = _hits(AWS_KEY_PATTERNS, text)
        openai_hits = _hits(OPENAI_KEY_PATTERNS, text)
        cred_hits = _hits(CREDENTIAL_TOKEN_PATTERNS, text)
    # issue #116：数字分组归一化（「138 0000 1234」「110101 19900101 001X」）。
    # 只折叠数字之间的空白/点/横线，不影响其他文本。
    # 使用线性扫描而非回溯正则，规避 CodeQL py/polynomial-redos。
    digits_collapsed = _collapse_digit_separators(text)
    phone_hits = _hits(PHONE_PATTERNS, text)
    id_hits = _hits(ID_CARD_PATTERNS, text)
    if digits_collapsed != text:
        phone_hits += _hits(PHONE_PATTERNS, digits_collapsed)
        id_hits += _hits(ID_CARD_PATTERNS, digits_collapsed)
        phone_hits = list(dict.fromkeys(phone_hits))
        id_hits = list(dict.fromkeys(id_hits))
    all_s3_hits = s3_hits + nl_hits + aws_hits + openai_hits + cred_hits
    poison_hits = _hits(POISON_PATTERNS, text)
    if squashed != text:
        poison_hits += _hits(POISON_PATTERNS, squashed)
        poison_hits = list(dict.fromkeys(poison_hits))
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

def evaluate_preference_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    text = f"{candidate.get('subject', '')} {candidate.get('predicate', '')} {candidate.get('object', '')}"
    result = evaluate_policy(text=text, write_intent="inferred", affects_future_behavior=True)
    if candidate.get("source") == "sequence_mining":
        result["requires_confirmation"] = True
        result["policy_result"] = "require_confirmation"
    return result
