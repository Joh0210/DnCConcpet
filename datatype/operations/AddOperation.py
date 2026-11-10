from abc import abstractmethod

from datatype.Operation import MultipleOperation


class AddOperation(MultipleOperation):
    @staticmethod
    def instance():
        return AddOperation()

    def useInt(self, *values):
        return sum(values)

    def useBool(self, *values):
        return any(values)