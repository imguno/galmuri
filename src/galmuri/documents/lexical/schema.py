"""Portable inverted index: no backend-specific full-text tokenizer required."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS lexical_metadata (
 name TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lexical_corpora (
 app TEXT PRIMARY KEY, document_count INTEGER NOT NULL, total_length BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS lexical_terms (
 app TEXT NOT NULL, term TEXT NOT NULL, document_count INTEGER NOT NULL,
 PRIMARY KEY(app,term)
);
CREATE TABLE IF NOT EXISTS lexical_documents (
 app TEXT NOT NULL, key TEXT NOT NULL, length INTEGER NOT NULL,
 PRIMARY KEY(app,key),
 FOREIGN KEY(app,key) REFERENCES documents(app,key) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS lexical_postings (
 app TEXT NOT NULL, term TEXT NOT NULL, key TEXT NOT NULL, frequency INTEGER NOT NULL,
 PRIMARY KEY(app,term,key),
 FOREIGN KEY(app,key) REFERENCES lexical_documents(app,key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS lexical_document_terms ON lexical_postings(app,key);
"""
