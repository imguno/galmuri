"""Document visibility transitions used within the shared acceptance transaction."""


def retire_source(connection, app, source_key, *, deleted=False):
    connection.execute(
        "UPDATE documents SET state=? WHERE app=? AND source_key=?",
        ("DELETED" if deleted else "WITHDRAWN", app, source_key),
    )


def retire_app(connection, app, *, reset_permissions=False):
    connection.execute("UPDATE documents SET state='WITHDRAWN' WHERE app=?", (app,))
    if reset_permissions:
        connection.execute(
            "UPDATE documents SET readers='[]',writers='[]',acl_override=0 WHERE app=?", (app,)
        )
