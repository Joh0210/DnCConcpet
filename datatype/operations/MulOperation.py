from abc import abstractmethod
from operator import mul

from datatype.Operation import MultipleOperation


class MulOperation(MultipleOperation):
    @staticmethod
    def instance():
        return MulOperation()

    def useInt(self, *values):
        return mul(*values)

    def useBool(self, *values):
        return all(values)