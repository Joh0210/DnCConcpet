from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

#: Saved content of one container, shaped like the container (concept §4.13):
#: single → one DbData, list → a list, map → key → DbData.
ChildrenData = Union["DbData", list["DbData"], dict[str, "DbData"]]


@dataclass
class DbData:
    """
    The saved form of one instance (concept §4.13). A save stores only what the
    definitions cannot know; everything else is rebuilt from them:

    - ``def_id``: the definition id (JSON key ``def``),
    - ``choices``: serialized values of ``choice`` props the user picked
      (being present here *is* the "reviewed" flag — no extra wire format),
    - ``state``: serialized values of ``state`` props that changed in play,
    - ``children``: container id → saved children, shaped like the container.

    Values are strings produced by ``Datatype.serialize``; reading accepts native
    JSON values too (``Datatype.parse``).
    """

    def_id: str
    choices: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    children: dict[str, ChildrenData] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """Nothing beyond the definition id — the instance is exactly its definition."""
        return not self.choices and not self.state and not self.children

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible dict with the keys of concept §4.13; empty sections are left out."""
        result: dict[str, Any] = {"def": self.def_id}
        if self.choices:
            result["choices"] = dict(self.choices)
        if self.state:
            result["state"] = dict(self.state)
        if self.children:
            result["children"] = {
                container_id: _children_to_dict(children)
                for container_id, children in self.children.items()
            }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DbData:
        return cls(
            def_id=data["def"],
            choices=dict(data.get("choices", {})),
            state=dict(data.get("state", {})),
            children={
                container_id: _children_from_dict(children)
                for container_id, children in data.get("children", {}).items()
            },
        )

    @classmethod
    def coerce(cls, data: DbData | dict[str, Any]) -> DbData:
        """Accept a DbData or its dict form."""
        return data if isinstance(data, DbData) else cls.from_dict(data)


def _children_to_dict(children: ChildrenData) -> Any:
    if isinstance(children, DbData):
        return children.to_dict()
    if isinstance(children, list):
        return [child.to_dict() for child in children]
    return {key: child.to_dict() for key, child in children.items()}


def _children_from_dict(children: Any) -> ChildrenData:
    if isinstance(children, DbData):
        return children
    if isinstance(children, list):
        return [DbData.coerce(child) for child in children]
    if "def" in children:  # a single child
        return DbData.from_dict(children)
    return {key: DbData.coerce(child) for key, child in children.items()}


@dataclass
class ComponentPath:
    """A component's position in the entity tree, as a linked list toward the root."""

    name: str
    upper_path: Optional[ContainerPath] = None

    def __str__(self) -> str:
        """``character/equipment:mainHand/battleaxe`` — for logs, traces and tie-breaks."""
        if self.upper_path is None:
            return self.name
        return f"{self.upper_path}/{self.name}"


@dataclass
class ContainerPath:
    """One hop of a ComponentPath: which container of which parent component."""

    upper_path: ComponentPath
    container_id: Optional[str] = None
    component_key: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.upper_path}/{self.container_id}:{self.component_key}"
