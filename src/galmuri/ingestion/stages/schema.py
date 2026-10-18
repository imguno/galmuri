"""Accepted raw inputs and parsed output stay private to the coordinator."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
 job TEXT PRIMARY KEY REFERENCES jobs(id), app TEXT NOT NULL,
 identity TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'READING',
 content BYTEA, file_metadata TEXT, parsed TEXT,
 error TEXT, updated DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_step_checkpoints (
 job TEXT NOT NULL REFERENCES ingestion_checkpoints(job),
 position INTEGER NOT NULL, name TEXT NOT NULL, identity TEXT NOT NULL,
 kind TEXT NOT NULL, payload TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(job,position)
);
"""
