import unittest

from datatype.Datatype import Datatype
from datatype.Operation import Operation
from datatype.datatypes.TypeInt import TypeInt
from datatype.operations.AddOperation import AddOperation
from errors import DefinitionError, UnsupportedOperationError


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


def use(type_name, operation_name, *values):
    return Datatype.get(type_name).use_operation(Operation.get(operation_name), *values)


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
        for type_name, value in [("int", 7), ("number", 2.5), ("bool", True), ("text", "hi"), ("Slot", "body")]:
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


class OperationTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(use("int", "add", 3, 4), 7)
        self.assertEqual(use("number", "add", 1.5, 1), 2.5)
        self.assertIs(use("bool", "add", False, True), True)

    def test_mul_floors_on_int_and_takes_any_number_of_values(self):
        self.assertEqual(use("int", "mul", 7, 0.5), 3)
        self.assertEqual(use("int", "mul", 2, 3, 4), 24)
        self.assertIs(use("bool", "mul", True, True, False), False)

    def test_at_least_and_at_most_use_the_type_order(self):
        self.assertEqual(use("int", "atLeast", 3, 5), 5)
        self.assertEqual(use("int", "atMost", 3, 5), 3)
        self.assertEqual(use("ArmorCategory", "atLeast", "medium", "light"), "medium")

    def test_override_and_transform_take_the_new_value(self):
        self.assertEqual(use("int", "override", 3, 9), 9)
        self.assertEqual(use("text", "transform", "a", "b"), "b")

    def test_unsupported_combination_raises_a_clear_error(self):
        with self.assertRaisesRegex(UnsupportedOperationError, "'mul' does not support type 'text'"):
            use("text", "mul", "a", 2)

    def test_new_datatype_needs_no_change_to_operations(self):
        self.assertEqual(use("test-celsius", "atLeast", 12.5, 20.0), 20.0)
        self.assertEqual(use("test-celsius", "override", 12.5, 3.0), 3.0)
        with self.assertRaises(UnsupportedOperationError):
            use("test-celsius", "add", 1.0, 2.0)

    def test_instance_returns_the_registered_operation(self):
        self.assertIs(AddOperation.instance(), Operation.get("add"))

    def test_rank_orders_compute_then_clamp_then_override(self):
        names = sorted(Operation.names(), key=lambda name: Operation.get(name).rank)
        self.assertEqual(names, ["transform", "add", "mul", "atLeast", "atMost", "override"])

    def test_unknown_operation_suggests_the_closest_name(self):
        with self.assertRaisesRegex(DefinitionError, "did you mean 'atLeast'"):
            Operation.get("atleast")


if __name__ == "__main__":
    unittest.main()
