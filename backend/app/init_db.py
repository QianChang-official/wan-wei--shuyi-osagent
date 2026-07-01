from .db import get_conn

def main():
    conn=get_conn(); cur=conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS memory_events(event_id TEXT PRIMARY KEY, source_type TEXT, scene TEXT, content TEXT, quality_score REAL, sensitivity_level TEXT, trust_score REAL, created_at TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(event_id, content);
    CREATE TABLE IF NOT EXISTS memory_capsules(capsule_id TEXT PRIMARY KEY, memory_type TEXT, payload TEXT, lifecycle TEXT, trust_score REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS audit_logs(audit_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, created_at TEXT);
    """)
    conn.commit(); print('initialized')
if __name__=='__main__': main()
