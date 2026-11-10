from datatype.Datatype import Datatype


class TypeBool(Datatype):
    @staticmethod
    def instance():
        return TypeBool()

    def deserialize(self, string):
        return string == "True"

    def serialize(self, value):
        return str(value)

    def useOperation(self, operation, *values):
        return operation.useBool(*values)