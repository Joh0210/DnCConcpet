from datatype.Operation import DuoOperation, Operation


class TransformOperation(DuoOperation):
    """
    Any function of ``previous``. The effect's value expression already computed
    the new value from ``previous`` (it is in the EvalContext), so this only
    takes it over. Ranked first: it rewrites the value before anything is added.
    """

    rank = 0

    def name(self) -> str:
        return "transform"

    def use_any(self, datatype, previous, value):
        return value


Operation.register(TransformOperation())
