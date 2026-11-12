"""Effects across the tree: owner / entity targets, guards, the backpack boundary, re-binding."""
import unittest

from engine.errors import BindingError
from engine.instance.Instance import Instance
from tests.fixtures import attribute, make_game, new, register_game, snapshot, walking
from tests.ir import ENTITY, OWNER, key, lit, path


class OwnerEffectTest(unittest.TestCase):
    def test_an_enchantment_changes_its_weapon_and_follows_its_level(self):
        dagger = new("dagger")
        keen = dagger.container("enchantments").add("keen")
        self.assertEqual(dagger.get("damage"), 5)
        keen.prop("level").choose(3)
        self.assertEqual(dagger.get("damage"), 7)
        dagger.container("enchantments").remove(keen.uid)
        self.assertEqual(dagger.get("damage"), 4)
        self.assertEqual(keen.prop("level").resolve(), 3)  # the removed enchantment keeps its choice

    def test_own_effects_work_on_a_stand_alone_item(self):
        axe = new("battleaxe")
        self.assertEqual(axe.get("weight"), 4)
        axe.container("material").add("steel")
        self.assertEqual(axe.get("weight"), 6)  # × steel 1.5
        self.assertEqual(axe.get("power"), 1)
        self.assertEqual(axe.get("value"), 1)  # power 1 → 1²

    def test_trace_lists_every_effect_in_order_with_labels(self):
        axe = new("battleaxe")
        axe.container("material").add("steel")
        axe.prop("stack").write(2)
        labels = [m.description for m in axe.prop("weight").get_manipulation_trace()]
        self.assertEqual(labels, ["Battleaxe: × stack", "Battleaxe: material weight"])
        self.assertEqual(axe.get("weight"), 12)


class EntityEffectTest(unittest.TestCase):
    def test_entity_effects_are_inert_until_the_source_is_on_an_entity(self):
        char = new("character")
        dagger = char.spawn("dagger")
        dagger.container("enchantments").add("ability-score-boost")
        self.assertEqual(attribute(char, "str"), 10)

        char.container("equipment").add(dagger, "mainHand")
        self.assertEqual(attribute(char, "str"), 13)

        char.container("equipment").remove("mainHand")
        self.assertEqual(attribute(char, "str"), 10)

    def test_a_choice_moves_the_target(self):
        char = new("character")
        dagger = char.container("equipment").add("dagger", "mainHand")
        boost = dagger.container("enchantments").add("ability-score-boost")
        boost.prop("stat").choose("dex")
        self.assertEqual((attribute(char, "str"), attribute(char, "dex")), (10, 13))
        boost.prop("level").choose(3)
        self.assertEqual(attribute(char, "dex"), 17)
        trace = char.container("attributes").get("dex").prop("value").get_manipulation_trace()
        self.assertEqual([m.description for m in trace], ["Ability Score Boost 3: Your dex increases by 7"])

    def test_effects_follow_an_item_to_another_entity(self):
        alice, bob = new("character"), new("character")
        dagger = alice.container("equipment").add("dagger", "mainHand")
        dagger.container("enchantments").add("ability-score-boost")
        self.assertEqual(attribute(alice, "str"), 13)

        bob.container("equipment").add(dagger, "offHand")
        self.assertEqual((attribute(alice, "str"), attribute(bob, "str")), (10, 13))

    def test_an_items_own_effects_survive_leaving_a_tree(self):
        # The old root re-binds batched (after the item is its own root again);
        # it must not take the item's own effects with it.
        alice, bob = new("character"), new("character")
        axe = alice.container("equipment").add("battleaxe", "mainHand")
        axe.container("material").add("steel")
        self.assertEqual(axe.get("weight"), 6)

        alice.container("equipment").remove("mainHand")
        self.assertEqual(axe.get("weight"), 6)

        alice.container("equipment").add(axe, "mainHand")
        with alice.batch():  # move while the old root's re-bind is deferred
            bob.container("equipment").add(axe, "mainHand")
        self.assertEqual(axe.get("weight"), 6)
        self.assertEqual([m.description for m in axe.prop("weight").get_manipulation_trace()],
                         ["Battleaxe: × stack", "Battleaxe: material weight"])

    def test_one_path_can_hit_several_properties(self):
        char = new("character")
        rope = char.container("inventory").add("rope")
        rope.prop("stack").write(11)  # 110 > carry limit 100 → overloaded
        advantages = {key: attribute(char, key, "advantage") for key in ("str", "dex", "con", "wis")}
        self.assertEqual(advantages, {"str": -1, "dex": -1, "con": -1, "wis": 0})


class BackpackTest(unittest.TestCase):
    def test_items_in_the_backpack_affect_themselves_but_not_the_entity(self):
        char = new("character")
        dagger = char.container("inventory").add("dagger")
        dagger.container("enchantments").add("keen")
        dagger.container("enchantments").add("ability-score-boost")
        self.assertEqual(dagger.get("damage"), 5)  # keen still works inside the dagger
        self.assertEqual(attribute(char, "str"), 10)  # the boost does not reach out

        char.container("equipment").add(dagger, "mainHand")  # equip it
        self.assertEqual(attribute(char, "str"), 13)
        self.assertEqual(dagger.get("damage"), 5)


class GuardTest(unittest.TestCase):
    def test_anti_magic_suppresses_magic_enchantments_only(self):
        char = new("character")
        dagger = char.container("equipment").add("dagger", "mainHand")
        dagger.container("enchantments").add("keen")  # not magic: +1
        dagger.container("enchantments").add("flaming")  # magic: +2
        self.assertEqual(dagger.get("damage"), 7)

        field = char.container("conditions").add("anti-magic-field")
        self.assertEqual(dagger.get("damage"), 5)
        flaming = [m for m in dagger.prop("damage").get_manipulation_trace() if m.source.def_id == "flaming"][0]
        self.assertFalse(flaming.is_applicable())  # still bound, but inert

        char.container("conditions").remove_instance(field)
        self.assertEqual(dagger.get("damage"), 7)

    def test_a_state_driven_condition_reacts_to_the_whole_chain(self):
        char = new("character")
        rope = char.container("inventory").add("rope")
        self.assertEqual(walking(char), 30)

        rope.prop("stack").write(11)  # carry weight 110 > limit 100
        self.assertEqual(walking(char), 10)
        self.assertEqual(attribute(char, "str", "advantage"), -1)

        dagger = char.container("equipment").add("dagger", "mainHand")  # +1 weight
        dagger.container("enchantments").add("ability-score-boost")  # str 13 → limit 130
        self.assertEqual(char.get("carryWeight"), 111)
        self.assertEqual(walking(char), 30)
        self.assertEqual(attribute(char, "str", "advantage"), 0)

    def test_clamp_holds_after_all_effects(self):
        game = make_game({
            "id": "lead-boots",
            "extends": "feat",
            "effects": [{"target": path(ENTITY, "speed", "walking"), "add": -25}],
        })
        char = new("character", game)
        char.container("feats").add("lead-boots")
        self.assertEqual(walking(char), 5)
        char.container("inventory").add("rope").prop("stack").write(20)  # overloaded: -20
        self.assertEqual(walking(char), 0)  # clamp [0, null] after every effect


class DeterminismTest(unittest.TestCase):
    def test_the_order_of_adding_does_not_change_results_or_traces(self):
        first, second = new("character"), new("character")
        first.container("feats").add("fleet-footed")
        first.container("feats").add("slow-and-steady")
        second.container("feats").add("slow-and-steady")
        second.container("feats").add("fleet-footed")

        def trace(char):
            # the trace also lists bound but inert effects (Overloaded) — the sheet can grey them out
            prop = char.container("speed").get().prop("walking")
            return [m.description for m in prop.get_manipulation_trace() if m.is_applicable()]

        self.assertEqual(walking(first), walking(second))
        self.assertEqual(trace(first), trace(second))
        self.assertEqual(trace(first), ["Fleet-Footed: add 10", "Slow and Steady: add -5"])

    def test_loading_does_not_depend_on_container_order(self):
        char = new("character")
        char.container("attributes").get("str").prop("value").choose(12)
        dagger = char.container("equipment").add("dagger", "mainHand")
        dagger.container("enchantments").add("ability-score-boost")
        dagger.container("enchantments").add("keen")
        char.container("inventory").add("rope").prop("stack").write(13)
        char.container("feats").add("fleet-footed")
        # suppresses the boost → str 12 → limit 120 < 131 → overloaded: a long chain to restore
        char.container("conditions").add("anti-magic-field")
        self.assertEqual(walking(char), 20)

        loaded = Instance(char.to_data())
        self.assertEqual(snapshot(loaded), snapshot(char))


#: A board with cells keyed by attribute; tools on it change a cell's ``x``.
#: A ``soft`` cell's x is modifiable, a ``hard`` cell's is not.
BOARD = [
    {"id": "board", "contains": {"cells": {"of": "cell", "map": "Attribute"}, "tools": {"of": "tool-base", "list": True}}},
    {"id": "cell", "abstract": True},
    {"id": "soft", "extends": "cell", "props": {"x": {"type": "int", "default": 0, "modifiable": True}}},
    {"id": "hard", "extends": "cell", "props": {"x": {"type": "int", "default": 0}}},
    {"id": "tool-base", "abstract": True},
    {   # owner.cells[which].x += 1
        "id": "tool", "extends": "tool-base",
        "props": {"which": {"type": "Attribute", "source": "choice", "default": "str"}},
        "effects": [{"target": path(OWNER, "cells", key(path("which", type="Attribute")), "x"), "add": 1}],
    },
    {   # the tool's own effect binds, the second one cannot (dex is hard)
        "id": "bad-tool", "extends": "tool",
        "effects": [{"target": path(OWNER, "cells", key(lit("dex", "Attribute")), "x"), "add": 1}],
    },
    {   # the target key is a state value: writing it would not re-bind
        "id": "stateful-tool", "extends": "tool-base",
        "props": {"which": {"type": "Attribute", "source": "state", "default": "str"}},
        "effects": [{"target": path(OWNER, "cells", key(path("which", type="Attribute")), "x"), "add": 1}],
    },
]


class BindingSafetyTest(unittest.TestCase):
    def setUp(self):
        self.board = Instance.new("board", register_game(*BOARD))
        cells = self.board.container("cells")
        self.soft = cells.add("soft", "str")
        self.hard = cells.add("hard", "dex")

    def test_an_add_that_cannot_be_bound_is_rolled_back(self):
        tools = self.board.container("tools")
        with self.assertRaisesRegex(BindingError, "not modifiable"):
            tools.add("bad-tool")
        self.assertEqual(len(tools), 0)
        self.assertEqual(self.soft.get("x"), 0)  # no effect of the refused tool stayed bound
        tools.add("tool")  # the tree still works
        self.assertEqual(self.soft.get("x"), 1)

    def test_a_choice_that_cannot_be_bound_is_taken_back(self):
        tool = self.board.container("tools").add("tool")
        self.assertEqual(self.soft.get("x"), 1)
        with self.assertRaisesRegex(BindingError, "not modifiable"):
            tool.prop("which").choose("dex")
        self.assertEqual(tool.get("which"), "str")
        self.assertEqual((self.soft.get("x"), self.hard.get("x")), (1, 0))

    def test_a_load_that_cannot_be_bound_reverts_a_live_instance(self):
        self.board.container("tools").add("tool")
        before = self.board.to_data()
        broken = before.to_dict()
        broken["children"]["tools"] = [{"def": "bad-tool"}]
        with self.assertRaises(BindingError):
            self.board.load(broken)
        self.assertEqual(self.board.to_data(), before)
        # load rebuilds non-fixed children, so read the cell anew
        self.assertEqual(self.board.container("cells").get("str").get("x"), 1)

    def test_a_target_may_not_read_a_state_value(self):
        tools = self.board.container("tools")
        with self.assertRaisesRegex(BindingError, "which is a state value"):
            tools.add("stateful-tool")
        self.assertEqual(len(tools), 0)


if __name__ == "__main__":
    unittest.main()
