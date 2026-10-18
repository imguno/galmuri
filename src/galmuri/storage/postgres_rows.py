"""Rows preserve the existing named and positional persistence contract."""

from collections.abc import Mapping


class Row(Mapping):
    def __init__(self, names, values):
        self._values = tuple(values)
        self._named = dict(zip(names, self._values, strict=True))

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, (int, slice)) else self._named[key]

    def __iter__(self):
        return iter(self._named)

    def __len__(self):
        return len(self._named)


def row_factory(cursor):
    names = tuple(column.name for column in (cursor.description or ()))
    return lambda values: Row(names, values)
