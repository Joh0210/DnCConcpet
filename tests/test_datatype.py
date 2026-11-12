import unittest

from engine.datatype.Datatype import Datatype, common_type
from engine.datatype.datatypes.TypeInt import TypeInt
from engine.errors import DefinitionError, ExpressionError, UnsupportedOperationError
from engine.operation.Operation import Operation
from engine.operation.operations.ArithmeticOperations import AddOperation


class TypeCelsius(Datatype):
    """A type added "from outside": no operation knows it, yet the generic ones work."""

    ordered = True

    def name(self):
        return "test-celsius"

    def deserialize(self, string):
        return float(string.rstrip("C"))

    def serialize(self, value):
        return f"{value}C"

    def validate(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"expected degrees, got {value!r}")
        return value


Datatype.register(TypeCelsius())


def resolve(operation_name, *type_names):
    """The overload of ``operation_name`` for arguments of ``type_names``."""
    return Operation.get(operation_name).resolve([Datatype.get(name) for name in type_names])


def call(operation_name, *typed):
    """``call("add", ("int", 3), ("int", 4))`` — resolve by the types, call with the values."""
    return resolve(operation_name, *(t for t, _ in typed))(*(v for _, v in typed))


class DatatypeTest(unittest.TestCase):
    def test_lookup_by_name_returns_the_shared_instance(self):
        self.assertIs(Datatype.get("int"), TypeInt.instance())

    def test_unknown_type_suggests_the_closest_name(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'Attribute'"):
            Datatype.get("Atribute")

    def test_parse_accepts_strings_and_native_values(self):
        self.assertEqual(Datatype.get("int").parse("10"), 10)
        self.assertEqual(Datatype.get("int").parse(10), 10)
        self.assertEqual(Datatype.get("int").parse(4.0), 4)
        self.assertEqual(Datatype.get("number").parse("2.5"), 2.5)
        self.assertIs(Datatype.get("bool").parse("yes"), True)
        self.assertIs(Datatype.get("bool").parse(False), False)
        self.assertEqual(Datatype.get("Attribute").parse("dex"), "dex")

    def test_serialize_round_trips(self):
        for type_name, value in [("int", 7), ("number", 2.5), ("bool", True), ("text", "hi"), ("Slot", "body"),
                                 ("list<int>", [1, 2])]:
            datatype = Datatype.get(type_name)
            self.assertEqual(datatype.parse(datatype.serialize(value)), value, type_name)

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            Datatype.get("int").parse(True)
        with self.assertRaises(ValueError):
            Datatype.get("int").parse(2.5)
        with self.assertRaisesRegex(ValueError, "did you mean 'dex'"):
            Datatype.get("Attribute").parse("dax")

    def test_enum_order_is_the_option_order(self):
        armor = Datatype.get("ArmorCategory")
        self.assertEqual(armor.clamp("heavy", upper="medium"), "medium")
        self.assertEqual(armor.clamp("clothing", lower="light"), "light")

    def test_parametrized_types_are_built_once_and_shared(self):
        numbers = Datatype.get("list<number>")
        self.assertIs(Datatype.get("list< number >"), numbers)
        self.assertIs(numbers.element, Datatype.get("number"))
        self.assertEqual(numbers.kind(), "list")
        self.assertEqual(Datatype.get("ref<weapon>").kind(), "ref")
        with self.assertRaisesRegex(DefinitionError, "unknown type constructor 'lsit'"):
            Datatype.get("lsit<int>")

    def test_int_widens_to_number_and_narrows_only_on_request(self):
        int_type, number = Datatype.get("int"), Datatype.get("number")
        self.assertIsNotNone(number.converter(int_type))
        self.assertIsNone(int_type.converter(number))
        self.assertEqual(int_type.converter(number, narrowing=True)(3.7), 3)
        self.assertIs(common_type(int_type, number), number)
        self.assertIs(common_type(Datatype.get("null"), int_type), int_type)
        self.assertIsNone(common_type(Datatype.get("Attribute"), Datatype.get("Slot")))


class OperationTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(call("add", ("int", 3), ("int", 4)), 7)
        self.assertEqual(call("add", ("number", 1.5), ("number", 1)), 2.5)
        self.assertIs(call("add", ("bool", False), ("bool", True)), True)
        self.assertEqual(call("add", ("text", "a"), ("text", "b")), "ab")

    def test_the_overload_decides_the_result_type(self):
        self.assertEqual(resolve("add", "int", "int").returns.name(), "int")
        self.assertEqual(resolve("add", "int", "number").returns.name(), "number")  # int widens
        self.assertEqual(resolve("div", "int", "int").returns.name(), "number")
        self.assertEqual(resolve("floor", "number").returns.name(), "int")
        self.assertEqual(resolve("lt", "int", "number").returns.name(), "bool")
        self.assertEqual(resolve("sum", "list<int>").returns.name(), "int")
        self.assertEqual(resolve("cond", "bool", "int", "number").returns.name(), "number")

    def test_resolution_is_cached_per_argument_types(self):
        self.assertIs(resolve("mul", "int", "number"), resolve("mul", "int", "number"))

    def test_mul_mixes_int_and_number(self):
        self.assertEqual(call("mul", ("int", 7), ("number", 0.5)), 3.5)  # an effect on an int floors it later
        self.assertIs(call("mul", ("bool", True), ("bool", False)), False)

    def test_at_least_and_at_most_use_the_type_order(self):
        self.assertEqual(call("atLeast", ("int", 3), ("int", 5)), 5)
        self.assertEqual(call("atMost", ("int", 3), ("int", 5)), 3)
        self.assertEqual(call("atLeast", ("ArmorCategory", "medium"), ("ArmorCategory", "light")), "medium")

    def test_override_and_transform_take_the_new_value(self):
        self.assertEqual(call("override", ("int", 3), ("int", 9)), 9)
        self.assertEqual(call("transform", ("text", "a"), ("text", "b")), "b")

    def test_comparisons_and_lists(self):
        self.assertIs(call("lt", ("ArmorCategory", "light"), ("ArmorCategory", "heavy")), True)
        self.assertIs(call("eq", ("ref<material>", None), ("null", None)), True)
        self.assertIs(call("in", ("Attribute", "dex"), ("list<Attribute>", ["str", "dex"])), True)
        self.assertEqual(call("sum", ("list<number>", [])), 0)
        self.assertIsNone(call("max", ("list<int>", [])))
        self.assertEqual(call("max", ("int", 2), ("number", 2.5)), 2.5)

    def test_list_helpers(self):
        self.assertEqual(resolve("avg", "list<int>").returns.name(), "number")
        self.assertEqual(call("avg", ("list<int>", [1, 2])), 1.5)
        self.assertIsNone(call("avg", ("list<number>", [])))
        self.assertEqual(call("last", ("list<int>", [1, 2])), 2)
        self.assertIs(call("any", ("list<bool>", [False, True])), True)
        self.assertIs(call("any", ("list<bool>", [])), False)
        self.assertIs(call("all", ("list<bool>", [True, False])), False)
        self.assertIs(call("all", ("list<bool>", [])), True)
        with self.assertRaises(UnsupportedOperationError):
            resolve("any", "list<int>")

    def test_number_helpers(self):
        self.assertEqual(call("abs", ("int", -3)), 3)
        self.assertEqual(call("abs", ("number", -1.5)), 1.5)
        self.assertEqual(call("clamp", ("int", 15), ("int", 0), ("int", 10)), 10)
        self.assertEqual(call("clamp", ("int", 5), ("null", None), ("int", 3)), 3)  # null = open bound
        self.assertEqual(call("clamp", ("ArmorCategory", "heavy"), ("ArmorCategory", "clothing"),
                              ("ArmorCategory", "medium")), "medium")
        self.assertEqual(resolve("clamp", "int", "int", "number").returns.name(), "number")

    def test_text_helpers(self):
        self.assertEqual([call("roman", ("int", n)) for n in (1, 4, 9, 14, 1994)], ["I", "IV", "IX", "XIV", "MCMXCIV"])
        with self.assertRaisesRegex(ExpressionError, "1 … 3999"):
            call("roman", ("int", 0))
        self.assertEqual([call("signed", ("int", n)) for n in (2, 0, -1)], ["+2", "+0", "-1"])
        self.assertEqual([call("signed", ("number", n)) for n in (1.5, -2.0)], ["+1.5", "-2"])
        self.assertEqual(call("join", ("list<Attribute>", ["str", "dex"])), "str, dex")
        self.assertEqual(call("join", ("list<int>", [1, None, 2]), ("text", " / ")), "1 / 2")

    def test_unsupported_combination_lists_what_is_supported(self):
        with self.assertRaisesRegex(UnsupportedOperationError, r"'mul' does not support \(text, int\); supported: "
                                                               r"\(int, int\) -> int"):
            resolve("mul", "text", "int")
        with self.assertRaisesRegex(UnsupportedOperationError, "for every ordered T"):
            resolve("lt", "Attribute", "Slot")  # no common type
        with self.assertRaises(DefinitionError):  # a content error: raised while the definition loads
            resolve("lt", "text", "text")

    def test_new_datatype_needs_no_change_to_operations(self):
        self.assertEqual(call("atLeast", ("test-celsius", 12.5), ("test-celsius", 20.0)), 20.0)
        self.assertEqual(call("override", ("test-celsius", 12.5), ("test-celsius", 3.0)), 3.0)
        self.assertIs(call("eq", ("test-celsius", 1.0), ("test-celsius", 1.0)), True)
        with self.assertRaises(UnsupportedOperationError):
            resolve("add", "test-celsius", "test-celsius")

    def test_instance_returns_the_registered_operation(self):
        self.assertIs(AddOperation.instance(), Operation.get("add"))

    def test_effect_operations_in_order_compute_then_clamp_then_override(self):
        self.assertEqual(Operation.effect_names(), ["transform", "add", "mul", "atLeast", "atMost", "override"])
        self.assertIsNone(Operation.get("sub").rank)  # expressions only

    def test_unknown_operation_suggests_the_closest_name(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'atLeast'"):
            Operation.get("atleast")


if __name__ == "__main__":
    unittest.main()
