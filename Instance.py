from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from DbData import ComponentPath, DbData
from Definitions import DEFAULT_STORE, DefinitionStore
from InnerFunction import EvalContext, evaluate_value
from container.Container import Container
from errors import ContainerError, DefinitionError, PropertyError, did_you_mean
from property.BufferElement import BufferElement
from property.Manipulation import Manipulation
from property.Property import Property

#: Model type whose instances are entities. ``entity`` in a path means the nearest
#: instance of this type at or above the current one.
ENTITY_TYPE = "entity"

#: Entry keys (concept §4.1) this prototype interprets.
HANDLED_KEYS = {
    "id", "name", "extends", "traits", "abstract", "props", "set", "refine",
    "contains", "appliesTo", "effects", "active", "text", "footer",
}
#: Entry keys of features outside this prototype (grants, events, actions). They
#: are accepted so real content loads, and ignored.
IGNORED_KEYS = {"grants", "on", "args", "cost", "steps", "applicable", "always"}
ENTRY_KEYS = HANDLED_KEYS | IGNORED_KEYS


class Instance:
    """
    A live game object, built from a definition id and its saved data — the
    "ComponentDefinition" of the Engine-Konzept.

    Nothing is a subclass per entry anymore: the instance reads its definition as
    a recipe. It walks the ``extends`` chain (child → parent), then applies the
    entries from the base down to the child, so children override: declared
    ``props`` become :class:`Property` objects, ``contains`` become
    :class:`Container` objects, ``set`` / ``refine`` adjust inherited props,
    ``effects`` become :class:`Manipulation` objects, ``active`` guards are
    collected. Finally the saved data is applied.

    Effects are bound by the *root* of a tree (the topmost instance): after every
    structural change it resolves every effect target again and applies only the
    difference (:meth:`_rebind`). That replaces the old per-component
    apply / remove cascade and makes loading independent of container order.
    """

    def __init__(
        self,
        id: str,
        data: DbData | dict | None = None,
        store: DefinitionStore | None = None,
        params: dict[str, Any] | None = None,
    ):
        self._prop_call_stack: list[BufferElement] = []
        self._contained: Container | None = None
        self.id = id
        self.store = store if store is not None else DEFAULT_STORE
        self.params: dict[str, Any] = dict(params or {})
        self.props: dict[str, Property] = {}
        self.containers: dict[str, Container] = {}
        self.sub_ids: list[str] = []
        self.traits: list[str] = []
        #: The most specific ``appliesTo`` of the chain; ``None`` = fits wherever ``of`` allows.
        self.applies_to: list[str] | None = None
        self._texts: dict[str, Any] = {}
        # `active` of every definition in the chain — AND-ed (concept §4.9).
        self._guards: list[Any] = []
        # One manipulation per effect of the chain.
        self._manipulations: list[Manipulation] = []

        # Notified when `contained` changes, so values that read owner / entity re-resolve.
        self._buffer = BufferElement(self.prop_call_stack, lambda: None)

        # Effect bindings — used only while this instance is the root of its tree.
        self._bindings: dict[Manipulation, set[Property]] = {}
        self._batch_depth = 0
        self._rebind_pending = False

        # 1. Vererbungskette ablaufen (Kind -> Eltern), Zyklen melden
        definitions = []
        current_id: str | None = id
        while current_id is not None:
            if current_id in self.sub_ids:
                cycle = " -> ".join([*self.sub_ids, current_id])
                raise DefinitionError(f"cyclic extends: {cycle}")
            self.sub_ids.append(current_id)
            data_object = self.store.get(current_id)
            definitions.append(data_object)
            current_id = data_object.get("extends")

        if definitions[0].get("abstract", False):
            raise DefinitionError(f"'{id}' is abstract and cannot be instantiated")

        # 2. Von der Basis zum Kind anwenden (LIFO), damit Kinder überschreiben
        for data_object in reversed(definitions):
            self._apply_definition(data_object)

        open_props = [prop.id for prop in self.props.values() if prop.is_open()]
        if open_props:
            raise DefinitionError(f"'{id}' leaves {open_props} without a value; set them or mark '{id}' abstract")

        # 3. Daten setzen
        saved = DbData.coerce(data) if data is not None else None
        if saved is not None and saved.def_id != id:
            raise DefinitionError(f"save of '{saved.def_id}' cannot be loaded into '{id}'")
        with self.batch():
            if saved is not None:
                self._check_saved_containers(saved)
                self._load_values(saved)
            for container_id, container in self.containers.items():
                container.initialize(saved.children.get(container_id) if saved is not None else None)
            self._structure_changed()  # bind the effects of the new tree

    # ------------------------------------------------------------------ building

    def _apply_definition(self, entry: dict) -> None:
        entry_id = entry.get("id", "?")
        unknown = set(entry) - ENTRY_KEYS
        if unknown:
            key = sorted(unknown)[0]
            raise DefinitionError(f"'{entry_id}': unknown key '{key}'{did_you_mean(key, ENTRY_KEYS)}")

        for trait_id in entry.get("traits", []):
            if trait_id in self.traits:
                raise DefinitionError(f"'{entry_id}': trait '{trait_id}' is applied twice")
            self.traits.append(trait_id)
            self._apply_definition(self.store.get(trait_id))

        for prop_id, spec in entry.get("props", {}).items():
            self._check_new_name(prop_id, entry_id)
            self.props[prop_id] = Property(self, prop_id, spec)

        for container_id, spec in entry.get("contains", {}).items():
            self._check_new_name(container_id, entry_id)
            self.containers[container_id] = Container(self, container_id, spec)

        for prop_id, value in entry.get("set", {}).items():
            self._declared_prop(prop_id, entry_id, "set").adjust(value)

        for prop_id, spec in entry.get("refine", {}).items():
            self._declared_prop(prop_id, entry_id, "refine").refine(spec)

        for effect in entry.get("effects", []):
            self._manipulations.append(
                Manipulation.from_effect(effect, source=self, index=len(self._manipulations))
            )

        if "active" in entry:
            self._guards.append(entry["active"])
        if "appliesTo" in entry:
            self.applies_to = list(entry["appliesTo"])
        for key in ("name", "text", "footer"):
            if key in entry:
                self._texts[key] = entry[key]

    def _check_new_name(self, name: str, entry_id: str) -> None:
        if name in self.props or name in self.containers:
            raise DefinitionError(
                f"'{entry_id}' redeclares '{name}', which it already inherits — use `set` / `refine`"
            )

    def _declared_prop(self, prop_id: str, entry_id: str, key: str) -> Property:
        if prop_id not in self.props:
            raise DefinitionError(
                f"'{entry_id}': `{key}` on unknown prop '{prop_id}'{did_you_mean(prop_id, self.props)}"
            )
        return self.props[prop_id]

    def spawn(self, def_id: str, data: DbData | dict | None = None, params: dict | None = None) -> Instance:
        """A new instance from the same definition store (used by containers)."""
        return type(self)(def_id, data, store=self.store, params=params)

    # ------------------------------------------------------------------ access

    def prop(self, prop_id: str) -> Property:
        try:
            return self.props[prop_id]
        except KeyError:
            raise PropertyError(f"'{self.id}' has no prop '{prop_id}'{did_you_mean(prop_id, self.props)}") from None

    def get(self, prop_id: str) -> Any:
        """The current value of a prop (tracked like every resolve)."""
        return self.prop(prop_id).resolve()

    def container(self, container_id: str) -> Container:
        try:
            return self.containers[container_id]
        except KeyError:
            raise ContainerError(
                f"'{self.id}' has no container '{container_id}'{did_you_mean(container_id, self.containers)}"
            ) from None

    def is_a(self, type_id: str) -> bool:
        """Whether ``type_id`` is this entry or one of its ``extends`` ancestors."""
        return type_id in self.sub_ids

    @property
    def definition(self) -> dict:
        return self.store.get(self.id)

    @property
    def effects(self) -> tuple[Manipulation, ...]:
        return tuple(self._manipulations)

    def is_active(self) -> bool:
        """Every ``active`` guard of the chain holds. Reads are tracked, so this re-evaluates on change."""
        ctx = EvalContext(this=self)
        return all(bool(evaluate_value(guard, ctx)) for guard in self._guards)

    # ------------------------------------------------------------------ texts

    @property
    def name(self) -> str:
        """Display name; may be a template (``"Shadow {roman(level)}"``). Defaults to the id."""
        return self._text("name", self.id)

    @property
    def description(self) -> str:
        """Flavor text (``text``)."""
        return self._text("text", "")

    @property
    def footer(self) -> str:
        return self._text("footer", "")

    def _text(self, key: str, default: str) -> str:
        if key not in self._texts:
            return default
        return str(evaluate_value(self._texts[key], EvalContext(this=self)))

    # ------------------------------------------------------------------ position in the tree

    @property
    def contained(self) -> Container | None:
        """The container this instance sits in (tracked)."""
        return self._buffer.read_operation(lambda: self._contained)

    @contained.setter
    def contained(self, contained: Container | None) -> None:
        """
        Attach to ``contained`` (or detach with ``None``). Same steps as the old
        ComponentDefinition, but run by the roots instead of every component:

        1. the old root drops, right away, every binding that touches this subtree
           (removeModifiers) — all of them if this instance is the root itself,
        2. switch the container and notify everything that read owner / entity,
        3. let the old and the new root re-bind their effects (applyModifiers).

        Step 1 must not wait for the old root's (possibly batched) re-bind: the new
        root binds the subtree's own effects again, and a late re-bind of the old
        root would remove exactly those.

        Containers call this; use :meth:`Container.add` / :meth:`Container.remove`.
        """
        old_root = self.root
        old_root._release_bindings(None if old_root is self else self)

        self._contained = contained
        self._buffer.update()

        if old_root is not self:
            old_root._structure_changed()
        self.root._structure_changed()

    @property
    def owner(self) -> Instance | None:
        """The instance whose container holds this one (``owner`` in a path)."""
        contained = self.contained
        return contained.owner if contained is not None else None

    @property
    def entity(self) -> Instance | None:
        """Das Entity, in dem diese Instanz liegt: sie selbst, wenn sie eins ist, sonst das Entity ihres Owners."""
        if self.is_a(ENTITY_TYPE):
            return self
        owner = self.owner
        return owner.entity if owner is not None else None

    @property
    def root(self) -> Instance:
        """The topmost instance of the tree (untracked)."""
        node = self
        while node._contained is not None:
            node = node._contained.owner
        return node

    def prop_call_stack(self) -> list[BufferElement]:
        """
        The call stack shared by every BufferElement of one tree (kept by the root).
        Reads the private ``_contained`` on purpose: the stack must not itself be
        part of the observer graph.
        """
        if self._contained is not None:
            return self._contained.owner.prop_call_stack()
        return self._prop_call_stack

    def walk(self) -> Iterator[Instance]:
        """This instance and everything below it (untracked)."""
        yield self
        for container in self.containers.values():
            for child in container.all_untracked():
                yield from child.walk()

    def _is_within(self, ancestor: Instance) -> bool:
        node: Instance | None = self
        while node is not None:
            if node is ancestor:
                return True
            node = node._contained.owner if node._contained is not None else None
        return False

    @property
    def path(self) -> ComponentPath:
        """This instance's position in the tree, as a linked list toward the root."""
        # TODO: cache — this walks the whole path.
        upper = self._contained.path_of(self) if self._contained is not None else None
        return ComponentPath(name=self.id, upper_path=upper)

    # ------------------------------------------------------------------ effect binding

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group structural changes: the root re-binds effects once at the end, not after each change."""
        root = self.root
        root._batch_depth += 1
        try:
            yield
        finally:
            root._batch_depth -= 1
            if root._batch_depth == 0 and root._rebind_pending:
                root._rebind()

    def _structure_changed(self) -> None:
        """Something below the root changed (child added / removed / moved, a choice changed)."""
        root = self.root
        if root._batch_depth > 0:
            root._rebind_pending = True
        else:
            root._rebind()

    def _rebind(self) -> None:
        """
        (Root only.) Resolve every effect target of the tree again and apply only
        the difference to what is bound.

        Complete because targets depend only on structure and on const / choice
        values (stratification, concept §4.10) — exactly what triggers a rebind.

        ``activates: false`` is a boundary: an effect whose source sits below a
        non-activating container (an item in the backpack) still reaches targets
        inside that item, but nothing outside it — ``entity.*`` stays inert.
        """
        self._rebind_pending = False
        desired: dict[Manipulation, set[Property]] = {}
        for source in self.walk():
            scope = source._effect_scope()
            for manipulation in source._manipulations:
                targets = {
                    prop for prop in manipulation.target.resolve(source)
                    if prop.instance._is_within(scope)
                }
                if targets:
                    desired[manipulation] = targets

        for manipulation, props in self._bindings.items():
            for prop in props - desired.get(manipulation, set()):
                prop.remove_manipulation(manipulation)
        for manipulation, props in desired.items():
            for prop in props - self._bindings.get(manipulation, set()):
                prop.add_manipulation(manipulation)
        self._bindings = desired

    def _release_bindings(self, subtree: Instance | None = None) -> None:
        """
        (Root only.) Remove the bindings that touch ``subtree`` — its source or its
        target lies in it — or every binding if ``subtree`` is ``None``. Used when
        ``subtree`` leaves this tree, or this root becomes part of another tree.
        """
        members = None if subtree is None else set(subtree.walk())
        kept: dict[Manipulation, set[Property]] = {}
        for manipulation, props in self._bindings.items():
            cut = members is None or manipulation.source in members
            for prop in props:
                if cut or prop.instance in members:
                    prop.remove_manipulation(manipulation)
                else:
                    kept.setdefault(manipulation, set()).add(prop)
        self._bindings = kept

    def _effect_scope(self) -> Instance:
        """The topmost instance this one's effects may reach (see :meth:`_rebind`)."""
        node = self
        while node._contained is not None and node._contained.activates:
            node = node._contained.owner
        return node

    # ------------------------------------------------------------------ save / load

    def to_data(self) -> DbData:
        """Only what the definitions cannot know (concept §4.13)."""
        data = DbData(self.id)
        for prop in self.props.values():
            serialized = prop.serialize()
            if serialized is not None:
                getattr(data, prop.source.save_section)[prop.id] = serialized
        for container_id, container in self.containers.items():
            saved = container.to_data()
            if saved is not None:
                data.children[container_id] = saved
        return data

    def _load(self, data: DbData) -> None:
        """Apply a save to this (freshly built) instance: its values, then its containers."""
        if data.def_id != self.id:
            raise DefinitionError(f"save of '{data.def_id}' cannot be loaded into '{self.id}'")
        self._check_saved_containers(data)
        with self.batch():
            self._load_values(data)
            for container_id, saved in data.children.items():
                self.containers[container_id].load_data(saved)

    def _load_values(self, data: DbData) -> None:
        for section in ("choices", "state"):
            for prop_id, raw in getattr(data, section).items():
                prop = self.prop(prop_id)
                if prop.source.save_section != section:
                    raise PropertyError(
                        f"'{prop.path_str}' is {prop.source.name}; it cannot be loaded from '{section}'"
                    )
                prop.deserialize(raw)

    def _check_saved_containers(self, data: DbData) -> None:
        for container_id in data.children:
            if container_id not in self.containers:
                raise ContainerError(
                    f"save of '{self.id}' has unknown container '{container_id}'"
                    f"{did_you_mean(container_id, self.containers)}"
                )

    # ------------------------------------------------------------------ diagnostics

    def issues(self) -> list[str]:
        """Every reported rule violation in this tree (e.g. a container over its ``limit``)."""
        found: list[str] = []
        for instance in self.walk():
            for container in instance.containers.values():
                found.extend(container.issues())
        return found

    def __repr__(self) -> str:
        return f"<Instance {self.path}>"
