from .db import get_conn


def main():
    conn = get_conn(); cur = conn.cursor()
    cur.executescript("""
    -- legacy v0.2 tables (kept for backward compatibility)
    CREATE TABLE IF NOT EXISTS memory_events(event_id TEXT PRIMARY KEY, source_type TEXT, scene TEXT, content TEXT, quality_score REAL, sensitivity_level TEXT, trust_score REAL, created_at TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(event_id, content);
    CREATE TABLE IF NOT EXISTS memory_capsules(capsule_id TEXT PRIMARY KEY, memory_type TEXT, payload TEXT, lifecycle TEXT, trust_score REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS audit_logs(audit_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, created_at TEXT);

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
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memory_reflections(reflection_id TEXT PRIMARY KEY, task_id TEXT, payload TEXT, created_at TEXT);
    """)
    conn.commit(); print('initialized')


if __name__ == '__main__':
    main()
