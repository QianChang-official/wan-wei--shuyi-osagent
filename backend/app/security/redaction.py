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

"""Redaction utilities for sensitive data in audit logs and responses."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


# issue #172：入口长度闸。URL 凭据正则在「不含 :// 的长文本」上会从每个
# 候选起点贪婪延伸到串尾再逐步回溯（O(n²)，实测 128KB ≈ 40s），处理期间
# 持有 GIL，单请求即可饿死事件循环。超过该阈值的输入改走分段处理
# （见 redact_sensitive_text），保证单次调用耗时随输入线性可控。
_LARGE_TEXT_THRESHOLD = 16 * 1024

# 分段单段上限：即便某段命中回溯最坏输入，代价也被限制在该值平方量级。
# 段边界优先落在换行符之后（行内 token 不含换行，不会被切断）；对超长单行
# 则按定长硬切，保证最坏情况输入下每段规模仍有上界。
_REDACT_SEGMENT_CHARS = 1024

# Database URL / 连接串凭据（user:password@host）。独立命名便于测试引用，
# 也便于 _LINE_SCOPED_PATTERNS 过滤时用 is 判定。
# issue #172：用户段排除 @、user/password 各加 {1,256} 上限并保留尾部终止
# @ 断言，杜绝超长凭据段在无终止符文本上的逐点回溯；正常 URL 的脱敏结果
# 与旧正则逐字符一致。
_URL_CREDENTIAL_RE = re.compile(
    r'([a-z][a-z0-9+.-]*://)([^/:\s@]{1,256}):([^@\s]{1,256})@',
    re.IGNORECASE,
)

# Private key blocks 规则（多行 DOTALL）：大文本分段时可能被切在块中间，
# 需在拼接后的完整串上兜底执行一次；该规则本身线性、无回溯风险。
_PRIVATE_KEY_RE = re.compile(
    r'-----BEGIN [A-Z ]+PRIVATE KEY-----[^-]+-----END [A-Z ]+PRIVATE KEY-----',
    re.DOTALL,
)
_PRIVATE_KEY_REPLACEMENT = r'***PRIVATE_KEY_REDACTED***'


# Patterns for sensitive data detection
_PATTERNS = [
    # Passwords
    (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\'}\r\n,]+)', re.IGNORECASE), r'\1***REDACTED***'),
    # Generic credential assignments
    (re.compile(r'((?:api[_-]?key|secret|token)["\']?\s*[:=]\s*["\']?)([^"\'}\r\n,]+)', re.IGNORECASE), r'\1***REDACTED***'),
    # Bearer tokens
    (re.compile(r'(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)', re.IGNORECASE), r'\1***REDACTED***'),
    # Common provider / SaaS token formats
    (re.compile(r'\b(sk-[A-Za-z0-9_-]{16,})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(sk-ant-[A-Za-z0-9_-]{16,})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(sess-[A-Za-z0-9]{32,})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(gh[pousr]_[A-Za-z0-9_]{20,})'), r'***REDACTED***'),
    (re.compile(r'\b(AIza[0-9A-Za-z_-]{20,})'), r'***REDACTED***'),
    (re.compile(r'\b(xox[baprs]-[0-9A-Za-z-]{10,})'), r'***REDACTED***'),
    (re.compile(r'\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'), r'***REDACTED***'),
    # Database URLs with user:password@host
    (_URL_CREDENTIAL_RE, r'\1\2:***REDACTED***@'),
    # Natural language passwords
    (re.compile(r'((?:the\s+)?password\s+(?:is|=|:)\s+)([^\r\n,;]+)', re.IGNORECASE), r'\1***REDACTED***'),
    # AWS keys
    (re.compile(r'\b(AKIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(ASIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED***'),
    # FIX-05: Email addresses (与 policy_gate EMAIL_PATTERNS 对齐)
    (re.compile(r'\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b'), r'[REDACTED_EMAIL]'),
    # Chinese mobile phone (11 digits starting with 1)
    (re.compile(r'\b1[3-9]\d{9}\b'), r'***PHONE***'),
    # Chinese ID card (18 digits or 17 digits + X)
    (re.compile(r'\b\d{17}[\dXx]\b'), r'***ID***'),
    # Private key blocks
    (_PRIVATE_KEY_RE, _PRIVATE_KEY_REPLACEMENT),
]

# 行内/单 token 规则：匹配结果不会跨越换行符，可对分段逐一执行且与整串执行
# 结果一致。私钥块规则（DOTALL、可跨行跨段）单独剥离，在大文本分段脱敏后
# 于拼接完整串上兜底执行，避免分段把 BEGIN/END 块切散导致漏掩。
_LINE_SCOPED_PATTERNS = tuple(
    (pattern, replacement)
    for pattern, replacement in _PATTERNS
    if pattern is not _PRIVATE_KEY_RE
)
_MULTILINE_TAIL_PATTERNS = ((_PRIVATE_KEY_RE, _PRIVATE_KEY_REPLACEMENT),)

# 补跑阶段按锚点窗口执行 URL 凭据规则时的窗口半径：覆盖 scheme 最短前缀
# （如 a:// 为 1 字符 scheme）与 user/password 段的 {1,256} 上界，保证任何
# 合法匹配完整落在某个窗口内（窗口两侧各取 300 ≥ 256 + 余量）。
_URL_ANCHOR_WINDOW = 300

# 除 URL 凭据规则外的全部规则（含私钥块）：这些正则本身线性（定长前缀/
# 字符类有界/固定结构），可在补跑阶段对整串安全执行。
_NON_URL_PATTERNS = tuple(
    (pattern, replacement)
    for pattern, replacement in _PATTERNS
    if pattern is not _URL_CREDENTIAL_RE
)


def _apply_patterns(text: str, patterns) -> str:
    """按顺序对文本应用每一组 (编译后正则, 替换串)。"""
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


def _redact_with_url_anchors(text: str) -> str:
    """全规则兜底补跑，但 URL 凭据规则按锚点窗口执行（防 O(n·256) 起点试探）。

    ``_URL_CREDENTIAL_RE`` 虽然各分支有 {1,256} 上界，但引擎仍会为**每个起点**
    试探 scheme 前缀 ``[a-z][a-z0-9+.-]*://``——对不含 ``://`` 的长文本这是
    O(n) 起点 × 每起点 O(256) 的常量级放大，在补跑阶段对整串执行时退化为
    二次行为（168KB 全字母实测 63s）。因此补跑时先用 ``str.find``（线性）
    定位每个 ``://`` 锚点，仅在锚点前后 ``_URL_ANCHOR_WINDOW`` 字符的窗口上
    应用该规则；其余规则天然线性，整串执行。窗口大小覆盖用户段/密码段
    {1,256} 上界与 scheme 最短前缀，保证任何合法匹配都完整落在某个窗口内。
    """
    if not text:
        return text
    first_colon = text.find("://")
    if first_colon == -1:
        # 无任何 URL 锚点：URL 规则不可能匹配，跳过之（这正是 DoS 载荷形态）。
        return _apply_patterns(text, _NON_URL_PATTERNS)
    window = _URL_ANCHOR_WINDOW
    pieces: list[str] = []
    pos = 0
    while True:
        anchor = text.find("://", pos)
        if anchor == -1:
            pieces.append(_apply_patterns(text[pos:], _NON_URL_PATTERNS))
            break
        win_start = max(pos, anchor - window)
        win_end = min(len(text), anchor + len("://") + window)
        pieces.append(_apply_patterns(text[pos:win_start], _NON_URL_PATTERNS))
        pieces.append(_apply_patterns(text[win_start:win_end], _PATTERNS))
        pos = win_end
    return "".join(pieces)


def _iter_segments(text: str):
    """逐段产出文本，单段不超过 ``_REDACT_SEGMENT_CHARS`` 个字符。

    段边界优先落在窗口内最后一个换行符之后，使完整行留在同一段内；当输入
    连续超长且没有换行（如纯字母 DoS 载荷）时按定长硬切，保证最坏输入下
    每段规模仍有上界。
    """
    limit = _REDACT_SEGMENT_CHARS
    start = 0
    n = len(text)
    while start < n:
        end = start + limit
        if end >= n:
            yield text[start:]
            return
        cut = text.rfind('\n', start, end)
        if cut > start:
            yield text[start:cut + 1]
            start = cut + 1
        else:
            yield text[start:end]
            start = end


def redact_sensitive_text(text: str) -> str:
    """
    Redact sensitive information from text.

    Args:
        text: Input text that may contain sensitive data

    Returns:
        Text with sensitive data replaced by redaction markers
    """
    # issue #172 长度闸：不超过阈值保持原有单串处理，行为逐字符不变；超过
    # 阈值的输入按段脱敏再拼接，避免 URL 凭据正则在最坏输入上的 O(n²) 回溯
    # 饿死事件循环，单次调用耗时随输入长度线性可控。
    if len(text) <= _LARGE_TEXT_THRESHOLD:
        return _apply_patterns(text, _PATTERNS)

    # 1) 行内/单 token 规则逐段执行；2) 私钥块（唯一可跨行的 DOTALL 规则）+
    # 3) 拼接后全规则兜底补跑一遍。
    #
    # 兜底补跑的必要性（交叉审查发现）：段边界优先落换行、无换行时定长硬切，
    # 跨越切点的 URL 凭据/Bearer token 等敏感模式会被腰斩而在两段中都不匹配，
    # 逐段脱敏因此是**保守**的（宁漏勿爆）。拼接后 token 重新合体，再跑一遍
    # 全规则即可回收这些漏网模式。补跑不破坏防 DoS 语义：
    # - 逐段处理已把每段规模压到 _REDACT_SEGMENT_CHARS 量级，拼接串里的敏感
    #   token 已被段内规则掩掉，补跑面对的是"标记+残骸"文本，不构成回溯放大；
    # - 所有行内规则本身线性（{1,256} 加界/sk- 定长前缀/电话身份证定长），
    #   URL 凭据规则带 {1,256} 上界与 @ 终止断言，最坏仍是线性；
    # - 补跑产生的标记在再入时对标记文本自身不匹配（标记不含可再触发的结构），
    #   幂等，测试覆盖。
    pieces = [
        _apply_patterns(segment, _LINE_SCOPED_PATTERNS)
        for segment in _iter_segments(text)
    ]
    joined = _apply_patterns(''.join(pieces), _MULTILINE_TAIL_PATTERNS)
    return _redact_with_url_anchors(joined)


def _redact_value(value: Any) -> Any:
    """Return a recursively redacted copy of a JSON-compatible value."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return deepcopy(value)


def redact_capsule_for_output(capsule: dict[str, Any]) -> dict[str, Any]:
    """Create an independent capsule copy that is safe for external output.

    issue #116：输出脱敏**无条件执行**，不再由 ``policy_result == "redact"``
    门控。旧实现形成「闸门放行 → 跳过脱敏」闭环：policy_gate 的凭据识别
    只覆盖 AWS/sk- 两种前缀，ghp_/AIza/xox/JWT/PEM/数据库连接串等格式
    会被判 ``allow``，于是本模块专门为这些格式写的掩码规则在结构上永远
    走不到——明文密钥可入库并原样读回。脱敏是输出边界的独立防线，
    不该依赖上游风险分级的完备性。

    The deep-copy contract is intentional: output handling must never replace
    the original text held by storage or by another caller sharing the same
    in-memory object.
    """
    return _redact_value(capsule)


def redact_dict(data: dict[str, Any], in_place: bool = False) -> dict[str, Any]:
    """
    Recursively redact sensitive data from dictionary.

    Args:
        data: Dictionary that may contain sensitive data
        in_place: If True, modify dict in place; otherwise create copy

    Returns:
        Dictionary with sensitive data redacted

    字符串值经 ``redact_sensitive_text`` 处理，自动落在 issue #172 的 16KB
    长度闸之后（超大字符串走分段脱敏，耗时线性）。
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

    # Policy-rejected content is blocked from memory, including nested legacy
    # event payloads. Keep decision metadata but discard every content field.
    is_reject = (result.get('policy_result') == 'reject'
                  or result.get('guard', {}).get('policy_result') == 'reject')
    if is_reject:
        def strip_content(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: '[REDACTED - Policy Block]' if key == 'content' else strip_content(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [strip_content(item) for item in value]
            return value

        result = strip_content(result)

    return result
