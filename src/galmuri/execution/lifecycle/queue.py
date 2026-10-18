"""Execution owns claims, leases and terminal transition records."""

import uuid

from galmuri.execution.lifecycle.transitions import event, finish, require_transition

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "SUPERSEDED"}


class Queue:
    def __init__(self, database, apps, clock):
        self.database, self.apps, self.clock = database, apps, clock

    def claim(self, worker, supported_apps=None):
        eligible = {
            name: app.revision
            for name, app in self.apps.items()
            if supported_apps is None or supported_apps.get(name) == app.revision
        }
        with self.database.transaction() as connection:
            now = self.clock()
            expired = connection.execute(
                "SELECT * FROM jobs WHERE state='RUNNING' AND lease_until<=?", (now,)
            ).fetchall()
            for job in expired:
                # Arbitrary handler code may have external effects; expiry is not proof of failure.
                finish(connection, job, "RECONCILING", now, "Worker lease expired")
            if not eligible:
                return None
            parameters = [now]
            eligibility = (
                " AND (" + " OR ".join("(j.app=? AND j.revision=?)" for _ in eligible) + ")"
            )
            for name, revision in eligible.items():
                parameters.extend((name, revision))
            job = connection.execute(
                "SELECT j.*,a.revision AS active_revision FROM jobs j "
                "JOIN app_state a ON a.name=j.app "
                "JOIN source_refs r ON r.app=j.app AND r.key=j.source_key "
                "WHERE j.state IN ('READY','RETRY_WAIT') AND j.available<=? AND a.paused=0 "
                "AND j.revision=a.revision AND j.version=r.version AND j.deleted=r.deleted "
                + eligibility
                + " ORDER BY j.created,j.id LIMIT 1",
                parameters,
            ).fetchone()
            if job is None:
                return None
            app = self.apps.get(job["app"])
            if (
                app is None
                or app.revision != job["revision"]
                or job["active_revision"] != job["revision"]
            ):
                finish(connection, job, "SUPERSEDED", now, "App revision changed")
                return dict(job) | {"skip": True}
            token = uuid.uuid4().hex
            require_transition(job, "RUNNING")
            generation = connection.execute(
                "SELECT acl_generation FROM source_refs WHERE app=? AND key=?",
                (job["app"], job["source_key"]),
            ).fetchone()[0]
            connection.execute(
                "UPDATE jobs SET state='RUNNING',token=?,worker=?,lease_until=?,"
                "attempts=attempts+1,"
                "acl_generation=?,updated=? WHERE id=?",
                (token, worker, now + app.policy.lease_seconds, generation, now, job["id"]),
            )
            connection.execute(
                "INSERT INTO attempts(job_id,number,token,worker,started) VALUES(?,?,?,?,?)",
                (job["id"], job["attempts"] + 1, token, worker, now),
            )
            claimed = dict(
                connection.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            )
            event(connection, claimed, "RUNNING", "Claimed by " + worker, now)
            return claimed

    def heartbeat(self, job_id, token):
        with self.database.transaction() as connection:
            now = self.clock()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if (
                not job
                or job["state"] != "RUNNING"
                or job["token"] != token
                or job["lease_until"] <= now
            ):
                return False
            connection.execute(
                "UPDATE jobs SET lease_until=? WHERE id=?",
                (now + self.apps[job["app"]].policy.lease_seconds, job_id),
            )
            return True

    def fail(self, job, error, unknown=False):
        with self.database.transaction() as connection:
            now = self.clock()
            current = connection.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if current["state"] != "RUNNING" or current["token"] != job["token"]:
                return
            policy = self.apps[job["app"]].policy
            state = (
                "RECONCILING"
                if unknown
                else ("FAILED" if job["attempts"] >= policy.max_attempts else "RETRY_WAIT")
            )
            if current["lease_until"] <= now:
                state = "RECONCILING"
            finish(connection, current, state, now, str(error), now + policy.retry_delay)

    def command(self, job_id, command):
        with self.database.transaction() as connection:
            now = self.clock()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise KeyError(job_id)
            if command == "cancel":
                if job["state"] in TERMINAL:
                    return
                if job["state"] in {"RUNNING", "RECONCILING"}:
                    finish(
                        connection,
                        job,
                        "RECONCILING",
                        now,
                        "Cancellation awaiting effect reconciliation",
                    )
                else:
                    finish(connection, job, "CANCELLED", now)
            elif command == "retry":
                if job["state"] not in {"FAILED", "RETRY_WAIT"}:
                    raise ValueError("Only confirmed failures can be retried")
                if not self._current_intent(connection, job):
                    raise ValueError("Cannot retry a superseded source or app revision")
                finish(connection, job, "READY", now, available=now)
            else:
                raise ValueError(command)

    def lookup(self, job_id):
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def reconcile(self, job_id, outcome):
        states = {"retry_safe": "RETRY_WAIT", "failed": "FAILED", "cancelled": "CANCELLED"}
        if outcome not in states:
            raise ValueError(
                "Expected retry_safe, failed, or cancelled; success needs prepared result"
            )
        with self.database.transaction() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["state"] != "RECONCILING":
                raise ValueError("Job is not awaiting reconciliation")
            if outcome == "retry_safe" and not self._current_intent(connection, job):
                finish(connection, job, "SUPERSEDED", self.clock(), "Resolved old source intent")
                return
            finish(connection, job, states[outcome], self.clock(), available=self.clock())

    @staticmethod
    def _current_intent(connection, job):
        current = connection.execute(
            "SELECT a.revision,r.version,r.deleted FROM app_state a JOIN source_refs r "
            "ON r.app=a.name WHERE a.name=? AND r.key=?",
            (job["app"], job["source_key"]),
        ).fetchone()
        return (
            current is not None
            and current["revision"] == job["revision"]
            and current["version"] == job["version"]
            and current["deleted"] == job["deleted"]
        )
