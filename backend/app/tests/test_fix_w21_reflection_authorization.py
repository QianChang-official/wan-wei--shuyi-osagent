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

"""issue #117：/memory/v2/reflection 自我申报校验回归测试。

攻击面（修复前实测）：
- 单个 POST 携带全部胶囊 id 即可把整个记忆库 deprecate（列表无上限、id 不校验）；
- 不存在的 id 被静默接受（200 + 空 actions）；
- helpful/misleading 与「本次任务真实召回集合」无任何交叉校验，
  经济账本的 utility/ROI 全靠调用方自我申报。

修复口径：
- schema 层：helpful/misleading/memory_used max_length=50（与 ForgetConfirmIn 对齐），
  task_id 必填且限长；
- 端点层：id 必须存在（422 reflection_unknown_capsule），
  且必须在本实例真实召回过（422 reflection_capsule_not_recalled，
  memory_ledger op_type=retrieve 为授权依据）。
"""

import pytest
from fastapi import HTTPException

from backend.app.app_runtime import v2_reflection, v2_search
from backend.app.memory_runtime.capsule_store import write_capsule
from backend.app.schemas import ReflectionIn


def _write(text: str, soul_id: str | None = None) -> str:
    capsule = write_capsule(
        memory_class="knowledge",
        content={"text": text},
        provenance={"source": "test", "soul_id": soul_id},
        source_type="user_input",
        write_intent="explicit",
        soul_id=soul_id,
    )
    return capsule["capsule_id"]


def _recall(q: str, soul_id: str | None = None) -> None:
    """触发一次真实检索，让命中胶囊在 memory_ledger 留下 retrieve 凭证。"""
    v2_search(q=q, top_k=5, high_risk=False, soul_id=soul_id)


def test_reflection_rejects_unknown_capsule_ids(isolated_db):
    cap_id = _write("真实存在的记忆 alpha")
    _recall("alpha")

    with pytest.raises(HTTPException) as exc_info:
        v2_reflection(
            ReflectionIn(
                task_id="task_unknown",
                helpful_memories=[cap_id, "cap_ghost_never_existed"],
            )
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "reflection_unknown_capsule"
    assert "cap_ghost_never_existed" in exc_info.value.detail["capsule_ids"]


def test_reflection_rejects_never_recalled_capsule(isolated_db):
    """id 真实存在但从未被召回 → 422（防止凭空 deprecate 全库）。"""
    cap_id = _write("从未被检索过的记忆 bravo")

    with pytest.raises(HTTPException) as exc_info:
        v2_reflection(
            ReflectionIn(task_id="task_norecall", misleading_memories=[cap_id])
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "reflection_capsule_not_recalled"

    # 生命周期必须保持不变
    from backend.app.memory_runtime.capsule_store import get_capsule

    assert get_capsule(cap_id)["state"]["lifecycle"] == "active"


def test_reflection_accepts_recalled_capsule(isolated_db):
    """正常流程：写入 → 检索命中 → 反思结算，全链路仍然可用。"""
    cap_id = _write("周报写作模板 charlie")
    _recall("周报")

    result = v2_reflection(
        ReflectionIn(task_id="task_ok", helpful_memories=[cap_id])
    )
    actions = {a["action"] for a in result["evolution_actions"]}
    assert "reinforce" in actions


def test_reflection_schema_caps_list_length():
    """issue #117 根因之一：单 POST 无界 deprecate。schema 层封顶 50。"""
    with pytest.raises(Exception):
        ReflectionIn(task_id="task_bulk", misleading_memories=[f"cap_{i}" for i in range(51)])


def test_reflection_schema_requires_task_id():
    with pytest.raises(Exception):
        ReflectionIn(task_id="")


def test_dream_schema_matches_reflection_caps():
    """SoulDreamIn 与 ReflectionIn 同口径（同一自我申报面）。"""
    from backend.app.schemas import SoulDreamIn

    with pytest.raises(Exception):
        SoulDreamIn(
            soul_id="soul_x",
            task_id="task_dream",
            helpful_memories=[f"cap_{i}" for i in range(51)],
        )
