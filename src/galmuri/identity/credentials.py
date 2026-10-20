"""Opaque credentials, live revocation and bounded issuance."""

import hashlib
import json
import re
import secrets
import uuid

from . import validation
from .errors import AuthenticationError, IdentityError
from .principal import VerifiedPrincipal


def digest_token(raw):
    if not isinstance(raw, str) or re.fullmatch(r"fw_[A-Za-z0-9_-]{43}", raw) is None:
        raise AuthenticationError("Invalid credentials")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def credential_record(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "kind": row["kind"],
        "name": row["name"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "revoked": bool(row["revoked"]),
        "scopes": json.loads(row["scopes"]),
        "apps": json.loads(row["apps"]),
    }


class Credentials:
    def _issue(self, connection, user, *, kind, name, scopes, apps, ttl):
        if not user["enabled"]:
            raise AuthenticationError("Invalid credentials")
        raw, identifier = "fw_" + secrets.token_urlsafe(32), str(uuid.uuid4())
        now = self.clock()
        connection.execute(
            "INSERT INTO identity_credentials(id,user_id,digest,kind,name,generation,scopes,apps,"
            "created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                user["id"],
                digest_token(raw),
                kind,
                name,
                user["generation"],
                json.dumps(scopes),
                json.dumps(apps),
                now,
                now + ttl,
            ),
        )
        result = credential_record(
            connection.execute(
                "SELECT * FROM identity_credentials WHERE id=?",
                (identifier,),
            ).fetchone()
        )
        result["token"] = raw
        return result

    def issue_token(self, user_id, name, *, scopes=("read",), apps=("*",), ttl=2592000):
        display, _ = validation.name(name)
        scopes, apps = validation.restrictions(scopes, apps)
        ttl = validation.ttl(ttl)
        with self.db.transaction() as connection:
            user = connection.execute(
                "SELECT * FROM identity_users WHERE id=?", (user_id,)
            ).fetchone()
            if user is None:
                raise IdentityError("Account does not exist")
            return self._issue(
                connection, user, kind="mcp", name=display, scopes=scopes, apps=apps, ttl=ttl
            )

    def list_tokens(self, user_id):
        with self.db.connection() as connection:
            now = self.clock()
            rows = connection.execute(
                "SELECT c.*,u.enabled,u.generation AS current_generation "
                "FROM identity_credentials c "
                "JOIN identity_users u ON u.id=c.user_id WHERE user_id=? AND kind='mcp' "
                "ORDER BY created_at,id",
                (user_id,),
            ).fetchall()
        result = []
        for row in rows:
            record = credential_record(row)
            record["active"] = bool(
                not row["revoked"]
                and row["enabled"]
                and row["generation"] == row["current_generation"]
                and row["expires_at"] > now
            )
            result.append(record)
        return result

    def revoke_token(self, token_id, user_id=None):
        with self.db.transaction() as connection:
            query, parameters = "UPDATE identity_credentials SET revoked=1 WHERE id=?", [token_id]
            if user_id is not None:
                query += " AND user_id=?"
                parameters.append(user_id)
            if not connection.execute(query, parameters).rowcount:
                raise IdentityError("Credential does not exist")

    def _credential(self, digest):
        # Directory and credential state must come from one coherent database snapshot.
        with self.db.snapshot() as connection:
            row = connection.execute(
                "SELECT c.*,u.enabled,u.administrator,u.is_root,u.generation AS current_generation "
                "FROM identity_credentials c JOIN identity_users u ON u.id=c.user_id "
                "WHERE c.digest=?",
                (digest,),
            ).fetchone()
            if (
                row is None
                or row["revoked"]
                or not row["enabled"]
                or row["generation"] != row["current_generation"]
                or row["expires_at"] <= self.clock()
            ):
                raise AuthenticationError("Invalid credentials")
            current = dict(row)
            current["scopes"], current["apps"] = json.loads(row["scopes"]), json.loads(row["apps"])
            current["groups"] = frozenset(
                r[0]
                for r in connection.execute(
                    "SELECT group_id FROM identity_members WHERE user_id=?",
                    (row["user_id"],),
                )
            )
            return current

    def authenticate(self, raw_token):
        digest = digest_token(raw_token)
        row = self._credential(digest)
        return VerifiedPrincipal(self, digest, row)
