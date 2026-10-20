"""Default persistence schema, partitioned by lifecycle owner."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
 name TEXT PRIMARY KEY, revision TEXT NOT NULL, source_identity TEXT,
 paused INTEGER NOT NULL DEFAULT 0,
 checkpoint TEXT, next_collection DOUBLE PRECISION NOT NULL DEFAULT 0,
 collection_token TEXT, collection_until DOUBLE PRECISION,
 collection_state TEXT NOT NULL DEFAULT 'PLANNED',
 collection_error TEXT
);
CREATE TABLE IF NOT EXISTS source_refs (
 app TEXT NOT NULL, key TEXT NOT NULL, version TEXT NOT NULL, metadata TEXT NOT NULL,
 deleted INTEGER NOT NULL DEFAULT 0, acl_generation INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(app,key)
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, app TEXT NOT NULL, source_key TEXT NOT NULL, version TEXT NOT NULL,
 metadata TEXT NOT NULL, revision TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, available DOUBLE PRECISION NOT NULL,
 token TEXT, worker TEXT, lease_until DOUBLE PRECISION, acl_generation INTEGER,
 error TEXT, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ready_jobs ON jobs(state,available);
CREATE TABLE IF NOT EXISTS attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, number INTEGER NOT NULL,
 token TEXT NOT NULL, worker TEXT NOT NULL,
 started DOUBLE PRECISION NOT NULL, ended DOUBLE PRECISION,
 outcome TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, app TEXT NOT NULL,
 at DOUBLE PRECISION NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
 app TEXT NOT NULL, key TEXT NOT NULL, source_key TEXT NOT NULL, version TEXT NOT NULL,
 text TEXT NOT NULL, metadata TEXT NOT NULL, readers TEXT NOT NULL, writers TEXT NOT NULL,
 acl_override INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'ACTIVE',
 PRIMARY KEY(app,key)
);
CREATE INDEX IF NOT EXISTS document_source ON documents(app,source_key);
CREATE TABLE IF NOT EXISTS writes (
 id TEXT PRIMARY KEY, app TEXT NOT NULL, source_key TEXT NOT NULL,
 expected_version TEXT NOT NULL, revision TEXT, source_identity TEXT,
 state TEXT NOT NULL, error TEXT, created DOUBLE PRECISION NOT NULL
);
"""
