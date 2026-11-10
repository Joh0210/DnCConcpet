from datatype.Operation import DuoOperation, Operation


class OverrideOperation(DuoOperation):
    """Replaces the value. Ranked last so an override really wins within its priority."""

    rank = 50

    def name(self) -> str:
        return "override"

    def use_any(self, datatype, previous, value):
        return value


Operation.register(OverrideOperation())
