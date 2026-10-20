"""Current published document inventory behind the relational query adapter."""

import json

from galmuri.retrieval.indexing.snapshots import current_documents


def listing(database, app, principal, *, query="", offset=0, limit=100, inventory=False):
    with database.connection() as connection:
        items = []
        for row in current_documents(connection, app):
            readers, writers = json.loads(row["readers"]), json.loads(row["writers"])
            if not inventory and not principal.matches(readers):
                continue
            name = str(json.loads(row["metadata"]).get("name", row["key"]))
            if query.casefold() not in name.casefold():
                continue
            generation = connection.execute(
                "SELECT acl_generation FROM source_refs WHERE app=? AND key=?",
                (app, row["source_key"]),
            ).fetchone()[0]
            item = {
                "key": row["key"],
                "name": name,
                "uri": row["source_key"],
                "version": row["version"],
                "permissions_revision": generation,
                "can_write": principal.matches(writers),
            }
            if inventory:
                item.update(readers=readers, writers=writers)
            items.append(item)
    items.sort(key=lambda item: (item["name"].casefold(), item["key"]))
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
    }
