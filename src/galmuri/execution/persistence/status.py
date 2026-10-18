"""JSON-safe administrative projection; no document bodies or claim secrets."""


def status(database, app_name=None):
    where, parameters = (" WHERE app=?", (app_name,)) if app_name else ("", ())
    with database.connection() as connection:
        apps = [
            dict(row)
            for row in connection.execute(
                "SELECT name,revision,paused,checkpoint,next_collection,collection_state,"
                "collection_error "
                "FROM app_state" + (" WHERE name=?" if app_name else ""),
                parameters,
            )
        ]
        jobs = [
            dict(row)
            for row in connection.execute(
                "SELECT id,app,source_key,version,revision,deleted,state,attempts,available,worker,"
                "lease_until,error,created,updated FROM jobs" + where + " ORDER BY created,id",
                parameters,
            )
        ]
        attempts = [
            dict(row)
            for row in connection.execute(
                "SELECT t.id,t.job_id,t.number,t.worker,t.started,t.ended,t.outcome,t.error "
                "FROM attempts t JOIN jobs j ON j.id=t.job_id"
                + (" WHERE j.app=?" if app_name else "")
                + " ORDER BY t.id",
                parameters,
            )
        ]
        events = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM events" + where + " ORDER BY id DESC LIMIT 1000", parameters
            )
        ]
        writes = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM writes" + where + " ORDER BY created,id", parameters
            )
        ]
        counts = [
            dict(row)
            for row in connection.execute(
                "SELECT app,state,COUNT(*) AS count FROM documents" + where + " GROUP BY app,state",
                parameters,
            )
        ]
    return {
        "apps": apps,
        "jobs": jobs,
        "attempts": attempts,
        "events": events,
        "writes": writes,
        "documents": counts,
    }
