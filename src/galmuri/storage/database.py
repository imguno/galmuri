"""A process-safe SQLite transaction boundary for the default persistence adapter."""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    integrity_errors = (sqlite3.IntegrityError,)

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def initialize(self, schema: str) -> None:
        with self.connection() as connection:
            connection.executescript(schema)

    @contextmanager
    def snapshot(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN")
            yield connection

    @staticmethod
    def columns(connection, table: str) -> set[str]:
        from galmuri.storage.identifiers import identifier

        identifier(table)
        return {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}

    @staticmethod
    def now() -> float:
        return time.time()

    clock = now
