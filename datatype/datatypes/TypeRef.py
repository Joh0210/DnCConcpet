from datatype.Datatype import Datatype


class TypeRef(Datatype):
    """
    ``ref<X>``: an instance of the definition ``X`` or of one extending it — what
    a path yields when it ends at an instance instead of a prop (``material``,
    ``entity``, ``it``). Compared with ``==`` / ``!=`` (``material != null``).

    Parametrized: ``Datatype.get("ref<material>")``. Saving refs is not part of
    this prototype: :meth:`serialize` gives the definition id for display only.
    """

    def __init__(self, target: str):
        self.target = target

    def name(self) -> str:
        return f"ref<{self.target}>"

    def kind(self) -> str:
        return "ref"

    def deserialize(self, string):
        raise ValueError(f"{self.name()} values cannot be read from text yet")

    def serialize(self, value):
        return value.def_id

    def validate(self, value):
        is_a = getattr(value, "is_a", None)
        if is_a is None or not is_a(self.target):
            raise ValueError(f"expected an instance of '{self.target}', got {value!r}")
        return value


Datatype.register_constructor("ref", TypeRef)
