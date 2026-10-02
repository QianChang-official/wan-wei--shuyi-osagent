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

"""JSON serialization must not turn a rejected credential into allowed memory."""
import json

import pytest

from backend.app.memory_runtime.policy_gate import evaluate_policy


@pytest.mark.parametrize("key", ["token", "password", "api_key", "api-key", "secret"])
@pytest.mark.parametrize("nested", [False, True])
def test_quoted_json_credential_assignment_is_rejected(key, nested):
    content = {key: "synthetic-credential-value"}
    if nested:
        content = {"context": content}
    assert evaluate_policy(text=json.dumps(content))["policy_result"] == "reject"


@pytest.mark.parametrize("content", [
    {"token_count": 42},
    {"tokenizer": "unicode"},
    {"topic": "token renewal policy"},
])
def test_token_related_noncredential_fields_remain_allowed(content):
    assert evaluate_policy(text=json.dumps(content))["policy_result"] == "allow"


def test_rejected_json_token_is_not_stored_or_indexed(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_API_KEY", "json-policy-synthetic-test-key-only-20261002")
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    from backend.app.db import get_conn
    from backend.app.memory_runtime.capsule_store import write_capsule

    result = write_capsule(memory_class="knowledge", content={"token": "synthetic-credential-value"})
    assert result["governance"]["policy_result"] == "reject"
    assert "content" not in result
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM memory_capsules_v2").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM memory_capsules_v2_fts").fetchone()[0] == 0
