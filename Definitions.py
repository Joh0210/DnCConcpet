"""
The loaded definition JSON — stand-in for the generator's output
(``YAML (authored) → validate → JSON (IR) → engine``, concept §2).

Entries are plain dicts with the keys of concept §4.1. Expressions inside them are
:class:`InnerFunction` / :class:`TargetPath` objects; the parser that would build
those from strings is out of scope, tests build them from Python functions.

Every game (rule system: ``pathfinder2e``, ``dnd5e``, ``daggerhart``, ...) has its
own :class:`DefinitionStore`. They are registered once in :data:`GAMES`; an
instance only knows its game id and looks its definitions up there, so nobody has
to pass a store around.
"""
from __future__ import annotations

from typing import Iterable

from errors import DefinitionError, did_you_mean


class DefinitionStore:
    """Every model and content entry of one game, indexed by its ``id`` (unique within the game)."""

    def __init__(self, game: str, entries: Iterable[dict] = ()):
        if not isinstance(game, str) or not game:
            raise DefinitionError(f"a definition store needs a game id, got {game!r}")
        self.game = game
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
            raise DefinitionError(f"duplicate id '{def_id}' in game '{self.game}'")
        self._entries[def_id] = entry

    def get(self, def_id: str) -> dict:
        try:
            return self._entries[def_id]
        except KeyError:
            raise DefinitionError(
                f"unknown definition '{def_id}' in game '{self.game}'{did_you_mean(def_id, self._entries)}"
            ) from None

    def has(self, def_id: str) -> bool:
        return def_id in self._entries

    def ids(self) -> list[str]:
        return list(self._entries)

    def __repr__(self) -> str:
        return f"<DefinitionStore {self.game} ({len(self._entries)} entries)>"


class GameRegistry:
    """
    Every loaded game: game id → its :class:`DefinitionStore`. One per process
    (:data:`GAMES`).

    A game id names one store for the whole lifetime of the process — registering
    it twice is an error. Instances look their store up by id, so replacing it
    would silently change what every live instance of that game is built from.
    """

    def __init__(self) -> None:
        self._stores: dict[str, DefinitionStore] = {}

    def register(self, store: DefinitionStore) -> DefinitionStore:
        if store.game in self._stores:
            raise DefinitionError(f"game '{store.game}' is already registered")
        self._stores[store.game] = store
        return store

    def unregister(self, game: str) -> None:
        """Drop a game (tests, unloading content). Its live instances can no longer look up definitions."""
        self._stores.pop(game, None)

    def get(self, game: str) -> DefinitionStore:
        try:
            return self._stores[game]
        except KeyError:
            raise DefinitionError(f"unknown game '{game}'{did_you_mean(game, self._stores)}") from None

    def has(self, game: str) -> bool:
        return game in self._stores

    def ids(self) -> list[str]:
        return list(self._stores)


#: The global registry every instance looks its definitions up in.
GAMES = GameRegistry()


def get_data_definition_from_yml(def_id: str, game: str) -> dict:
    """Name kept from the pseudocode: the definition entry for ``def_id`` in ``game``."""
    return GAMES.get(game).get(def_id)
