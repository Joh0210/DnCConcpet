"""
Builds expression nodes from the JSON (concept §4.14)::

    VALUE = STATIC_VALUE | OPERATION | PATH

    STATIC_VALUE  {"value": "<parsable>", "type": "<type id>"}   or a bare JSON scalar
    OPERATION     {"op": "<operation id>", "args": [VALUE, ...]}
    PATH          {"path": [STEP, ...], "type": "<type id>", "from": "<root>"}

The node kind is the one key that only it has (``value`` / ``op`` / ``path``).
This module is the only place that tells the kinds apart (a deliberate choice):
everything else — Property, Manipulation, Container, Instance — holds
:class:`InnerFunction` nodes and just calls ``evaluate``.

Building checks what can be checked without a game running: the shape, the
types (every operation resolves for its argument types), and that the node's
type fits the slot it stands in (``expected``, e.g. the prop's type).
"""
from __future__ import annotations

from typing import Any

from engine.datatype.Datatype import Datatype
from engine.errors import DefinitionError, did_you_mean
from engine.value.InnerFunction import InnerFunction
from engine.value.OperationValue import OperationValue
from engine.value.PathValue import PathValue
from engine.value.StaticValue import StaticValue

#: The key that marks a node kind → the class that builds it.
NODE_KINDS = {"value": StaticValue, "op": OperationValue, "path": PathValue}


def build_value(raw: Any, expected: Datatype | None = None) -> InnerFunction:
    """
    The node for ``raw`` — a VALUE of the JSON, a bare scalar (shorthand for a
    static value, typed by ``expected`` if given), or an already built node.
    Raises :class:`DefinitionError` if it is malformed or its type does not fit
    ``expected``.
    """
    if isinstance(raw, InnerFunction):
        node = raw
    elif isinstance(raw, dict):
        node = _build_node(raw)
    else:
        node = StaticValue.shorthand(raw, expected)
    check_type(node, expected)
    return node


def build_target(raw: Any) -> PathValue:
    """The path an effect targets: a PATH node (its ``type`` is optional — each bound prop has its own)."""
    node = raw if isinstance(raw, PathValue) else _build_node(raw) if isinstance(raw, dict) else None
    if not isinstance(node, PathValue):
        raise DefinitionError(f"a target must be a path ({{'path': [...]}}), got {raw!r}")
    return node


def check_type(node: InnerFunction, expected: Datatype | None) -> None:
    """``node`` may stand where a value of ``expected`` is needed: same type, a widening or null."""
    if node.type is None:
        raise DefinitionError(f"path '{node.describe()}' is used as a value, so it needs a 'type'")
    if expected is not None and expected.converter(node.type) is None:
        raise DefinitionError(
            f"expected {expected.name()}, got {node.type.name()}: {node.describe()}"
        )


def _build_node(raw: dict) -> InnerFunction:
    """The node for one JSON object, after checking it has exactly one kind key and no unknown keys."""
    kinds = [key for key in NODE_KINDS if key in raw]
    if len(kinds) != 1:
        hint = did_you_mean(next(iter(raw), ""), NODE_KINDS) if raw else ""
        raise DefinitionError(
            f"a value needs exactly one of 'value', 'op' or 'path', got {sorted(raw)}{hint}"
        )
    node_class = NODE_KINDS[kinds[0]]
    unknown = set(raw) - node_class.KEYS
    if unknown:
        key = sorted(unknown)[0]
        raise DefinitionError(f"{kinds[0]} node: unknown key '{key}'{did_you_mean(key, node_class.KEYS)}")
    if node_class is StaticValue:
        return StaticValue.from_json(raw)  # a literal has no child nodes to build
    return node_class.from_json(raw, build_value)
