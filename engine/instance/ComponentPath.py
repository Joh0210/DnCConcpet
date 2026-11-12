"""Where an instance sits in its tree — for messages, traces and the order of effects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ComponentPath:
    """A component's position in the entity tree, as a linked list toward the root."""

    name: str
    parent: Optional[ContainerPath] = None

    def __str__(self) -> str:
        """``character/equipment:mainHand/battleaxe`` — for logs, traces and tie-breaks."""
        if self.parent is None:
            return self.name
        return f"{self.parent}/{self.name}"


@dataclass
class ContainerPath:
    """One hop of a ComponentPath: which container of which parent component."""

    parent: ComponentPath
    container_id: str
    key: str

    def __str__(self) -> str:
        """``character/equipment:mainHand``"""
        return f"{self.parent}/{self.container_id}:{self.key}"
