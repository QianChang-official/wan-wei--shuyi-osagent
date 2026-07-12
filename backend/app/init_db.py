from .db import get_conn
from .utils.datetime_utils import utc_now_iso_compact


VECTOR_GENERATION_FENCING_MIGRATION = "vector_generation_fencing_v1"


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
    CREATE TABLE IF NOT EXISTS memory_events(event_id TEXT PRIMARY KEY, source_type TEXT, scene TEXT, content TEXT, quality_score REAL, sensitivity_level TEXT, trust_score REAL, created_at TEXT);
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
    """)
    migrate_legacy_vector_refs(conn)
    conn.commit(); print('initialized')


if __name__ == '__main__':
    main()
