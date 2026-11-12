"""
Paths (concept §4.6) as a node of the expression AST.

JSON form — a flat list of steps instead of a chain of ``next`` links::

    {"path": [STEP, ...], "type": "<type>", "from": "this" | "it" | "previous" | <name>}

The steps are listed in :mod:`engine.value.PathStep`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from engine.container.Container import Container
from engine.datatype.Datatype import Datatype
from engine.errors import DefinitionError, ExpressionError
from engine.property.Property import Property
from engine.value.InnerFunction import EvalContext, InnerFunction, TargetPath
from engine.value.PathStep import ABSENT, Step, build_step

if TYPE_CHECKING:
    from engine.instance.Instance import Instance


class PathValue(InnerFunction, TargetPath):
    """
    A path, usable both ways:

    - as a **value** (:meth:`evaluate`): walks from ``ctx.this`` (or ``from``) and
      reads what it ends at — a prop's value, an instance (``ref<X>``), or a list
      of them when a step fans out. Needs a declared ``type``.
    - as a **target** (:meth:`resolve`): the props an effect binds to.

    The declared ``type`` is the type of the whole path: ``list<T>`` exactly when
    a step fans out. It must be declared because a path may yield nothing — an
    absent ``?.`` segment or an empty list carries no type at runtime, yet
    ``sum(inventory[*].weight)`` has to know it is a ``number``.

    **Absent segments** (concept §4.6): a step finds nothing — no owner, an empty
    single container, a missing key or member. Where the step is marked
    ``"opt": true`` (written ``?.``) the path yields null, and a fanned-out path
    just leaves that branch out. Elsewhere it is an :class:`ExpressionError` in a
    value — the validator should have demanded a ``?.`` — and makes a target inert.
    """

    KEYS = {"path", "type", "from"}

    def __init__(self, steps: list[Step], datatype: Datatype | None = None, start: str = "this"):
        self.steps = steps
        self.start = start
        self.fans_out = any(step.fans_out for step in steps)
        self.type = datatype
        self._element_type: Datatype | None = None
        if datatype is not None:
            is_list = datatype.kind() == "list"
            if is_list != self.fans_out:
                expected = "a list<…> type" if self.fans_out else "a single type, not a list"
                raise DefinitionError(f"path '{self.describe()}' needs {expected}, got '{datatype.name()}'")
            self._element_type = datatype.element if is_list else datatype

    @classmethod
    def from_json(cls, raw: dict, build: Callable[..., InnerFunction]) -> PathValue:
        steps = raw["path"]
        if not isinstance(steps, list):
            raise DefinitionError(f"'path' must be a list of steps, got {steps!r}")
        datatype = Datatype.get(raw["type"]) if raw.get("type") is not None else None
        return cls([build_step(step, build) for step in steps], datatype, raw.get("from", "this"))

    # ------------------------------------------------------------------ walking

    def _walk(self, ctx: EvalContext, as_target: bool) -> list | None:
        """
        The nodes the path ends at, or ``None`` when an optional segment was
        absent in a single (not fanned-out) path. Props in the middle of a path
        are read and the walk continues on their value (a ``ref`` prop).
        """
        nodes = [ctx.var(self.start)]
        last = len(self.steps) - 1
        for index, step in enumerate(self.steps):
            more = index < last  # more steps follow, so the walk needs something to continue on
            found = []
            for node in nodes:
                if node is None:  # only the start can be null here; later nulls are handled below
                    if as_target:
                        continue
                    raise ExpressionError(f"'{self.describe()}' starts at '{self.start}', which is null here")
                for result in step.apply(node, ctx):
                    if more and isinstance(result, Property):
                        result = result.resolve()
                    # Nothing here — a null in the middle (no owner, an empty single container) counts as absent.
                    if result is ABSENT or (result is None and more):
                        if as_target:
                            continue  # inert
                        if step.optional:
                            if self.fans_out:
                                continue  # a list just leaves this branch out
                            return None  # a single value becomes null
                        raise ExpressionError(
                            f"'{self.describe()}': '{step.text().lstrip('.')}' is absent here — "
                            f"mark it as optional (?.) and handle the null"
                        )
                    found.append(result)
            nodes = found
        return nodes

    def evaluate(self, ctx: EvalContext) -> Any:
        if self.type is None:
            raise DefinitionError(f"path '{self.describe()}' has no type, so it cannot be used as a value")
        nodes = self._walk(ctx, as_target=False)
        if nodes is None:
            return None
        values = [self._read(node) for node in nodes]
        if self.fans_out:
            return values
        return values[0] if values else None

    def _read(self, node: Any) -> Any:
        """The value an end node stands for: a prop's value (checked against the declared type) or the node itself."""
        if isinstance(node, Property):
            if node.datatype is not self._element_type and self._element_type.converter(node.datatype) is None:
                raise ExpressionError(
                    f"'{self.describe()}' is declared as {self._element_type.name()}, "
                    f"but '{node.path_str}' is {node.datatype.name()}"
                )
            return node.resolve()
        if isinstance(node, Container):
            raise ExpressionError(
                f"'{self.describe()}' ends at the {node.shape.name} container '{node.path_str}' — add [*] or a key"
            )
        return node

    def resolve(self, source: Instance) -> list[Property]:
        nodes = self._walk(EvalContext(this=source), as_target=True) or []  # None: an absent optional segment
        for node in nodes:
            if not isinstance(node, Property):
                raise DefinitionError(f"target '{self.describe()}' must end at a prop, it ends at {node!r}")
        return nodes

    # ------------------------------------------------------------------ text

    def describe(self) -> str:
        """The path in the language of concept §4.6: ``entity?.attributes[stat].value``."""
        text = "" if self.start == "this" else self.start
        for step in self.steps:
            part = step.text()
            text = text + part if text else part.lstrip(".")
            if step.optional:
                text += "?"
        # An optional segment before a key is written `?.[`; a path without steps is just its start.
        return text.replace("?[", "?.[") or "this"

    def __repr__(self) -> str:
        shown = self.type.name() if self.type is not None else "target"
        return f"<PathValue {self.describe()}: {shown}>"
