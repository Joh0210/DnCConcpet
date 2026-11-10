from typing import List

from property.BufferElement import BufferElement
from property.Property import Property


class Instance:
    def __init__(self, id: str, data: "DbData"):
        self._propCallStack: List[BufferElement] = []
        self._contained = None
        self.id = id
        self.props: dict[str, Property] = {}

        # todo:
        #  self.container: dict[str, "Container"] = {}
        self.sub_ids: list[str] = []

        # 1. Vererbungskette ablaufen (Kind -> Eltern), Zyklen verhindern
        definitions = []
        current_id: str | None = id
        while current_id is not None and current_id not in self.sub_ids:
            self.sub_ids.append(current_id)
            data_object = get_data_definition_from_yml(current_id)
            definitions.append(data_object)
            current_id = data_object.extends

        # 2. Von der Basis zum Kind anwenden (LIFO), damit Kinder überschreiben
        for data_object in reversed(definitions):
            for prop in data_object.properties:
                # todo: adjust so that the property uses the YML definition as a parameter instead of the individual keys.
                self.props[prop.id] = Property(self, prop)
            #todo:
            # for container in data_object.container:
            #     self.container[container.id] = container
            for override in data_object.set:
                # todo: add an adjust function to properties that bulk overrides the behavior
                self.props[override.id].adjust(override.data)

        # 3. Daten setzen
        for key, value in data.items():
            pass # todo

    def toData(self) -> "DbData":
        pass # todo

    


    def prop_call_stack(self) -> List[BufferElement]:
        container = (
            self._contained.container if self._contained is not None else None
        )
        if container is not None:
            return container.prop_call_stack

        return self._propCallStack