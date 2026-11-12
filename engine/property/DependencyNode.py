from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


class DependencyNode:
    """
    One node of the dependency graph between values — the observer half of a
    :class:`engine.property.Property.Property`. Every property owns one; so does every
    container (its children) and every instance (its ``contained``), because
    values read those too.

    The graph is never built centrally. :meth:`track_read` puts this node on the
    tree's resolve stack while its value computes; every node read meanwhile
    sees the reader on top of the stack and links the two. Invalidation then
    flows the other way, from a changed node to everything that read it.
    """

    def __init__(
        self,
        get_resolve_stack: Callable[[], list[DependencyNode]],
        on_invalidate: Callable[[], None],
        owner: object = None,
    ) -> None:
        """
        :param get_resolve_stack: returns the resolve stack shared by every node
            of one instance tree (kept by its root).
        :param on_invalidate: runs when this node becomes stale — a property
            clears its cached value here.
        :param owner: what the node belongs to (a property, container or
            instance) — lets the binder see *what* a target path read.
        """
        self.owner = owner
        #: Nodes that read this one — invalidated when this one changes.
        self._dependents: set[DependencyNode] = set()
        #: Nodes this one read while computing — forgotten when its inputs are reset.
        self._dependencies: set[DependencyNode] = set()

        self._up_to_date: bool = False
        self._get_resolve_stack = get_resolve_stack
        self._on_invalidate = on_invalidate

    @property
    def is_stale(self) -> bool:
        """``True`` when the value behind this node needs recomputing."""
        return not self._up_to_date

    def track_read(self, compute: Callable[[], T]) -> T:
        """
        Read this node: link it to whoever is computing right now (the top of the
        resolve stack), then run ``compute`` with this node on the stack, so that
        everything ``compute`` reads links itself to this node. A re-entrant read
        (a cycle back to this node) just runs ``compute``.
        """
        stack = self._get_resolve_stack()
        reentrant = bool(stack) and stack[-1] is self

        if stack:
            reader = stack[-1]
            if reader not in self._dependents:
                self._dependents.add(reader)
                reader._add_dependency(self)

        if reentrant:
            result = compute()
        else:
            if not self._up_to_date:
                # About to compute afresh: forget what the last computation read. Otherwise a
                # branch no longer taken (`flag ? a : b`) or a removed child would stay an
                # input forever — needless recomputes, and removed instances never freed.
                self._forget_dependencies()
            stack.append(self)
            try:
                result = compute()
            finally:
                # Pop even if compute() raised — a stale stack entry would corrupt
                # dependency tracking for the whole tree.
                stack.pop()
        self._up_to_date = True
        return result

    def invalidate(self) -> None:
        """Mark this node stale and cascade to every dependent. No-op if already stale."""
        if self._up_to_date:
            self._up_to_date = False
            self._on_invalidate()
            # Iterate over a copy: Python raises if a set changes size during iteration.
            for dependent in list(self._dependents):
                dependent.invalidate()

    def reset_dependencies(self) -> None:
        """
        Forget everything this node read and invalidate it — for when its value
        no longer comes from those inputs (a value was chosen, an effect was
        unbound). Its dependents are kept.
        """
        self._forget_dependencies()
        self.invalidate()

    def dependencies_closure(self) -> list[DependencyNode]:
        """Every node this one read, directly or through the nodes it read (as of their last computation)."""
        seen: set[DependencyNode] = set()
        pending = list(self._dependencies)
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(node._dependencies)
        return list(seen)

    def _forget_dependencies(self) -> None:
        """Unlink this node from everything it read (both directions)."""
        for dependency in self._dependencies:
            dependency._remove_dependent(self)
        self._dependencies = set()

    def _add_dependency(self, node: DependencyNode) -> None:
        """Record that this node read ``node`` while computing."""
        self._dependencies.add(node)

    def _remove_dependent(self, node: DependencyNode) -> None:
        """``node`` no longer reads this one; nothing to recompute."""
        self._dependents.discard(node)
