from datatype.Datatype import Datatype


class TypeInt(Datatype):
    @staticmethod
    def instance():
        return TypeInt()

    def deserialize(self, string):
        return int(string)

    def serialize(self, value):
        return str(value)

    def useOperation(self, operation, *values):
        return operation.useInt(*values)