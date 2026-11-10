import unittest

from Definitions import DefinitionStore
from Instance import Instance
from datatype.Operation import Operation
from errors import (
    CyclicDependencyError,
    DefinitionError,
    IllegalMutationError,
    PropertyError,
)
from property.Manipulation import Manipulation
from tests.fixtures import Fn, get, own

COUNTER = {
    "id": "counter",
    "props": {
        "maxLevel": {"type": "int", "default": 3},
        "level": {"type": "int", "source": "choice", "default": 1, "range": [1, get("maxLevel")]},
        "double": {"type": "int", "derive": Fn("2 * level", lambda c: 2 * c.this.get("level"))},
        "max": {"type": "int", "default": 10},
        "current": {"type": "int", "source": "state", "default": get("max"), "range": [0, get("max")]},
        "dmgType": {"type": "DamageType", "source": "choice", "default": "fire", "options": ["fire", "cold", "lightning"]},
        "note": {"type": "text", "optional": True},
    },
}


def build(*entries, **params) -> Instance:
    """Instantiate the last of ``entries`` from a store holding them and COUNTER."""
    store = DefinitionStore([COUNTER, *entries])
    return Instance(entries[-1]["id"], store=store, params=params)


def counter() -> Instance:
    return Instance("counter", store=DefinitionStore([COUNTER]))


class SourceTest(unittest.TestCase):
    def test_const_default_and_optional(self):
        inst = counter()
        self.assertEqual(inst.get("max"), 10)
        self.assertIsNone(inst.get("note"))

    def test_derived_value_follows_its_inputs(self):
        inst = counter()
        self.assertEqual(inst.get("double"), 2)
        inst.prop("level").choose(3)
        self.assertEqual(inst.get("double"), 6)

    def test_choose_checks_the_range_with_an_expression_bound(self):
        inst = counter()
        with self.assertRaisesRegex(PropertyError, "outside the range"):
            inst.prop("level").choose(4)
        child = build({"id": "big", "extends": "counter", "set": {"maxLevel": 5}})
        child.prop("level").choose(4)
        self.assertEqual(child.get("level"), 4)

    def test_choose_checks_options(self):
        inst = counter()
        with self.assertRaisesRegex(PropertyError, "not one of"):
            inst.prop("dmgType").choose("psychic")
        inst.prop("dmgType").choose("cold")
        self.assertEqual(inst.get("dmgType"), "cold")

    def test_reviewed_tracks_an_explicit_choice_even_of_the_default(self):
        prop = counter().prop("level")
        self.assertFalse(prop.reviewed)
        prop.choose(1)
        self.assertTrue(prop.reviewed)
        prop.reset()
        self.assertFalse(prop.reviewed)

    def test_only_choice_props_can_be_chosen_and_only_state_props_written(self):
        inst = counter()
        with self.assertRaisesRegex(PropertyError, "only choice properties"):
            inst.prop("max").choose(3)
        with self.assertRaisesRegex(PropertyError, "only state properties"):
            inst.prop("level").write(2)

    def test_state_follows_its_default_until_written_and_is_clamped(self):
        inst = counter()
        self.assertEqual(inst.get("current"), 10)
        inst.prop("current").write(15)
        self.assertEqual(inst.get("current"), 10)
        inst.prop("current").write(-3)
        self.assertEqual(inst.get("current"), 0)
        inst.prop("current").write(4)
        self.assertEqual(inst.get("current"), 4)

    def test_param_is_bound_by_the_creator(self):
        entry = {
            "id": "greeting",
            "props": {
                "who": {"type": "text", "source": "param", "default": "world"},
                "line": {"type": "text", "derive": Fn("'hello ' + who", lambda c: "hello " + c.this.get("who"))},
            },
        }
        self.assertEqual(build(entry).get("line"), "hello world")
        self.assertEqual(build(entry, who="Ada").get("line"), "hello Ada")


class DefinitionTest(unittest.TestCase):
    def test_derived_props_cannot_be_set(self):
        with self.assertRaisesRegex(DefinitionError, "derived; it cannot be set"):
            build({"id": "bad", "extends": "counter", "set": {"double": 3}})

    def test_refine_can_lock_a_choice(self):
        inst = build({"id": "fixed", "extends": "counter", "refine": {"level": {"lock": 2}}})
        self.assertEqual(inst.get("level"), 2)
        with self.assertRaisesRegex(PropertyError, "locked"):
            inst.prop("level").choose(1)

    def test_refine_narrows_the_range(self):
        inst = build({"id": "narrow", "extends": "counter", "refine": {"level": {"range": [2, 2], "default": 2}}})
        self.assertEqual(inst.get("level"), 2)
        with self.assertRaises(PropertyError):
            inst.prop("level").choose(1)

    def test_unknown_spec_key_suggests_the_closest(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'default'"):
            build({"id": "typo", "props": {"x": {"type": "int", "defualt": 1}}})

    def test_range_on_an_unordered_type_is_rejected(self):
        with self.assertRaisesRegex(DefinitionError, "has no order"):
            build({"id": "bad", "props": {"x": {"type": "text", "default": "a", "range": ["a", "z"]}}})


ORDERED = {
    "id": "ordered",
    "props": {"x": {"type": "int", "default": 10, "modifiable": True}},
    "effects": [  # deliberately declared out of order
        {"target": own("x"), "atMost": 30},
        {"target": own("x"), "mul": 3},
        {"target": own("x"), "add": 2},
    ],
}


class ManipulationTest(unittest.TestCase):
    def test_effects_compute_then_clamp_regardless_of_declaration_order(self):
        inst = build(ORDERED)
        self.assertEqual(inst.get("x"), 30)  # (10 + 2) * 3 = 36, then atMost 30
        ops = [m.operation.name() for m in inst.prop("x").get_manipulation_trace()]
        self.assertEqual(ops, ["add", "mul", "atMost"])

    def test_priority_stages_run_before_operation_order(self):
        inst = build({
            "id": "staged",
            "props": {"x": {"type": "int", "default": 10, "modifiable": True}},
            "effects": [
                {"target": own("x"), "add": 2},
                {"target": own("x"), "override": 5, "priority": "base"},
                {"target": own("x"), "atMost": 20, "priority": "final"},
                {"target": own("x"), "mul": 3},
            ],
        })
        self.assertEqual(inst.get("x"), 20)  # base: override 5 → +2 → ×3 = 21 → final: atMost 20

    def test_transform_sees_previous(self):
        inst = build({
            "id": "halved",
            "props": {"x": {"type": "int", "default": 9, "modifiable": True}},
            "effects": [{"target": own("x"), "transform": Fn("previous // 2", lambda c: c.previous // 2)}],
        })
        self.assertEqual(inst.get("x"), 4)

    def test_when_gates_a_single_effect(self):
        inst = build({
            "id": "gated",
            "extends": "counter",
            "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
            "effects": [{"target": own("x"), "add": 100, "when": Fn("level >= 2", lambda c: c.this.get("level") >= 2)}],
        })
        self.assertEqual(inst.get("x"), 1)
        inst.prop("level").choose(2)
        self.assertEqual(inst.get("x"), 101)

    def test_clamp_applies_after_all_effects(self):
        inst = build({
            "id": "clamped",
            "props": {"x": {"type": "int", "default": 3, "modifiable": True, "clamp": [1, None]}},
            "effects": [{"target": own("x"), "add": -10}],
        })
        self.assertEqual(inst.get("x"), 1)

    def test_static_manipulation_belongs_to_the_property(self):
        inst = build(ORDERED)
        inst.prop("x").add_static_manipulation(
            Manipulation(Operation.get("atLeast"), 50, priority="final", label="minimum 50")
        )
        self.assertEqual(inst.get("x"), 50)
        self.assertEqual(inst.prop("x").get_manipulation_trace()[-1].description, "minimum 50")

    def test_effects_on_non_modifiable_props_are_rejected(self):
        with self.assertRaisesRegex(PropertyError, "not modifiable"):
            build({"id": "bad", "extends": "counter", "effects": [{"target": own("max"), "add": 1}]})

    def test_effect_with_two_operations_is_rejected(self):
        with self.assertRaisesRegex(DefinitionError, "exactly one operation"):
            build({"id": "bad", "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
                   "effects": [{"target": own("x"), "add": 1, "mul": 2}]})

    def test_unknown_effect_key_suggests_the_closest(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'atLeast'"):
            build({"id": "bad", "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
                   "effects": [{"target": own("x"), "atleast": 1}]})


class ObserverTest(unittest.TestCase):
    def test_cyclic_base_values_raise(self):
        with self.assertRaises(CyclicDependencyError):
            build({
                "id": "loop",
                "props": {
                    "a": {"type": "int", "derive": get("b")},
                    "b": {"type": "int", "derive": get("a")},
                },
            }).get("a")

    def test_cycle_through_effects_returns_the_partial_value_and_warns(self):
        inst = build({
            "id": "loop",
            "props": {
                "a": {"type": "int", "default": 1, "modifiable": True},
                "b": {"type": "int", "default": 1, "modifiable": True},
            },
            "effects": [
                {"target": own("a"), "add": get("b")},
                {"target": own("b"), "add": get("a")},
            ],
        })
        with self.assertLogs("engine", "WARNING") as logs:
            self.assertEqual(inst.get("a"), 3)  # b sees a's partial value 1
        self.assertIn("cyclic dependency", logs.output[0])

    def test_changing_a_value_during_a_resolve_is_blocked(self):
        inst = build({
            "id": "sneaky",
            "extends": "counter",
            "props": {"bad": {"type": "int", "derive": Fn("choose", lambda c: c.this.prop("level").choose(2) or 0)}},
        })
        with self.assertRaises(IllegalMutationError):
            inst.get("bad")
        self.assertEqual(inst.get("level"), 1)

    def test_values_are_cached_until_an_input_changes(self):
        calls = []
        inst = build({
            "id": "counted",
            "extends": "counter",
            "props": {"y": {"type": "int", "derive": Fn("level", lambda c: calls.append(1) or c.this.get("level"))}},
        })
        inst.get("y")
        inst.get("y")
        self.assertEqual(len(calls), 1)
        inst.prop("dmgType").choose("cold")  # not read by y
        inst.get("y")
        self.assertEqual(len(calls), 1)
        inst.prop("level").choose(2)
        self.assertEqual(inst.get("y"), 2)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
