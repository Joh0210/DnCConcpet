"""
Paths (concept §4.6) as a node of the expression AST.

JSON form — a flat list of steps instead of a chain of ``next`` links::

    {"path": [STEP, ...], "type": "<type>", "from": "this" | "it" | "previous" | <name>}

    STEP = "<name>"                          prop or container of the current instance
         | "*"                               every child of a container            [*]
         | {"get": "<name>", "opt": true}    a segment that may be absent          material?.power
         | {"to": "owner" | "entity"}        navigation (may carry "opt": true)    entity?.level
         | {"key": [VALUE, ...]}             map / list keys — several keys fan out [stat], [.str, .dex]
         | {"is": "<definition id>"}         type filter                           [is weapon]
         | {"where": VALUE}                  predicate on the candidate `it`       [where it.weight > 5]

Every step maps each current node to zero or more nodes; the rest of the path
applies to every one of them. That is all the branching the path language has —
``[.str, .dex].advantage`` continues with the same ``.advantage`` in both
branches — so a list is enough and no step has to repeat its continuation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from InnerFunction import EvalContext, InnerFunction, TargetPath
from container.Container import Container
from datatype.Datatype import Datatype
from errors import DefinitionError, ExpressionError, did_you_mean
from property.Property import Property

if TYPE_CHECKING:
    from Instance import Instance

#: A step found nothing: no such member, no such key, an empty single container, no owner.
ABSENT = object()

#: Where a navigation step can go (concept §4.6: ``owner``, ``entity``).
NAVIGATION = ("owner", "entity")


# ---------------------------------------------------------------------- steps


class Step:
    """One step of a path. :meth:`apply` maps one node to the nodes it leads to (``ABSENT`` = nothing)."""

    #: May lead to several nodes — the path then yields a list.
    fans_out = False

    def __init__(self, optional: bool = False):
        #: This segment may be absent (``?.``): the path then yields null instead of failing.
        self.optional = optional

    def apply(self, node: Any, ctx: EvalContext) -> list:
        raise NotImplementedError

    def text(self) -> str:
        """The step written in the path language, with its leading ``.`` if it has one."""
        raise NotImplementedError


class MemberStep(Step):
    """``.name`` — a prop or a container of the current instance. A single container is transparent."""

    def __init__(self, name: str, optional: bool = False):
        super().__init__(optional)
        self.name = name

    def apply(self, node, ctx):
        if isinstance(node, Container):
            raise ExpressionError(
                f"'{node.path_str}' is a {node.shape.name} container — use [*], a key or a filter before '.{self.name}'"
            )
        props = getattr(node, "props", None)
        if props is None:
            raise ExpressionError(f"cannot read '{self.name}' of the value {node!r}")
        prop = props.get(self.name)
        if prop is not None:
            return [prop]
        container = node.containers.get(self.name)
        if container is None:
            return [ABSENT]
        if container.shape.name == "single":
            return [container.get()]  # tracked; None while empty
        return [container]

    def text(self):
        return f".{self.name}"


class NavigateStep(Step):
    """``owner`` / ``entity`` — the instance holding this one, or the entity it lies in."""

    def __init__(self, to: str, optional: bool = False):
        if to not in NAVIGATION:
            raise DefinitionError(f"unknown path navigation '{to}'{did_you_mean(to, NAVIGATION)}")
        super().__init__(optional)
        self.to = to

    def apply(self, node, ctx):
        return [getattr(node, self.to)]  # tracked through `contained`

    def text(self):
        return f".{self.to}"


class KeyStep(Step):
    """``[key]`` / ``[.str, .dex]`` — children of a map or list container by key; keys are values."""

    def __init__(self, keys: list[InnerFunction], optional: bool = False):
        if not keys:
            raise DefinitionError("a key step needs at least one key")
        super().__init__(optional)
        self.keys = keys
        self.fans_out = len(keys) > 1

    def apply(self, node, ctx):
        if not isinstance(node, Container):
            raise ExpressionError(f"a key needs a list or map container, got {node!r}")
        found = []
        for key_node in self.keys:
            key = key_node.evaluate(ctx)
            child = None if key is None else node.get(key if isinstance(key, str) else str(key))
            found.append(ABSENT if child is None else child)
        return found

    def text(self):
        return f"[{', '.join(key.describe() for key in self.keys)}]"


class AllStep(Step):
    """``[*]`` — every child of a container."""

    fans_out = True

    def apply(self, node, ctx):
        if not isinstance(node, Container):
            raise ExpressionError(f"[*] needs a list or map container, got {node!r}")
        return node.all()

    def text(self):
        return "[*]"


class _FilterStep(Step):
    """Keeps the children (of a container) or the instances (after a fan-out) that match."""

    fans_out = True

    def apply(self, node, ctx):
        candidates = node.all() if isinstance(node, Container) else [node]
        return [candidate for candidate in candidates if self.matches(candidate, ctx)]

    def matches(self, candidate, ctx) -> bool:
        raise NotImplementedError


class IsStep(_FilterStep):
    """``[is weapon]`` — every entry extending a definition (a concrete id works too)."""

    def __init__(self, def_id: str):
        super().__init__()
        self.def_id = def_id

    def matches(self, candidate, ctx):
        return candidate.is_a(self.def_id)

    def text(self):
        return f"[is {self.def_id}]"


class WhereStep(_FilterStep):
    """``[where it.weight > 5]`` — a predicate on the candidate ``it``."""

    def __init__(self, predicate: InnerFunction):
        super().__init__()
        self.predicate = predicate

    def matches(self, candidate, ctx):
        return bool(self.predicate.evaluate(ctx.with_it(candidate)))

    def text(self):
        return f"[where {self.predicate.describe()}]"


# ---------------------------------------------------------------------- path


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

    def __init__(self, steps: list[Step], datatype: Datatype | None = None, root: str = "this"):
        self.steps = steps
        self.root = root
        self.fans_out = any(step.fans_out for step in steps)
        self.type = datatype
        self._element: Datatype | None = None
        if datatype is not None:
            is_list = datatype.kind() == "list"
            if is_list != self.fans_out:
                expected = "a list<…> type" if self.fans_out else "a single type, not a list"
                raise DefinitionError(f"path '{self.describe()}' needs {expected}, got '{datatype.name()}'")
            self._element = datatype.element if is_list else datatype

    @classmethod
    def from_json(cls, raw: dict, build: Callable[..., InnerFunction]) -> PathValue:
        steps = raw["path"]
        if not isinstance(steps, list):
            raise DefinitionError(f"'path' must be a list of steps, got {steps!r}")
        datatype = Datatype.get(raw["type"]) if raw.get("type") is not None else None
        return cls([_step(step, build) for step in steps], datatype, raw.get("from", "this"))

    # ------------------------------------------------------------------ walking

    def _walk(self, ctx: EvalContext, target: bool) -> list | None:
        """
        The nodes the path ends at, or ``None`` when an optional segment was
        absent in a single (not fanned-out) path. Props in the middle of a path
        are read and the walk continues on their value (a ``ref`` prop).
        """
        nodes = [ctx.var(self.root)]
        last = len(self.steps) - 1
        for index, step in enumerate(self.steps):
            more = index < last
            found = []
            for node in nodes:
                if node is None:  # only the start can be null here; later nulls are handled below
                    if target:
                        continue
                    raise ExpressionError(f"'{self.describe()}' starts at '{self.root}', which is null here")
                for result in step.apply(node, ctx):
                    if more and isinstance(result, Property):
                        result = result.resolve()
                    if result is ABSENT or (result is None and more):
                        if target:
                            continue  # inert
                        if step.optional:
                            if self.fans_out:
                                continue
                            return None
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
        nodes = self._walk(ctx, target=False)
        if nodes is None:
            return None
        values = [self._read(node) for node in nodes]
        if self.fans_out:
            return values
        return values[0] if values else None

    def _read(self, node: Any) -> Any:
        if isinstance(node, Property):
            if node.datatype is not self._element and self._element.converter(node.datatype) is None:
                raise ExpressionError(
                    f"'{self.describe()}' is declared as {self._element.name()}, "
                    f"but '{node.path_str}' is {node.datatype.name()}"
                )
            return node.resolve()
        if isinstance(node, Container):
            raise ExpressionError(
                f"'{self.describe()}' ends at the {node.shape.name} container '{node.path_str}' — add [*] or a key"
            )
        return node

    def resolve(self, source: Instance) -> list[Property]:
        nodes = self._walk(EvalContext(this=source), target=True) or []
        for node in nodes:
            if not isinstance(node, Property):
                raise DefinitionError(f"target '{self.describe()}' must end at a prop, it ends at {node!r}")
        return nodes

    # ------------------------------------------------------------------ text

    def describe(self) -> str:
        """The path in the language of concept §4.6: ``entity?.attributes[stat].value``."""
        text = "" if self.root == "this" else self.root
        for step in self.steps:
            part = step.text()
            text = text + part if text else part.lstrip(".")
            if step.optional:
                text += "?"
        return text.replace("?[", "?.[") or "this"

    def __repr__(self) -> str:
        shown = self.type.name() if self.type is not None else "target"
        return f"<PathValue {self.describe()}: {shown}>"


def _step(raw: Any, build: Callable[..., InnerFunction]) -> Step:
    if isinstance(raw, str):
        return AllStep() if raw == "*" else MemberStep(raw)
    if not isinstance(raw, dict):
        raise DefinitionError(f"a path step is a name, '*' or an object, got {raw!r}")
    optional = bool(raw.get("opt", False))
    kinds = set(raw) - {"opt"}
    if len(kinds) != 1:
        raise DefinitionError(f"a path step needs exactly one of get / to / key / is / where, got {sorted(raw)}")
    kind = kinds.pop()
    if kind == "get":
        return MemberStep(raw["get"], optional)
    if kind == "to":
        return NavigateStep(raw["to"], optional)
    if kind == "key":
        keys = raw["key"] if isinstance(raw["key"], list) else [raw["key"]]
        return KeyStep([build(key) for key in keys], optional)
    if kind == "is":
        return IsStep(raw["is"])
    if kind == "where":
        return WhereStep(build(raw["where"], Datatype.get("bool")))
    raise DefinitionError(f"unknown path step '{kind}'{did_you_mean(kind, ['get', 'to', 'key', 'is', 'where'])}")
