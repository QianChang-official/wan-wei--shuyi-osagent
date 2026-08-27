"""perception/intake.py 单元测试。

覆盖:
1. 情绪检测(_detect_emotion)— 5 种基本情绪 + neutral
2. 意图分类(_classify_intent)— gratitude / complaint / question / share_emotion / neutral
3. 情绪增量(_emotion_delta)— 各情绪映射到 P-A-D 增量
4. 情绪→心情映射(_mood_for_emotion)
5. _clamp 边界行为
6. extract_entities 中文实体抽取(去重 + 至少 2 字符)
7. intake_perception 主流程 — 完整写库 + 失败注入

设计说明:
- _detect_emotion / _classify_intent 等私有函数的直接测试是**有意的**:
  它们是 intake_perception 的决策中枢,行为漂移(例如改词表、改增量)必须报警
- intake_perception 主流程用 conftest.isolated_db 隔离
- 失败注入:用不存在的 soul_id 触发兜底路径(不抛异常,走默认分支)
"""
from __future__ import annotations

import pytest

from backend.app.perception import intake


# ---------------------------------------------------------------------------
# _detect_emotion — 5 种情绪 + neutral
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("今天好开心", "joy"),
        ("我非常高兴能看到你", "joy"),
        ("太让人兴奋了", "joy"),
        ("我很难过", "sadness"),
        ("这事儿让人沮丧", "sadness"),
        ("太让人生气", "anger"),
        ("真让人恼火", "anger"),
        ("我好害怕", "fear"),
        ("这事儿让我焦虑", "fear"),
        ("谢谢你", "gratitude"),
        ("多谢提醒", "gratitude"),
        ("今天天气不错", "neutral"),
        ("我想问一下问题", "neutral"),
    ],
)
def test_detect_emotion(text, expected):
    assert intake._detect_emotion(text) == expected


# ---------------------------------------------------------------------------
# _classify_intent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("谢谢你的帮助", "gratitude"),
        ("这个功能太差了", "complaint"),
        ("我很不满意", "complaint"),
        ("为什么会这样", "question"),
        ("怎么用这个功能?", "question"),
        ("我今天心情不太好", "share_emotion"),
        ("我感觉很疲惫", "share_emotion"),
        ("帮我查一下天气", "neutral"),
    ],
)
def test_classify_intent(text, expected):
    assert intake._classify_intent(text) == expected


# ---------------------------------------------------------------------------
# _emotion_delta — 增量必须是数值,且符号方向正确
# ---------------------------------------------------------------------------


def test_emotion_delta_joy_positive_pleasure():
    delta = intake._emotion_delta("joy")
    assert delta["pleasure"] > 0
    assert -1.0 <= delta["arousal"] <= 1.0
    assert -1.0 <= delta["dominance"] <= 1.0


def test_emotion_delta_anger_negative_pleasure():
    delta = intake._emotion_delta("anger")
    assert delta["pleasure"] < 0


def test_emotion_delta_unknown_falls_back_to_neutral():
    delta = intake._emotion_delta("unknown_emotion_xyz")
    assert delta == {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0}


# ---------------------------------------------------------------------------
# _mood_for_emotion
# ---------------------------------------------------------------------------


def test_mood_for_known_emotions():
    assert intake._mood_for_emotion("joy") == "happy"
    assert intake._mood_for_emotion("sadness") == "sad"
    assert intake._mood_for_emotion("anger") == "irritated"
    assert intake._mood_for_emotion("fear") == "anxious"
    assert intake._mood_for_emotion("gratitude") == "content"
    assert intake._mood_for_emotion("neutral") == "calm"


def test_mood_for_unknown_defaults_calm():
    assert intake._mood_for_emotion("unknown") == "calm"


# ---------------------------------------------------------------------------
# _clamp 边界
# ---------------------------------------------------------------------------


def test_clamp_within_range():
    assert intake._clamp(0.5) == 0.5


def test_clamp_below_min():
    assert intake._clamp(-0.5) == 0.0


def test_clamp_above_max():
    assert intake._clamp(1.5) == 1.0


def test_clamp_custom_range():
    assert intake._clamp(5.0, min_val=0.0, max_val=10.0) == 5.0


# ---------------------------------------------------------------------------
# extract_entities — 中文实体抽取
# ---------------------------------------------------------------------------


def test_extract_entities_basic():
    """中文 + 英文混排时,正则会按「中文连续段」切分,英文被丢弃。"""
    entities = intake.extract_entities("我喜欢用Python写代码")
    # 实测行为:[\u4e00-\u9fff]{2,} 贪婪匹配,「Python」不是中文被丢弃,
    # 「我喜欢用」和「写代码」是两段独立中文,各自成实体
    assert entities == ['我喜欢用', '写代码']


def test_extract_entities_dedupes():
    """同一段中文重复出现时,结果只保留第一次。

    注意:正则 `[\u4e00-\u9fff]{2,}` 对「北京北京」会一次性匹配为「北京北京」
    而不是拆成两个「北京」。要触发 dedup,必须用「中文-非中文-中文」结构。
    """
    entities = intake.extract_entities("北京,北京,上海,上海")
    # 「,」不是中文,所以「北京」「北京」「上海」「上海」是 4 个独立匹配
    # dedup 后应该只剩 ['北京', '上海']
    assert entities == ['北京', '上海']


def test_extract_entities_min_two_chars():
    entities = intake.extract_entities("我爱北京天安门")
    # 至少包含一个 2+ 字符的中文短语
    assert all(len(e) >= 2 for e in entities)


def test_extract_entities_empty():
    assert intake.extract_entities("") == []


def test_extract_entities_english_only():
    # 纯英文不应命中中文正则
    entities = intake.extract_entities("hello world")
    assert entities == []


# ---------------------------------------------------------------------------
# intake_perception — 主流程(integration)
# ---------------------------------------------------------------------------


def test_intake_perception_happy_path(isolated_db):
    """主流程:写入一条对话,影响 affect_state 并写 conversation_turns + memory_capsules_v2。"""
    from backend.app.db import get_conn

    conn = get_conn()
    # 在 soul_persona 里注册一个测试 soul(外键约束要求)
    conn.execute(
        """
        INSERT OR IGNORE INTO soul_persona(soul_id, owner_id, name, created_at, updated_at)
        VALUES('test-soul-001', 'test-owner', '测试灵魂', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    result = intake.intake_perception(
        soul_id='test-soul-001',
        role='user',
        content='我今天好开心',
        used_capsule_ids=[],
        owner_id='test-owner',
    )

    # 返回结构必须包含 affect 前后对比
    assert 'affect_before' in result
    assert 'affect_after' in result
    assert 'emotion_detected' in result
    assert result['emotion_detected'] == 'joy'
    # joy 应该让 pleasure 增加
    assert result['affect_after']['pleasure'] >= result['affect_before']['pleasure']

    # 验证 affect_state 落库
    row = conn.execute(
        "SELECT pleasure, arousal, dominance, current_mood FROM affect_state WHERE soul_id=?",
        ('test-soul-001',),
    ).fetchone()
    assert row is not None
    assert row['current_mood'] == 'happy'


def test_intake_perception_negative_emotion(isolated_db):
    """负面情绪应该让 pleasure 下降。"""
    from backend.app.db import get_conn

    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO soul_persona(soul_id, owner_id, name, created_at, updated_at)
        VALUES('test-soul-002', 'test-owner', '测试', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    # 先注入一个初始 affect_state(pleasure=0.5)
    conn.execute(
        """
        INSERT OR REPLACE INTO affect_state(soul_id, pleasure, arousal, dominance, current_mood, mood_intensity, updated_at)
        VALUES('test-soul-002', 0.5, 0.5, 0.5, 'calm', 0.5, '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    result = intake.intake_perception(
        soul_id='test-soul-002',
        role='user',
        content='我很难过',
        used_capsule_ids=[],
        owner_id='test-owner',
    )

    assert result['emotion_detected'] == 'sadness'
    # pleasure 应该下降
    assert result['affect_after']['pleasure'] < result['affect_before']['pleasure']


def test_intake_perception_idempotent_turn_id(isolated_db):
    """turn_id 必须是唯一的:连续两次调用产生不同 turn_id。"""
    from backend.app.db import get_conn

    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO soul_persona(soul_id, owner_id, name, created_at, updated_at)
        VALUES('test-soul-003', 'test-owner', '测试', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    r1 = intake.intake_perception(soul_id='test-soul-003', role='user', content='开心', used_capsule_ids=[], owner_id='test-owner')
    r2 = intake.intake_perception(soul_id='test-soul-003', role='user', content='开心', used_capsule_ids=[], owner_id='test-owner')

    # 真实断言:两次调用必须产生不同的 turn_id
    # (intake.py:118 用 uuid4 生成,撞 id 就是真 bug)
    assert 'turn_id' in r1, 'intake_perception 返回值必须含 turn_id'
    assert 'turn_id' in r2, 'intake_perception 返回值必须含 turn_id'
    assert r1['turn_id'] != r2['turn_id'], \
        f'turn_id 冲突: r1={r1["turn_id"]} r2={r2["turn_id"]}'
    assert r1['turn_id'].startswith('turn_')
    assert r2['turn_id'].startswith('turn_')

    # 同时验证 conversation_turns 表写了 2 条
    # (如果 intake_perception 改为不写表,这条会暴露契约漂移)
    rows = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversation_turns WHERE soul_id='test-soul-003'"
    ).fetchone()
    assert rows['cnt'] == 2, \
        f'conversation_turns 应写入 2 条记录,实际 {rows["cnt"]} 条'


# ---------------------------------------------------------------------------
# 失败注入
# ---------------------------------------------------------------------------


def test_intake_perception_with_nonexistent_soul_uses_default_path(isolated_db):
    """soul_id 不存在时不应抛异常,应该走默认 affect 初始化路径。

    区分两条路径:
    - 默认初始化路径(intake.py:144-151): affect_before = {pleasure:0.5, arousal:0.4, dominance:0.5, current_mood:'calm', mood_intensity:0.3}
    - 异常兜底路径(intake.py:266-275): affect_before = {} / affect_after = {}

    只断言 'affect_before' in result 不够 — 兜底路径也有这两个键。
    必须断言**默认值内容**,才能区分「真的走了默认分支」与「崩溃兜底」。
    """
    result = intake.intake_perception(
        soul_id='nonexistent-soul-xyz',
        role='user',
        content='测试',
        used_capsule_ids=[],
    )
    # 不应抛异常,且应该返回结构化的结果
    assert 'affect_before' in result
    assert 'affect_after' in result

    # 关键:区分「默认初始化」与「异常兜底」
    # 异常兜底的 affect_before 是 {} — 真走了默认分支应该有 5 个字段
    assert result['affect_before'] != {}, \
        f'走了异常兜底路径,不是默认初始化: {result}'
    assert result['affect_before']['current_mood'] == 'calm'
    assert result['affect_before']['pleasure'] == 0.5
    assert result['affect_before']['arousal'] == 0.4
    assert result['affect_before']['dominance'] == 0.5
    assert result['affect_before']['mood_intensity'] == 0.3


def test_intake_perception_empty_content(isolated_db):
    """空 content 应该走 neutral 分支,不抛异常。"""
    result = intake.intake_perception(
        soul_id='any-soul',
        role='user',
        content='',
        used_capsule_ids=[],
    )
    assert result['emotion_detected'] == 'neutral'
