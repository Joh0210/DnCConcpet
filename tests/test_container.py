import unittest

from engine.errors import ContainerError, IllegalMutationError
from engine.instance.Instance import Instance
from engine.operation.Operation import Operation, signature
from tests.fixtures import make_game, new
from tests.ir import op


class GreedyOperation(Operation):
    """A misbehaving kernel function: it changes structure while a property resolves."""

    lazy = True

    def name(self):
        return "test-greedy-add"

    @signature(returns="int")
    def grab(self, ctx):
        ctx.this.container("items").add("rope")
        return 0


Operation.register(GreedyOperation())


class ShapeTest(unittest.TestCase):
    def test_list_uses_the_lowest_free_numeric_key(self):
        char = new("character")
        inventory = char.container("inventory")
        first = inventory.add("rope")
        inventory.add("dagger")
        self.assertEqual(inventory.keys(), ["0", "1"])
        inventory.remove("0")
        self.assertIsNone(first.contained)
        inventory.add("rope")
        self.assertEqual(inventory.keys(), ["0", "1"])

    def test_single_replaces_its_child(self):
        axe = new("battleaxe")
        steel = axe.container("material").add("steel")
        other = axe.container("material").add("steel")
        self.assertIs(axe.container("material").get(), other)
        self.assertIsNone(steel.contained)
        self.assertIs(steel.root, steel)

    def test_map_needs_a_valid_key(self):
        equipment = new("character").container("equipment")
        with self.assertRaisesRegex(ContainerError, "give a key"):
            equipment.add("dagger")
        with self.assertRaisesRegex(ContainerError, "did you mean 'mainHand'"):
            equipment.add("dagger", "mainhand")

    def test_fixed_entries_exist_from_the_start_and_cannot_change(self):
        attributes = new("character").container("attributes")
        self.assertEqual(attributes.keys(), ["str", "dex", "con", "int", "wis", "cha"])
        with self.assertRaisesRegex(ContainerError, "fixed"):
            attributes.add("attribute", "str")
        with self.assertRaisesRegex(ContainerError, "fixed"):
            attributes.remove("str")

    def test_moving_an_instance_takes_it_out_of_its_old_container(self):
        char = new("character")
        dagger = char.container("inventory").add("dagger")
        char.container("equipment").add(dagger, "offHand")
        self.assertEqual(len(char.container("inventory")), 0)
        self.assertIs(dagger.owner, char)
        self.assertEqual(dagger.contained.id, "equipment")

    def test_an_instance_cannot_be_put_inside_itself(self):
        game = make_game({"id": "bag", "extends": "rope", "contains": {"items": {"of": "item", "list": True}}})
        bag = new("bag", game)
        inner = bag.container("items").add("bag")
        with self.assertRaisesRegex(ContainerError, "inside itself"):
            inner.container("items").add(bag)


class AcceptanceTest(unittest.TestCase):
    def test_of_requires_the_type(self):
        with self.assertRaisesRegex(ContainerError, "is not a 'enchantment'"):
            new("dagger").container("enchantments").add("steel")

    def test_applies_to_narrows_where_an_entry_may_go(self):
        with self.assertRaisesRegex(ContainerError, r"applies only to \['armor'\]"):
            new("dagger").container("material").add("leather")
        new("padded-armor").container("material").add("leather")
        with self.assertRaisesRegex(ContainerError, r"applies only to \['weapon'\]"):
            new("padded-armor").container("enchantments").add("keen")

    def test_accepts_checks_the_candidate(self):
        with self.assertRaisesRegex(ContainerError, "does not accept 'oak'"):
            new("battleaxe").container("material").add("oak")  # needs metal
        new("dagger").container("material").add("oak")  # any material
        with self.assertRaisesRegex(ContainerError, "does not accept 'steel'"):
            new("padded-armor").container("material").add("steel")  # not metal

    def test_can_accept_answers_without_raising(self):
        axe = new("battleaxe")
        self.assertTrue(axe.container("material").can_accept(new("steel")))
        self.assertFalse(axe.container("material").can_accept(new("oak")))

    def test_unique_refuses_a_second_copy(self):
        feats = new("character").container("feats")
        feats.add("alert")
        with self.assertRaisesRegex(ContainerError, "unique"):
            feats.add("alert")

    def test_limit_is_reported_not_blocked(self):
        char = new("character")
        char.container("feats").add("alert")
        char.container("feats").add("fleet-footed")  # featCount is 1 at level 1
        self.assertEqual(char.issues(), ["'character/feats' holds 2 entries, the limit is 1"])
        char.prop("level").choose(4)  # featCount 2
        self.assertEqual(char.issues(), [])

    def test_granted_containers_are_filled_only_by_grants(self):
        char = new("character")
        actions = char.container("actions")
        with self.assertRaisesRegex(ContainerError, "only by grants"):
            actions.add("dash")
        dash = actions.grant("dash")
        self.assertEqual(len(actions), 1)
        self.assertIsNone(char.to_data().children.get("actions"))  # rebuilt by grants, not saved
        self.assertTrue(actions.revoke(dash))
        self.assertEqual(len(actions), 0)


class SeedTest(unittest.TestCase):
    def test_new_instances_start_with_the_seed(self):
        conditions = new("character").container("conditions")
        self.assertEqual([c.def_id for c in conditions.all()], ["overloaded"])

    def test_a_removed_seed_stays_removed_after_loading(self):
        char = new("character")
        char.container("conditions").remove("0")
        loaded = Instance(char.to_data())
        self.assertEqual(len(loaded.container("conditions")), 0)


class ObserverTest(unittest.TestCase):
    def test_a_value_that_reads_a_container_follows_its_changes(self):
        char = new("character")
        self.assertEqual(char.get("carryWeight"), 0)
        rope = char.container("inventory").add("rope")
        self.assertEqual(char.get("carryWeight"), 10)
        rope.prop("stack").write(3)
        self.assertEqual(char.get("carryWeight"), 30)
        char.container("equipment").add("dagger", "mainHand")
        self.assertEqual(char.get("carryWeight"), 31)
        char.container("inventory").remove("0")
        self.assertEqual(char.get("carryWeight"), 1)

    def test_changing_a_container_during_a_resolve_is_blocked(self):
        game = make_game({
            "id": "greedy",
            "extends": "rope",
            "contains": {"items": {"of": "item", "list": True}},
            "props": {"bad": {"type": "int", "derive": op("test-greedy-add")}},
        })
        with self.assertRaises(IllegalMutationError):
            new("greedy", game).get("bad")


if __name__ == "__main__":
    unittest.main()
