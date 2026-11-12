"""
Exceptions raised by the engine.

Every message names the definition / property / container involved, so an author
(or an AI) can fix the content without reading engine code. Most of these are
errors the validator should catch before runtime; the engine checks them anyway
so a broken entry fails loudly instead of computing wrong values.
"""
from difflib import get_close_matches
from typing import Iterable


class EngineError(Exception):
    """Base class of every engine error."""


class DefinitionError(EngineError):
    """A definition entry (or the chain it inherits from) is malformed."""


class PropertyError(EngineError):
    """A property was used against its declaration: wrong source, out of range, not modifiable, ..."""


class ContainerError(EngineError):
    """A child does not fit a container, or the container refuses the change."""


class IllegalMutationError(EngineError):
    """A value or the structure was changed while a property was resolving.

    Changing something mid-resolve would make results depend on evaluation order.
    """


class CyclicDependencyError(EngineError):
    """A property depends on itself — through its base value or through an effect.

    Always an error: any fallback value would depend on which property was read
    first, so two engines (browser preview, server) could compute different results.
    """


class BindingError(PropertyError):
    """Effects could not be bound after a structural change (wrong type, target not
    modifiable, a target path that reads a value it must not).

    Binding is all or nothing: when this is raised, no binding has changed, and a
    single ``add`` / ``choose`` / ``load`` has been rolled back.
    """


class UnsupportedOperationError(DefinitionError, TypeError):
    """An operation was applied to argument types it has no overload for.

    Raised when an expression is built (the definition loads), not while it runs:
    operations are resolved by the static types of their arguments.
    """


class ExpressionError(EngineError):
    """An expression failed while it ran — e.g. a path segment is absent where
    the content did not allow it (no ``?.``), or a division by zero."""


def did_you_mean(name: str, candidates: Iterable[str]) -> str:
    """Suffix for an error message: `` — did you mean 'level'?`` or an empty string."""
    match = get_close_matches(name, [str(c) for c in candidates], n=1)
    return f" — did you mean '{match[0]}'?" if match else ""
