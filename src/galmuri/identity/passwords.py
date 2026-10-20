"""Argon2id password verification with a shared, race-safe attempt budget."""

import hashlib

from argon2.exceptions import InvalidHashError, VerificationError

from . import validation
from .errors import AuthenticationError, IdentityError

WINDOW = 900
ATTEMPTS = 10


class Passwords:
    def _reserve(self, normalized, rate_key):
        if not isinstance(rate_key, str) or not 1 <= len(rate_key) <= 1024:
            raise AuthenticationError("Invalid credentials")
        keys = ["account:" + normalized, "peer:" + rate_key]
        buckets = [hashlib.sha256(k.encode()).hexdigest() for k in keys]
        reservations = []
        with self.db.transaction() as connection:
            now = self.clock()
            for bucket in buckets:
                row = connection.execute(
                    "SELECT * FROM identity_login_limits WHERE bucket=?", (bucket,)
                ).fetchone()
                started = row["started"] if row and now - row["started"] < WINDOW else now
                count = row["attempts"] if row and started == row["started"] else 0
                if count >= ATTEMPTS:
                    raise AuthenticationError("Login temporarily unavailable")
                connection.execute(
                    "INSERT INTO identity_login_limits VALUES(?,?,?) ON CONFLICT(bucket) "
                    "DO UPDATE SET started=excluded.started,attempts=excluded.attempts",
                    (bucket, started, count + 1),
                )
                reservations.append((bucket, started))
        return reservations

    def login(self, username, password, *, ttl=3600, rate_key="local"):
        ttl = validation.ttl(ttl, maximum=86400)
        try:
            _, normalized = validation.name(username)
            validation.password(password)
        except IdentityError:
            # Invalid login shape also consumes the peer's budget.
            self._reserve("invalid-login", rate_key)
            raise AuthenticationError("Invalid credentials") from None
        reservations = self._reserve(normalized, rate_key)
        with self.db.connection() as connection:
            user = connection.execute(
                "SELECT * FROM identity_users WHERE normalized=?", (normalized,)
            ).fetchone()
        encoded = user["password_hash"] if user else self._dummy_hash
        try:
            valid = self.hasher.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid or not user or not user["enabled"]:
            raise AuthenticationError("Invalid credentials")
        # Hashing occurs outside the write lock. Recheck the exact generation under
        # the same transaction which issues the session to prevent password/disable races.
        with self.db.transaction() as connection:
            current = connection.execute(
                "SELECT * FROM identity_users WHERE id=?", (user["id"],)
            ).fetchone()
            if (
                not current
                or not current["enabled"]
                or current["generation"] != user["generation"]
                or current["password_hash"] != encoded
            ):
                raise AuthenticationError("Invalid credentials")
            result = self._issue(
                connection,
                current,
                kind="session",
                name="browser session",
                scopes=("read", "write", "manage"),
                apps=("*",),
                ttl=ttl,
            )
            # Successful attempts remove only their own reservation, never a competing failure.
            for bucket, started in reservations:
                connection.execute(
                    "UPDATE identity_login_limits SET attempts="
                    "CASE WHEN attempts>0 THEN attempts-1 ELSE 0 END "
                    "WHERE bucket=? AND started=?",
                    (bucket, started),
                )
            return result
