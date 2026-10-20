"""Translate internal qmark statements without changing quoted text or comments."""

import re
import uuid
from contextlib import contextmanager


def placeholders(statement: str) -> str:
    output, position, state, dollar = [], 0, "plain", ""
    while position < len(statement):
        current = statement[position]
        pair = statement[position : position + 2]
        if state == "plain":
            if pair in ("--", "/*"):
                state = "line" if pair == "--" else "block"
                output.append(pair)
                position += 2
                continue
            if current in ("'", '"'):
                state = current
            elif current == "$":
                match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", statement[position:])
                if match:
                    dollar, state = match[0], "dollar"
                    output.append(dollar)
                    position += len(dollar)
                    continue
            elif current == "?":
                output.append("%s")
                position += 1
                continue
        elif state in ("'", '"') and current == state:
            if pair == state * 2:
                output.append(pair)
                position += 2
                continue
            state = "plain"
        elif state == "line" and current == "\n":
            state = "plain"
        elif state == "block" and pair == "*/":
            output.append(pair)
            state = "plain"
            position += 2
            continue
        elif state == "dollar" and statement.startswith(dollar, position):
            output.append(dollar)
            state = "plain"
            position += len(dollar)
            continue
        # Psycopg applies percent placeholders even inside SQL literals and comments.
        output.append("%%" if current == "%" else current)
        position += 1
    return "".join(output)


class Connection:
    def __init__(self, connection):
        self.raw = connection

    def execute(self, statement, parameters=None):
        if parameters is None:
            return self.raw.execute(statement)
        return self.raw.execute(placeholders(statement), tuple(_parameter(v) for v in parameters))

    def executemany(self, statement, parameters):
        cursor = self.raw.cursor()
        cursor.executemany(
            placeholders(statement), [tuple(_parameter(v) for v in row) for row in parameters]
        )
        return cursor

    @contextmanager
    def stream(self, statement, parameters):
        """A transaction-owned server cursor keeps large read results off the client."""
        with self.raw.cursor(name="read_" + uuid.uuid4().hex) as cursor:
            cursor.execute(placeholders(statement), tuple(_parameter(v) for v in parameters))
            yield cursor


def _parameter(value):
    return int(value) if isinstance(value, bool) else value
