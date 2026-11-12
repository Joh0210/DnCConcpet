"""
Where a property's base value comes from (concept §4.4, ``source``).

One small strategy per source, looked up by name. They replace the old class split
into ``MutableProperty`` and ``StorableProperty``: that split made a value that is
both chosen and modified by effects (``attribute.value``: choice + modifiable)
impossible, while in the concept ``source`` and ``modifiable`` are independent.

A new source is a subclass plus ``Source.register``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from errors import DefinitionError, did_you_mean

if TYPE_CHECKING:
    from property.Property import Property


class Source:
    _registry: ClassVar[dict[str, Source]] = {}

    name: ClassVar[str] = ""
    #: A definition may give it a value with ``set``.
    settable: ClassVar[bool] = True
    #: The user picks the value (Wiki / sheet) → ``Property.choose``.
    choosable: ClassVar[bool] = False
    #: Play changes the value (steps) → ``Property.write``.
    writable: ClassVar[bool] = False
    #: A concrete entry must give it a value somewhere in its chain.
    requires_value: ClassVar[bool] = True

    @staticmethod
    def register(source: Source) -> Source:
        Source._registry[source.name] = source
        return source

    @staticmethod
    def get(name: str) -> Source:
        try:
            return Source._registry[name]
        except KeyError:
            raise DefinitionError(
                f"unknown property source '{name}'{did_you_mean(name, Source._registry)}"
            ) from None

    def base(self, prop: Property) -> Any:
        """The value before any effect."""
        return prop.convert(prop.base_expression, "base value")

    def __repr__(self) -> str:
        return f"<Source {self.name}>"


class ConstSource(Source):
    """Fixed by the definition chain (``default`` / ``set``). Not saved."""

    name = "const"


class DerivedSource(Source):
    """Computed by its ``derive`` expression. Not saved, cannot be ``set``."""

    name = "derived"
    settable = False


class ChoiceSource(Source):
    """Picked per instance within ``range`` / ``options``; the default until picked. Saved."""

    name = "choice"
    choosable = True

    def base(self, prop: Property) -> Any:
        return prop.stored if prop.has_stored else super().base(prop)


class StateSource(Source):
    """Changes during play, written only by steps; ``range`` clamps every write. Saved."""

    name = "state"
    writable = True

    def base(self, prop: Property) -> Any:
        return prop.stored if prop.has_stored else super().base(prop)


class ParamSource(Source):
    """Bound by whoever creates the instance (``Instance(..., params={...})``). Not saved."""

    name = "param"
    requires_value = False

    def base(self, prop: Property) -> Any:
        params = prop.instance.params
        if prop.id in params:
            return prop.convert(params[prop.id], "parameter")
        return super().base(prop)


for _source in (ConstSource(), DerivedSource(), ChoiceSource(), StateSource(), ParamSource()):
    Source.register(_source)
