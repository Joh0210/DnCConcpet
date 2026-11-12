"""
One effect, applied to one or more properties (concept §4.8).

Replaces ``IManipulation`` / ``manipulation()`` and the manipulation half of
``LocalModifier`` / ``PlayerModifier``: instead of a closure the effect is data —
an operation, a value (literal or expression), a ``TargetPath``, a priority, an
optional ``when`` and ``label``. Which properties it currently hits is decided by
the root's binding (``Instance._rebind``), not by the manipulation itself.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from InnerFunction import EvalContext, InnerFunction, TargetPath, describe_value, evaluate_value
from datatype.Operation import Operation
from errors import DefinitionError, PropertyError, did_you_mean

if TYPE_CHECKING:
    from Instance import Instance
    from property.Property import Property

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
    def __init__(
        self,
        operation: Operation,
        value: Any,
        target: TargetPath | None = None,
        source: Instance | None = None,
        priority: str | int = "normal",
        when: Any = None,
        label: Any = None,
        index: int = 0,
    ):
        """
        :param operation: how ``value`` is combined with the value so far.
        :param value: literal or :class:`InnerFunction`, evaluated with ``this = source``.
        :param target: where the effect goes; ``None`` for a kernel-internal (static) manipulation.
        :param source: the instance the effect belongs to; its ``active`` guard gates the effect.
        :param index: position among the source's effects — the last tie-break.
        """
        self.operation = operation
        self.value = value
        self.target = target
        self.source = source
        self.priority = priority_value(priority)
        self.when = when
        self.label = label
        self.index = index

    @classmethod
    def from_effect(cls, effect: dict, source: Instance, index: int) -> Manipulation:
        """Build the manipulation for one entry of a definition's ``effects`` list."""
        where = f"effect #{index} of '{source.id}'"
        operations = [key for key in effect if key not in EFFECT_KEYS]
        known = Operation.names()
        unknown = [key for key in operations if key not in known]
        if unknown:
            raise DefinitionError(
                f"{where}: unknown key '{unknown[0]}'{did_you_mean(unknown[0], [*known, *EFFECT_KEYS])}"
            )
        if len(operations) != 1:
            raise DefinitionError(f"{where}: needs exactly one operation ({', '.join(known)})")
        target = effect.get("target")
        if not isinstance(target, TargetPath):
            raise DefinitionError(f"{where}: 'target' must be a TargetPath")

        operation = Operation.get(operations[0])
        return cls(
            operation=operation,
            value=effect[operations[0]],
            target=target,
            source=source,
            priority=effect.get("priority", "normal"),
            when=effect.get("when"),
            label=effect.get("label"),
            index=index,
        )

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
            text = str(evaluate_value(self.label, EvalContext(this=self.source)))
        else:
            text = f"{self.operation.name()} {describe_value(self.value)}"
        return f"{self.source.name}: {text}" if self.source is not None else text

    # ------------------------------------------------------------------ apply

    def is_applicable(self) -> bool:
        """The source is ``active`` and ``when`` holds. Reads are tracked like any other read."""
        if self.source is not None and not self.source.is_active():
            return False
        return self.when is None or bool(evaluate_value(self.when, EvalContext(this=self.source)))

    def apply(self, previous: Any, prop: Property) -> Any:
        """The value of ``prop`` after this manipulation; ``previous`` unchanged while inert."""
        if not self.is_applicable():
            return previous
        value = evaluate_value(self.value, EvalContext(this=self.source, previous=previous))
        result = prop.datatype.use_operation(self.operation, previous, value)
        try:
            return prop.datatype.validate(result)
        except ValueError as error:
            raise PropertyError(
                f"effect '{self.description}' on '{prop.path_str}' produced an invalid value: {error}"
            ) from error

    def __repr__(self) -> str:
        target = self.target.describe() if self.target is not None else "-"
        return f"<Manipulation {self.operation.name()} {describe_value(self.value)} → {target}>"
