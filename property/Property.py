import InnerFunction
from datatype.Datatype import Datatype
from property.BufferElement import BufferElement


class Property:
    # todo: add an flag to allow for extension properties. This would just be ref properties, with an additional evaluation
    # todo: add option for lower and upper limits, as well as an option for selected values only.
    #  Weather one of those is applicable for the corresponding datatype is defined by the type (e.g. lower limit for string does not make sense9
    def __init__(self, id: str, instance: "Instance", dataType: Datatype, baseValue: str | InnerFunction, choice: bool):
        self.id = id
        self.instance = instance
        self.dataType = dataType

        self.choice = choice


        self.__baseValue = baseValue

        """
        Dynamic manipulations added by external modifiers. Wiped by {@link remove}
        and re-applied when the owning component is re-attached.
        """
        self._manipulationTrace = []
        """
        Manipulations that are part of the component's own definition (added in
        its constructor). They are permanent and survive {@link remove}.
        """
        self._staticManipulation = []

        self.__cachedValue = None
        self.__hasCache = False

        """
        Guards against cyclic dependencies while {@link calc} is running.
        """
        self._resolving = False
        """
        Value accumulated so far, returned when a cycle re-enters {@link calc}.
        """
        self._partialValue = None
        self._cycleReported = False

        self._override = None # todo: this needs to be saved
        """
        Indicates that the property has been overridden by a user.     
        Also indicates that the property has been set by a user, and didn't just use the default value. (Only relevant for choice properties.)
        """
        self._isOverridden = False # todo: this needs to be saved

        """
        Notifies properties that depend on this one when its value changes, and
        clears this property's own cache when a dependency changes.
        """
        self._propertyBuffer = BufferElement(
            self.instance.propCallStack, self.onUpdate
        )

    def reviewed(self):
        return self._reviewed or not self.choice

    # todo: validate input before setting
    def override(self, value: str):
        self._override = value
        self._isOverridden = True
        self._propertyBuffer.update_and_reset_lower_list()

    def resetOverride(self):
        self._override = None
        self._isOverridden = False
        self._propertyBuffer.update_and_reset_lower_list()


    def onUpdate(self):
        self.__cachedValue = None
        self.__hasCache = False


    def resolve(self):
        return self._propertyBuffer.read_operation()

    def tempCalc(self):
        if (self.__hasCache or self._propertyBuffer.should_update):
            self.__cachedValue = self.calc()
            self.__hasCache = True
        return self.__cachedValue

    def calc(self):
        if(self._override != None and self._isOverridden):
            return self.dataType.deserialize(self._override)

        if(self._resolving):
            self.reportCycle()
            if(self._partialValue != None):
                return self._partialValue
            else:
                return self.baseValue()

        self._resolving = True
        try:
            ret = self.baseValue()
            self.partialValue = ret

            for manipulation in self._staticManipulation:
                ret = manipulation.valueFunc(ret, self.instance)
                self.partialValue = ret

            return ret
        finally:
            self._resolving = False
            self._partialValue = None



    def baseValue(self):
        if isinstance(self.__baseValue, InnerFunction):
            return self.instance.resolveInnerFunction(self.__baseValue).resolve()
        return self.dataType.deserialize(self.__baseValue)

    def reportCycle(self):
        if self._cycleReported:
            return
        self._cycleReported = True

        message =  f"MutableProperty: cyclic dependency detected while resolving '{self.id}' on '{self.definition.pathAsStr}' returning the value accumulated so far."

        # todo: alternative for production
        print(message)

    def addStaticManipulation(self, manipulation):
        self._staticManipulation.append(manipulation)
        self._propertyBuffer.update()

    def addManipulation(self, manipulation):
        if manipulation not in self._manipulationTrace:
            self._manipulationTrace.append(manipulation)
            self._propertyBuffer.update()

    def removeManipulation(self, manipulation):
        if manipulation in self._manipulationTrace:
            self._manipulationTrace.remove(manipulation)
            self._propertyBuffer.update_and_reset_lower_list()
            return True
        return False

    def getManipulationTrace(self):
        combined = [*self._manipulationTrace, *self._staticManipulation]
        return tuple(sorted(combined, key=lambda m: (m.order, m.description)))

    def remove(self):
        self._propertyBuffer.remove()
        self._manipulationTrace.clear()

    def serialize(self) -> str:
        pass # todo return the things that need to be saved

    def deserialize(self, serialized: str):
        pass # todo set the things that have been saved.

