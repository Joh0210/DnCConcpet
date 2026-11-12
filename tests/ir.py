"""
Helpers to write the expression JSON (concept §4.14) by hand — what the parser
will emit from the YAML strings. Every helper returns plain JSON data (dicts,
lists, scalars); nothing here is engine code, and ``json.dumps`` works on all of it.

    2 * level + 1               op("add", op("mul", 2, path("level", type="int")), 1)
    entity?.magic.antiMagic     path(opt(ENTITY), "magic", "antiMagic", type="int")
    inventory[*].weight         path("inventory", ALL, "weight", type="list<number>")
    entity.attributes[stat]     path(ENTITY, "attributes", key(path("stat", type="Attribute")))
"""
from __future__ import annotations

from typing import Any

#: ``null``
NULL = {"value": None, "type": "null"}
#: ``owner`` / ``entity`` — navigation steps.
OWNER = {"to": "owner"}
ENTITY = {"to": "entity"}
#: ``[*]``
ALL = "*"


def lit(value: Any, type: str) -> dict:
    """A static value of a named type — needed for enums (``.metal``); other scalars may stay bare."""
    return {"value": value, "type": type}


def op(name: str, *args: Any) -> dict:
    """An operation; bare scalars among ``args`` are static values typed by their JSON kind."""
    return {"op": name, "args": list(args)}


def path(*steps: Any, type: str | None = None, start: str | None = None) -> dict:
    """A path; ``type`` is required where it is used as a value, ``start`` = ``it`` / ``previous`` / ..."""
    node: dict = {"path": list(steps)}
    if type is not None:
        node["type"] = type
    if start is not None:
        node["from"] = start
    return node


def opt(step: str | dict) -> dict:
    """The segment ``step`` may be absent (``?.``)."""
    return {"get": step, "opt": True} if isinstance(step, str) else {**step, "opt": True}


def key(*keys: Any) -> dict:
    """``[k]`` / ``[k1, k2]`` — keys are values; several fan out."""
    return {"key": list(keys)}


def is_a(def_id: str) -> dict:
    """``[is weapon]``"""
    return {"is": def_id}


def where(predicate: dict) -> dict:
    """``[where <predicate on it>]``"""
    return {"where": predicate}


def template(*parts: Any) -> dict:
    """``"Your {stat} rises"`` → ``template("Your ", path("stat", ...), " rises")``."""
    return op("concat", *parts)
