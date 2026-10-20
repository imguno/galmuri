"""Index mutations participate in the document owner's acceptance transaction."""


def remove(connection, app, key):
    existing = connection.execute(
        "SELECT length FROM lexical_documents WHERE app=? AND key=?", (app, key)
    ).fetchone()
    if existing is None:
        return
    terms = connection.execute(
        "SELECT term FROM lexical_postings WHERE app=? AND key=?", (app, key)
    ).fetchall()
    connection.executemany(
        "UPDATE lexical_terms SET document_count=document_count-1 WHERE app=? AND term=?",
        ((app, row["term"]) for row in terms),
    )
    connection.executemany(
        "DELETE FROM lexical_terms WHERE app=? AND term=? AND document_count=0",
        ((app, row["term"]) for row in terms),
    )
    connection.execute("DELETE FROM lexical_documents WHERE app=? AND key=?", (app, key))
    connection.execute(
        "UPDATE lexical_corpora SET document_count=document_count-1,"
        "total_length=total_length-? WHERE app=?",
        (existing["length"], app),
    )


def replace(connection, app, key, terms):
    remove(connection, app, key)
    length = sum(terms.values())
    connection.execute(
        "INSERT INTO lexical_documents(app,key,length) VALUES(?,?,?)", (app, key, length)
    )
    connection.executemany(
        "INSERT INTO lexical_postings(app,term,key,frequency) VALUES(?,?,?,?)",
        ((app, term, key, frequency) for term, frequency in terms.items()),
    )
    connection.executemany(
        "INSERT INTO lexical_terms(app,term,document_count) VALUES(?,?,1) "
        "ON CONFLICT(app,term) DO UPDATE SET document_count=lexical_terms.document_count+1",
        ((app, term) for term in terms),
    )
    connection.execute(
        "INSERT INTO lexical_corpora(app,document_count,total_length) VALUES(?,1,?) "
        "ON CONFLICT(app) DO UPDATE SET document_count=lexical_corpora.document_count+1,"
        "total_length=lexical_corpora.total_length+excluded.total_length",
        (app, length),
    )


def retire_source(connection, app, source_key):
    keys = connection.execute(
        "SELECT key FROM documents WHERE app=? AND source_key=?", (app, source_key)
    ).fetchall()
    for row in keys:
        remove(connection, app, row["key"])


def retire_app(connection, app):
    connection.execute("DELETE FROM lexical_documents WHERE app=?", (app,))
    connection.execute("DELETE FROM lexical_terms WHERE app=?", (app,))
    connection.execute("DELETE FROM lexical_corpora WHERE app=?", (app,))
