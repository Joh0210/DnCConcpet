"""
One effect, applied to one or more properties (concept §4.8).

Replaces ``IManipulation`` / ``manipulation()`` and the manipulation half of
``LocalModifier`` / ``PlayerModifier``: instead of a closure the effect is data —
an operation, a value (a VALUE node), a target path, a priority, an optional
``when`` and ``label``. Which properties it currently hits is decided by the
root's binding (``Instance._rebind``), not by the manipulation itself.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from InnerFunction import EvalContext, InnerFunction
from datatype.Datatype import Datatype
from datatype.Operation import Operation, Overload
from errors import DefinitionError, PropertyError, UnsupportedOperationError, did_you_mean
from value import build_value

if TYPE_CHECKING:
    from Instance import Instance
    from property.Property import Property
    from value.PathValue import PathValue

#: Named priority stages, internally numbers with gaps so stages can be inserted later.
#: ``base`` adjusts the starting value, ``final`` holds caps / overrides after everything else.
PRIORITIES: dict[str, int] = {"base": 100, "normal": 500, "final": 900}

#: Keys of an effect entry besides the operation key.
EFFECT_KEYS = {"target", "priority", "when", "label"}


def priority_value(priority: str | int) -> int:
    if isinstance(priority, int) and not isinstance(priority, bool):
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
        self.priority = priority_value(priority)
        self.when: InnerFunction | None = None if when is None else build_value(when, Datatype.get("bool"))
        self.label: InnerFunction | None = None if label is None else build_value(label, Datatype.get("text"))
        self.index = index
        # prop type → (overload, assignment), resolved when bound to a prop of that type
        self._appliers: dict[Datatype, tuple[Overload, Callable[[Any], Any]]] = {}

    @classmethod
    def from_effect(cls, effect: dict, source: Instance, index: int) -> Manipulation:
        """Build the manipulation for one entry of a definition's ``effects`` list."""
        where = f"effect #{index} of '{source.id}'"
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
        source_id = self.source.id if self.source is not None else ""
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
        self._applier(prop)

    def _applier(self, prop: Property) -> tuple[Overload, Callable[[Any], Any]]:
        found = self._appliers.get(prop.datatype)
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
            found = self._appliers[prop.datatype] = (overload, assign)
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
        overload, assign = self._applier(prop)
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
