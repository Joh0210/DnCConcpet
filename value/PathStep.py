"""
The steps of a path (see :class:`value.PathValue.PathValue`)::

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

from typing import Any, Callable

from container.Container import Container
from datatype.Datatype import Datatype
from errors import DefinitionError, ExpressionError, did_you_mean
from value.InnerFunction import EvalContext, InnerFunction

#: A step found nothing: no such member, no such key, an empty single container, no owner.
ABSENT = object()

#: Where a navigation step can go (concept §4.6: ``owner``, ``entity``).
NAVIGATION = ("owner", "entity")


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
        props = getattr(node, "props", None)  # duck typing: anything with props is an instance
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
            child = None if key is None else node.get(key if isinstance(key, str) else str(key))  # list keys are "0", "1", ...
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


def build_step(raw: Any, build: Callable[..., InnerFunction]) -> Step:
    """The step for one JSON step (see the module docstring); ``build`` builds the VALUEs inside it."""
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
