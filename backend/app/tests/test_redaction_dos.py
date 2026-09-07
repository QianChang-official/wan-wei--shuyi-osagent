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

"""issue #172 regression tests: ReDoS + unbounded payload.

Covers four fixes:
1. redact_sensitive_text stays under ~1s on a 168KB worst-case (all-letter)
   input that previously took tens of seconds (quadratic regex backtracking).
2. Normal-URL credential redaction is character-identical to the old regex
   (http/https/ftp, multiple segments, no-credential URLs, Chinese context).
3. WorkflowRunIn.scenario / user_goal reject overlong input with HTTP 422.
4. The 16KB length gate is transparent: segmented processing yields the same
   result as whole-string processing on non-backtracking text (incl. a PEM
   block that spans several segment boundaries).
"""
import os
import re
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _client(tmp_path: Path, *, api_key: str = "test-key"):
    """Create test client with fresh app instance (same pattern as test_security_followup)."""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import importlib

    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod
    import backend.app.security.auth as auth_mod

    importlib.reload(auth_mod)
    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _build_safe_multiline_text() -> str:
    """Deterministic >16KB text that never triggers quadratic backtracking.

    Lines stay short (well under the segment cap) so the length-gate segments
    only on newline boundaries and no token is ever split. A synthetic PEM
    block is included whose body alone spans many segment boundaries, so the
    tail private-key pass is exercised.
    """
    import random

    rng = random.Random(7)  # deterministic body
    lines: list[str] = [
        "联系 mysql://root:toor@127.0.0.1:3306 同步数据到 postgres://etl:pw@10.0.0.1:5432/dw",
        "alice@example.com 与 bob@example.org 收件，手机 13812345678。",
        "password = s3cret-abc, api_key = k_12345x, Bearer eyJhbGciOiJIUzI1NiJ9.abc.def",
        "-----BEGIN RSA PRIVATE KEY-----",
    ]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    body = "".join(rng.choice(alphabet) for _ in range(64 * 40))  # ~2.5KB across segments
    lines.extend(body[i:i + 64] for i in range(0, len(body), 64))
    lines.append("-----END RSA PRIVATE KEY-----")
    filler = "模块生成长文本载荷，包含正常长句与换行、无回溯风险。" * 3
    lines.extend(f"[{i}] {filler}" for i in range(300))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 1. performance: 168KB worst-case stays linear
# --------------------------------------------------------------------------
def test_redact_sensitive_text_168kb_is_fast():
    from backend.app.security.redaction import redact_sensitive_text

    # Pure-letter text with no "://" was the O(n²) killer: the URL regex tried
    # every start offset and backtracked to the end of input on each one.
    text = "a" * (168 * 1024)
    start = time.monotonic()
    result = redact_sensitive_text(text)
    elapsed = time.monotonic() - start

    # Nothing to redact in all-'a' input, and the result must be returned intact.
    assert result == text
    # Spec target is <1s; assert at 3s for a 3x safety margin on slow CI.
    assert elapsed < 3.0, f"168KB redaction took {elapsed:.3f}s (expected < 3s)"


def test_redact_audit_payload_large_value_is_fast():
    from backend.app.security.redaction import redact_audit_payload

    payload = {"level": "info", "content": "a" * (168 * 1024)}
    start = time.monotonic()
    result = redact_audit_payload(payload)
    elapsed = time.monotonic() - start

    assert result["content"] == payload["content"]
    assert elapsed < 3.0, f"168KB audit payload redaction took {elapsed:.3f}s (expected < 3s)"


# --------------------------------------------------------------------------
# 2. normal-URL redaction is identical to the old regex
# --------------------------------------------------------------------------
def test_url_credential_redaction_matches_old_regex(monkeypatch):
    from backend.app.security import redaction

    old_url_re = re.compile(
        r"([a-z][a-z0-9+.-]*://[^/:\s]+:)([^@\s]+)(@)", re.IGNORECASE
    )
    old_replacement = r"\1***REDACTED***\3"

    corpus = [
        "http://user:pass@example.com/path",
        "https://alice:s3cr3t@api.example.com/v1/models",
        "postgres://etl:pw@10.0.0.1:5432/dw",
        "mysql://root:toor@127.0.0.1:3306/app",
        "ftp://ftpuser:ftppass@ftp.example.com/file.txt",
        "先连 http://a:b@c.example.net:8080/x 再连 https://u:p@d.example.org/y/z?q=1",
        "https://no-cred.example.com/plain 无凭据 URL 不应被改写",
        "邮件 alice@example.com，无 URL。",
        "请把 mysql://root:toor@127.0.0.1:3306 的数据同步到 postgres://etl:pw@10.0.0.1:5432/dw",
    ]

    new_results = [redaction.redact_sensitive_text(item) for item in corpus]

    # Swap only the URL credential rule back to the old regex and re-run.
    patched = []
    for pattern, replacement in redaction._PATTERNS:
        if pattern is redaction._URL_CREDENTIAL_RE:
            patched.append((old_url_re, old_replacement))
        else:
            patched.append((pattern, replacement))
    monkeypatch.setattr(redaction, "_PATTERNS", patched)
    old_results = [redaction.redact_sensitive_text(item) for item in corpus]

    assert new_results == old_results
    # Concrete expectations lock the exact output shape.
    assert new_results[0] == "http://user:***REDACTED***@example.com/path"
    assert new_results[2] == "postgres://etl:***REDACTED***@10.0.0.1:5432/dw"
    assert new_results[5] == (
        "先连 http://a:***REDACTED***@c.example.net:8080/x "
        "再连 https://u:***REDACTED***@d.example.org/y/z?q=1"
    )
    assert new_results[6] == "https://no-cred.example.com/plain 无凭据 URL 不应被改写"


# --------------------------------------------------------------------------
# 3. WorkflowRunIn overlong scenario / user_goal -> 422
# --------------------------------------------------------------------------
def test_workflow_run_in_rejects_overlong_fields():
    from pydantic import ValidationError

    from backend.app.security.input_limits import MAX_GOAL_LENGTH
    from backend.app.workflow.service import WorkflowRunIn

    # boundary (== limit) is accepted
    ok = WorkflowRunIn(scenario="s" * MAX_GOAL_LENGTH, user_goal="g" * MAX_GOAL_LENGTH)
    assert len(ok.scenario) == MAX_GOAL_LENGTH
    assert len(ok.user_goal) == MAX_GOAL_LENGTH

    with pytest.raises(ValidationError, match="scenario"):
        WorkflowRunIn(scenario="x" * (MAX_GOAL_LENGTH + 1))
    with pytest.raises(ValidationError, match="user_goal"):
        WorkflowRunIn(user_goal="y" * (MAX_GOAL_LENGTH + 1))


def test_workflow_endpoints_return_422_for_overlong_input(tmp_path):
    from backend.app.security.input_limits import MAX_GOAL_LENGTH
    from backend.app.workflow.persistence import init_workflow_persistence

    client = _client(tmp_path, api_key="test-key")
    init_workflow_persistence()
    headers = {"X-API-Key": "test-key"}

    body = {
        "scenario": "weekly_report_preference_learning",
        "user_goal": "生成本周项目周报。",
        "include_model_gateway": True,
        "include_forgetting": True,
        "dry_run": True,
    }
    long_scenario = dict(body, scenario="x" * (MAX_GOAL_LENGTH + 1))
    long_goal = dict(body, user_goal="y" * (MAX_GOAL_LENGTH + 1))

    for endpoint in ("/workflow/runs", "/workflow/run-dry-run"):
        assert client.post(endpoint, json=long_scenario, headers=headers).status_code == 422
        assert client.post(endpoint, json=long_goal, headers=headers).status_code == 422


# --------------------------------------------------------------------------
# 4. length gate is transparent: segmented == whole for safe text
# --------------------------------------------------------------------------
def test_large_text_segmented_matches_whole_processing(monkeypatch):
    from backend.app.security import redaction

    text = _build_safe_multiline_text()
    assert len(text) > redaction._LARGE_TEXT_THRESHOLD  # default call is the segmented path

    segmented = redaction.redact_sensitive_text(text)

    # Force the whole-string path by raising the gate above the input size.
    monkeypatch.setattr(redaction, "_LARGE_TEXT_THRESHOLD", len(text) + 1)
    whole = redaction.redact_sensitive_text(text)

    assert segmented == whole
    # The markers prove both paths actually redacted real content.
    assert "***PRIVATE_KEY_REDACTED***" in segmented
    assert "[REDACTED_EMAIL]" in segmented
    assert "***REDACTED***" in segmented


# --------------------------------------------------------------------------
# 5. cross-boundary tokens: segmentation must not split a sensitive token in
#    half and leak it (cross-review finding). The final whole-string re-pass
#    reassembles any token severed at a hard cut point.
# --------------------------------------------------------------------------
def _build_text_with_token_at_cut(token: str) -> str:
    """Place `token` so it straddles the first 1024-char hard-cut boundary.

    No newlines for 3KB => the segmenter falls back to fixed-size cuts at
    offsets 1024, 2048, ... We position the token so its middle sits exactly
    on the 1024 offset: both halves alone fail to match any pattern.
    """
    from backend.app.security import redaction

    cut = redaction._REDACT_SEGMENT_CHARS  # 1024
    head_len = cut - len(token) // 2
    filler = "A" * head_len + token + "A" * 15360
    assert "\n" not in filler[: cut + len(token)]
    assert len(filler) > redaction._LARGE_TEXT_THRESHOLD, f"filler too short: {len(filler)}"
    return filler


@pytest.mark.parametrize(
    "token,marker",
    [
        # URL credential straddling the cut: user:password@ both halves alone
        # match neither _LINE_SCOPED_PATTERNS nor anything else.
        ("https://Us3r:p4ssw0rd@db.internal.example/root", "***REDACTED***"),
        # Bearer token split mid-value.
        ("Bearer AbCdEf1234567890QQQ", "***REDACTED***"),
        # password= assignment split after the colon.
        ("password: hunter2secretvalue", "***REDACTED***"),
    ],
)
def test_cross_boundary_tokens_are_still_redacted(token, marker):
    from backend.app.security import redaction

    text = _build_text_with_token_at_cut(token)
    out = redaction.redact_sensitive_text(text)
    assert token not in out, f"leaked across segment boundary: {token!r}"
    assert marker in out


def test_cross_boundary_url_credential_matches_whole_path():
    """Segmented output must equal whole-string output for a severed URL credential."""
    from backend.app.security import redaction

    token = "https://Us3r:p4ssw0rd@db.internal.example/root"
    text = _build_text_with_token_at_cut(token)
    assert redaction.redact_sensitive_text(text) == redaction._apply_patterns(text, redaction._PATTERNS)


def test_repass_is_idempotent_on_markers():
    """Re-running redaction on its own output must not nest or grow markers."""
    from backend.app.security import redaction

    text = _build_text_with_token_at_cut("https://Us3r:p4ssw0rd@db.internal.example/root")
    once = redaction.redact_sensitive_text(text)
    twice = redaction.redact_sensitive_text(once)
    assert once == twice
