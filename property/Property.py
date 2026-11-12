from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from InnerFunction import EvalContext, InnerFunction
from datatype.Datatype import Datatype
from errors import (
    CyclicDependencyError,
    DefinitionError,
    IllegalMutationError,
    PropertyError,
    did_you_mean,
)
from property.BufferElement import BufferElement
from property.Source import Source

if TYPE_CHECKING:
    from Instance import Instance
    from property.Manipulation import Manipulation

log = logging.getLogger("engine")

#: Keys a property declaration (an entry under ``props:``) may contain.
SPEC_KEYS = {"type", "source", "default", "derive", "modifiable", "range", "options", "clamp", "optional"}
#: Keys a ``refine:`` entry may contain.
REFINE_KEYS = {"range", "options", "default", "lock"}

_NOTHING = object()


class Property:
    """
    One value of an instance (concept §4.4) — and the core of the observer pattern.

    The value is computed as::

        base (from the source) → manipulations, sorted by their order → clamp

    and cached. The BufferElement records what the computation read and drops the
    cache when any of it changes, so dependants never see a stale value and
    nothing recomputes needlessly.

    Built from the declaration in the YML/JSON (``props: {weight: {type: number, ...}}``):

    - ``type``: name of a :class:`Datatype`; it parses, validates and orders values.
    - ``source``: where the base comes from (:mod:`property.Source`); ``derive``
      implies ``derived``, otherwise ``const`` is the default.
    - ``default`` / ``derive``: a VALUE (concept §4.14).
    - ``modifiable``: whether effects may change the value.
    - ``range`` (bounds are VALUEs), ``options`` (a list of VALUEs or one
      ``list<T>`` VALUE), ``clamp`` (after all effects), ``optional`` (may be ``None``).

    Every value from the definition is a node (:class:`InnerFunction`) — a
    literal, a path or an operation are the same thing here, built by the
    game's store and checked against the prop's type when the definition loads
    (:meth:`_value`). The property only ever calls :meth:`evaluate` on them.
    Values from outside the definitions — a choice, a write, a parameter, a
    save — are plain data and go through the datatype (:meth:`parse_input`).
    """

    def __init__(self, instance: Instance, id: str, spec: dict):
        self.id = id
        self.instance = instance

        unknown = set(spec) - SPEC_KEYS
        if unknown:
            key = sorted(unknown)[0]
            raise DefinitionError(f"prop '{id}': unknown key '{key}'{did_you_mean(key, SPEC_KEYS)}")
        if "type" not in spec:
            raise DefinitionError(f"prop '{id}' has no type")

        self.datatype: Datatype = Datatype.get(spec["type"])
        source = spec.get("source", "derived" if "derive" in spec else "const")
        if "derive" in spec and source != "derived":
            raise DefinitionError(f"prop '{id}': 'derive' cannot be combined with source '{source}'")
        self.source: Source = Source.get(source)
        self.modifiable: bool = bool(spec.get("modifiable", False))
        self.optional: bool = bool(spec.get("optional", False))

        # Base value (const / derived) or default (choice / state / param): a node, None while open.
        self._has_base: bool = "derive" in spec or "default" in spec
        self._base: InnerFunction | None = (
            self._value(spec["derive"] if "derive" in spec else spec["default"], "base value")
            if self._has_base else None
        )
        self._range = self._check_bounds(spec.get("range"), "range")
        self._options = self._check_options(spec.get("options"))
        self._clamp = self._check_bounds(spec.get("clamp"), "clamp")
        self._locked = False

        # The value picked by the user (choice) or written in play (state). It
        # replaces the *base* value, not the result: effects still apply on top
        # (attribute.value is chosen *and* raised by enchantments).
        self._stored: Any = None
        self._has_stored = False
        """
        Indicates that the user has set the property explicitly and it didn't just
        use the default value. (Only relevant for choice properties.)
        """
        self._reviewed = False

        """
        Effects bound to this property by the root of its tree (Instance._rebind).
        Bound and unbound as the structure changes.
        """
        self._manipulation_trace: list[Manipulation] = []
        """
        Kernel-internal manipulations that are part of the property itself. They
        are permanent and survive remove().
        """
        self._static_manipulation: list[Manipulation] = []

        self._cached_value: Any = None
        self._has_cache = False

        """
        Guards against cyclic dependencies while calc is running.
        """
        self._resolving = False
        """
        Value accumulated so far, returned when a cycle re-enters calc.
        """
        self._partial_value: Any = _NOTHING
        self._cycle_reported = False

        """
        Notifies properties that depend on this one when its value changes, and
        clears this property's own cache when a dependency changes.
        """
        self._property_buffer = BufferElement(self.instance.prop_call_stack, self._on_update)

    # ------------------------------------------------------------------ definition

    def adjust(self, value: Any) -> None:
        """A ``set`` in a definition: the base value (const) or the default (choice / state / param)."""
        if not self.source.settable:
            raise DefinitionError(f"'{self.path_str}' is {self.source.name}; it cannot be set")
        self._base = self._value(value, "value")
        self._has_base = True
        self._property_buffer.update()

    def refine(self, spec: dict) -> None:
        """A ``refine`` in a definition: narrow ``range`` / ``options``, change ``default``, ``lock`` a choice."""
        unknown = set(spec) - REFINE_KEYS
        if unknown:
            key = sorted(unknown)[0]
            raise DefinitionError(
                f"refine of '{self.path_str}': unknown key '{key}'{did_you_mean(key, REFINE_KEYS)}"
            )
        if "range" in spec:
            self._range = self._check_bounds(spec["range"], "range")
        if "options" in spec:
            self._options = self._check_options(spec["options"])
        if "default" in spec:
            self.adjust(spec["default"])
        if "lock" in spec:
            if not self.source.choosable:
                raise DefinitionError(f"'{self.path_str}' is {self.source.name}; only a choice can be locked")
            self._base = self._value(spec["lock"], "lock")
            self._has_base = True
            self._locked = True
        self._property_buffer.update()

    def is_open(self) -> bool:
        """Declared without a value — allowed only on abstract entries."""
        return not self._has_base and not self.optional and self.source.requires_value

    def _value(self, raw: Any, what: str, expected: Datatype | None = None) -> InnerFunction:
        """A value of the definition as a node of the prop's type (``expected``), shared through the store."""
        try:
            return self.instance.store.value(raw, expected or self.datatype)
        except DefinitionError as error:
            raise DefinitionError(f"prop '{self.id}': {what}: {error}") from None

    def _check_bounds(self, bounds: Any, key: str) -> list[InnerFunction] | None:
        if bounds is None:
            return None
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise DefinitionError(f"prop '{self.id}': '{key}' must be [min, max] (null = unbounded)")
        if not self.datatype.ordered:
            raise DefinitionError(f"prop '{self.id}': type '{self.datatype.name()}' has no order, '{key}' makes no sense")
        return [self._value(bound, f"{key} bound") for bound in bounds]

    def _check_options(self, options: Any) -> list[InnerFunction] | InnerFunction | None:
        """A list of values, or one value of type ``list<T>`` (``DamageType[where ...]``)."""
        if options is None:
            return None
        if isinstance(options, (list, tuple)):
            return [self._value(option, "option") for option in options]
        return self._value(options, "options", Datatype.get(f"list<{self.datatype.name()}>"))

    # ------------------------------------------------------------------ reading

    def resolve(self) -> Any:
        """The current value. Whoever is resolving right now becomes a dependant (see BufferElement)."""
        return self._property_buffer.read_operation(self._cached_calc)

    def _cached_calc(self) -> Any:
        if not self._has_cache or self._property_buffer.should_update:
            self._cached_value = self.calc()
            self._has_cache = True
        return self._cached_value

    def _on_update(self) -> None:
        self._cached_value = None
        self._has_cache = False

    def calc(self) -> Any:
        if self._resolving:
            if self._partial_value is _NOTHING:
                raise CyclicDependencyError(
                    f"'{self.path_str}' depends on itself while computing its base value"
                )
            self._report_cycle()
            return self._partial_value

        self._resolving = True
        try:
            ret = self.base_value()
            self._partial_value = ret

            if ret is not None:
                # an absent optional value stays absent
                # todo: should this be a special case? I mean probably one of the "manipulations" will
                #  initialize it to something, but if not, it will stay None.
                for manipulation in self.get_manipulation_trace():
                    ret = manipulation.apply(ret, self)
                    self._partial_value = ret
                ret = self._apply_clamp(ret)

            return ret
        finally:
            self._resolving = False
            self._partial_value = _NOTHING

    def base_value(self) -> Any:
        """The value before any effect, as the source defines it."""
        return self.source.base(self)

    @property
    def base_expression(self) -> InnerFunction | None:
        """The declared base / default node (``None`` while open)."""
        return self._base

    def evaluate(self, node: InnerFunction | None, what: str = "value") -> Any:
        """A node of the definition evaluated with ``this`` = the instance, checked by the datatype."""
        if node is None:
            return None
        value = node.evaluate(EvalContext(this=self.instance))
        if value is None:
            return None
        try:
            return self.datatype.validate(value)
        except ValueError as error:
            raise PropertyError(f"'{self.path_str}': invalid {what}: {error}") from error

    def parse_input(self, raw: Any, what: str = "value") -> Any:
        """A value from outside the definitions (choice, write, parameter, save) parsed by the datatype."""
        if raw is None:
            return None
        try:
            return self.datatype.parse(raw)
        except ValueError as error:
            raise PropertyError(f"'{self.path_str}': invalid {what}: {error}") from error

    def bounds(self) -> tuple[Any, Any]:
        """``range`` evaluated; ``(None, None)`` when unbounded."""
        if self._range is None:
            return None, None
        lower, upper = self._range
        return self.evaluate(lower, "range bound"), self.evaluate(upper, "range bound")

    def options(self) -> list | None:
        """``options`` evaluated, or ``None`` when any value of the type is allowed."""
        if self._options is None:
            return None
        if isinstance(self._options, list):
            return [self.evaluate(option, "option") for option in self._options]
        ctx = EvalContext(this=self.instance)
        return [self.datatype.validate(option) for option in self._options.evaluate(ctx)]

    def _apply_clamp(self, value: Any) -> Any:
        if self._clamp is None:
            return value
        lower, upper = (self.evaluate(bound, "clamp bound") for bound in self._clamp)
        return self.datatype.clamp(value, lower, upper)

    def _report_cycle(self) -> None:
        if self._cycle_reported:
            return
        self._cycle_reported = True
        # todo: alternative for production
        log.warning(
            "cyclic dependency detected while resolving '%s'; returning the value accumulated so far",
            self.path_str,
        )

    # ------------------------------------------------------------------ writing

    def choose(self, value: Any) -> None:
        """
        Pick the value of a ``choice`` prop (Wiki / sheet). Checked against
        ``range`` / ``options``; marks the prop as reviewed.
        """
        if not self.source.choosable:
            raise PropertyError(
                f"'{self.path_str}' is a {self.source.name} property; only choice properties can be chosen"
            )
        if self._locked:
            raise PropertyError(f"'{self.path_str}' is locked to {self._base.describe()}")
        self._check_mutable()
        value = self.parse_input(value)
        self.check_allowed(value)
        self._store(value)
        # A target path may depend on a choice (entity.attributes[stat]): let the root re-bind.
        self.instance._structure_changed()

    def write(self, value: Any) -> None:
        """Write a ``state`` prop (a step during play). ``range`` clamps the value."""
        if not self.source.writable:
            raise PropertyError(
                f"'{self.path_str}' is a {self.source.name} property; only state properties can be written"
            )
        self._check_mutable()
        value = self.parse_input(value)
        if value is not None:
            lower, upper = self.bounds()
            value = self.datatype.clamp(value, lower, upper)
        self._store(value)

    def reset(self) -> None:
        """Forget the chosen / written value: back to the default."""
        self._check_mutable()
        if not self._has_stored:
            return
        self._stored = None
        self._has_stored = False
        self._reviewed = False
        self._property_buffer.update_and_reset_lower_list()
        if self.source.choosable:
            self.instance._structure_changed()

    def check_allowed(self, value: Any) -> None:
        """Raise :class:`PropertyError` if ``value`` is outside ``range`` / ``options``."""
        if value is None:
            if not self.optional:
                raise PropertyError(f"'{self.path_str}' is not optional")
            return
        lower, upper = self.bounds()
        key = self.datatype.sort_key
        if (lower is not None and key(value) < key(lower)) or (upper is not None and key(value) > key(upper)):
            raise PropertyError(f"'{self.path_str}': {value!r} is outside the range [{lower}, {upper}]")
        options = self.options()
        if options is not None and value not in options:
            raise PropertyError(
                f"'{self.path_str}': {value!r} is not one of {options}{did_you_mean(str(value), options)}"
            )

    def _store(self, value: Any) -> None:
        self._stored = value
        self._has_stored = True
        self._reviewed = True
        # The value no longer comes from the default expression: forget what it read.
        self._property_buffer.update_and_reset_lower_list()

    def _check_mutable(self) -> None:
        """Changing a value mid-resolve would make results depend on evaluation order."""
        stack = self.instance.prop_call_stack()
        if stack:
            raise IllegalMutationError(
                f"'{self.path_str}' changed while a property was resolving (stack depth {len(stack)})"
            )

    @property
    def stored(self) -> Any:
        return self._stored

    @property
    def has_stored(self) -> bool:
        return self._has_stored

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def reviewed(self) -> bool:
        """Whether the user explicitly picked this choice (even its default). Always true for other sources."""
        return self._reviewed or not self.source.choosable

    # ------------------------------------------------------------------ manipulations

    def add_static_manipulation(self, manipulation: Manipulation) -> None:
        """A kernel-internal manipulation that belongs to the property itself (survives :meth:`remove`)."""
        manipulation.check_target(self)
        if manipulation not in self._static_manipulation:
            self._static_manipulation.append(manipulation)
            self._property_buffer.update()

    def add_manipulation(self, manipulation: Manipulation) -> None:
        """
        Bind an effect. Only ``modifiable`` properties accept effects, and only
        effects whose operation works on this prop's type and whose result fits it.
        """
        if not self.modifiable:
            raise PropertyError(
                f"'{self.path_str}' is not modifiable; effect {manipulation!r} cannot target it"
            )
        manipulation.check_target(self)
        if manipulation not in self._manipulation_trace:
            self._manipulation_trace.append(manipulation)
            self._property_buffer.update()

    def remove_manipulation(self, manipulation: Manipulation) -> bool:
        if manipulation in self._manipulation_trace:
            self._manipulation_trace.remove(manipulation)
            # forget what the removed manipulation read, too
            self._property_buffer.update_and_reset_lower_list()
            return True
        return False

    def get_manipulation_trace(self) -> tuple[Manipulation, ...]:
        """Every manipulation, in the order it is applied — the breakdown the sheet can show."""
        combined = [*self._manipulation_trace, *self._static_manipulation]
        return tuple(sorted(combined, key=lambda m: m.order))

    def remove(self) -> None:
        """Detach the property from the dependency graph and drop its bound effects."""
        self._property_buffer.remove()
        self._manipulation_trace.clear()

    # ------------------------------------------------------------------ save

    def serialize(self) -> str | None:
        """
        What the save stores for this property, or ``None`` (still the default).
        Only ``choose`` / ``write`` store a value, so only choice and state props are ever saved.
        """
        if not self._has_stored:
            return None
        return self.datatype.serialize(self._stored)

    def deserialize(self, serialized: Any) -> None:
        """Restore a value written by :meth:`serialize` — with the same checks as a fresh choice / write."""
        if self.source.choosable:
            self.choose(serialized)
        elif self.source.writable:
            self.write(serialized)
        else:
            raise PropertyError(f"'{self.path_str}' is {self.source.name}; it is not saved")

    # ------------------------------------------------------------------ misc

    @property
    def path_str(self) -> str:
        return f"{self.instance.path}.{self.id}"

    def __repr__(self) -> str:
        return f"<Property {self.path_str} ({self.source.name} {self.datatype.name()})>"
