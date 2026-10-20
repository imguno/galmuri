"""Inspect actual local vectors and private checkpoint retention independently."""

import json
import sqlite3


def vectors(path):
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT namespace,id,vector FROM vector_points ORDER BY id")
        return [
            {"namespace": row[0], "id": row[1], "dimensions": len(json.loads(row[2]))}
            for row in rows
        ]


def checkpoints(path):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                "SELECT c.stage,c.content IS NOT NULL AS retains_content,"
                "c.parsed IS NOT NULL AS retains_parsed,j.state AS job_state "
                "FROM ingestion_checkpoints c JOIN jobs j ON j.id=c.job ORDER BY c.updated,c.job"
            )
        ]
