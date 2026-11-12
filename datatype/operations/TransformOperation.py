from datatype.Operation import Operation


class TransformOperation(Operation):
    """
    Any function of ``previous``. The effect's value expression already computed
    the new value from ``previous`` (a path ``{"path": [], "from": "previous"}``),
    so this only takes it over. Ranked first: it rewrites the value before
    anything is added.
    """

    rank = 0

    def name(self) -> str:
        return "transform"

    def generic(self, types):
        """(T, U) -> U for every T, U"""
        if len(types) != 2:
            return None
        return self.overload(types, types[1], lambda previous, value: value)


Operation.register(TransformOperation())
