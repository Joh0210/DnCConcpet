from __future__ import annotations

from typing import Any

from engine.datatype.Datatype import Datatype
from engine.errors import DefinitionError
from engine.value.InnerFunction import EvalContext, InnerFunction

#: The type a bare JSON scalar gets when the slot it stands in has no type of its own.
#: ``bool`` comes first: in Python every bool is also an int.
_JSON_KINDS: tuple[tuple[type, str], ...] = ((bool, "bool"), (int, "int"), (float, "number"), (str, "text"))


class StaticValue(InnerFunction):
    """
    A literal: ``{"value": "<parsable>", "type": "<type id>"}``.

    The value is parsed by its datatype **once**, when the node is built — the
    node then only hands it out. ``null`` is a value of every type (an absent
    optional value); its own type is ``null``.

    A bare JSON scalar is shorthand for a static value (:meth:`shorthand`):
    ``set: {weight: 4}`` instead of ``set: {weight: {value: "4", type: number}}``.
    """

    KEYS = {"value", "type"}
    is_literal = True

    def __init__(self, value: Any, datatype: Datatype):
        self.value = value
        self.type = datatype

    @classmethod
    def from_json(cls, raw: dict) -> StaticValue:
        if "type" not in raw:
            return cls.shorthand(raw["value"])
        return cls.parsed(raw["value"], Datatype.get(raw["type"]))

    @classmethod
    def parsed(cls, raw: Any, datatype: Datatype) -> StaticValue:
        """``raw`` parsed by ``datatype`` (strings via ``deserialize``, native values via ``validate``)."""
        if raw is None:
            return cls(None, datatype)
        try:
            return cls(datatype.parse(raw), datatype)
        except ValueError as error:
            raise DefinitionError(f"invalid {datatype.name()} literal {raw!r}: {error}") from None

    @classmethod
    def shorthand(cls, raw: Any, expected: Datatype | None = None) -> StaticValue:
        """
        A bare JSON scalar as a static value: typed by the slot (``expected``, e.g.
        the prop's type) when it has one, otherwise by its JSON kind — ``true`` →
        ``bool``, ``3`` → ``int``, ``2.5`` → ``number``, ``"a"`` → ``text``,
        ``null`` → ``null``. Enum values therefore need a typed slot or the full
        form (``{"value": "heavy", "type": "ArmorCategory"}``).

        todo: evaluate if this function is still needed or should/could be removed,
         since the json is created by an compiler
        """
        if expected is not None:
            return cls.parsed(raw, expected)
        if raw is None:
            return cls(None, Datatype.get("null"))
        for python_type, type_name in _JSON_KINDS:
            if isinstance(raw, python_type):
                return cls.parsed(raw, Datatype.get(type_name))
        raise DefinitionError(
            f"{raw!r} is not a value — write a literal, {{'op': ...}} or {{'path': ...}} (concept §4.14)"
        )

    def evaluate(self, ctx: EvalContext) -> Any:
        return self.value

    def describe(self) -> str:
        if self.value is None:
            return "null"
        return self.type.literal(self.value)

    def __repr__(self) -> str:
        return f"<StaticValue {self.describe()}: {self.type.name()}>"
