"""
Importing this package registers every built-in operation.
A new operation: add a module that calls ``Operation.register`` and import it here.
"""
from datatype.operations import (  # noqa: F401
    AddOperation,
    ArithmeticOperations,
    AtLeastOperation,
    AtMostOperation,
    ComparisonOperations,
    ListOperations,
    LogicOperations,
    MulOperation,
    OverrideOperation,
    TextOperations,
    TransformOperation,
)
