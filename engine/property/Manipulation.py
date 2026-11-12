"""
One effect, applied to one or more properties (concept §4.8).

Design decision: an effect is data, not a closure — an operation, a value (a
VALUE node), a target path, a priority, an optional ``when`` and ``label``. That
keeps the content pure JSON. Which properties it currently hits is decided by
the root's binding (``Instance._rebind``), not by the manipulation itself.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from engine.datatype.Datatype import Datatype
from engine.errors import DefinitionError, PropertyError, UnsupportedOperationError, did_you_mean
from engine.operation.Operation import Operation, Overload
from engine.value.InnerFunction import EvalContext, InnerFunction
from engine.value.build import build_value

if TYPE_CHECKING:
    from engine.instance.Instance import Instance
    from engine.property.Property import Property
    from engine.value.PathValue import PathValue

#: Named priority stages, internally numbers with gaps so stages can be inserted later.
#: ``base`` adjusts the starting value, ``final`` holds caps / overrides after everything else.
PRIORITIES: dict[str, int] = {"base": 100, "normal": 500, "final": 900}

#: Keys of an effect entry besides the operation key.
EFFECT_KEYS = {"target", "priority", "when", "label"}


def priority_number(priority: str | int) -> int:
    """A priority as its number: a stage name from :data:`PRIORITIES`, or a number as is."""
    if isinstance(priority, int) and not isinstance(priority, bool):  # a bool is an int in Python
        return priority
    try:
        return PRIORITIES[priority]
    except (KeyError, TypeError):
        raise DefinitionError(
            f"unknown priority '{priority}'{did_you_mean(str(priority), PRIORITIES)}"
        ) from None


class Manipulation:
    """
    An effect is an operation call whose first argument is the target's value
    so far: ``add: 2`` on ``x`` computes ``add(previous, 2)``. The operation is
    the same as in expressions; it is resolved for ``(prop type, value type)``
    when the effect is bound to a prop (:meth:`check_target`) — a mismatch is
    reported then, not on some later read.

    The result is *assigned* to the prop: the same type or a widening as is,
    and the one narrowing an effect may do — ``number`` → ``int`` floors, which
    is how a fractional ``mul`` works without a ``div`` (concept §4.8).
    """

    def __init__(
        self,
        operation: Operation,
        value: Any,
        target: PathValue | None = None,
        source: Instance | None = None,
        priority: str | int = "normal",
        when: Any = None,
        label: Any = None,
        index: int = 0,
    ):
        """
        :param operation: how ``value`` is combined with the value so far; must be an effect operation.
        :param value: a VALUE node, evaluated with ``this = source`` (a bare scalar is built into one).
        :param target: where the effect goes; ``None`` for a kernel-internal (static) manipulation.
        :param source: the instance the effect belongs to; its ``active`` guard gates the effect.
        :param when: ``bool`` VALUE gating this effect alone.
        :param label: ``text`` VALUE (a template) shown instead of the generated description.
        :param index: position among the source's effects — the last tie-break.
        """
        if operation.rank is None:
            raise DefinitionError(
                f"'{operation.name()}' is not an effect operation ({', '.join(Operation.effect_names())})"
            )
        self.operation = operation
        self.value: InnerFunction = build_value(value)
        self.target = target
        self.source = source
        self.priority = priority_number(priority)
        self.when: InnerFunction | None = None if when is None else build_value(when, Datatype.get("bool"))
        self.label: InnerFunction | None = None if label is None else build_value(label, Datatype.get("text"))
        self.index = index
        # prop type → (overload, assignment), resolved when bound to a prop of that type
        self._resolved: dict[Datatype, tuple[Overload, Callable[[Any], Any]]] = {}

    @classmethod
    def from_effect(cls, effect: dict, source: Instance, index: int) -> Manipulation:
        """Build the manipulation for one entry of a definition's ``effects`` list."""
        where = f"effect #{index} of '{source.def_id}'"
        operations = [key for key in effect if key not in EFFECT_KEYS]
        known = Operation.effect_names()
        unknown = [key for key in operations if key not in known]
        if unknown:
            raise DefinitionError(
                f"{where}: unknown key '{unknown[0]}'{did_you_mean(unknown[0], [*known, *EFFECT_KEYS])}"
            )
        if len(operations) != 1:
            raise DefinitionError(f"{where}: needs exactly one operation ({', '.join(known)})")
        if "target" not in effect:
            raise DefinitionError(f"{where}: needs a 'target'")

        store = source.store
        bool_type, text_type = Datatype.get("bool"), Datatype.get("text")
        try:
            return cls(
                operation=Operation.get(operations[0]),
                value=store.value(effect[operations[0]]),
                target=store.target(effect["target"]),
                source=source,
                priority=effect.get("priority", "normal"),
                when=store.value(effect["when"], bool_type) if "when" in effect else None,
                label=store.value(effect["label"], text_type) if "label" in effect else None,
                index=index,
            )
        except DefinitionError as error:
            raise DefinitionError(f"{where}: {error}") from None

    # ------------------------------------------------------------------ order

    @property
    def order(self) -> tuple:
        """
        Sort key on a property: priority → operation rank → source id → source
        path → effect index. The result never depends on the order in which
        things were added (concept §4.8).
        """
        source_id = self.source.def_id if self.source is not None else ""
        source_path = str(self.source.path) if self.source is not None else ""
        return self.priority, self.operation.rank, source_id, source_path, self.index

    @property
    def description(self) -> str:
        """The effect's label (a template is evaluated) or a generated one, prefixed with the source's name."""
        if self.label is not None:
            text = str(self.label.evaluate(EvalContext(this=self.source)))
        else:
            text = f"{self.operation.name()} {self.value.describe()}"
        return f"{self.source.name}: {text}" if self.source is not None else text

    # ------------------------------------------------------------------ apply

    def check_target(self, prop: Property) -> None:
        """Raise :class:`PropertyError` unless this effect can change ``prop`` (its operation fits the types)."""
        self._resolve_for(prop)

    def why_not(self, prop: Property) -> str | None:
        """Why this effect cannot change ``prop`` (its operation does not fit the types), or ``None``."""
        try:
            self._resolve_for(prop)
        except PropertyError as error:
            return str(error)
        return None

    def _resolve_for(self, prop: Property) -> tuple[Overload, Callable[[Any], Any]]:
        """
        The overload of the operation for ``(prop type, value type)`` and the
        assignment of its result to the prop — resolved once per prop type.
        """
        found = self._resolved.get(prop.datatype)
        if found is None:
            try:
                overload = self.operation.resolve((prop.datatype, self.value.type))
            except UnsupportedOperationError as error:
                raise PropertyError(f"effect {self!r} cannot change '{prop.path_str}': {error}") from None
            assign = prop.datatype.converter(overload.returns, narrowing=True)
            if assign is None:
                raise PropertyError(
                    f"effect {self!r} yields {overload.returns.name()}, "
                    f"'{prop.path_str}' is {prop.datatype.name()}"
                )
            found = self._resolved[prop.datatype] = (overload, assign)
        return found

    def is_applicable(self) -> bool:
        """The source is ``active`` and ``when`` holds. Reads are tracked like any other read."""
        if self.source is not None and not self.source.is_active():
            return False
        return self.when is None or bool(self.when.evaluate(EvalContext(this=self.source)))

    def apply(self, previous: Any, prop: Property) -> Any:
        """The value of ``prop`` after this manipulation; ``previous`` unchanged while inert."""
        if not self.is_applicable():
            return previous
        overload, assign = self._resolve_for(prop)
        value = self.value.evaluate(EvalContext(this=self.source, previous=previous))
        result = assign(overload(previous, value))
        try:
            return prop.datatype.validate(result)
        except ValueError as error:
            raise PropertyError(
                f"effect '{self.description}' on '{prop.path_str}' produced an invalid value: {error}"
            ) from error

    def __repr__(self) -> str:
        target = self.target.describe() if self.target is not None else "-"
        return f"<Manipulation {self.operation.name()} {self.value.describe()} → {target}>"
