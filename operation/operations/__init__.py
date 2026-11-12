"""
Importing this package registers every built-in operation.
A new operation: add it to the module of its kind (or a new module that calls
``Operation.register``, imported here).
"""
from operation.operations import (  # noqa: F401
    ArithmeticOperations,
    ComparisonOperations,
    EffectOperations,
    ListOperations,
    LogicOperations,
    TextOperations,
)
