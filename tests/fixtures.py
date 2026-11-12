"""
Test data: what the generator would produce from model.yaml / content.yaml —
definition entries as Python dicts (the JSON IR).

Expressions and target paths are Python functions behind the InnerFunction /
TargetPath interfaces, because the parser is out of scope. Each ``Fn`` / ``Path``
carries the expression text it stands for, so traces and errors stay readable.

Deviations from doc/rewrite/*.yaml, to stay inside this prototype:

- damage is a plain int (no Dice / Damage types yet),
- no grants, events or actions — only a ``granted`` container to test its API,
- ``material.power ?? 0`` and similar null handling is written out in Python.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable

from Definitions import DefinitionStore
from InnerFunction import EvalContext, InnerFunction, TargetPath
from Instance import Instance


class Fn(InnerFunction):
    """An expression written as a Python function of the EvalContext."""

    def __init__(self, text: str, func: Callable[[EvalContext], Any]):
        self.text = text
        self.func = func

    def evaluate(self, ctx: EvalContext) -> Any:
        return self.func(ctx)

    def describe(self) -> str:
        return self.text


class Path(TargetPath):
    """A target path written as a Python function of the source instance."""

    def __init__(self, text: str, func: Callable[[Instance], Iterable | None]):
        self.text = text
        self.func = func

    def resolve(self, source: Instance) -> list:
        return [prop for prop in (self.func(source) or []) if prop is not None]

    def describe(self) -> str:
        return self.text


# ---------------------------------------------------------------------- path helpers


def own(prop_id: str) -> Path:
    """``<prop>`` — a prop of the source itself."""
    return Path(prop_id, lambda source: [source.prop(prop_id)])


def on_owner(prop_id: str) -> Path:
    """``owner.<prop>`` — inert while unattached or when the owner has no such prop."""

    def resolve(source: Instance):
        owner = source.owner
        return [owner.prop(prop_id)] if owner is not None and prop_id in owner.props else []

    return Path(f"owner.{prop_id}", resolve)


def on_entity(container_id: str, prop_id: str, keys=None) -> Path:
    """
    ``entity.<container>[keys].<prop>``. ``keys``: ``None`` for a single container,
    a list of literal keys, or a function of the source (``[stat]``).
    """

    def resolve(source: Instance):
        entity = source.entity
        if entity is None:
            return []
        container = entity.container(container_id)
        if keys is None:
            children = [container.get()]
        else:
            children = [container.get(key) for key in (keys(source) if callable(keys) else keys)]
        return [child.prop(prop_id) for child in children if child is not None]

    shown = "" if keys is None else f"[{'stat' if callable(keys) else ', '.join('.' + k for k in keys)}]"
    return Path(f"entity.{container_id}{shown}.{prop_id}", resolve)


def get(name: str) -> Fn:
    """The expression ``<name>``: an own prop."""
    return Fn(name, lambda c: c.this.get(name))


# ---------------------------------------------------------------------- expression helpers


def _material(this: Instance) -> Instance | None:
    return this.container("material").get()


def _anti_magic(this: Instance) -> int:
    entity = this.entity
    return entity.container("magic").get().get("antiMagic") if entity is not None else 0


def _owner_power(this: Instance) -> float:
    owner = this.owner
    return owner.get("power") if owner is not None else 10


def _overloaded(this: Instance) -> bool:
    entity = this.entity
    return entity is not None and entity.get("carryWeight") > entity.get("carryLimit")


# ---------------------------------------------------------------------- model

MODEL: list[dict] = [
    {
        "id": "entity",
        "abstract": True,
        "props": {
            "level": {"type": "int", "source": "choice", "default": 1, "range": [1, 20]},
            "featCount": {
                "type": "int",
                "modifiable": True,
                "derive": Fn("1 + floor(level / 4)", lambda c: 1 + c.this.get("level") // 4),
            },
            "carryWeight": {
                "type": "number",
                "derive": Fn(
                    "sum(inventory[*].weight) + sum(equipment[*].weight)",
                    lambda c: sum(i.get("weight") for i in c.this.container("inventory").all())
                    + sum(i.get("weight") for i in c.this.container("equipment").all()),
                ),
            },
            "carryLimit": {
                "type": "number",
                "modifiable": True,
                "derive": Fn(
                    "attributes.str.value * 10",
                    lambda c: c.this.container("attributes").get("str").get("value") * 10,
                ),
            },
        },
        "contains": {
            "attributes": {"of": "attribute", "map": "Attribute", "fixed": True},
            "speed": {"of": "speed", "fixed": True},
            "magic": {"of": "magic", "fixed": True},
            "inventory": {"of": "item", "list": True, "activates": False},  # backpack: effects stay inside
            "equipment": {"of": "equipment", "map": "Slot"},
            "feats": {"of": "feat", "list": True, "unique": True, "limit": get("featCount")},
            "conditions": {"of": "condition", "list": True, "seed": ["overloaded"]},
            "actions": {"of": "action", "list": True, "granted": True},
        },
    },
    {"id": "character", "name": "Character", "extends": "entity"},
    {
        "id": "attribute",
        "props": {
            "value": {"type": "int", "source": "choice", "default": 10, "range": [1, 30], "modifiable": True},
            "mod": {"type": "int", "derive": Fn("floor((value - 10) / 2)", lambda c: math.floor((c.this.get("value") - 10) / 2))},
            "advantage": {"type": "int", "default": 0, "modifiable": True},
        },
    },
    {
        "id": "speed",
        "props": {
            "walking": {"type": "int", "default": 30, "modifiable": True, "clamp": [0, None]},
            "flying": {"type": "int", "default": 0, "modifiable": True},
        },
    },
    {"id": "magic", "props": {"antiMagic": {"type": "int", "default": 0, "modifiable": True}}},
    # ── items ──
    {
        "id": "item",
        "abstract": True,
        "props": {
            "baseValue": {"type": "number"},
            "weight": {"type": "number", "modifiable": True},
            "stack": {"type": "int", "source": "state", "default": 1, "range": [1, None]},
            "power": {"type": "number", "default": 0, "modifiable": True},
            "value": {
                "type": "number",
                "derive": Fn(
                    "power > 0 ? power ^ 2 : baseValue",
                    lambda c: c.this.get("power") ** 2 if c.this.get("power") > 0 else c.this.get("baseValue"),
                ),
            },
        },
        "effects": [{"target": own("weight"), "mul": get("stack"), "label": "× stack"}],
    },
    {
        "id": "equipment",
        "extends": "item",
        "abstract": True,
        "props": {"requiredMaterial": {"type": "MaterialRequired", "default": "any"}},
        "contains": {
            "enchantments": {"of": "enchantment", "list": True},
            "material": {
                "of": "material",
                "optional": True,
                "accepts": Fn(
                    "it.category == .any or requiredMaterial == .any or (it.category == .metal) == (requiredMaterial == .metal)",
                    lambda c: c.it.get("category") == "any"
                    or c.this.get("requiredMaterial") == "any"
                    or (c.it.get("category") == "metal") == (c.this.get("requiredMaterial") == "metal"),
                ),
            },
        },
        "effects": [
            {
                "target": own("power"),
                "add": Fn(
                    "sum(enchantments[*].power) + (material?.power ?? 0)",
                    lambda c: sum(e.get("power") for e in c.this.container("enchantments").all())
                    + (_material(c.this).get("power") if _material(c.this) is not None else 0),
                ),
                "label": "enchantments + material",
            },
            {
                "target": own("weight"),
                "mul": Fn("material.weightMod", lambda c: _material(c.this).get("weightMod")),
                "when": Fn("material != null", lambda c: _material(c.this) is not None),
                "label": "material weight",
            },
        ],
    },
    {
        "id": "weapon",
        "extends": "equipment",
        "abstract": True,
        "props": {
            "martial": {"type": "bool"},
            "damage": {"type": "int", "modifiable": True},
        },
    },
    {
        "id": "armor",
        "extends": "equipment",
        "abstract": True,
        "props": {"baseAC": {"type": "int", "modifiable": True}},
    },
    {
        "id": "material",
        "abstract": True,
        "appliesTo": ["equipment"],
        "props": {
            "weightMod": {"type": "number"},
            "power": {"type": "number", "default": 0},
            "category": {"type": "MaterialCategory"},
        },
    },
    {
        "id": "enchantment",
        "abstract": True,
        "appliesTo": ["equipment"],
        "props": {
            "maxLevel": {"type": "int", "default": 1},
            "level": {"type": "int", "source": "choice", "default": 1, "range": [1, get("maxLevel")]},
            "power": {"type": "number"},
            "magic": {"type": "bool", "default": True},
        },
        # anti-magic, written once for every enchantment (today: Enchantment.isSuppressed)
        "active": Fn(
            "not magic or (entity?.magic.antiMagic ?? 0) <= (owner?.power ?? 10)",
            lambda c: not c.this.get("magic") or _anti_magic(c.this) <= _owner_power(c.this),
        ),
    },
    {"id": "feat", "abstract": True},
    {
        "id": "condition",
        "abstract": True,
        "props": {"level": {"type": "int", "source": "state", "default": 1, "range": [1, None]}},
    },
    {"id": "action", "abstract": True},
]

# ---------------------------------------------------------------------- content

CONTENT: list[dict] = [
    {
        "id": "battleaxe",
        "name": "Battleaxe",
        "extends": "weapon",
        "set": {"martial": True, "requiredMaterial": "metal", "baseValue": 10, "weight": 4, "damage": 8},
    },
    {
        "id": "dagger",
        "name": "Dagger",
        "extends": "weapon",
        "set": {"martial": False, "baseValue": 2, "weight": 1, "damage": 4},
    },
    {
        "id": "padded-armor",
        "name": "Padded Armor",
        "extends": "armor",
        "set": {"requiredMaterial": "notMetal", "baseValue": 5, "weight": 8, "baseAC": 11},
    },
    {"id": "rope", "name": "Rope", "extends": "item", "set": {"baseValue": 1, "weight": 10}},
    {"id": "steel", "name": "Steel", "extends": "material", "set": {"weightMod": 1.5, "power": 1, "category": "metal"}},
    {"id": "oak", "name": "Oak", "extends": "material", "set": {"weightMod": 0.5, "category": "wood"}},
    {
        "id": "leather",
        "name": "Leather",
        "extends": "material",
        "appliesTo": ["armor"],  # replaces `applicableOnWeapon: false`
        "set": {"weightMod": 1, "category": "wood"},
    },
    {
        "id": "ability-score-boost",
        "name": Fn("Ability Score Boost {level}", lambda c: f"Ability Score Boost {c.this.get('level')}"),
        "extends": "enchantment",
        "props": {"stat": {"type": "Attribute", "source": "choice", "default": "str"}},
        "set": {"maxLevel": 3, "power": Fn("2.5 * level + 1", lambda c: 2.5 * c.this.get("level") + 1)},
        "effects": [
            {
                "target": on_entity("attributes", "value", keys=lambda source: [source.get("stat")]),
                "add": Fn("2 * level + 1", lambda c: 2 * c.this.get("level") + 1),
                "label": Fn(
                    "Your {stat} increases by {2 * level + 1}",
                    lambda c: f"Your {c.this.get('stat')} increases by {2 * c.this.get('level') + 1}",
                ),
            }
        ],
        "text": "A shimmering rune that strengthens its wearer.",
    },
    {
        "id": "keen",
        "name": "Keen",
        "extends": "enchantment",
        "appliesTo": ["weapon"],
        "set": {"maxLevel": 5, "magic": False, "power": Fn("1.25 * level + 2", lambda c: 1.25 * c.this.get("level") + 2)},
        "effects": [
            {
                "target": on_owner("damage"),
                "add": get("level"),
                "label": Fn("+{level} damage", lambda c: f"+{c.this.get('level')} damage"),
            }
        ],
    },
    {
        "id": "flaming",
        "name": "Flaming",
        "extends": "enchantment",
        "appliesTo": ["weapon"],
        "set": {"maxLevel": 3, "power": Fn("1.5 * level + 3", lambda c: 1.5 * c.this.get("level") + 3)},
        "effects": [{"target": on_owner("damage"), "add": Fn("2 * level", lambda c: 2 * c.this.get("level"))}],
    },
    {
        "id": "fleet-footed",
        "name": "Fleet-Footed",
        "extends": "feat",
        "effects": [{"target": on_entity("speed", "walking"), "add": 10}],
    },
    {
        "id": "slow-and-steady",
        "name": "Slow and Steady",
        "extends": "feat",
        "effects": [{"target": on_entity("speed", "walking"), "add": -5}],
    },
    {"id": "alert", "name": "Alert", "extends": "feat"},
    {
        "id": "overloaded",
        "name": "Overloaded",
        "extends": "condition",
        "active": Fn("entity != null and entity.carryWeight > entity.carryLimit", lambda c: _overloaded(c.this)),
        "effects": [
            {
                "target": on_entity("attributes", "advantage", keys=["str", "dex", "con"]),
                "add": -1,
                "label": "disadvantage on STR, DEX and CON",
            },
            {"target": on_entity("speed", "walking"), "add": -20},
        ],
    },
    {
        "id": "anti-magic-field",
        "name": "Anti-Magic Field",
        "extends": "condition",
        "effects": [{"target": on_entity("magic", "antiMagic"), "add": 50}],
    },
    {"id": "dash", "name": "Dash", "extends": "action"},
]


def make_store(*extra: dict) -> DefinitionStore:
    """A fresh store with the model, the content and ``extra`` entries."""
    return DefinitionStore([*MODEL, *CONTENT, *extra])


def new(def_id: str, data=None, store: DefinitionStore | None = None, **params) -> Instance:
    return Instance(def_id, data, store=store if store is not None else make_store(), params=params)


def attribute(entity: Instance, key: str, prop: str = "value"):
    return entity.container("attributes").get(key).get(prop)


def walking(entity: Instance) -> int:
    return entity.container("speed").get().get("walking")


def snapshot(root: Instance) -> dict[tuple[str, str], Any]:
    """Every resolved value in the tree, keyed by (instance path, prop id)."""
    return {
        (str(instance.path), prop_id): prop.resolve()
        for instance in root.walk()
        for prop_id, prop in instance.props.items()
    }
