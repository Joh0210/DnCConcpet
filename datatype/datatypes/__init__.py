"""
Importing this package registers every built-in datatype.
A new type: add a module that calls ``Datatype.register`` and import it here.
"""
from datatype.datatypes import TypeBool, TypeEnum, TypeInt, TypeNumber, TypeText  # noqa: F401
