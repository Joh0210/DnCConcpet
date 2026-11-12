"""
Importing this package registers every built-in datatype.
A new type: add a module that calls ``Datatype.register`` and import it here.
"""
from engine.datatype.datatypes import (  # noqa: F401
    TypeBool,
    TypeEnum,
    TypeInt,
    TypeList,
    TypeNull,
    TypeNumber,
    TypeRef,
    TypeText,
)
