import json
import unittest

from DbData import DbData
from Instance import Instance
from errors import ContainerError, DefinitionError, PropertyError
from tests.fixtures import attribute, make_store, new, snapshot, walking


class InheritanceTest(unittest.TestCase):
    def test_chain_is_walked_child_to_parent(self):
        axe = new("battleaxe")
        self.assertEqual(axe.sub_ids, ["battleaxe", "weapon", "equipment", "item"])
        self.assertTrue(axe.is_a("equipment"))
        self.assertFalse(axe.is_a("armor"))

    def test_props_and_containers_are_inherited_and_set_applied(self):
        axe = new("battleaxe")
        self.assertTrue(set(axe.props).issuperset({"weight", "stack", "power", "damage", "martial"}))
        self.assertEqual(set(axe.containers), {"enchantments", "material"})
        self.assertEqual(axe.get("damage"), 8)
        self.assertIs(axe.get("martial"), True)
        self.assertEqual(axe.get("value"), 10)  # power 0 → baseValue

    def test_abstract_entries_cannot_be_instantiated(self):
        with self.assertRaisesRegex(DefinitionError, "abstract"):
            new("weapon")

    def test_unknown_definition_suggests_the_closest_id(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'battleaxe'"):
            new("batleaxe")

    def test_cyclic_extends(self):
        store = make_store({"id": "a", "extends": "b"}, {"id": "b", "extends": "a"})
        with self.assertRaisesRegex(DefinitionError, "cyclic extends: a -> b -> a"):
            Instance("a", store=store)

    def test_redeclaring_an_inherited_prop_is_an_error(self):
        store = make_store({"id": "bad-axe", "extends": "battleaxe", "props": {"damage": {"type": "int"}}})
        with self.assertRaisesRegex(DefinitionError, "redeclares 'damage'"):
            Instance("bad-axe", store=store)

    def test_set_on_an_unknown_prop_suggests_the_closest(self):
        store = make_store({"id": "bad-axe", "extends": "battleaxe", "set": {"damgae": 3}})
        with self.assertRaisesRegex(DefinitionError, "did you mean 'damage'"):
            Instance("bad-axe", store=store)

    def test_unknown_entry_key_suggests_the_closest(self):
        store = make_store({"id": "bad-axe", "extends": "battleaxe", "efects": []})
        with self.assertRaisesRegex(DefinitionError, "did you mean 'effects'"):
            Instance("bad-axe", store=store)

    def test_concrete_entry_must_give_every_prop_a_value(self):
        store = make_store({"id": "half-axe", "extends": "weapon", "set": {"martial": True}})
        with self.assertRaisesRegex(DefinitionError, "without a value"):
            Instance("half-axe", store=store)

    def test_traits_add_props_and_cannot_be_applied_twice(self):
        trait = {"id": "glowing", "props": {"light": {"type": "int", "default": 10}}}
        store = make_store(trait, {"id": "lamp", "extends": "rope", "traits": ["glowing"]})
        self.assertEqual(Instance("lamp", store=store).get("light"), 10)
        store = make_store(trait, {"id": "lamp", "extends": "rope", "traits": ["glowing", "glowing"]})
        with self.assertRaisesRegex(DefinitionError, "applied twice"):
            Instance("lamp", store=store)

    def test_ignored_keys_of_later_features_are_accepted(self):
        store = make_store({"id": "torch", "extends": "rope", "on": {"long-rest": []}, "grants": []})
        self.assertEqual(Instance("torch", store=store).get("weight"), 10)


class TextTest(unittest.TestCase):
    def test_name_defaults_to_the_id_and_may_be_a_template(self):
        store = make_store()
        self.assertEqual(Instance("battleaxe", store=store).name, "Battleaxe")
        self.assertEqual(Instance("attribute", store=store).name, "attribute")
        boost = Instance("ability-score-boost", store=store)
        boost.prop("level").choose(2)
        self.assertEqual(boost.name, "Ability Score Boost 2")
        self.assertIn("rune", boost.description)


class TreeTest(unittest.TestCase):
    def test_owner_entity_and_root(self):
        char = new("character")
        dagger = char.spawn("dagger")
        self.assertIsNone(dagger.owner)
        self.assertIsNone(dagger.entity)
        self.assertIs(dagger.root, dagger)

        char.container("equipment").add(dagger, "mainHand")
        keen = dagger.container("enchantments").add("keen")
        self.assertIs(dagger.owner, char)
        self.assertIs(keen.owner, dagger)
        self.assertIs(keen.entity, char)
        self.assertIs(keen.root, char)
        self.assertIs(char.entity, char)
        self.assertEqual(str(keen.path),"character/equipment:mainHand/dagger/enchantments:0/keen")


class SaveTest(unittest.TestCase):
    def build_character(self) -> Instance:
        char = new("character")
        char.prop("level").choose(5)
        char.container("attributes").get("str").prop("value").choose(14)
        axe = char.container("equipment").add("battleaxe", "mainHand")
        axe.container("material").add("steel")
        axe.container("enchantments").add({"def": "keen", "props": {"level": "2"}})
        boost = axe.container("enchantments").add("ability-score-boost")
        boost.prop("stat").choose("dex")
        rope = char.container("inventory").add("rope")
        rope.prop("stack").write(3)
        char.container("feats").add("fleet-footed")
        return char

    def test_a_fresh_instance_saves_only_its_seeded_containers(self):
        self.assertEqual(
            new("character").to_data().to_dict(),
            {"def": "character", "children": {"conditions": [{"def": "overloaded"}]}},
        )

    def test_round_trip_through_json_restores_every_value(self):
        char = self.build_character()
        saved = json.loads(json.dumps(char.to_data().to_dict()))
        loaded = Instance("character", saved, store=char.store)

        self.assertEqual(snapshot(loaded), snapshot(char))
        self.assertEqual(loaded.to_data(), char.to_data())
        self.assertEqual(attribute(loaded, "dex"), 13)  # 10 + boost level 1
        self.assertEqual(walking(loaded), 40)

    def test_choices_and_state_are_saved_as_strings(self):
        data = self.build_character().to_data()
        self.assertEqual(data.props, {"level": "5"})
        self.assertEqual(data.children["attributes"], {"str": DbData("attribute", props={"value": "14"})})
        self.assertEqual(data.children["inventory"], [DbData("rope", props={"stack": "3"})])

    def test_unknown_container_in_a_save_is_reported(self):
        with self.assertRaisesRegex(ContainerError, "did you mean 'inventory'"):
            new("character", {"def": "character", "children": {"inventroy": []}})

    def test_a_value_of_an_unsaved_prop_is_reported(self):
        with self.assertRaisesRegex(PropertyError, "is derived; it is not saved"):
            new("character", {"def": "character", "props": {"featCount": "3"}})

    def test_a_choice_out_of_range_in_a_save_is_reported(self):
        with self.assertRaisesRegex(PropertyError, "outside the range"):
            new("character", {"def": "character", "props": {"level": "42"}})

    def test_save_of_another_definition_is_rejected(self):
        with self.assertRaises(DefinitionError):
            new("character", {"def": "dagger"})


if __name__ == "__main__":
    unittest.main()
