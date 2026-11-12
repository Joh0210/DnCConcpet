"""
The loaded definition JSON — stand-in for the generator's output
(``YAML (authored) → validate → JSON (IR) → engine``, concept §2).

Entries are plain JSON: dicts with the keys of concept §4.1. Expressions inside
them are already ASTs (concept §4.14: ``{"op": ...}``, ``{"path": ...}``,
``{"value": ...}``) — the parser that writes them from the YAML strings is out of
scope; tests write them with the helpers in ``tests/ir.py``.

Every game (rule system: ``pathfinder2e``, ``dnd5e``, ``daggerhart``, ...) has its
own :class:`DefinitionStore`. They are registered once in :data:`GAMES`; an
instance only knows its game id and looks its definitions up there, so nobody has
to pass a store around.
"""
from __future__ import annotations

from typing import Any, Iterable

from datatype.Datatype import Datatype
from errors import DefinitionError, did_you_mean
from value.InnerFunction import InnerFunction
from value.PathValue import PathValue
from value.build import build_target, build_value, check_type


class DefinitionStore:
    """
    Every model and content entry of one game, indexed by its ``id`` (unique within the game).

    Also the compile cache of the game's expressions: :meth:`value` builds each
    JSON node once — when the first instance needs it — and every later instance
    of any definition that contains it shares the node. Nodes are immutable and
    get their instance only through the context, so sharing is safe; it saves
    rebuilding (and re-resolving the operations of) every expression per instance.
    """

    def __init__(self, game: str, entries: Iterable[dict] = ()):
        if not isinstance(game, str) or not game:
            raise DefinitionError(f"a definition store needs a game id, got {game!r}")
        self.game = game
        self._entries: dict[str, dict] = {}
        # id(json node) → (json node, built node). The JSON is kept so its id stays unique.
        self._compiled: dict[int, tuple[dict, InnerFunction]] = {}
        self.load(entries)

    def load(self, entries: Iterable[dict]) -> None:
        """Add every entry of ``entries``."""
        for entry in entries:
            self.add(entry)

    def add(self, entry: dict) -> None:
        """Add one entry; its ``id`` must be new in this game."""
        def_id = entry.get("id")
        if not isinstance(def_id, str) or not def_id:
            raise DefinitionError(f"entry without an id: {entry!r}")
        if def_id in self._entries:
            raise DefinitionError(f"duplicate id '{def_id}' in game '{self.game}'")
        self._entries[def_id] = entry

    def get(self, def_id: str) -> dict:
        """The entry ``def_id``; an unknown id is reported with the closest match."""
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

    # ------------------------------------------------------------------ expressions

    def value(self, raw: Any, expected: Datatype | None = None) -> InnerFunction:
        """
        The node for a value of this game's JSON (see :func:`value.build.build_value`),
        built once per JSON node. A bare scalar is cheap and typed by its slot,
        so it is built every time.
        """
        if not isinstance(raw, dict):
            return build_value(raw, expected)
        # Built without the slot's type, so every slot shares the node; the slot is checked separately.
        node = self._compile(raw, build_value)
        check_type(node, expected)
        return node

    def target(self, raw: Any) -> PathValue:
        """The path an effect targets, built once per JSON node."""
        if not isinstance(raw, dict):
            return build_target(raw)
        return self._compile(raw, build_target)

    def _compile(self, raw: dict, build) -> Any:
        """``build(raw)``, cached by the identity of the JSON node (equal JSON elsewhere is built again)."""
        cached = self._compiled.get(id(raw))
        if cached is None:
            cached = self._compiled[id(raw)] = (raw, build(raw))
        return cached[1]

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
        """Make ``store`` available under its game id. Returns it for chaining."""
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
