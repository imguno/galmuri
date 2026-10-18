"""Escaped administrative projections; no database or lifecycle decisions."""

import html
import json


def table(title, rows, columns):
    if not isinstance(rows, list):
        rows = []
    rows = [row for row in rows if isinstance(row, dict)]
    heading = f"<h2>{html.escape(title)}</h2>"
    if not rows:
        return heading + '<p class="subtitle">No records yet.</p>'
    headers = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            cells.append(f"<td>{html.escape(str(value) if value is not None else '—')}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        heading
        + '<div class="table-wrap"><table><thead><tr>'
        + headers
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def status_tables(status):
    sections = (
        (
            "App state",
            "apps",
            (
                ("name", "App"),
                ("revision", "Revision"),
                ("collection_state", "Collection"),
                ("paused", "Paused"),
                ("collection_error", "Last error"),
            ),
        ),
        (
            "Processing jobs",
            "jobs",
            (
                ("id", "Job"),
                ("app", "App"),
                ("source_key", "Source"),
                ("state", "State"),
                ("attempts", "Attempts"),
                ("error", "Error"),
            ),
        ),
        (
            "Document publications",
            "documents",
            (("app", "App"), ("state", "State"), ("count", "Documents")),
        ),
        (
            "Execution attempts",
            "attempts",
            (
                ("job_id", "Job"),
                ("number", "Attempt"),
                ("worker", "Worker"),
                ("outcome", "Outcome"),
                ("error", "Error"),
            ),
        ),
        (
            "Source writes",
            "writes",
            (
                ("id", "Operation"),
                ("app", "App"),
                ("source_key", "Source"),
                ("state", "State"),
                ("error", "Error"),
            ),
        ),
    )
    return "".join(
        "<section>" + table(title, status.get(key, []), columns) + "</section>"
        for title, key, columns in sections
    )
