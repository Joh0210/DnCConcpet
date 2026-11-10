from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DbData:
    """
    The serialized form of one component: its `name` (= register id), its stored
    property values, and its sub-containers' contents keyed by container id.
    Produced by `DataUtil.save_data`, consumed by `DataUtil.load_from_data`.
    """

    name: str
    storable_data: dict[str, str] = field(default_factory=dict)
    # TS: Record<string, Map<string, DbData>>
    component_data: dict[str, dict[str, DbData]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converts to a JSON-compatible dict using the original TS key names."""
        return {
            "storableData": dict(self.storable_data),
            "componentData": {
                container_id: {key: child.to_dict() for key, child in children.items()}
                for container_id, children in self.component_data.items()
            },
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DbData:
        """Builds a DbData from a dict using the original TS key names."""
        return cls(
            name=data["name"],
            storable_data=dict(data.get("storableData", {})),
            component_data={
                container_id: {key: cls.from_dict(child) for key, child in children.items()}
                for container_id, children in data.get("componentData", {}).items()
            },
        )


@dataclass
class ComponentPath:
    """A component's position in the entity tree, as a linked list toward the root."""

    name: str
    upper_path: Optional[ContainerPath] = None


@dataclass
class ContainerPath:
    """One hop of a ComponentPath: which container of which parent component."""

    upper_path: ComponentPath
    container_id: Optional[str] = None
    component_key: Optional[str] = None