"""Identity persistence: immutable directory IDs and hashed credential lifecycle."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_users (
    id TEXT PRIMARY KEY, username TEXT NOT NULL, normalized TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1, administrator INTEGER NOT NULL DEFAULT 0,
    is_root INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS identity_groups (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, normalized TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS identity_members (
    group_id TEXT NOT NULL REFERENCES identity_groups(id),
    user_id TEXT NOT NULL REFERENCES identity_users(id),
    PRIMARY KEY(group_id,user_id)
);
CREATE TABLE IF NOT EXISTS identity_credentials (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES identity_users(id),
    digest TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, name TEXT NOT NULL,
    generation INTEGER NOT NULL, scopes TEXT NOT NULL, apps TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS identity_credentials_user ON identity_credentials(user_id);
CREATE TABLE IF NOT EXISTS identity_login_limits (
    bucket TEXT PRIMARY KEY, started DOUBLE PRECISION NOT NULL, attempts INTEGER NOT NULL
);
"""


def migrate(database):
    """Old installations gain an explicit false flag; no administrator is promoted."""
    with database.transaction() as connection:
        columns = database.columns(connection, "identity_users")
        if "is_root" not in columns:
            connection.execute(
                "ALTER TABLE identity_users ADD COLUMN is_root INTEGER NOT NULL DEFAULT 0"
            )
