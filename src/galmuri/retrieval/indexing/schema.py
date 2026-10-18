"""Projection snapshots, ownership and independent remote cleanup state."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_configs (
 app TEXT PRIMARY KEY, fingerprint TEXT, revision TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_heads (
 app TEXT NOT NULL, key TEXT NOT NULL, build TEXT NOT NULL,
 PRIMARY KEY(app,key)
);
CREATE TABLE IF NOT EXISTS semantic_builds (
 id TEXT PRIMARY KEY, app TEXT NOT NULL, key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, store_identity TEXT NOT NULL,
 revision TEXT NOT NULL, snapshot TEXT NOT NULL,
 body TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'EMBEDDING',
 attempts INTEGER NOT NULL DEFAULT 0, available DOUBLE PRECISION NOT NULL,
 token TEXT, worker TEXT, lease_until DOUBLE PRECISION, prepared TEXT,
 error TEXT, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS semantic_ready ON semantic_builds(state,available);
CREATE TABLE IF NOT EXISTS semantic_artifacts (
 app TEXT NOT NULL, key TEXT NOT NULL, identity TEXT NOT NULL,
 prepared TEXT NOT NULL, created DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(app,key,identity)
);
CREATE TABLE IF NOT EXISTS semantic_cleanup (
 build TEXT PRIMARY KEY, app TEXT NOT NULL, fingerprint TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'READY', attempts INTEGER NOT NULL DEFAULT 0,
 available DOUBLE PRECISION NOT NULL, token TEXT, lease_until DOUBLE PRECISION, error TEXT
);
CREATE TABLE IF NOT EXISTS semantic_requests (
 request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL,
 created DOUBLE PRECISION NOT NULL
);
"""
