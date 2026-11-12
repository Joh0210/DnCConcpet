"""Expression nodes from the JSON (concept §4.14): static values, operations, paths."""
import json
import unittest

from engine.datatype.Datatype import Datatype
from engine.errors import DefinitionError, ExpressionError, UnsupportedOperationError
from engine.operation.Operation import Operation, signature
from tests.fixtures import CONTENT, MODEL, new, register_game, snapshot
from tests.ir import ALL, ENTITY, NULL, OWNER, is_a, key, lit, op, opt, path, template, where
from engine.value.InnerFunction import EvalContext
from engine.value.build import build_target, build_value

LEVEL = path("level", type="int")


class TallyOperation(Operation):
    """Passes its argument through and counts how often it ran."""

    calls = 0

    def name(self):
        return "test-tally"

    @signature("any", returns="int")
    def tally(self, value):
        TallyOperation.calls += 1
        return value


Operation.register(TallyOperation())


def value_of(raw, this=None, **names):
    return build_value(raw).evaluate(EvalContext(this=this, **names))


class StaticValueTest(unittest.TestCase):
    def test_a_literal_is_parsed_once_by_its_type(self):
        node = build_value(lit("10", "int"))
        self.assertEqual((node.value, node.type.name()), (10, "int"))
        self.assertEqual(build_value(lit("dex", "Attribute")).describe(), ".dex")

    def test_bare_scalars_are_typed_by_their_slot_or_their_json_kind(self):
        kinds = [build_value(raw).type.name() for raw in (3, 2.5, True, "a", None)]
        self.assertEqual(kinds, ["int", "number", "bool", "text", "null"])
        self.assertEqual(build_value("dex", Datatype.get("Attribute")).type.name(), "Attribute")

    def test_invalid_literals_fail_when_built(self):
        with self.assertRaisesRegex(DefinitionError, "invalid int literal"):
            build_value(lit("x", "int"))
        with self.assertRaisesRegex(DefinitionError, "did you mean 'dex'"):
            build_value("dax", Datatype.get("Attribute"))


class OperationValueTest(unittest.TestCase):
    def test_the_type_comes_from_the_resolved_overload(self):
        self.assertEqual(build_value(op("div", 1, 2)).type.name(), "number")
        self.assertEqual(build_value(op("lt", op("div", 1, 2), 1)).type.name(), "bool")
        self.assertEqual(value_of(op("floor", op("div", op("sub", 15, 10), 2))), 2)

    def test_a_type_error_stops_the_definition_from_loading(self):
        with self.assertRaises(UnsupportedOperationError):
            build_value(op("mul", "a", 2))
        game = register_game({"id": "bad", "props": {"x": {"type": "int", "derive": op("add", "a", "b")}}})
        with self.assertRaisesRegex(DefinitionError, "prop 'x': base value: expected int, got text"):
            new("bad", game)

    def test_malformed_nodes_are_reported(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'args'"):
            build_value({"op": "add", "arg": [1, 2]})
        with self.assertRaisesRegex(DefinitionError, "exactly one of 'value', 'op' or 'path'"):
            build_value({"op": "add", "path": []})
        with self.assertRaisesRegex(DefinitionError, "did you mean 'floor'"):
            build_value(op("flor", 1.5))

    def test_lazy_operations_evaluate_only_what_they_need(self):
        broken = path("x", type="bool")  # `this` is null here: evaluating it fails
        self.assertIs(value_of(op("and", False, broken)), False)
        self.assertIs(value_of(op("or", True, broken)), True)
        self.assertEqual(value_of(op("cond", True, 1, path("x", type="int"))), 1)
        self.assertEqual(value_of(op("coalesce", 5, path("x", type="int"))), 5)
        self.assertEqual(value_of(op("coalesce", NULL, 5)), 5)
        with self.assertRaises(ExpressionError):
            value_of(op("and", True, broken))

    def test_the_untaken_branch_is_no_dependency(self):
        game = register_game({
            "id": "switch",
            "props": {
                "flag": {"type": "bool", "source": "choice", "default": False},
                "a": {"type": "int", "source": "choice", "default": 1},
                "b": {"type": "int", "source": "choice", "default": 2},
                # flag ? a : b, counted
                "y": {"type": "int", "derive": op("test-tally", op("cond", path("flag", type="bool"),
                                                                   path("a", type="int"), path("b", type="int")))},
            },
        })
        inst = new("switch", game)
        TallyOperation.calls = 0
        self.assertEqual(inst.get("y"), 2)
        inst.prop("a").choose(5)  # not read: the cached value stays valid
        self.assertEqual(inst.get("y"), 2)
        self.assertEqual(TallyOperation.calls, 1)
        inst.prop("flag").choose(True)
        self.assertEqual(inst.get("y"), 5)
        self.assertEqual(TallyOperation.calls, 2)

    def test_a_null_reaching_an_eager_operation_is_reported(self):
        with self.assertRaisesRegex(ExpressionError, "'null \\+ 1' failed"):
            value_of(op("add", lit(None, "int"), 1))


class PathValueTest(unittest.TestCase):
    def setUp(self):
        self.char = new("character")
        self.ctx = EvalContext(this=self.char)

    def read(self, raw):
        return build_value(raw).evaluate(self.ctx)

    def test_a_fanning_out_path_yields_a_list_never_null(self):
        weights = path("inventory", ALL, "weight", type="list<number>")
        self.assertEqual(self.read(weights), [])
        self.assertEqual(self.read(op("sum", weights)), 0)
        self.char.container("inventory").add("rope")
        self.assertEqual(self.read(weights), [10])

    def test_several_keys_fan_out_and_continue_with_the_same_rest(self):
        self.char.container("attributes").get("dex").prop("value").choose(14)
        self.assertEqual(self.read(path("attributes", key("str", "dex"), "value", type="list<int>")), [10, 14])
        self.assertEqual(self.read(path("attributes", key(lit("dex", "Attribute")), "mod", type="int")), 2)

    def test_a_key_is_any_value(self):
        self.char.container("attributes").get("dex").prop("value").choose(14)
        picked = path(start="picked", type="Attribute")  # a context name, like `args` of an action
        node = build_value(path("attributes", key(picked), "mod", type="int"))
        self.assertEqual(node.evaluate(EvalContext(this=self.char, picked="dex")), 2)
        self.assertEqual(node.describe(), "attributes[picked].mod")

    def test_filters_by_type_and_by_predicate(self):
        inventory = self.char.container("inventory")
        inventory.add("rope")
        inventory.add("dagger")
        self.assertEqual(self.read(path("inventory", is_a("weapon"), "weight", type="list<number>")), [1])
        heavy = where(op("gt", path("weight", start="it", type="number"), 5))
        self.assertEqual(self.read(path("inventory", heavy, "weight", type="list<number>")), [10])

    def test_a_list_is_one_value_for_list_operations(self):
        average = op("avg", path("attributes", ALL, "value", type="list<int>"))
        self.assertEqual(build_value(average).describe(), "avg(attributes[*].value)")
        self.assertEqual(self.read(average), 10)
        self.char.container("attributes").get("str").prop("value").choose(16)
        self.assertEqual(self.read(average), 11)  # (16 + 5 × 10) / 6

    def test_a_template_with_a_kernel_function(self):
        game = register_game({
            "id": "shadow",
            # "Shadow {roman(level)}"
            "name": template("Shadow ", op("roman", LEVEL)),
            "props": {"level": {"type": "int", "source": "choice", "default": 3, "range": [1, 10]}},
        })
        shadow = new("shadow", game)
        self.assertEqual(shadow.name, "Shadow III")
        shadow.prop("level").choose(4)
        self.assertEqual(shadow.name, "Shadow IV")
        self.assertEqual(build_value(template("Shadow ", op("roman", LEVEL))).describe(), '"Shadow {roman(level)}"')

    def test_a_single_container_is_transparent(self):
        self.assertEqual(self.read(path("speed", "walking", type="int")), 30)
        self.assertIs(self.read(path("magic", type="ref<magic>")), self.char.container("magic").get())

    def test_an_absent_segment_needs_opt_in_a_value(self):
        axe = new("battleaxe")
        ctx = EvalContext(this=axe)
        self.assertIsNone(build_value(path(opt("material"), "power", type="number")).evaluate(ctx))
        with self.assertRaisesRegex(ExpressionError, "'material' is absent here — mark it as optional"):
            build_value(path("material", "power", type="number")).evaluate(ctx)
        self.assertIsNone(build_value(path(opt(OWNER), "power", type="number")).evaluate(ctx))
        self.assertIsNone(build_value(path(ENTITY, type="ref<entity>")).evaluate(ctx))  # a null end is a value

    def test_an_absent_segment_makes_a_target_inert(self):
        dagger = new("dagger")
        keen = dagger.container("enchantments").add("keen")
        target = build_target(path(OWNER, "damage"))
        self.assertEqual(target.resolve(keen), [dagger.prop("damage")])
        self.assertEqual(target.resolve(new("keen")), [])  # unattached
        self.assertEqual(build_target(path(OWNER, "baseAC")).resolve(keen), [])  # a weapon has no baseAC

    def test_types_are_checked(self):
        with self.assertRaisesRegex(DefinitionError, "needs a list<…> type"):
            build_value(path("inventory", ALL, "weight", type="number"))
        with self.assertRaisesRegex(DefinitionError, "needs a single type"):
            build_value(path("level", type="list<int>"))
        with self.assertRaisesRegex(DefinitionError, "needs a 'type'"):
            build_value(path("level"))
        with self.assertRaisesRegex(ExpressionError, "declared as int, but 'character.carryWeight' is number"):
            self.read(path("carryWeight", type="int"))
        self.assertEqual(self.read(path("level", type="number")), 1)  # int widens to number

    def test_a_target_must_end_at_a_prop(self):
        axe = new("battleaxe")
        axe.container("material").add("steel")
        with self.assertRaisesRegex(DefinitionError, "must end at a prop"):
            build_target(path("material")).resolve(axe)

    def test_a_list_container_needs_a_selector(self):
        with self.assertRaisesRegex(ExpressionError, r"use \[\*\], a key or a filter"):
            self.read(path("inventory", "weight", type="number"))


class DescribeTest(unittest.TestCase):
    def assertDescribes(self, raw, text):
        self.assertEqual(build_value(raw).describe(), text)

    def test_operations_are_written_with_minimal_parentheses(self):
        self.assertDescribes(op("add", op("mul", 2, LEVEL), 1), "2 * level + 1")
        self.assertDescribes(op("mul", op("add", 1, 2), 3), "(1 + 2) * 3")
        self.assertDescribes(op("sub", 10, op("sub", 4, 1)), "10 - (4 - 1)")
        self.assertDescribes(op("floor", op("div", LEVEL, 4)), "floor(level / 4)")
        self.assertDescribes(op("not", path("magic", type="bool")), "not magic")
        self.assertDescribes(
            op("cond", op("gt", path("power", type="number"), 0), op("pow", path("power", type="number"), 2),
               path("baseValue", type="number")),
            "power > 0 ? power ^ 2 : baseValue",
        )
        self.assertDescribes(
            op("add", op("sum", path("enchantments", ALL, "power", type="list<number>")),
               op("coalesce", path(opt("material"), "power", type="number"), 0)),
            "sum(enchantments[*].power) + (material?.power ?? 0)",
        )

    def test_parentheses_follow_associativity(self):
        category = path("category", start="it", type="MaterialCategory")
        required = path("requiredMaterial", type="MaterialRequired")
        self.assertDescribes(  # comparisons do not chain: both sides keep their parentheses
            op("eq", op("eq", category, lit("metal", "MaterialCategory")),
               op("eq", required, lit("metal", "MaterialRequired"))),
            "(it.category == .metal) == (requiredMaterial == .metal)",
        )
        self.assertDescribes(op("lt", op("add", 1, 2), 4), "1 + 2 < 4")
        self.assertDescribes(op("pow", 2, op("pow", 3, 2)), "2 ^ 3 ^ 2")  # ^ is right-associative
        self.assertDescribes(op("pow", op("pow", 2, 3), 2), "(2 ^ 3) ^ 2")
        self.assertDescribes(op("sub", op("sub", 10, 4), 1), "10 - 4 - 1")  # left-associative as before

    def test_coalesce_is_parenthesized_when_combined_with_another_operator(self):
        level = path(opt(ENTITY), "level", type="int")
        power = op("coalesce", path(opt("material"), "power", type="number"), 0)
        self.assertDescribes(op("coalesce", level, op("mul", 0, 2)), "entity?.level ?? (0 * 2)")
        self.assertDescribes(op("mul", op("coalesce", level, 0), 2), "(entity?.level ?? 0) * 2")
        self.assertDescribes(op("cond", path("magic", type="bool"), power, 1), "magic ? (material?.power ?? 0) : 1")
        self.assertDescribes(op("coalesce", level, op("sum", path("inventory", ALL, "weight", type="list<int>"))),
                             "entity?.level ?? sum(inventory[*].weight)")  # a call is no operator
        self.assertDescribes(op("coalesce", op("coalesce", level, NULL), 0), "entity?.level ?? null ?? 0")

    def test_paths_and_templates_read_like_the_source(self):
        stat = path("stat", type="Attribute")
        self.assertDescribes(path(opt(ENTITY), "attributes", key(stat), "value", type="int"),
                             "entity?.attributes[stat].value")
        self.assertDescribes(path("category", start="it", type="MaterialCategory"), "it.category")
        self.assertDescribes(path(start="previous", type="int"), "previous")
        self.assertDescribes(path("attributes", key(lit("str", "Attribute"), lit("dex", "Attribute")), "advantage",
                                  type="list<int>"), "attributes[.str, .dex].advantage")
        self.assertDescribes(template("Your ", stat, " increases by ", op("add", op("mul", 2, LEVEL), 1)),
                             '"Your {stat} increases by {2 * level + 1}"')

    def test_literals_are_written_in_the_expression_language(self):
        self.assertDescribes(op("and", path("magic", type="bool"), False), "magic and false")
        self.assertDescribes(op("add", "hello ", path("who", type="text")), "'hello ' + who")
        self.assertDescribes("it's", r"'it\'s'")
        self.assertDescribes(op("mul", 2.5, 2), "2.5 * 2")
        self.assertDescribes(template("Hi ", True), '"Hi {true}"')  # text parts of a template stay inline


class ContentAsDataTest(unittest.TestCase):
    def test_the_content_is_plain_json(self):
        content = [*MODEL, *CONTENT]
        self.assertEqual(json.loads(json.dumps(content)), content)

    def test_a_game_read_from_json_text_behaves_the_same(self):
        from_text = register_game(*json.loads(json.dumps([*MODEL, *CONTENT])))

        def play(game):
            char = new("character", game)
            dagger = char.container("equipment").add("dagger", "mainHand")
            dagger.container("enchantments").add("keen")
            dagger.container("enchantments").add("ability-score-boost").prop("stat").choose("dex")
            char.container("inventory").add("rope").prop("stack").write(12)
            return snapshot(char)

        self.assertEqual(play(from_text), play(new("character").game))

    def test_nodes_are_built_once_per_game_and_shared(self):
        axe, dagger = new("battleaxe"), new("dagger")
        self.assertIs(axe.prop("value").base_expression, dagger.prop("value").base_expression)
        self.assertIs(axe.effects[0].value, dagger.effects[0].value)
        self.assertIs(axe.effects[0].target, dagger.effects[0].target)


if __name__ == "__main__":
    unittest.main()
