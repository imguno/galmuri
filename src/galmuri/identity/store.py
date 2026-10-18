"""Account storage composes directory, login and credential responsibilities."""

import secrets
import time

from argon2 import PasswordHasher, Type

from galmuri.storage.database import Database

from .credentials import Credentials
from .directory import Directory
from .passwords import Passwords
from .schema import SCHEMA, migrate


class IdentityStore(Directory, Passwords, Credentials):
    def __init__(self, path=None, clock=time.time, *, database=None):
        if database is not None and path is not None:
            raise TypeError("Use an identity database or a path, not both")
        if database is None and path is None:
            raise TypeError("An identity database or path is required")
        self.db = database if database is not None else Database(path)
        self.clock = self.db.now if clock is time.time else clock
        self.hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
        self._dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))
        self.db.initialize(SCHEMA)
        migrate(self.db)
