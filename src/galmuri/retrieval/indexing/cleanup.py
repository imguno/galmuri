"""Retryable exact-ID deletion, independent from semantic activation."""

import json
import uuid

from galmuri.retrieval.indexing.snapshots import namespace


def work_once(database, apps, clock, app_name=None, *, cleanup_stores=None):
    stores = dict(cleanup_stores or {}) | {
        app.retrieval.store.identity: app.retrieval.store
        for app in apps.values()
        if app.retrieval is not None
    }
    with database.transaction() as connection:
        now = clock()
        candidates = connection.execute(
            "SELECT c.*,b.prepared,b.store_identity,b.lease_until AS build_lease "
            "FROM semantic_cleanup c JOIN semantic_builds b ON b.id=c.build "
            "WHERE (c.state!='SUCCEEDED' OR b.state='SUPERSEDED') AND c.available<=? "
            "AND (c.lease_until IS NULL OR c.lease_until<=?) ORDER BY c.available,c.build",
            (now, now),
        ).fetchall()
        selected = None
        for row in candidates:
            if app_name and row["app"] != app_name:
                continue
            if row["build_lease"] is not None and row["build_lease"] > now:
                continue
            if row["store_identity"] not in stores:
                connection.execute(
                    "UPDATE semantic_cleanup SET state='WAITING_STORE',error=? WHERE build=?",
                    (
                        "Original store unavailable; run an index worker with store identity "
                        + row["store_identity"],
                        row["build"],
                    ),
                )
                continue
            token = str(uuid.uuid4())
            connection.execute(
                "UPDATE semantic_cleanup SET state='RUNNING',token=?,lease_until=?,"
                "attempts=attempts+1 WHERE build=?",
                (token, now + 60, row["build"]),
            )
            selected = dict(row) | {"token": token}
            break
    if selected is None:
        return False
    try:
        prepared = json.loads(selected["prepared"]) if selected["prepared"] else []
        identifiers = tuple(item["id"] for item in prepared)
        if identifiers:
            stores[selected["store_identity"]].delete(
                namespace(selected["fingerprint"]), identifiers
            )
    except Exception as error:
        state, message, available = (
            "RETRY_WAIT",
            str(error),
            clock() + min(60, 2 ** min(6, selected["attempts"])),
        )
    else:
        app = apps.get(selected["app"])
        config = app.retrieval if app is not None else None
        interval = config.cleanup_interval if config is not None else 300
        state, message, available = "SUCCEEDED", None, clock() + interval
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_cleanup SET state=?,error=?,available=?,lease_until=NULL,token=NULL "
            "WHERE build=? AND token=?",
            (state, message, available, selected["build"], selected["token"]),
        )
    return True
