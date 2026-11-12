import unittest

from Instance import Instance
from datatype.Operation import Operation, signature
from errors import (
    CyclicDependencyError,
    DefinitionError,
    IllegalMutationError,
    PropertyError,
)
from property.Manipulation import Manipulation
from tests.fixtures import register_game
from tests.ir import op, path

LEVEL = path("level", type="int")
MAX = path("max", type="int")


def x() -> dict:
    """The target path ``x``."""
    return path("x")


class CountingOperation(Operation):
    """A kernel function that records every call — to observe caching."""

    calls: list = []

    def name(self):
        return "test-count"

    @signature("int", returns="int")
    def count(self, value):
        CountingOperation.calls.append(value)
        return value


class SneakyChooseOperation(Operation):
    """A misbehaving kernel function: it changes a value while a property resolves."""

    lazy = True

    def name(self):
        return "test-sneaky-choose"

    @signature(returns="int")
    def sneak(self, ctx):
        ctx.this.prop("level").choose(2)
        return 0


Operation.register(CountingOperation())
Operation.register(SneakyChooseOperation())

COUNTER = {
    "id": "counter",
    "props": {
        "maxLevel": {"type": "int", "default": 3},
        "level": {"type": "int", "source": "choice", "default": 1, "range": [1, path("maxLevel", type="int")]},
        "double": {"type": "int", "derive": op("mul", 2, LEVEL)},
        "max": {"type": "int", "default": 10},
        "current": {"type": "int", "source": "state", "default": MAX, "range": [0, MAX]},
        "dmgType": {"type": "DamageType", "source": "choice", "default": "fire", "options": ["fire", "cold", "lightning"]},
        "note": {"type": "text", "optional": True},
    },
}


COUNTER_GAME = register_game(COUNTER)


def build(*entries, **params) -> Instance:
    """Instantiate the last of ``entries`` from a new game holding them and COUNTER."""
    return Instance.new(entries[-1]["id"], register_game(COUNTER, *entries), params)


def counter() -> Instance:
    return Instance.new("counter", COUNTER_GAME)


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
                "line": {"type": "text", "derive": op("add", "hello ", path("who", type="text"))},
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
        {"target": x(), "atMost": 30},
        {"target": x(), "mul": 3},
        {"target": x(), "add": 2},
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
                {"target": x(), "add": 2},
                {"target": x(), "override": 5, "priority": "base"},
                {"target": x(), "atMost": 20, "priority": "final"},
                {"target": x(), "mul": 3},
            ],
        })
        self.assertEqual(inst.get("x"), 20)  # base: override 5 → +2 → ×3 = 21 → final: atMost 20

    def test_transform_sees_previous(self):
        inst = build({
            "id": "halved",
            "props": {"x": {"type": "int", "default": 9, "modifiable": True}},
            # floor(previous / 2)
            "effects": [{"target": x(), "transform": op("floor", op("div", path(root="previous", type="int"), 2))}],
        })
        self.assertEqual(inst.get("x"), 4)

    def test_a_fractional_mul_on_an_int_floors(self):
        inst = build({
            "id": "halved",
            "props": {"x": {"type": "int", "default": 7, "modifiable": True}},
            "effects": [{"target": x(), "mul": 0.5}],
        })
        self.assertEqual(inst.get("x"), 3)  # mul(int, number) is a number; assigning it to the int floors

    def test_an_effect_whose_result_does_not_fit_the_prop_is_rejected_when_bound(self):
        with self.assertRaisesRegex(PropertyError, "'add' does not support \\(int, text\\)"):
            build({
                "id": "bad",
                "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
                "effects": [{"target": x(), "add": "oops"}],
            })

    def test_only_effect_operations_are_effects(self):
        with self.assertRaisesRegex(DefinitionError, "unknown key 'sub'"):
            build({"id": "bad", "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
                   "effects": [{"target": x(), "sub": 1}]})

    def test_when_gates_a_single_effect(self):
        inst = build({
            "id": "gated",
            "extends": "counter",
            "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
            "effects": [{"target": x(), "add": 100, "when": op("ge", LEVEL, 2)}],
        })
        self.assertEqual(inst.get("x"), 1)
        inst.prop("level").choose(2)
        self.assertEqual(inst.get("x"), 101)

    def test_clamp_applies_after_all_effects(self):
        inst = build({
            "id": "clamped",
            "props": {"x": {"type": "int", "default": 3, "modifiable": True, "clamp": [1, None]}},
            "effects": [{"target": x(), "add": -10}],
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
            build({"id": "bad", "extends": "counter", "effects": [{"target": path("max"), "add": 1}]})

    def test_effect_with_two_operations_is_rejected(self):
        with self.assertRaisesRegex(DefinitionError, "exactly one operation"):
            build({"id": "bad", "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
                   "effects": [{"target": x(), "add": 1, "mul": 2}]})

    def test_unknown_effect_key_suggests_the_closest(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'atLeast'"):
            build({"id": "bad", "props": {"x": {"type": "int", "default": 1, "modifiable": True}},
                   "effects": [{"target": x(), "atleast": 1}]})


class ObserverTest(unittest.TestCase):
    def test_cyclic_base_values_raise(self):
        with self.assertRaises(CyclicDependencyError):
            build({
                "id": "loop",
                "props": {
                    "a": {"type": "int", "derive": path("b", type="int")},
                    "b": {"type": "int", "derive": path("a", type="int")},
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
                {"target": path("a"), "add": path("b", type="int")},
                {"target": path("b"), "add": path("a", type="int")},
            ],
        })
        with self.assertLogs("engine", "WARNING") as logs:
            self.assertEqual(inst.get("a"), 3)  # b sees a's partial value 1
        self.assertIn("cyclic dependency", logs.output[0])

    def test_changing_a_value_during_a_resolve_is_blocked(self):
        inst = build({
            "id": "sneaky",
            "extends": "counter",
            "props": {"bad": {"type": "int", "derive": op("test-sneaky-choose")}},
        })
        with self.assertRaises(IllegalMutationError):
            inst.get("bad")
        self.assertEqual(inst.get("level"), 1)

    def test_values_are_cached_until_an_input_changes(self):
        calls = CountingOperation.calls
        calls.clear()
        inst = build({
            "id": "counted",
            "extends": "counter",
            "props": {"y": {"type": "int", "derive": op("test-count", LEVEL)}},
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
