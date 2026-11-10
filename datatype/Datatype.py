from abc import abstractmethod


class Datatype:
    def __init__(self):
        pass

    @abstractmethod
    def deserialize(self, string):
        pass

    @abstractmethod
    def serialize(self, value):
        pass

    @abstractmethod
    def useOperation(self, operation, *values):
        pass