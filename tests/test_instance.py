import json
import unittest

from engine.errors import ContainerError, DefinitionError, PropertyError
from engine.instance.DbData import DbData
from engine.instance.Instance import Instance
from tests.fixtures import TEST_GAME, attribute, make_game, new, snapshot, walking, without_uids


class InheritanceTest(unittest.TestCase):
    def test_chain_is_walked_child_to_parent(self):
        axe = new("battleaxe")
        self.assertEqual(axe.extends_chain, ["battleaxe", "weapon", "equipment", "item"])
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
        game = make_game({"id": "a", "extends": "b"}, {"id": "b", "extends": "a"})
        with self.assertRaisesRegex(DefinitionError, "cyclic extends: a -> b -> a"):
            new("a", game)

    def test_redeclaring_an_inherited_prop_is_an_error(self):
        game = make_game({"id": "bad-axe", "extends": "battleaxe", "props": {"damage": {"type": "int"}}})
        with self.assertRaisesRegex(DefinitionError, "redeclares 'damage'"):
            new("bad-axe", game)

    def test_set_on_an_unknown_prop_suggests_the_closest(self):
        game = make_game({"id": "bad-axe", "extends": "battleaxe", "set": {"damgae": 3}})
        with self.assertRaisesRegex(DefinitionError, "did you mean 'damage'"):
            new("bad-axe", game)

    def test_unknown_entry_key_suggests_the_closest(self):
        game = make_game({"id": "bad-axe", "extends": "battleaxe", "efects": []})
        with self.assertRaisesRegex(DefinitionError, "did you mean 'effects'"):
            new("bad-axe", game)

    def test_concrete_entry_must_give_every_prop_a_value(self):
        game = make_game({"id": "half-axe", "extends": "weapon", "set": {"martial": True}})
        with self.assertRaisesRegex(DefinitionError, "without a value"):
            new("half-axe", game)

    def test_traits_add_props_and_cannot_be_applied_twice(self):
        trait = {"id": "glowing", "props": {"light": {"type": "int", "default": 10}}}
        game = make_game(trait, {"id": "lamp", "extends": "rope", "traits": ["glowing"]})
        self.assertEqual(new("lamp", game).get("light"), 10)
        game = make_game(trait, {"id": "lamp", "extends": "rope", "traits": ["glowing", "glowing"]})
        with self.assertRaisesRegex(DefinitionError, "applied twice"):
            new("lamp", game)

    def test_ignored_keys_of_later_features_are_accepted(self):
        game = make_game({"id": "torch", "extends": "rope", "on": {"long-rest": []}, "grants": []})
        self.assertEqual(new("torch", game).get("weight"), 10)


class TextTest(unittest.TestCase):
    def test_name_defaults_to_the_id_and_may_be_a_template(self):
        self.assertEqual(new("battleaxe").name, "Battleaxe")
        self.assertEqual(new("attribute").name, "attribute")
        boost = new("ability-score-boost")
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
        self.assertEqual(str(keen.path), f"character/equipment:mainHand/dagger/enchantments:{keen.uid}/keen")


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
            {"game": TEST_GAME, "def": "character", "children": {"conditions": [{"def": "overloaded", "uid": "1"}]}},
        )

    def test_round_trip_through_json_restores_every_value(self):
        char = self.build_character()
        saved = json.loads(json.dumps(char.to_data().to_dict()))
        loaded = Instance(saved)

        self.assertEqual(snapshot(loaded), snapshot(char))
        self.assertEqual(loaded.to_data(), char.to_data())
        self.assertEqual(attribute(loaded, "dex"), 13)  # 10 + boost level 1
        self.assertEqual(walking(loaded), 40)

    def test_choices_and_state_are_saved_as_strings(self):
        data = self.build_character().to_data()
        self.assertEqual(data.props, {"level": "5"})
        self.assertEqual(data.children["attributes"], {"str": DbData("attribute", props={"value": "14"})})
        [rope] = data.children["inventory"]
        self.assertEqual((rope.def_id, rope.props), ("rope", {"stack": "3"}))
        self.assertIsNotNone(rope.uid)  # list children carry their identity

    def test_unknown_container_in_a_save_is_reported(self):
        with self.assertRaisesRegex(ContainerError, "did you mean 'inventory'"):
            new({"def": "character", "children": {"inventroy": []}})

    def test_a_value_of_an_unsaved_prop_is_reported(self):
        with self.assertRaisesRegex(PropertyError, "is derived; it is not saved"):
            new({"def": "character", "props": {"featCount": "3"}})

    def test_a_choice_out_of_range_in_a_save_is_reported(self):
        with self.assertRaisesRegex(PropertyError, "outside the range"):
            new({"def": "character", "props": {"level": "42"}})

    def test_save_of_another_definition_is_rejected(self):
        with self.assertRaisesRegex(DefinitionError, "cannot be loaded into 'character'"):
            new("character").load({"def": "dagger"})


class GameTest(unittest.TestCase):
    def test_a_save_names_its_game_once_and_is_enough_to_rebuild(self):
        char = new("character")
        char.container("inventory").add("rope")
        data = char.to_data()
        self.assertEqual(data.game, TEST_GAME)
        self.assertIsNone(data.children["inventory"][0].game)  # children inherit the game
        self.assertEqual(Instance(data.to_dict()).game, TEST_GAME)

    def test_a_save_without_a_game_is_rejected(self):
        with self.assertRaisesRegex(DefinitionError, r"names no game — use Instance\.new\('character'"):
            Instance({"def": "character"})
        with self.assertRaisesRegex(DefinitionError, "names no game"):
            Instance("character")  # a bare id is a save without a game

    def test_new_builds_a_fresh_instance_of_a_game(self):
        char = Instance.new("character", TEST_GAME)
        self.assertEqual((char.def_id, char.game), ("character", TEST_GAME))
        self.assertEqual(char.to_data(), new("character").to_data())
        with self.assertRaisesRegex(DefinitionError, "unknown game 'tset' — did you mean 'test'"):
            Instance.new("character", "tset")

    def test_children_cannot_belong_to_another_game(self):
        other = make_game()
        with self.assertRaisesRegex(DefinitionError, f"belongs to game '{other}'"):
            new({"def": "character", "children": {"inventory": [{"game": other, "def": "rope"}]}})
        with self.assertRaisesRegex(DefinitionError, f"belongs to game '{other}'"):
            new("character").load({"game": other, "def": "character"})

    def test_an_instance_of_another_game_does_not_fit(self):
        rope = new("rope", make_game())
        with self.assertRaisesRegex(ContainerError, "belongs to game"):
            new("character").container("inventory").add(rope)

    def test_children_are_spawned_in_their_parents_game(self):
        game = make_game()
        rope = new("character", game).container("inventory").add("rope")
        self.assertEqual(rope.game, game)


class LoadTest(unittest.TestCase):
    def test_load_reverts_a_live_instance_to_a_save(self):
        char = SaveTest().build_character()
        saved = char.to_data()
        strength = char.container("attributes").get("str")

        char.prop("level").choose(7)
        strength.prop("value").choose(8)
        inventory = char.container("inventory")
        inventory.get(inventory.keys()[0]).prop("stack").write(9)
        char.container("inventory").add("dagger")
        for container_id in ("feats", "conditions"):
            container = char.container(container_id)
            container.remove(container.keys()[0])
        char.container("equipment").remove("mainHand")
        self.assertNotEqual(char.to_data(), saved)

        char.load(saved)
        self.assertEqual(char.to_data(), saved)
        self.assertEqual(snapshot(char), snapshot(Instance(saved)))
        self.assertIs(char.container("attributes").get("str"), strength)  # fixed entries are loaded into
        self.assertEqual(attribute(char, "dex"), 13)  # effects bound again

    def test_loading_a_bare_id_resets_to_the_definition(self):
        char = SaveTest().build_character()
        char.load("character")
        # The seed comes back as a new instance with a new uid (uids are never reused).
        self.assertEqual(without_uids(char.to_data()), without_uids(new("character").to_data()))
        self.assertEqual(snapshot(char), snapshot(new("character")))

    def test_a_bad_save_is_rejected_before_anything_changes(self):
        char = new("character")
        char.prop("level").choose(5)
        with self.assertRaisesRegex(ContainerError, "unknown container"):
            char.load({"def": "character", "children": {"inventroy": []}})
        self.assertEqual(char.get("level"), 5)


if __name__ == "__main__":
    unittest.main()
