from datatype.Operation import Operation


class OverrideOperation(Operation):
    """Replaces the value. Ranked last so an override really wins within its priority."""

    rank = 50

    def name(self) -> str:
        return "override"

    def generic(self, types):
        """(T, U) -> U for every T, U"""
        if len(types) != 2:
            return None
        return self.overload(types, types[1], lambda previous, value: value)


Operation.register(OverrideOperation())
