from .db import get_conn
from .utils.datetime_utils import utc_now_iso_compact


VECTOR_GENERATION_FENCING_MIGRATION = "vector_generation_fencing_v1"
SOUL_OWNERSHIP_MIGRATION = "soul_owner_scope_v1"
TIER_UNIFICATION_MIGRATION = "memory_tier_unify_v1"
# Legacy migration name from the first #56 MVP iteration. It added a redundant
# ``tier`` column next to the pre-existing ``memory_tier`` column; kept here so
# the unification migration can detect and fold back databases that applied it.
LEGACY_TIER_COLUMN_MIGRATION = "memory_tier_column_v1"


def migrate_legacy_vector_refs(conn) -> bool:
    """Fence pre-generation vector attempts without reusing their native IDs."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_schema_migrations(
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    if conn.execute(
        "SELECT 1 FROM memory_schema_migrations WHERE name=?",
        (VECTOR_GENERATION_FENCING_MIGRATION,),
    ).fetchone():
        return False

    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT 1 FROM memory_schema_migrations WHERE name=?",
            (VECTOR_GENERATION_FENCING_MIGRATION,),
        ).fetchone():
            conn.commit()
            return False

        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_vector_refs)")}
        if "attempt_generation" not in columns:
            conn.execute(
                "ALTER TABLE memory_vector_refs "
                "ADD COLUMN attempt_generation INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_vector_id_allocations(vector_id,allocated_at)
            SELECT vector_id,created_at FROM memory_vector_refs
            """,
        )
        rows = conn.execute(
            """
            SELECT vector_id,capsule_id,provider,collection_name,status,
                   attempt_generation,created_at,updated_at
            FROM memory_vector_refs
            WHERE attempt_generation=0
              AND status IN ('allocated','indexing','index_failed','deleted')
            ORDER BY vector_id ASC
            """
        ).fetchall()
        for row in rows:
            timestamp = utc_now_iso_compact()
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_vector_tombstones(
                    provider,collection_name,vector_id,status,checked_at,created_at,updated_at
                ) VALUES (?,?,?,'delete_pending',NULL,?,?)
                """,
                (row["provider"], row["collection_name"], row["vector_id"], timestamp, timestamp),
            )
            if row["status"] not in {"allocated", "indexing", "index_failed"}:
                continue
            allocation = conn.execute(
                "INSERT INTO memory_vector_id_allocations(allocated_at) VALUES (?)",
                (timestamp,),
            )
            conn.execute(
                """
                UPDATE memory_vector_refs
                SET vector_id=?,status='allocated',model_name=NULL,dimension=NULL,updated_at=?
                WHERE vector_id=? AND attempt_generation=0 AND status=?
                """,
                (allocation.lastrowid, timestamp, row["vector_id"], row["status"]),
            )
        conn.execute(
            "INSERT INTO memory_schema_migrations(name,applied_at) VALUES (?,?)",
            (VECTOR_GENERATION_FENCING_MIGRATION, utc_now_iso_compact()),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def main():
    conn = get_conn(); cur = conn.cursor()
    cur.executescript("""
    -- legacy v0.2 tables (kept for backward compatibility)
    CREATE TABLE IF NOT EXISTS memory_events(event_id TEXT PRIMARY KEY, source_type TEXT, scene TEXT, content TEXT, quality_score REAL, sensitivity_level TEXT, trust_score REAL, created_at TEXT, soul_id TEXT, owner_id TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(event_id, content);
    CREATE TABLE IF NOT EXISTS memory_capsules(capsule_id TEXT PRIMARY KEY, memory_type TEXT, payload TEXT, lifecycle TEXT, trust_score REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS memory_event_capsules(event_id TEXT PRIMARY KEY, capsule_id TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS audit_logs(audit_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS memory_forget_requests(
        forget_request_id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        candidates TEXT NOT NULL,
        status TEXT NOT NULL,
        result TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- v0.6 MemoryOps runtime tables (MemoryCapsule 2.0)
    CREATE TABLE IF NOT EXISTS memory_capsules_v2(
        capsule_id TEXT PRIMARY KEY,
        memory_class TEXT,
        content TEXT,
        source_events TEXT,
        provenance TEXT,
        governance TEXT,
        state TEXT,
        production_context TEXT,
        alignment_metadata TEXT,
        affective_metadata TEXT,
        relation_edges TEXT,
        index_refs TEXT,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_capsules_v2_fts USING fts5(capsule_id, text);
    CREATE TABLE IF NOT EXISTS memory_vector_refs(
        vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
        capsule_id TEXT NOT NULL UNIQUE,
        provider TEXT NOT NULL,
        collection_name TEXT NOT NULL,
        model_name TEXT,
        dimension INTEGER,
        status TEXT NOT NULL,
        attempt_generation INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memory_vector_id_allocations(
        vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
        allocated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memory_vector_tombstones(
        provider TEXT NOT NULL,
        collection_name TEXT NOT NULL,
        vector_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        checked_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(provider, collection_name, vector_id)
    );
    CREATE TABLE IF NOT EXISTS memory_vector_delete_claims(
        provider TEXT NOT NULL,
        collection_name TEXT NOT NULL,
        vector_id INTEGER NOT NULL,
        claim_token TEXT NOT NULL,
        claimed_at TEXT NOT NULL,
        PRIMARY KEY(provider, collection_name, vector_id)
    );
    CREATE TABLE IF NOT EXISTS memory_schema_migrations(
        name TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memory_reflections(reflection_id TEXT PRIMARY KEY, task_id TEXT, payload TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS model_gateway_configs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL UNIQUE,
        api_base TEXT NOT NULL,
        api_key_encrypted TEXT,
        model TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- v0.11 Soul Awakening: new tables for soul injection, affect, dream, reflection
    CREATE TABLE IF NOT EXISTS soul_persona(
        soul_id TEXT PRIMARY KEY,
        owner_id TEXT,
        name TEXT NOT NULL DEFAULT '枢忆',
        core_traits TEXT NOT NULL DEFAULT '["严谨", "有温度", "会自省"]',
        voice TEXT DEFAULT '专业但不冷漠，偶尔幽默',
        soul_values TEXT DEFAULT '["诚实", "成长", "守护用户"]',
        self_narrative TEXT DEFAULT '我是枢忆，一个有记忆和情感的AI助手，我在持续学习和成长。',
        baseline_pleasure REAL DEFAULT 0.6,
        baseline_arousal REAL DEFAULT 0.4,
        baseline_dominance REAL DEFAULT 0.5,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS affect_state(
        soul_id TEXT PRIMARY KEY,
        pleasure REAL DEFAULT 0.5,
        arousal REAL DEFAULT 0.4,
        dominance REAL DEFAULT 0.5,
        current_mood TEXT DEFAULT 'calm',
        mood_intensity REAL DEFAULT 0.3,
        updated_at TEXT,
        FOREIGN KEY(soul_id) REFERENCES soul_persona(soul_id)
    );
    CREATE TABLE IF NOT EXISTS affect_events(
        event_id TEXT PRIMARY KEY,
        soul_id TEXT NOT NULL,
        emotion TEXT NOT NULL,
        pleasure REAL,
        arousal REAL,
        dominance REAL,
        intensity REAL,
        trigger TEXT,
        bound_capsule_ids TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS dream_lock(
        soul_id TEXT PRIMARY KEY,
        pid TEXT,
        started_at TEXT,
        last_dream_at TEXT,
        last_dream_duration_ms INTEGER,
        last_dream_summary TEXT,
        FOREIGN KEY(soul_id) REFERENCES soul_persona(soul_id)
    );
    CREATE TABLE IF NOT EXISTS dream_artifacts(
        dream_id TEXT PRIMARY KEY,
        soul_id TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        phase_stats TEXT,
        new_edges INTEGER DEFAULT 0,
        merged_capsules INTEGER DEFAULT 0,
        pruned_capsules INTEGER DEFAULT 0,
        synthesized_insights INTEGER DEFAULT 0,
        emotional_events_digested INTEGER DEFAULT 0,
        FOREIGN KEY(soul_id) REFERENCES soul_persona(soul_id)
    );
    CREATE TABLE IF NOT EXISTS reflection_log(
        reflection_id TEXT PRIMARY KEY,
        soul_id TEXT NOT NULL,
        task_id TEXT,
        failure_type TEXT,
        affect_before TEXT,
        affect_after TEXT,
        improvement_note TEXT,
        persona_delta TEXT,
        created_at TEXT,
        FOREIGN KEY(soul_id) REFERENCES soul_persona(soul_id)
    );
    CREATE TABLE IF NOT EXISTS conversation_turns(
        turn_id TEXT PRIMARY KEY,
        soul_id TEXT NOT NULL,
        role TEXT,
        content TEXT,
        emotion_detected TEXT,
        intent_classified TEXT,
        capsules_used TEXT,
        affect_before TEXT,
        affect_after TEXT,
        created_at TEXT,
        FOREIGN KEY(soul_id) REFERENCES soul_persona(soul_id)
    );
    """)
    migrate_legacy_vector_refs(conn)
    _migrate_soul_awakening(conn)
    _migrate_soul_ownership(conn)
    _migrate_tier_unification(conn)
    conn.commit(); print('initialized')


def _cleanup_orphan_soul_rows(conn) -> None:
    """一次性清理：删除 soul_persona 中不存在的 soul_id 遗留行。

    03-#10 启用 ``PRAGMA foreign_keys=ON`` 后新写入已无法产生孤儿行，
    但历史存量仍可能违反 FK。本函数幂等执行，通过先 DELETE 再 COUNT
    的方式把可能涉及的表全部扫一遍；清理量在每个表少量行时开销可忽略。
    """
    CLEANUP_NAME = "cleanup_orphan_soul_rows_v1"
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memory_schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    if conn.execute(
        "SELECT 1 FROM memory_schema_migrations WHERE name=?", (CLEANUP_NAME,)
    ).fetchone():
        return

    orphan_tables = [
        "affect_state",
        "affect_events",
        "dream_lock",
        "dream_artifacts",
        "reflection_log",
        "conversation_turns",
    ]
    total = 0
    for table in orphan_tables:
        # 表可能尚未创建（极老版本），用 IF EXISTS 风格避免报错
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue
        cur = conn.execute(
            f"DELETE FROM {table} WHERE soul_id NOT IN (SELECT soul_id FROM soul_persona)"
        )
        total += cur.rowcount

    conn.execute(
        "INSERT INTO memory_schema_migrations(name, applied_at) VALUES (?,?)",
        (CLEANUP_NAME, utc_now_iso_compact()),
    )
    conn.commit()
    if total:
        print(f"cleaned {total} orphan soul rows")


def _migrate_soul_awakening(conn) -> None:
    """Idempotent migration for v0.11 Soul Awakening schema changes."""
    MIGRATION_NAME = "soul_awakening_v11"
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memory_schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    if conn.execute(
        "SELECT 1 FROM memory_schema_migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone():
        return

    columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_capsules_v2)")}
    if "memory_tier" not in columns:
        conn.execute("ALTER TABLE memory_capsules_v2 ADD COLUMN memory_tier TEXT DEFAULT 'working'")
    if "emotional_weight" not in columns:
        conn.execute("ALTER TABLE memory_capsules_v2 ADD COLUMN emotional_weight REAL DEFAULT 0.0")
    if "created_in_dream" not in columns:
        conn.execute("ALTER TABLE memory_capsules_v2 ADD COLUMN created_in_dream INTEGER DEFAULT 0")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_affect_events_soul_created ON affect_events(soul_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_turns_soul_created ON conversation_turns(soul_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dream_artifacts_soul_started ON dream_artifacts(soul_id, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reflection_log_soul_created ON reflection_log(soul_id, created_at)"
    )

    # C5：在 FK ON 生效前已存在的历史孤儿行一次性清理（仅 soul 相关表）
    _cleanup_orphan_soul_rows(conn)

    # Seed default soul persona if none exists
    if not conn.execute("SELECT 1 FROM soul_persona LIMIT 1").fetchone():
        ts = utc_now_iso_compact()
        conn.execute(
            """INSERT INTO soul_persona(
                soul_id, name, core_traits, voice, soul_values, self_narrative,
                baseline_pleasure, baseline_arousal, baseline_dominance, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "soul_default",
                "枢忆",
                '["严谨", "有温度", "会自省"]',
                "专业但不冷漠，偶尔幽默",
                '["诚实", "成长", "守护用户"]',
                "我是枢忆，一个有记忆和情感的AI助手，我在持续学习和成长。",
                0.6, 0.4, 0.5, ts, ts,
            ),
        )
        conn.execute(
            """INSERT INTO affect_state(
                soul_id, pleasure, arousal, dominance, current_mood, mood_intensity, updated_at
            ) VALUES (?,?,?,?,?,?,?)""",
            ("soul_default", 0.5, 0.4, 0.5, "calm", 0.3, ts),
        )

    conn.execute(
        "INSERT INTO memory_schema_migrations(name, applied_at) VALUES (?,?)",
        (MIGRATION_NAME, utc_now_iso_compact()),
    )
    conn.commit()

    # B5 知识舱 schema（支持 FTS5 缺失时降级 LIKE）
    from .platform_api.knowledge import init_knowledge_schema
    init_knowledge_schema(conn)


def _migrate_soul_ownership(conn) -> None:
    """Add durable owner/soul scope while preserving legacy local data.

    Historical installations had one configured API key and globally scoped
    memories.  The migration assigns those rows to the actor derived from the
    currently configured key.  A missing capsule ``soul_id`` is attached to
    ``soul_default`` (or the only existing Soul) when that choice is
    unambiguous; otherwise it remains owner-scoped legacy data.
    """
    from .soul.ownership import configured_actor_id

    conn.execute(
        "CREATE TABLE IF NOT EXISTS memory_schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    if conn.execute(
        "SELECT 1 FROM memory_schema_migrations WHERE name=?",
        (SOUL_OWNERSHIP_MIGRATION,),
    ).fetchone():
        return

    owner_id = configured_actor_id()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT 1 FROM memory_schema_migrations WHERE name=?",
            (SOUL_OWNERSHIP_MIGRATION,),
        ).fetchone():
            conn.commit()
            return

        persona_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(soul_persona)")
        }
        if "owner_id" not in persona_columns:
            conn.execute("ALTER TABLE soul_persona ADD COLUMN owner_id TEXT")
        conn.execute(
            "UPDATE soul_persona SET owner_id=? WHERE owner_id IS NULL OR owner_id=''",
            (owner_id,),
        )

        default_row = conn.execute(
            "SELECT soul_id FROM soul_persona WHERE soul_id='soul_default' AND owner_id=?",
            (owner_id,),
        ).fetchone()
        if default_row is None:
            owned_rows = conn.execute(
                "SELECT soul_id FROM soul_persona WHERE owner_id=? ORDER BY created_at, soul_id LIMIT 2",
                (owner_id,),
            ).fetchall()
            default_soul_id = str(owned_rows[0]["soul_id"]) if len(owned_rows) == 1 else None
        else:
            default_soul_id = str(default_row["soul_id"])

        event_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(memory_events)")
        }
        if "soul_id" not in event_columns:
            conn.execute("ALTER TABLE memory_events ADD COLUMN soul_id TEXT")
        if "owner_id" not in event_columns:
            conn.execute("ALTER TABLE memory_events ADD COLUMN owner_id TEXT")
        conn.execute(
            "UPDATE memory_events SET owner_id=? WHERE owner_id IS NULL OR owner_id=''",
            (owner_id,),
        )
        if default_soul_id is not None:
            conn.execute(
                "UPDATE memory_events SET soul_id=? WHERE soul_id IS NULL OR soul_id=''",
                (default_soul_id,),
            )

        # Normalize malformed/empty historical provenance before adding scope.
        conn.execute(
            """
            UPDATE memory_capsules_v2
            SET provenance=CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END
            WHERE provenance IS NULL OR NOT json_valid(provenance)
            """
        )
        conn.execute(
            """
            UPDATE memory_capsules_v2
            SET provenance=json_set(
                provenance,
                '$.owner_id',
                COALESCE(
                    (SELECT persona.owner_id
                     FROM soul_persona AS persona
                     WHERE persona.soul_id=json_extract(memory_capsules_v2.provenance, '$.soul_id')),
                    ?
                )
            )
            WHERE json_extract(provenance, '$.owner_id') IS NULL
               OR json_extract(provenance, '$.owner_id')=''
            """,
            (owner_id,),
        )
        if default_soul_id is not None:
            conn.execute(
                """
                UPDATE memory_capsules_v2
                SET provenance=json_set(provenance, '$.soul_id', ?)
                WHERE (json_extract(provenance, '$.soul_id') IS NULL
                       OR json_extract(provenance, '$.soul_id')='')
                  AND json_extract(provenance, '$.owner_id')=?
                """,
                (default_soul_id, owner_id),
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_forget_request_scopes(
                forget_request_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                soul_id TEXT,
                FOREIGN KEY(forget_request_id)
                    REFERENCES memory_forget_requests(forget_request_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_forget_request_scopes(forget_request_id, owner_id, soul_id)
            SELECT forget_request_id, ?, ? FROM memory_forget_requests
            """,
            (owner_id, default_soul_id),
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_soul_persona_owner ON soul_persona(owner_id, soul_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_events_scope ON memory_events(owner_id, soul_id, created_at)"
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_capsules_v2_scope
            ON memory_capsules_v2(
                json_extract(provenance, '$.owner_id'),
                json_extract(provenance, '$.soul_id')
            )
            """
        )
        conn.execute(
            "INSERT INTO memory_schema_migrations(name, applied_at) VALUES (?,?)",
            (SOUL_OWNERSHIP_MIGRATION, utc_now_iso_compact()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _migrate_tier_unification(conn) -> None:
    """Unify tier storage on the pre-existing ``memory_tier`` column and create
    the tier-transition audit table (#56).

    Background:
    - ``memory_capsules_v2.memory_tier`` already exists (added by an earlier
      migration, default ``'working'``) and is the column ``write_capsule``
      populates on every insert.
    - The first #56 MVP iteration introduced a second, redundant ``tier``
      column (migration ``memory_tier_column_v1``). One copy of that migration
      also created ``idx_capsule_tier(tier, lifecycle)`` which references
      ``lifecycle`` — a JSON key inside the ``state`` column, not a real
      column — so it fails on a fresh database.

    This migration (``memory_tier_unify_v1``):
    1. If the legacy ``tier`` column exists, folds its non-default values into
       ``memory_tier`` and then drops the legacy column (SQLite >= 3.35; on
       older SQLite the column is left in place but simply unused).
    2. Drops the possibly mis-shaped ``idx_capsule_tier`` index and creates a
       correct one on ``memory_tier``.
    3. Creates ``tier_transition_log`` — the audit trail for every
       promote/demote, manual or automatic.

    对应 GitHub issue #56: 短期/中期记忆自动流转机制
    赛题要求(6): 兼容与记忆模块中短期、中期记忆间的数据流转
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memory_schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    if conn.execute(
        "SELECT 1 FROM memory_schema_migrations WHERE name=?",
        (TIER_UNIFICATION_MIGRATION,),
    ).fetchone():
        return

    try:
        conn.execute("BEGIN IMMEDIATE")

        # Double-check (race protection)
        if conn.execute(
            "SELECT 1 FROM memory_schema_migrations WHERE name=?",
            (TIER_UNIFICATION_MIGRATION,),
        ).fetchone():
            conn.commit()
            return

        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_capsules_v2)")}

        # 1. Fold the legacy ``tier`` column (if any) back into ``memory_tier``.
        if "tier" in columns:
            conn.execute(
                """
                UPDATE memory_capsules_v2
                SET memory_tier = tier
                WHERE tier IS NOT NULL AND tier != 'working'
                  AND (memory_tier IS NULL OR memory_tier = 'working')
                """
            )
            try:
                conn.execute("ALTER TABLE memory_capsules_v2 DROP COLUMN tier")
            except Exception:
                # SQLite < 3.35 has no DROP COLUMN; the column stays but is
                # no longer read or written by any code path.
                pass

        # 2. Replace the legacy index (wrongly shaped in the first MVP) with a
        #    correct one on the canonical column.
        conn.execute("DROP INDEX IF EXISTS idx_capsule_tier")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_capsules_v2_memory_tier "
            "ON memory_capsules_v2(memory_tier)"
        )

        # 3. Audit trail for tier transitions.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tier_transition_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capsule_id TEXT NOT NULL,
                from_tier TEXT NOT NULL,
                to_tier TEXT NOT NULL,
                reason TEXT,
                trigger_source TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tier_transition_capsule "
            "ON tier_transition_log(capsule_id, created_at)"
        )

        # Record migration
        conn.execute(
            "INSERT INTO memory_schema_migrations(name, applied_at) VALUES (?,?)",
            (TIER_UNIFICATION_MIGRATION, utc_now_iso_compact()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


if __name__ == '__main__':
    main()
