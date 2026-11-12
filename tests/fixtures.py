"""
Test data: what the generator would produce from model.yaml / content.yaml —
definition entries as plain JSON (the IR). Every expression is the AST the parser
would write (concept §4.14), spelled with the helpers in ``tests/ir.py``; the
YAML string it stands for is in the comment above it. ``json.dumps(MODEL)`` works:
there is no Python function left in the content.

Deviations from doc/rewrite/*.yaml, to stay inside this prototype:

- damage is a plain int (no Dice / Damage types yet),
- no grants, events or actions — only a ``granted`` container to test its API.
"""
from __future__ import annotations

import itertools
from typing import Any

from engine.definition.DefinitionStore import GAMES, DefinitionStore
from engine.instance.DbData import DbData
from engine.instance.Instance import Instance
from tests.ir import ALL, ENTITY, NULL, OWNER, key, lit, op, opt, path, template

LEVEL = path("level", type="int")

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
                # 1 + floor(level / 4)
                "derive": op("add", 1, op("floor", op("div", LEVEL, 4))),
            },
            "carryWeight": {
                "type": "number",
                # sum(inventory[*].weight) + sum(equipment[*].weight)
                "derive": op(
                    "add",
                    op("sum", path("inventory", ALL, "weight", type="list<number>")),
                    op("sum", path("equipment", ALL, "weight", type="list<number>")),
                ),
            },
            "carryLimit": {
                "type": "number",
                "modifiable": True,
                # attributes.str.value * 10
                "derive": op("mul", path("attributes", key(lit("str", "Attribute")), "value", type="int"), 10),
            },
        },
        "contains": {
            "attributes": {"of": "attribute", "map": "Attribute", "fixed": True},
            "speed": {"of": "speed", "fixed": True},
            "magic": {"of": "magic", "fixed": True},
            "inventory": {"of": "item", "list": True, "activates": False},  # backpack: effects stay inside
            "equipment": {"of": "equipment", "map": "Slot"},
            "feats": {"of": "feat", "list": True, "unique": True, "limit": path("featCount", type="int")},
            "conditions": {"of": "condition", "list": True, "seed": ["overloaded"]},
            "actions": {"of": "action", "list": True, "granted": True},
        },
    },
    {"id": "character", "name": "Character", "extends": "entity"},
    {
        "id": "attribute",
        "props": {
            "value": {"type": "int", "source": "choice", "default": 10, "range": [1, 30], "modifiable": True},
            # floor((value - 10) / 2)
            "mod": {"type": "int", "derive": op("floor", op("div", op("sub", path("value", type="int"), 10), 2))},
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
                # power > 0 ? power ^ 2 : baseValue
                "derive": op(
                    "cond",
                    op("gt", path("power", type="number"), 0),
                    op("pow", path("power", type="number"), 2),
                    path("baseValue", type="number"),
                ),
            },
        },
        "effects": [{"target": path("weight"), "mul": path("stack", type="int"), "label": "× stack"}],
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
                # it.category == .any or requiredMaterial == .any
                #   or (it.category == .metal) == (requiredMaterial == .metal)
                "accepts": op(
                    "or",
                    op("or",
                       op("eq", path("category", start="it", type="MaterialCategory"), lit("any", "MaterialCategory")),
                       op("eq", path("requiredMaterial", type="MaterialRequired"), lit("any", "MaterialRequired"))),
                    op("eq",
                       op("eq", path("category", start="it", type="MaterialCategory"), lit("metal", "MaterialCategory")),
                       op("eq", path("requiredMaterial", type="MaterialRequired"), lit("metal", "MaterialRequired"))),
                ),
            },
        },
        "effects": [
            {
                "target": path("power"),
                # sum(enchantments[*].power) + (material?.power ?? 0)
                "add": op(
                    "add",
                    op("sum", path("enchantments", ALL, "power", type="list<number>")),
                    op("coalesce", path(opt("material"), "power", type="number"), 0),
                ),
                "label": "enchantments + material",
            },
            {
                "target": path("weight"),
                "mul": path("material", "weightMod", type="number"),
                # material != null
                "when": op("ne", path("material", type="ref<material>"), NULL),
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
            "level": {"type": "int", "source": "choice", "default": 1, "range": [1, path("maxLevel", type="int")]},
            "power": {"type": "number"},
            "magic": {"type": "bool", "default": True},
        },
        # anti-magic, written once for every enchantment (today: Enchantment.isSuppressed)
        # not magic or (entity?.magic.antiMagic ?? 0) <= (owner?.power ?? 10)
        "active": op(
            "or",
            op("not", path("magic", type="bool")),
            op(
                "le",
                op("coalesce", path(opt(ENTITY), "magic", "antiMagic", type="int"), 0),
                op("coalesce", path(opt(OWNER), "power", type="number"), 10),
            ),
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
        # "Ability Score Boost {level}"
        "name": template("Ability Score Boost ", LEVEL),
        "extends": "enchantment",
        "props": {"stat": {"type": "Attribute", "source": "choice", "default": "str"}},
        # power: "2.5 * level + 1"
        "set": {"maxLevel": 3, "power": op("add", op("mul", 2.5, LEVEL), 1)},
        "effects": [
            {
                "target": path(ENTITY, "attributes", key(path("stat", type="Attribute")), "value"),
                "add": op("add", op("mul", 2, LEVEL), 1),
                # "Your {stat} increases by {2 * level + 1}"
                "label": template("Your ", path("stat", type="Attribute"), " increases by ",
                                  op("add", op("mul", 2, LEVEL), 1)),
            }
        ],
        "text": "A shimmering rune that strengthens its wearer.",
    },
    {
        "id": "keen",
        "name": "Keen",
        "extends": "enchantment",
        "appliesTo": ["weapon"],
        "set": {"maxLevel": 5, "magic": False, "power": op("add", op("mul", 1.25, LEVEL), 2)},
        "effects": [{"target": path(OWNER, "damage"), "add": LEVEL, "label": template("+", LEVEL, " damage")}],
    },
    {
        "id": "flaming",
        "name": "Flaming",
        "extends": "enchantment",
        "appliesTo": ["weapon"],
        "set": {"maxLevel": 3, "power": op("add", op("mul", 1.5, LEVEL), 3)},
        "effects": [{"target": path(OWNER, "damage"), "add": op("mul", 2, LEVEL)}],
    },
    {
        "id": "fleet-footed",
        "name": "Fleet-Footed",
        "extends": "feat",
        "effects": [{"target": path(ENTITY, "speed", "walking"), "add": 10}],
    },
    {
        "id": "slow-and-steady",
        "name": "Slow and Steady",
        "extends": "feat",
        "effects": [{"target": path(ENTITY, "speed", "walking"), "add": -5}],
    },
    {"id": "alert", "name": "Alert", "extends": "feat"},
    {
        "id": "overloaded",
        "name": "Overloaded",
        "extends": "condition",
        # entity != null and entity.carryWeight > entity.carryLimit
        "active": op(
            "and",
            op("ne", path(ENTITY, type="ref<entity>"), NULL),
            op("gt", path(ENTITY, "carryWeight", type="number"), path(ENTITY, "carryLimit", type="number")),
        ),
        "effects": [
            {
                "target": path(ENTITY, "attributes", key("str", "dex", "con"), "advantage"),
                "add": -1,
                "label": "disadvantage on STR, DEX and CON",
            },
            {"target": path(ENTITY, "speed", "walking"), "add": -20},
        ],
    },
    {
        "id": "anti-magic-field",
        "name": "Anti-Magic Field",
        "extends": "condition",
        "effects": [{"target": path(ENTITY, "magic", "antiMagic"), "add": 50}],
    },
    {"id": "dash", "name": "Dash", "extends": "action"},
]


_game_numbers = itertools.count(1)


def register_game(*entries: dict) -> str:
    """Register a new game holding ``entries`` under a fresh id (game ids are never reused); returns the id."""
    return GAMES.register(DefinitionStore(f"test-{next(_game_numbers)}", entries)).game


def make_game(*extra: dict) -> str:
    """A new game with the model, the content and ``extra`` entries; returns its id."""
    return register_game(*MODEL, *CONTENT, *extra)


#: The game of every test that needs no extra entries. Shared: definitions never change at runtime.
TEST_GAME = GAMES.register(DefinitionStore("test", [*MODEL, *CONTENT])).game


def new(data: str | dict, game: str = TEST_GAME, **params) -> Instance:
    """
    A fresh instance (definition id) or one from a save dict, in ``game`` unless
    the save names one; ``params`` are bound as instance parameters.
    """
    if isinstance(data, str):
        return Instance.new(data, game, params)
    return Instance({"game": game, **data}, params)


def attribute(entity: Instance, key: str, prop: str = "value"):
    return entity.container("attributes").get(key).get(prop)


def walking(entity: Instance) -> int:
    return entity.container("speed").get().get("walking")


def snapshot(root: Instance) -> dict[tuple[str, str], Any]:
    """
    Every resolved value in the tree, keyed by (position, prop id). The position
    names list children by their place, not their uid, so two trees built the same
    way compare equal even if they handed out different uids.
    """
    return {
        (position(instance), prop_id): prop.resolve()
        for instance in root.walk()
        for prop_id, prop in instance.props.items()
    }


def position(instance: Instance) -> str:
    """Like ``str(instance.path)``, with list children numbered by their place instead of their uid."""
    container = instance._contained
    if container is None:
        return instance.def_id
    key = container.key_of(instance)
    if container.keyed_by_uid:
        key = str(container.all_untracked().index(instance))
    return f"{position(container.owner)}/{container.id}:{key}/{instance.def_id}"


def without_uids(data: DbData) -> dict:
    """The JSON form of a save, without uids — what two equally built trees have in common."""
    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: strip(value) for key, value in node.items() if key != "uid"}
        if isinstance(node, list):
            return [strip(value) for value in node]
        return node
    return strip(data.to_dict())
