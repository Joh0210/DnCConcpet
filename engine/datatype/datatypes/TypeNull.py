from engine.datatype.Datatype import Datatype


class TypeNull(Datatype):
    """
    The type of the literal ``null`` — its only value is ``None``. It fits every
    other type (``material != null``, ``entity?.level ?? 0``), see
    :func:`common_type` and :meth:`Datatype.converter`.
    """

    def name(self) -> str:
        return "null"

    def deserialize(self, string):
        if string.strip() == "null":
            return None
        raise ValueError(f"expected null, got {string!r}")

    def serialize(self, value):
        return "null"

    def validate(self, value):
        if value is None:
            return None
        raise ValueError(f"expected null, got {value!r}")


Datatype.register(TypeNull())
