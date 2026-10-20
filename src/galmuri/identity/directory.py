"""Trusted account/group directory operations; transports authorize their callers."""

import uuid

from . import validation
from .errors import IdentityError


def user_record(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "enabled": bool(row["enabled"]),
        "administrator": bool(row["administrator"]),
        "root": bool(row["is_root"]),
    }


class Directory:
    def create_user(self, username, password, administrator=False, root=False):
        display, normalized = validation.name(username)
        if not isinstance(administrator, bool) or not isinstance(root, bool):
            raise IdentityError("Account privilege flags must be boolean")
        encoded = self.hasher.hash(validation.password(password))
        try:
            with self.db.transaction() as connection:
                identifier = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO identity_users"
                    "(id,username,normalized,password_hash,administrator,is_root) "
                    "VALUES(?,?,?,?,?,?)",
                    (identifier, display, normalized, encoded, administrator or root, root),
                )
                return user_record(
                    connection.execute(
                        "SELECT * FROM identity_users WHERE id=?",
                        (identifier,),
                    ).fetchone()
                )
        except self.db.integrity_errors:
            raise IdentityError("Account name already exists") from None

    def list_users(self):
        with self.db.connection() as connection:
            return [
                user_record(r)
                for r in connection.execute("SELECT * FROM identity_users ORDER BY normalized,id")
            ]

    def set_user_enabled(self, user_id, enabled):
        if not isinstance(enabled, bool):
            raise IdentityError("Enabled flag must be boolean")
        with self.db.transaction() as connection:
            if not connection.execute(
                "UPDATE identity_users SET enabled=?,generation=generation+"
                "CASE WHEN enabled<>? THEN 1 ELSE 0 END WHERE id=?",
                (enabled, enabled, user_id),
            ).rowcount:
                raise IdentityError("Account does not exist")
            return user_record(
                connection.execute(
                    "SELECT * FROM identity_users WHERE id=?",
                    (user_id,),
                ).fetchone()
            )

    def change_password(self, user_id, password):
        encoded = self.hasher.hash(validation.password(password))
        with self.db.transaction() as connection:
            if not connection.execute(
                "UPDATE identity_users SET password_hash=?,generation=generation+1 WHERE id=?",
                (encoded, user_id),
            ).rowcount:
                raise IdentityError("Account does not exist")

    def create_group(self, name):
        display, normalized = validation.name(name)
        identifier = str(uuid.uuid4())
        try:
            with self.db.transaction() as connection:
                connection.execute(
                    "INSERT INTO identity_groups VALUES(?,?,?)", (identifier, display, normalized)
                )
            return {"id": identifier, "name": display}
        except self.db.integrity_errors:
            raise IdentityError("Group name already exists") from None

    def list_groups(self):
        with self.db.connection() as connection:
            return [
                dict(r)
                for r in connection.execute(
                    "SELECT id,name FROM identity_groups ORDER BY normalized,id"
                )
            ]

    def add_member(self, group_id, user_id):
        try:
            with self.db.transaction() as connection:
                connection.execute(
                    "INSERT INTO identity_members VALUES(?,?) ON CONFLICT DO NOTHING",
                    (group_id, user_id),
                )
        except self.db.integrity_errors:
            raise IdentityError("Account or group does not exist") from None

    def remove_member(self, group_id, user_id):
        with self.db.transaction() as connection:
            connection.execute(
                "DELETE FROM identity_members WHERE group_id=? AND user_id=?", (group_id, user_id)
            )

    def members(self, group_id):
        with self.db.connection() as connection:
            if not connection.execute(
                "SELECT id FROM identity_groups WHERE id=?", (group_id,)
            ).fetchone():
                raise IdentityError("Group does not exist")
            return [
                user_record(r)
                for r in connection.execute(
                    "SELECT u.* FROM identity_users u JOIN identity_members m ON m.user_id=u.id "
                    "WHERE m.group_id=? ORDER BY u.normalized,u.id",
                    (group_id,),
                )
            ]
