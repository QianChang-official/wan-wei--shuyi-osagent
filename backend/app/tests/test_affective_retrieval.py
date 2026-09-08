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

"""
Affective-aware retrieval — retrieval.py 情感加权排序测试

验证闭环：emotion_memory 写入情感元数据（emotional_weight / affective_metadata）
后，检索排序公式确实按情感权重提升命中的优先级，而不是写完就丢。

v0.11.0 affective-retrieval
"""

from backend.app.memory_runtime import retrieval as rt
from backend.app.memory_runtime import capsule_store as cs
from backend.app.affect import emotion_memory as em


def _write(text):
    return cs.write_capsule(memory_class="knowledge", content={"text": text})["capsule_id"]


# ---------------------------------------------------------------------------
# _affective_score — 纯函数行为
# ---------------------------------------------------------------------------

def test_affective_score_prefers_explicit_weight():
    cap = {"emotional_weight": 0.8, "affective_metadata": {"mood_intensity": 0.2}}
    assert rt._affective_score(cap) == 0.8


def test_affective_score_falls_back_to_mood_intensity():
    cap = {"emotional_weight": 0.0, "affective_metadata": {"mood_intensity": 0.6}}
    assert rt._affective_score(cap) == 0.6


def test_affective_score_defaults_zero_when_no_affect():
    assert rt._affective_score({}) == 0.0
    assert rt._affective_score({"emotional_weight": None, "affective_metadata": None}) == 0.0


def test_affective_score_clamps_to_unit_interval():
    assert rt._affective_score({"emotional_weight": 1.7}) == 1.0
    assert rt._affective_score({"emotional_weight": -0.3}) == 0.0


def test_affective_score_ignores_garbage():
    assert rt._affective_score({"emotional_weight": "abc"}) == 0.0
    assert rt._affective_score({"affective_metadata": {"mood_intensity": "high"}}) == 0.0


# ---------------------------------------------------------------------------
# 集成：情感权重影响排序
# ---------------------------------------------------------------------------

def test_search_ranks_affective_capsule_first(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    # 两条内容几乎相同的记忆：语义/信任/置信完全一样，只有情感权重不同。
    low = _write("喵星人最喜欢在午后窗台晒太阳打盹")
    high = _write("喵星人最喜欢在午后窗台晒太阳打盹")
    em.apply_emotional_weight(high, 0.9)

    results = rt.search_capsules("喵星人午后晒太阳", top_k=5)
    ids = [r["capsule_id"] for r in results]

    assert high in ids and low in ids
    # 情感权重高的必须排前面——这就是 affective 项存在的意义。
    assert ids.index(high) < ids.index(low)
    # 观测字段透出情感分。
    top = next(r for r in results if r["capsule_id"] == high)
    assert top["retrieval_affective"] == 0.9


def test_search_without_affect_keeps_previous_behavior(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    # 未绑定任何情感数据的 capsule：affective 项为 0，不应破坏既有检索。
    _write("周报应使用正式语气和三段式结构")
    results = rt.search_capsules("周报", top_k=5)
    assert len(results) >= 1
    assert all(r["retrieval_affective"] == 0.0 for r in results)
