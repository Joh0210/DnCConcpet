from abc import ABC, abstractmethod


class Operation(ABC):
    pass

class SingleOperation(Operation):
    @abstractmethod
    def useInt(self, value):
        pass

    @abstractmethod
    def useBool(self, value):
        pass

class MultipleOperation(Operation):
    @abstractmethod
    def useInt(self, *values):
        pass

    @abstractmethod
    def useBool(self, *values):
        pass

class DuoOperation(Operation):
    @abstractmethod
    def useInt(self, value1, value2):
        pass

    @abstractmethod
    def useBool(self, value1, value2):
        pass

