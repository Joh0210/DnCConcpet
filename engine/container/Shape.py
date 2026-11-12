"""
How a container keys and saves its children (concept §4.5): single, list or map.
One strategy object per container, chosen from its declaration.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from engine.datatype.Datatype import Datatype
from engine.errors import ContainerError, DefinitionError
from engine.instance.DbData import DbData

if TYPE_CHECKING:
    from engine.container.Container import Container


class Shape:
    """Base of the shapes; :attr:`name` is how messages (and the concept) call it."""

    name = ""

    def new_key(self, container: Container) -> str:
        """The key for a child added without one."""
        raise ContainerError(f"'{container.path_str}' is a {self.name} container; give a key")

    def check_key(self, container: Container, key: Any) -> str:
        """``key`` normalized, or :class:`ContainerError` if this shape has no such key."""
        return str(key)

    def fixed_keys(self, container: Container) -> list[str]:
        """The keys a ``fixed`` container is created with."""
        return []

    def order(self, keys) -> list[str]:
        """``keys`` in the order children are read and saved."""
        return list(keys)

    def save(self, items: list[tuple[str, DbData]]) -> Any:
        """``(key, child save)`` pairs in the JSON form of this shape (concept §4.13)."""
        raise NotImplementedError

    def load(self, container: Container, raw: Any) -> dict[str, DbData]:
        """The inverse of :meth:`save`: key → child save."""
        raise NotImplementedError


class SingleShape(Shape):
    """At most one child, under the container's own id (``material``). Adding replaces it."""

    name = "single"

    def new_key(self, container):
        return container.id

    def check_key(self, container, key):
        if key != container.id:
            raise ContainerError(
                f"'{container.path_str}' holds a single child; its only key is '{container.id}'"
            )
        return key

    def fixed_keys(self, container):
        return [container.id]

    def save(self, items):
        return items[0][1] if items else None

    def load(self, container, raw):
        return {} if raw is None else {container.id: DbData.coerce(raw)}


class ListShape(Shape):
    """Any number of children under stable numeric keys (``"0"``, ``"1"``, ...). Saved as a list."""

    name = "list"

    def new_key(self, container):
        key = 0  # the lowest free number, so keys stay small and stable
        while str(key) in container._children:
            key += 1
        return str(key)

    def check_key(self, container, key):
        if not str(key).isdigit():
            raise ContainerError(f"'{container.path_str}': list keys are numbers, got '{key}'")
        return str(key)

    def order(self, keys):
        return sorted(keys, key=int)

    def save(self, items):
        return [data for _, data in items]

    def load(self, container, raw):
        return {str(index): DbData.coerce(data) for index, data in enumerate(raw or [])}


class MapShape(Shape):
    """One child per key of a kernel enum (``attributes: {map: Attribute}``, ``equipment: {map: Slot}``)."""

    name = "map"

    def __init__(self, key_type: Datatype):
        self.key_type = key_type

    def check_key(self, container, key):
        try:
            return self.key_type.validate(key)
        except ValueError as error:
            raise ContainerError(f"'{container.path_str}': {error}") from error

    def fixed_keys(self, container):
        options = getattr(self.key_type, "options", None)  # only enums have options
        if options is None:
            raise DefinitionError(f"'{container.path_str}': a fixed map needs an enum as key type")
        return list(options)

    def order(self, keys):
        return sorted(keys, key=self.key_type.sort_key) if self.key_type.ordered else list(keys)

    def save(self, items):
        return {key: data for key, data in items}

    def load(self, container, raw):
        return {self.check_key(container, key): DbData.coerce(data) for key, data in (raw or {}).items()}
