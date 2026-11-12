from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Iterator

from container.Container import Container
from datatype.Datatype import Datatype
from definition.DefinitionStore import GAMES, DefinitionStore
from errors import ContainerError, DefinitionError, PropertyError, did_you_mean
from instance.ComponentPath import ComponentPath
from instance.DbData import DbData
from property.DependencyNode import DependencyNode
from property.Manipulation import Manipulation
from property.Property import Property
from value.InnerFunction import EvalContext, InnerFunction

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
#: Every key an entry may have; anything else is reported as a typo.
ENTRY_KEYS = HANDLED_KEYS | IGNORED_KEYS


class Instance:
    """
    A live game object, built from a definition id and its saved data — the
    "ComponentDefinition" of the Engine-Konzept.

    Design decision: there is no subclass per entry — the instance reads its
    definition as a recipe. It walks the ``extends`` chain (child → parent), then
    applies the entries from the base down to the child, so children override: declared
    ``props`` become :class:`Property` objects, ``contains`` become
    :class:`Container` objects, ``set`` / ``refine`` adjust inherited props,
    ``effects`` become :class:`Manipulation` objects, ``active`` guards are
    collected. Finally the saved data is applied (:meth:`load`).

    Two ways to create one — the game is always given exactly once:

    - ``Instance(save)``: from a save, which names its definition and its game,
    - ``Instance.new("battleaxe", "dnd5e")``: a fresh instance, nothing saved yet.

    Design decision: effects are bound by the *root* of a tree (the topmost
    instance), not by each component: after every structural change the root
    resolves every effect target again and applies only the difference
    (:meth:`_rebind`). That makes loading independent of container order.
    """

    def __init__(self, data: DbData | dict, params: dict[str, Any] | None = None):
        """
        Build an instance from a save (:class:`DbData` or its dict form). The save
        holds everything needed: the definition id and the game whose definitions
        (:data:`definition.DefinitionStore.GAMES`) it is built from. ``params`` are bound by
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
        # Only the root's stack is used — see resolve_stack.
        self._resolve_stack: list[DependencyNode] = []
        self._contained: Container | None = None
        #: The game (rule system) whose definitions this instance is built from.
        self.game: str = saved.game
        #: The id of the definition entry this instance is built from — shared by every instance of it.
        self.def_id: str = saved.def_id
        self.params: dict[str, Any] = dict(params or {})
        self.props: dict[str, Property] = {}
        self.containers: dict[str, Container] = {}
        #: ``def_id`` and the ids it ``extends``, child → parent (see :meth:`is_a`).
        self.extends_chain: list[str] = []
        self.traits: list[str] = []
        #: The most specific ``appliesTo`` of the chain; ``None`` = fits wherever ``of`` allows.
        self.applies_to: list[str] | None = None
        # name / text / footer — `text` VALUEs (templates are concat operations).
        self._texts: dict[str, InnerFunction] = {}
        # `active` of every definition in the chain — `bool` VALUEs, AND-ed (concept §4.9).
        self._guards: list[InnerFunction] = []
        # One manipulation per effect of the chain.
        self._manipulations: list[Manipulation] = []

        # Notified when `contained` changes, so values that read owner / entity re-resolve.
        self._dependency_node = DependencyNode(self.resolve_stack, lambda: None)

        # Effect bindings and batching (see batch) — used only while this instance is the root of its tree.
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

        # 1. Walk the inheritance chain (child -> parent) and report cycles.
        definitions = []
        current_id: str | None = self.def_id
        while current_id is not None:
            if current_id in self.extends_chain:
                cycle = " -> ".join([*self.extends_chain, current_id])
                raise DefinitionError(f"cyclic extends: {cycle}")
            self.extends_chain.append(current_id)
            entry = store.get(current_id)
            definitions.append(entry)
            current_id = entry.get("extends")

        if definitions[0].get("abstract", False):
            raise DefinitionError(f"'{self.def_id}' is abstract and cannot be instantiated")

        # 2. Apply it from the base down to the child (LIFO), so children override.
        for entry in reversed(definitions):
            self._apply_definition(entry)

        open_props = [prop.id for prop in self.props.values() if prop.is_open()]
        if open_props:
            raise DefinitionError(
                f"'{self.def_id}' leaves {open_props} without a value; set them or mark '{self.def_id}' abstract"
            )

    def _apply_definition(self, entry: dict) -> None:
        """Apply one entry of the chain: its traits first, then its own keys."""
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
            self._guards.append(self._build_entry_node(entry, "active", "bool"))
        if "appliesTo" in entry:
            self.applies_to = list(entry["appliesTo"])
        for key in ("name", "text", "footer"):
            if key in entry:
                self._texts[key] = self._build_entry_node(entry, key, "text")

    def _build_entry_node(self, entry: dict, key: str, type_name: str) -> InnerFunction:
        """The VALUE under ``key`` of ``entry`` as a node of ``type_name``."""
        try:
            return self.store.value(entry[key], Datatype.get(type_name))
        except DefinitionError as error:
            raise DefinitionError(f"'{entry.get('id', '?')}': {key}: {error}") from None

    def _check_new_name(self, name: str, entry_id: str) -> None:
        """Props and containers share one namespace, and inherited names cannot be declared again."""
        if name in self.props or name in self.containers:
            raise DefinitionError(
                f"'{entry_id}' redeclares '{name}', which it already inherits — use `set` / `refine`"
            )

    def _declared_prop(self, prop_id: str, entry_id: str, key: str) -> Property:
        """The inherited prop a ``set`` / ``refine`` (``key``) of ``entry_id`` refers to."""
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
                f"save of '{saved.def_id}' belongs to game '{saved.game}', '{self.def_id}' to '{self.game}'"
            )
        return type(self)(saved, params)

    # ------------------------------------------------------------------ access

    def prop(self, prop_id: str) -> Property:
        """The prop ``prop_id``; an unknown id is reported with the closest match."""
        try:
            return self.props[prop_id]
        except KeyError:
            raise PropertyError(f"'{self.def_id}' has no prop '{prop_id}'{did_you_mean(prop_id, self.props)}") from None

    def get(self, prop_id: str) -> Any:
        """The current value of a prop (tracked like every resolve)."""
        return self.prop(prop_id).resolve()

    def container(self, container_id: str) -> Container:
        """The container ``container_id``; an unknown id is reported with the closest match."""
        try:
            return self.containers[container_id]
        except KeyError:
            raise ContainerError(
                f"'{self.def_id}' has no container '{container_id}'{did_you_mean(container_id, self.containers)}"
            ) from None

    def is_a(self, type_id: str) -> bool:
        """Whether ``type_id`` is this entry or one of its ``extends`` ancestors."""
        return type_id in self.extends_chain

    @property
    def store(self) -> DefinitionStore:
        """The definitions of this instance's game, looked up in :data:`GAMES`."""
        return GAMES.get(self.game)

    @property
    def definition(self) -> dict:
        """The JSON entry of :attr:`def_id` (without what it inherits)."""
        return self.store.get(self.def_id)

    @property
    def effects(self) -> tuple[Manipulation, ...]:
        """One manipulation per effect of the chain, base first."""
        return tuple(self._manipulations)

    def is_active(self) -> bool:
        """Every ``active`` guard of the chain holds. Reads are tracked, so this re-evaluates on change."""
        ctx = EvalContext(this=self)
        return all(bool(guard.evaluate(ctx)) for guard in self._guards)

    # ------------------------------------------------------------------ texts

    @property
    def name(self) -> str:
        """Display name; may be a template (``"Shadow {roman(level)}"``). Defaults to the id."""
        return self._text("name", self.def_id)

    @property
    def description(self) -> str:
        """Flavor text (``text``)."""
        return self._text("text", "")

    @property
    def footer(self) -> str:
        """Small print below the description (``footer``)."""
        return self._text("footer", "")

    def _text(self, key: str, default: str) -> str:
        """The text VALUE under ``key``, evaluated now, or ``default`` if the chain has none."""
        if key not in self._texts:
            return default
        return str(self._texts[key].evaluate(EvalContext(this=self)))

    # ------------------------------------------------------------------ position in the tree

    @property
    def contained(self) -> Container | None:
        """The container this instance sits in (tracked)."""
        return self._dependency_node.track_read(lambda: self._contained)

    @contained.setter
    def contained(self, contained: Container | None) -> None:
        """
        Attach to ``contained`` (or detach with ``None``). The same steps as
        ``set contained`` in the Engine-Konzept, but run by the roots instead of
        every component:

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
        self._dependency_node.invalidate()

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
        """The entity this instance lies in (``entity`` in a path): itself if it is one, else its owner's."""
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

    def resolve_stack(self) -> list[DependencyNode]:
        """
        The resolve stack shared by every DependencyNode of one tree (kept by the
        root): the values being computed right now, innermost last. Reads the
        private ``_contained`` on purpose: the stack must not itself be part of the
        dependency graph.
        """
        if self._contained is not None:
            return self._contained.owner.resolve_stack()
        return self._resolve_stack

    def walk(self) -> Iterator[Instance]:
        """This instance and everything below it (untracked)."""
        yield self
        for container in self.containers.values():
            for child in container.all_untracked():
                yield from child.walk()

    def _is_within(self, ancestor: Instance) -> bool:
        """Whether ``ancestor`` is this instance or lies above it (untracked)."""
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
        return ComponentPath(name=self.def_id, parent=upper)

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

        # Apply only the difference: unbind what is no longer desired, bind what is new.
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
            cut = members is None or manipulation.source in members  # the source leaves: drop all its targets
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
        data = DbData(self.def_id)
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
        if saved.def_id != self.def_id:
            raise DefinitionError(f"save of '{saved.def_id}' cannot be loaded into '{self.def_id}'")
        if saved.game is not None and saved.game != self.game:
            raise DefinitionError(
                f"save of '{saved.def_id}' belongs to game '{saved.game}', '{self.def_id}' to '{self.game}'"
            )
        for prop_id in saved.props:
            if prop_id not in self.props:
                raise PropertyError(
                    f"save of '{self.def_id}' has unknown prop '{prop_id}'{did_you_mean(prop_id, self.props)}"
                )
        for container_id in saved.children:
            if container_id not in self.containers:
                raise ContainerError(
                    f"save of '{self.def_id}' has unknown container '{container_id}'"
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
