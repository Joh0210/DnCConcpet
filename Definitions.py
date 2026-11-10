"""
The loaded definition JSON — stand-in for the generator's output
(``YAML (authored) → validate → JSON (IR) → engine``, concept §2).

Entries are plain dicts with the keys of concept §4.1. Expressions inside them are
:class:`InnerFunction` / :class:`TargetPath` objects; the parser that would build
those from strings is out of scope, tests build them from Python functions.
"""
from __future__ import annotations

from typing import Iterable

from errors import DefinitionError, did_you_mean


class DefinitionStore:
    """Every model and content entry, indexed by its globally unique ``id``."""

    def __init__(self, entries: Iterable[dict] = ()):
        self._entries: dict[str, dict] = {}
        self.load(entries)

    def load(self, entries: Iterable[dict]) -> None:
        for entry in entries:
            self.add(entry)

    def add(self, entry: dict) -> None:
        def_id = entry.get("id")
        if not isinstance(def_id, str) or not def_id:
            raise DefinitionError(f"entry without an id: {entry!r}")
        if def_id in self._entries:
            raise DefinitionError(f"duplicate id '{def_id}'")
        self._entries[def_id] = entry

    def get(self, def_id: str) -> dict:
        try:
            return self._entries[def_id]
        except KeyError:
            raise DefinitionError(
                f"unknown definition '{def_id}'{did_you_mean(def_id, self._entries)}"
            ) from None

    def has(self, def_id: str) -> bool:
        return def_id in self._entries

    def ids(self) -> list[str]:
        return list(self._entries)


#: Store used when an Instance is created without an explicit one.
DEFAULT_STORE = DefinitionStore()


def get_data_definition_from_yml(def_id: str, store: DefinitionStore | None = None) -> dict:
    """Name kept from the pseudocode: the definition entry for ``def_id``."""
    return (store if store is not None else DEFAULT_STORE).get(def_id)
