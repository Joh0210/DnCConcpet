from datatype.Datatype import Datatype
from errors import did_you_mean

#: Enums defined by the kernel (concept §4.4: "kernel enums"). The order of the
#: options is the order of the values (``atLeast`` on ArmorCategory, ranges).
#: A new enum is one line here.
KERNEL_ENUMS: dict[str, list[str]] = {
    "Attribute": ["str", "dex", "con", "int", "wis", "cha"],
    "Slot": ["mainHand", "offHand", "body"],
    "ArmorCategory": ["clothing", "light", "medium", "heavy"],
    "MaterialCategory": ["metal", "wood", "any"],
    "MaterialRequired": ["metal", "notMetal", "any"],
    "DamageType": ["physical", "fire", "cold", "lightning", "psychic"],
}


class TypeEnum(Datatype):
    """
    One value out of a fixed, ordered list of options. Every kernel enum is its
    own registered datatype (``Datatype.get("Attribute")``); operations dispatch
    on the shared kind ``enum``. Also the key type of ``map`` containers.
    """

    ordered = True

    def __init__(self, name: str, options: list[str]):
        super().__init__()
        self._name = name
        self.options: tuple[str, ...] = tuple(options)

    @classmethod
    def instance(cls):
        raise TypeError("TypeEnum is parametrized — use Datatype.get('<EnumName>')")

    def name(self) -> str:
        return self._name

    def kind(self) -> str:
        return "enum"

    def deserialize(self, string):
        return self.validate(string.strip())

    def serialize(self, value):
        return value

    def validate(self, value):
        if value in self.options:
            return value
        raise ValueError(
            f"'{value}' is not a {self._name} ({', '.join(self.options)})"
            f"{did_you_mean(str(value), self.options)}"
        )

    def sort_key(self, value):
        return self.options.index(value)


for _name, _options in KERNEL_ENUMS.items():
    Datatype.register(TypeEnum(_name, _options))
