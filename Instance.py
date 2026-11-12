from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Iterator

from DbData import ComponentPath, DbData
from Definitions import GAMES, DefinitionStore
from InnerFunction import EvalContext, InnerFunction
from container.Container import Container
from datatype.Datatype import Datatype
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
    collected. Finally the saved data is applied (:meth:`load`).

    Two ways to create one — the game is always given exactly once:

    - ``Instance(save)``: from a save, which names its definition and its game,
    - ``Instance.new("battleaxe", "dnd5e")``: a fresh instance, nothing saved yet.

    Effects are bound by the *root* of a tree (the topmost instance): after every
    structural change it resolves every effect target again and applies only the
    difference (:meth:`_rebind`). That replaces the old per-component
    apply / remove cascade and makes loading independent of container order.
    """

    def __init__(self, data: DbData | dict, params: dict[str, Any] | None = None):
        """
        Build an instance from a save (:class:`DbData` or its dict form). The save
        holds everything needed: the definition id and the game whose definitions
        (:data:`Definitions.GAMES`) it is built from. ``params`` are bound by
        whoever creates the instance and are not saved.

        Building has two steps: :meth:`_build` reads the definitions, then
        :meth:`load` applies the save — the same method that reverts a live
        instance to a save later.
        """
        saved = DbData.coerce(data)
        if saved.game is None:
            raise DefinitionError(
                f"save of '{saved.def_id}' names no game — "
                f"use Instance.new('{saved.def_id}', <game>) for a fresh instance"
            )
        self._prop_call_stack: list[BufferElement] = []
        self._contained: Container | None = None
        #: The game (rule system) whose definitions this instance is built from.
        self.game: str = saved.game
        self.id: str = saved.def_id
        self.params: dict[str, Any] = dict(params or {})
        self.props: dict[str, Property] = {}
        self.containers: dict[str, Container] = {}
        self.sub_ids: list[str] = []
        self.traits: list[str] = []
        #: The most specific ``appliesTo`` of the chain; ``None`` = fits wherever ``of`` allows.
        self.applies_to: list[str] | None = None
        # name / text / footer — `text` VALUEs (templates are concat operations)
        self._texts: dict[str, InnerFunction] = {}
        # `active` of every definition in the chain — `bool` VALUEs, AND-ed (concept §4.9).
        self._guards: list[InnerFunction] = []
        # One manipulation per effect of the chain.
        self._manipulations: list[Manipulation] = []

        # Notified when `contained` changes, so values that read owner / entity re-resolve.
        self._buffer = BufferElement(self.prop_call_stack, lambda: None)

        # Effect bindings — used only while this instance is the root of its tree.
        self._bindings: dict[Manipulation, set[Property]] = {}
        self._batch_depth = 0
        self._rebind_pending = False

        self._build()
        self.load(saved)

    @classmethod
    def new(cls, def_id: str, game: str, params: dict[str, Any] | None = None) -> Instance:
        """A fresh instance of ``def_id`` in ``game`` — nothing saved yet, everything at its default."""
        return cls(DbData(def_id, game=game), params)

    # ------------------------------------------------------------------ building

    def _build(self) -> None:
        """Read the definitions: walk the ``extends`` chain, then apply it from the base down."""
        store = self.store

        # 1. Vererbungskette ablaufen (Kind -> Eltern), Zyklen melden
        definitions = []
        current_id: str | None = self.id
        while current_id is not None:
            if current_id in self.sub_ids:
                cycle = " -> ".join([*self.sub_ids, current_id])
                raise DefinitionError(f"cyclic extends: {cycle}")
            self.sub_ids.append(current_id)
            data_object = store.get(current_id)
            definitions.append(data_object)
            current_id = data_object.get("extends")

        if definitions[0].get("abstract", False):
            raise DefinitionError(f"'{self.id}' is abstract and cannot be instantiated")

        # 2. Von der Basis zum Kind anwenden (LIFO), damit Kinder überschreiben
        for data_object in reversed(definitions):
            self._apply_definition(data_object)

        open_props = [prop.id for prop in self.props.values() if prop.is_open()]
        if open_props:
            raise DefinitionError(
                f"'{self.id}' leaves {open_props} without a value; set them or mark '{self.id}' abstract"
            )

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
            self._guards.append(self._entry_value(entry, "active", "bool"))
        if "appliesTo" in entry:
            self.applies_to = list(entry["appliesTo"])
        for key in ("name", "text", "footer"):
            if key in entry:
                self._texts[key] = self._entry_value(entry, key, "text")

    def _entry_value(self, entry: dict, key: str, type_name: str) -> InnerFunction:
        try:
            return self.store.value(entry[key], Datatype.get(type_name))
        except DefinitionError as error:
            raise DefinitionError(f"'{entry.get('id', '?')}': {key}: {error}") from None

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

    def spawn(self, data: DbData | dict | str, params: dict | None = None) -> Instance:
        """
        A new instance of this instance's game (used by containers): from a
        definition id or a child save. A child save names no game — it inherits
        this one; naming another game is an error.
        """
        saved = DbData.coerce(data)
        if saved.game is None:
            saved = replace(saved, game=self.game)
        elif saved.game != self.game:
            raise DefinitionError(
                f"save of '{saved.def_id}' belongs to game '{saved.game}', '{self.id}' to '{self.game}'"
            )
        return type(self)(saved, params)

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
    def store(self) -> DefinitionStore:
        """The definitions of this instance's game, looked up in :data:`GAMES`."""
        return GAMES.get(self.game)

    @property
    def definition(self) -> dict:
        return self.store.get(self.id)

    @property
    def effects(self) -> tuple[Manipulation, ...]:
        return tuple(self._manipulations)

    def is_active(self) -> bool:
        """Every ``active`` guard of the chain holds. Reads are tracked, so this re-evaluates on change."""
        ctx = EvalContext(this=self)
        return all(bool(guard.evaluate(ctx)) for guard in self._guards)

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
        return str(self._texts[key].evaluate(EvalContext(this=self)))

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
        """
        The save of this instance and everything below it — only what the
        definitions cannot know (concept §4.13). Names its game, so the save alone
        is enough to build the instance again: ``Instance(instance.to_data())``.
        """
        data = self._save()
        data.game = self.game
        return data

    def _save(self) -> DbData:
        """Like :meth:`to_data`, without the game — the form a child takes inside its parent's save."""
        data = DbData(self.id)
        for prop in self.props.values():
            serialized = prop.serialize()
            if serialized is not None:
                data.props[prop.id] = serialized
        for container_id, container in self.containers.items():
            saved = container.to_data()
            if saved is not None:
                data.children[container_id] = saved
        return data

    def load(self, data: DbData | dict | str) -> None:
        """
        Make this instance match a save: every saved value and child is restored,
        everything the save leaves out goes back to the definition's default
        (default values, ``seed``, untouched ``fixed`` entries). ``granted``
        containers are left alone — grants refill them.

        The constructor ends with this; called on a live instance it reverts the
        instance to the save (``inst.load(d)`` → ``inst.to_data() == d``). Fixed
        children are loaded into, never rebuilt, so effects bound to them survive.
        """
        saved = DbData.coerce(data)
        self._check_save(saved)
        with self.batch():
            # Reset first, so every saved choice is checked against the values it will live with.
            for prop in self.props.values():
                if prop.id not in saved.props:
                    prop.reset()
            for prop_id, raw in saved.props.items():
                self.props[prop_id].deserialize(raw)
            for container_id, container in self.containers.items():
                container.load(saved.children.get(container_id))
            self._structure_changed()  # bind the effects of the (new) tree

    def _check_save(self, saved: DbData) -> None:
        """Reject a save that does not fit this instance, before anything changes."""
        if saved.def_id != self.id:
            raise DefinitionError(f"save of '{saved.def_id}' cannot be loaded into '{self.id}'")
        if saved.game is not None and saved.game != self.game:
            raise DefinitionError(
                f"save of '{saved.def_id}' belongs to game '{saved.game}', '{self.id}' to '{self.game}'"
            )
        for prop_id in saved.props:
            if prop_id not in self.props:
                raise PropertyError(
                    f"save of '{self.id}' has unknown prop '{prop_id}'{did_you_mean(prop_id, self.props)}"
                )
        for container_id in saved.children:
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
