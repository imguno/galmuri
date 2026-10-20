"""BM25 candidate headers from indexed postings; document bodies are not ranked."""

import math

K1 = 1.2
B = 0.75


def statement(connection, app, terms):
    corpus = connection.execute(
        "SELECT document_count,total_length FROM lexical_corpora WHERE app=?", (app,)
    ).fetchone()
    if not corpus or not corpus["document_count"] or not terms:
        return None
    placeholders = ",".join("?" for _ in terms)
    frequencies = connection.execute(
        f"SELECT term,document_count FROM lexical_terms WHERE app=? AND term IN ({placeholders})",
        (app, *terms),
    ).fetchall()
    if not frequencies:
        return None
    hangul_count = sum(term.startswith("h:") for term in terms)
    required_count = len(terms) - hangul_count
    available = {row["term"] for row in frequencies}
    if any(not term.startswith("h:") and term not in available for term in terms):
        return None
    # Coverage is based on the complete query, including terms absent from this
    # index. Otherwise missing bigrams would silently make long queries broader.
    hangul_minimum = (hangul_count + 1) // 2
    count = corpus["document_count"]
    weights = [
        (
            row["term"],
            math.log1p((count - row["document_count"] + 0.5) / (row["document_count"] + 0.5)),
            int(row["term"].startswith("h:")),
        )
        for row in frequencies
    ]
    values = ",".join("(?,?,?)" for _ in weights)
    sql = (
        f"WITH query_terms(term,weight,hangul) AS (VALUES {values}) "
        "SELECT d.key,d.source_key,d.version,d.readers,a.revision,"
        "SUM(q.weight * p.frequency * ? / "
        "(p.frequency + ? * (? + ? * n.length / ?))) AS score "
        "FROM query_terms q JOIN lexical_postings p ON p.term=q.term AND p.app=? "
        "JOIN lexical_documents n ON n.app=p.app AND n.key=p.key "
        "JOIN documents d ON d.app=p.app AND d.key=p.key "
        "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
        "JOIN app_state a ON a.name=d.app "
        "WHERE d.state='ACTIVE' AND s.deleted=0 AND s.version=d.version "
        "GROUP BY d.key,d.source_key,d.version,d.readers,a.revision "
        "HAVING SUM(CASE WHEN q.hangul=0 THEN 1 ELSE 0 END)=? "
        "AND SUM(CASE WHEN q.hangul=1 THEN 1 ELSE 0 END)>=? "
        "ORDER BY score DESC,d.key"
    )
    parameters = tuple(value for pair in weights for value in pair) + (
        K1 + 1,
        K1,
        1 - B,
        B,
        corpus["total_length"] / count or 1.0,
        app,
        required_count,
        hangul_minimum,
    )
    return sql, parameters
