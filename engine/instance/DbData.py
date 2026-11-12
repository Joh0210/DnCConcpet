"""The save format of instances (concept §4.13)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

#: Saved content of one container, shaped like the container (concept §4.13):
#: single → one DbData, list → a list, map → key → DbData.
ChildrenData = Union["DbData", list["DbData"], dict[str, "DbData"]]


@dataclass
class DbData:
    """
    The saved form of one instance (concept §4.13) — everything needed to build it
    again. A save stores only what the definitions cannot know; everything else is
    rebuilt from them:

    - ``def_id``: the definition id (JSON key ``def``),
    - ``props``: prop id → serialized value of every ``choice`` prop the user picked
      and every ``state`` prop that changed in play. Which of the two a prop is
      comes from its definition, so the save does not repeat it; a ``choice``
      being present here *is* the "reviewed" flag — no extra wire format,
    - ``children``: container id → saved children, shaped like the container,
    - ``game``: the game (rule system) the definition belongs to. Required at the
      top of a save (``Instance(save)`` reads it); children always belong to the
      game of their parent, so they carry ``None`` = "inherit". (Addition to
      concept §4.13.)

    Values are strings produced by ``Datatype.serialize``; reading accepts native
    JSON values too (``Datatype.parse``).
    """

    def_id: str
    props: dict[str, Any] = field(default_factory=dict)
    children: dict[str, ChildrenData] = field(default_factory=dict)
    game: str | None = None
    #: The instance's identity in its tree (``Instance.uid``); ``None`` for entries of
    #: fixed containers and for a save that has never been in a tree (it gets one when added).
    uid: str | None = None

    def is_empty(self) -> bool:
        """Nothing beyond the definition id — the instance is exactly its definition."""
        return not self.props and not self.children

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible dict with the keys of concept §4.13; empty sections are left out."""
        result: dict[str, Any] = {} if self.game is None else {"game": self.game}
        result["def"] = self.def_id
        if self.uid is not None:
            result["uid"] = self.uid
        if self.props:
            result["props"] = dict(self.props)
        if self.children:
            result["children"] = {
                container_id: _children_to_dict(children)
                for container_id, children in self.children.items()
            }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DbData:
        """The inverse of :meth:`to_dict`."""
        return cls(
            def_id=data["def"],
            props=dict(data.get("props", {})),
            children={
                container_id: _children_from_dict(children)
                for container_id, children in data.get("children", {}).items()
            },
            game=data.get("game"),
            uid=None if data.get("uid") is None else str(data["uid"]),
        )

    @classmethod
    def coerce(cls, data: DbData | dict[str, Any] | str) -> DbData:
        """Accept a DbData, its dict form, or a bare definition id (= nothing saved yet)."""
        if isinstance(data, DbData):
            return data
        if isinstance(data, str):
            return cls(data)
        return cls.from_dict(data)


def _children_to_dict(children: ChildrenData) -> Any:
    """The JSON form of one container's saved children, keeping its shape."""
    if isinstance(children, DbData):
        return children.to_dict()
    if isinstance(children, list):
        return [child.to_dict() for child in children]
    return {key: child.to_dict() for key, child in children.items()}


def _children_from_dict(children: Any) -> ChildrenData:
    """
    The inverse of :func:`_children_to_dict`. The shape is told apart by the
    JSON alone: a list, a single save (it has ``def``) or a map of saves.
    """
    if isinstance(children, DbData):
        return children
    if isinstance(children, list):
        return [DbData.coerce(child) for child in children]
    if "def" in children:  # a single child
        return DbData.from_dict(children)
    return {key: DbData.coerce(child) for key, child in children.items()}
