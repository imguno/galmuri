import json

from galmuri.documents.lexical.analyzer import analyze
from galmuri.documents.lexical.projection import replace


def publish(connection, key, text, *, app="docs", readers=("*",), indexed=True):
    connection.execute(
        "INSERT INTO app_state(name,revision) VALUES(?,'r1') ON CONFLICT(name) DO NOTHING",
        (app,),
    )
    connection.execute(
        "INSERT INTO source_refs(app,key,version,metadata) VALUES(?,?,'v1','{}') "
        "ON CONFLICT(app,key) DO UPDATE SET version='v1',deleted=0",
        (app, key),
    )
    connection.execute(
        "INSERT INTO documents(app,key,source_key,version,text,metadata,readers,writers) "
        "VALUES(?,?,?,'v1',?,'{}',?,'[]') ON CONFLICT(app,key) DO UPDATE SET "
        "text=excluded.text,readers=excluded.readers,state='ACTIVE',version='v1'",
        (app, key, key, text, json.dumps(readers)),
    )
    if indexed:
        replace(connection, app, key, analyze(text))


def table(database, name):
    with database.connection() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM " + name)]
