import json

from engine.datatype.Datatype import Datatype


class TypeList(Datatype):
    """
    ``list<T>``: an ordered list of values of the element type ``T``. A path that
    fans out (``inventory[*].weight``) yields one; ``sum``, ``count``, ``in`` take
    one. Lists are never null — "nothing" is the empty list (concept §4.6).

    Parametrized: ``Datatype.get("list<number>")`` builds and shares the type.
    """

    def __init__(self, element: Datatype):
        self.element = element

    def name(self) -> str:
        return f"list<{self.element.name()}>"

    def kind(self) -> str:
        return "list"

    def deserialize(self, string):
        return self.validate(json.loads(string))

    def serialize(self, value):
        return json.dumps([self.element.serialize(item) for item in value])

    def validate(self, value):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"expected {self.name()}, got {value!r}")
        return [self.element.parse(item) for item in value]


Datatype.register_constructor("list", lambda argument: TypeList(Datatype.get(argument)))
