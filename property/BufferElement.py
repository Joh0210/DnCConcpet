from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


class BufferElement:
    """
    One node in the property dependency graph. Each property (and each container)
    owns one. It records the edges discovered while a value resolves —
    ``_upper_properties`` depend on this node's value, ``_lower_properties`` are
    the ones this node read — and propagates cache invalidation along them.

    The graph is never built centrally: :meth:`read_operation` pushes this node
    onto the shared per-tree call stack while a value computes, so whatever the
    computation reads records the reverse edge. See the Architecture guide,
    "the dependency graph".
    """

    def __init__(
        self,
        stack_getter: Callable[[], list[BufferElement]],
        on_update: Callable[[], None],
    ) -> None:
        """
        :param stack_getter: returns the shared per-tree call stack (all nodes of
            one component tree share one, keyed off the root).
        :param on_update: runs when this node becomes stale — a property clears
            its cached value here.
        """
        # Nodes whose value depends on this one — notified when this changes.
        self._upper_properties: set[BufferElement] = set()
        # Nodes this one read while computing — cleared when this recomputes.
        self._lower_properties: set[BufferElement] = set()

        self._up_to_date: bool = False
        self._stack_getter = stack_getter
        self._on_update = on_update

    @property
    def should_update(self) -> bool:
        """``True`` when the cached value behind this node needs recomputing."""
        return not self._up_to_date

    def notify_register(self, lower_prop: BufferElement) -> None:
        """Record that this node read ``lower_prop`` while computing."""
        self._lower_properties.add(lower_prop)

    def read_operation(self, calc: Callable[[], T]) -> T:
        """
        Run ``calc`` while this node is on the shared call stack, so any node
        ``calc`` reads links itself as a dependency. Re-entrant calls (a cycle)
        skip the push and just return ``calc()``.
        """
        stack = self._stack_getter()

        was_not_self = True
        if stack:
            element = stack[-1]
            was_not_self = element is not self

            if element not in self._upper_properties:
                self._upper_properties.add(element)
                element.notify_register(self)

        if was_not_self:
            stack.append(self)
            try:
                ret = calc()
                self._up_to_date = True
                return ret
            finally:
                # Pop even if calc() raised — a stale stack entry would corrupt
                # dependency tracking for the whole component tree.
                stack.pop()
        else:
            temp = calc()
            self._up_to_date = True
            return temp

    def update(self) -> None:
        """Mark this node stale and cascade the invalidation to every dependent. No-op if already stale."""
        if self._up_to_date:
            self._up_to_date = False
            self._on_update()

            # Iterate over a copy: unlike JS, Python raises if a set changes
            # size during iteration, and dependents may detach mid-cascade.
            for prop in list(self._upper_properties):
                prop.update()

    def remove(self) -> None:
        """Detach this node from the graph in both directions and invalidate dependents."""
        for prop in list(self._upper_properties):
            prop.notify_removed(True, self)
        self._upper_properties = set()

        for prop in list(self._lower_properties):
            prop.notify_removed(False, self)
        self._lower_properties = set()
        self.update()

    def update_and_reset_lower_list(self) -> None:
        """Drop this node's recorded dependencies and mark it stale, keeping its dependents."""
        for prop in list(self._lower_properties):
            prop.notify_removed(False, self)
        self._lower_properties = set()
        self.update()

    def notify_removed(self, from_lower: bool, prop: BufferElement) -> None:
        """
        A neighbour is detaching. ``from_lower`` — a dependency of this node went
        away, so this node is now stale; otherwise a dependent left and there is
        nothing to recompute.
        """
        if from_lower:
            self._lower_properties.discard(prop)
            self.update()
        else:
            self._upper_properties.discard(prop)