from __future__ import annotations

from typing import TYPE_CHECKING, Any, Union

from DbData import ContainerPath, DbData
from InnerFunction import EvalContext, InnerFunction
from datatype.Datatype import Datatype
from errors import ContainerError, DefinitionError, IllegalMutationError, did_you_mean
from property.BufferElement import BufferElement

if TYPE_CHECKING:
    from Instance import Instance

#: Keys a container declaration (an entry under ``contains:``) may contain.
SPEC_KEYS = {"of", "list", "map", "optional", "accepts", "unique", "limit", "fixed", "seed", "granted", "activates"}

#: What can be put into a container: an instance, its saved form, or a bare definition id.
ChildInput = Union["Instance", DbData, dict, str]


# ---------------------------------------------------------------------- shapes


class Shape:
    """How a container keys and saves its children (concept §4.5: single, list or map)."""

    name = ""

    def new_key(self, container: Container) -> str:
        raise ContainerError(f"'{container.path_str}' is a {self.name} container; give a key")

    def check_key(self, container: Container, key: Any) -> str:
        return str(key)

    def fixed_keys(self, container: Container) -> list[str]:
        return []

    def order(self, keys) -> list[str]:
        return list(keys)

    def save(self, items: list[tuple[str, DbData]]) -> Any:
        raise NotImplementedError

    def load(self, container: Container, raw: Any) -> dict[str, DbData]:
        raise NotImplementedError


class SingleShape(Shape):
    """At most one child, under the container's own id (``material``). Adding replaces it."""

    name = "single"

    def new_key(self, container):
        return container.id

    def check_key(self, container, key):
        if key != container.id:
            raise ContainerError(
                f"'{container.path_str}' holds a single child; its only key is '{container.id}'"
            )
        return key

    def fixed_keys(self, container):
        return [container.id]

    def save(self, items):
        return items[0][1] if items else None

    def load(self, container, raw):
        return {} if raw is None else {container.id: DbData.coerce(raw)}


class ListShape(Shape):
    """Any number of children under stable numeric keys (``"0"``, ``"1"``, ...). Saved as a list."""

    name = "list"

    def new_key(self, container):
        key = 0
        while str(key) in container._children:
            key += 1
        return str(key)

    def check_key(self, container, key):
        if not str(key).isdigit():
            raise ContainerError(f"'{container.path_str}': list keys are numbers, got '{key}'")
        return str(key)

    def order(self, keys):
        return sorted(keys, key=int)

    def save(self, items):
        return [data for _, data in items]

    def load(self, container, raw):
        return {str(index): DbData.coerce(data) for index, data in enumerate(raw or [])}


class MapShape(Shape):
    """One child per key of a kernel enum (``attributes: {map: Attribute}``, ``equipment: {map: Slot}``)."""

    name = "map"

    def __init__(self, key_type: Datatype):
        self.key_type = key_type

    def check_key(self, container, key):
        try:
            return self.key_type.validate(key)
        except ValueError as error:
            raise ContainerError(f"'{container.path_str}': {error}") from error

    def fixed_keys(self, container):
        options = getattr(self.key_type, "options", None)
        if options is None:
            raise DefinitionError(f"'{container.path_str}': a fixed map needs an enum as key type")
        return list(options)

    def order(self, keys):
        return sorted(keys, key=self.key_type.sort_key) if self.key_type.ordered else list(keys)

    def save(self, items):
        return {key: data for key, data in items}

    def load(self, container, raw):
        return {self.check_key(container, key): DbData.coerce(data) for key, data in (raw or {}).items()}


# ---------------------------------------------------------------------- container


class Container:
    """
    A named slot of an instance that holds other instances (concept §4.5):
    inventory, enchantments, the attribute map, the material.

    One class for every container — its behaviour comes from the declaration
    (an entry under ``contains:``), not from a subclass. It replaces CompContainer,
    RegisterContainer, StaticContainer and the Single* variants; ``canAdd`` and
    ``applicableOnWeapon`` become ``of`` / ``appliesTo`` / ``accepts``.

    ==============  ==============================================================
    ``of``          least common type; every descendant fits
    shape           single (default), ``list: true`` or ``map: <EnumType>``
    ``accepts``     extra predicate on the candidate ``it``
    ``unique``      no two children with the same definition
    ``limit``       max count — exceeding it is reported (:meth:`issues`), not blocked
    ``fixed``       the kernel creates the entries (one per map key / the seed); no add / remove
    ``seed``        definition ids every new instance starts with
    ``granted``     filled only by grants (:meth:`grant` / :meth:`revoke`), not saved
    ``activates``   whether the children's effects reach outside them (backpack: no)
    ``optional``    a single container may stay empty
    ==============  ==============================================================

    Reads (:meth:`get`, :meth:`all`, :meth:`keys`, ``len``) are tracked: a property
    that reads a container recomputes when a child is added or removed.
    """

    def __init__(self, owner: Instance, id: str, spec: dict):
        unknown = set(spec) - SPEC_KEYS
        if unknown:
            key = sorted(unknown)[0]
            raise DefinitionError(f"container '{id}': unknown key '{key}'{did_you_mean(key, SPEC_KEYS)}")
        if "of" not in spec:
            raise DefinitionError(f"container '{id}' has no 'of'")
        if spec.get("list") and "map" in spec:
            raise DefinitionError(f"container '{id}' cannot be both a list and a map")

        self.id = id
        self.owner = owner
        self.of: str = spec["of"]
        if "map" in spec:
            self.shape: Shape = MapShape(Datatype.get(spec["map"]))
        elif spec.get("list"):
            self.shape = ListShape()
        else:
            self.shape = SingleShape()
        self.optional = bool(spec.get("optional", False))
        #: ``bool`` VALUE on the candidate ``it``; ``None`` = no extra condition.
        self.accepts: InnerFunction | None = self._value(spec, "accepts", "bool")
        self.unique = bool(spec.get("unique", False))
        #: ``int`` VALUE; ``None`` = unlimited.
        self.limit: InnerFunction | None = self._value(spec, "limit", "int")
        self.fixed = bool(spec.get("fixed", False))
        self.seed: list[str] = list(spec.get("seed", []))
        self.granted = bool(spec.get("granted", False))
        self.activates = bool(spec.get("activates", True))
        if self.fixed and self.granted:
            raise DefinitionError(f"container '{id}' cannot be both fixed and granted")

        self._children: dict[str, Instance] = {}
        # Notified when a child is added or removed, so whatever read the container re-resolves.
        self._buffer = BufferElement(self.owner.prop_call_stack, lambda: None)

    def _value(self, spec: dict, key: str, type_name: str) -> InnerFunction | None:
        if key not in spec:
            return None
        try:
            return self.owner.store.value(spec[key], Datatype.get(type_name))
        except DefinitionError as error:
            raise DefinitionError(f"container '{self.id}': {key}: {error}") from None

    # ------------------------------------------------------------------ reading (tracked)

    def get(self, key: str | None = None) -> Instance | None:
        """The child under ``key``, or ``None``. A single container needs no key."""
        key = self._default_key(key)
        return self._buffer.read_operation(lambda: self._children.get(key))

    def all(self) -> list[Instance]:
        """Every child, in key order."""
        return self._buffer.read_operation(self.all_untracked)

    def keys(self) -> list[str]:
        return self._buffer.read_operation(lambda: self.shape.order(self._children))

    def items(self) -> list[tuple[str, Instance]]:
        return self._buffer.read_operation(
            lambda: [(key, self._children[key]) for key in self.shape.order(self._children)]
        )

    def __len__(self) -> int:
        return self._buffer.read_operation(lambda: len(self._children))

    def __iter__(self):
        return iter(self.all())

    def all_untracked(self) -> list[Instance]:
        """Like :meth:`all`, without registering the caller as a dependant (for the binder)."""
        return [self._children[key] for key in self.shape.order(self._children)]

    def key_of(self, instance: Instance) -> str | None:
        for key, child in self._children.items():
            if child is instance:
                return key
        return None

    @property
    def entity(self) -> Instance | None:
        return self.owner.entity

    # ------------------------------------------------------------------ changing

    def add(self, child: ChildInput, key: str | None = None) -> Instance:
        """
        Put a child in: under a new key (list), under ``key`` (map — required) or
        under the only key (single — replaces the current child). ``child`` may be
        an instance, its saved form or a definition id. Returns the instance.
        """
        self._refuse_if_managed("add to")
        key = self.shape.new_key(self) if key is None else self.shape.check_key(self, key)
        return self._put(key, child)

    def remove(self, key: str | None = None) -> Instance | None:
        """Take the child under ``key`` out; it becomes a stand-alone instance. Returns it."""
        self._refuse_if_managed("remove from")
        self._check_mutable()
        return self._take(self._default_key(key))

    def remove_instance(self, instance: Instance) -> bool:
        key = self.key_of(instance)
        if key is None:
            return False
        self.remove(key)
        return True

    def grant(self, child: ChildInput) -> Instance:
        """Put a child into a ``granted`` container — the way grants fill it (concept §4.10)."""
        if not self.granted:
            raise ContainerError(f"'{self.path_str}' is not a granted container")
        return self._put(self.shape.new_key(self), child)

    def revoke(self, instance: Instance) -> bool:
        if not self.granted:
            raise ContainerError(f"'{self.path_str}' is not a granted container")
        key = self.key_of(instance)
        if key is None:
            return False
        self._check_mutable()
        self._take(key)
        return True

    def why_not(self, instance: Instance, key: str | None = None) -> str | None:
        """Why ``instance`` cannot go in (``None``: it can). Checks game, ``of``, ``appliesTo``, ``unique``, ``accepts``."""
        if instance.game != self.owner.game:
            return f"'{instance.id}' belongs to game '{instance.game}', '{self.path_str}' to '{self.owner.game}'"
        if not instance.is_a(self.of):
            return f"'{instance.id}' is not a '{self.of}', so it does not fit '{self.path_str}'"
        if instance.applies_to is not None and not any(self.owner.is_a(t) for t in instance.applies_to):
            return f"'{instance.id}' applies only to {instance.applies_to}, not to '{self.owner.id}'"
        if self.owner._is_within(instance):
            return f"'{instance.id}' cannot be put inside itself"
        if self.unique:
            for other_key, other in self._children.items():
                if other_key != key and other is not instance and other.id == instance.id:
                    return f"'{self.path_str}' already holds '{instance.id}' (unique)"
        if self.accepts is not None and not self.accepts.evaluate(EvalContext(this=self.owner, it=instance)):
            return f"'{self.path_str}' does not accept '{instance.id}'"
        return None

    def can_accept(self, instance: Instance) -> bool:
        return self.why_not(instance) is None

    def _put(self, key: str, child: ChildInput, check: bool = True) -> Instance:
        self._check_mutable()
        instance = self._instantiate(child)
        if check:
            reason = self.why_not(instance, key)
            if reason is not None:
                raise ContainerError(reason)

        with self.owner.batch():
            if key in self._children:
                self._take(key)
            previous = instance._contained
            if previous is not None:  # moving: out of the old container first
                previous._children.pop(previous.key_of(instance))
                previous._buffer.update()
            # Map first, then `contained`: re-binding walks the tree and has to find the child.
            self._children[key] = instance
            instance.contained = self
            self._buffer.update()
        return instance

    def _take(self, key: str) -> Instance | None:
        instance = self._children.pop(key, None)
        if instance is None:
            return None
        # Out of the map first, so the old root re-binds without it.
        with self.owner.batch():
            instance.contained = None
            self._buffer.update()
        return instance

    def _instantiate(self, child: ChildInput) -> Instance:
        if isinstance(child, (str, DbData, dict)):
            return self.owner.spawn(child)
        return child

    def _refuse_if_managed(self, action: str) -> None:
        if self.fixed:
            raise ContainerError(f"cannot {action} '{self.path_str}': its entries are fixed")
        if self.granted:
            raise ContainerError(f"cannot {action} '{self.path_str}': it is filled only by grants")

    def _default_key(self, key: str | None) -> str:
        if key is not None:
            return key
        if self.shape.name == "single":
            return self.id
        raise ContainerError(f"'{self.path_str}' is a {self.shape.name} container; give a key")

    def _check_mutable(self) -> None:
        stack = self.owner.prop_call_stack()
        if stack:
            raise IllegalMutationError(
                f"'{self.path_str}' changed while a property was resolving (stack depth {len(stack)})"
            )

    # ------------------------------------------------------------------ diagnostics

    def issues(self) -> list[str]:
        """Rule violations that are reported, not blocked — it's a GM tool."""
        found = []
        count = len(self._children)
        if self.limit is not None:
            limit = self.limit.evaluate(EvalContext(this=self.owner))
            if count > limit:
                found.append(f"'{self.path_str}' holds {count} entries, the limit is {limit}")
        if self.shape.name == "single" and not self.optional and count == 0:
            found.append(f"'{self.path_str}' is empty but not optional")
        return found

    # ------------------------------------------------------------------ save / load

    def load(self, saved: Any = None) -> None:
        """
        Make the container hold exactly what ``saved`` says (shaped like the
        container); ``None`` means "nothing saved", i.e. the definition's default:

        - ``fixed``: the entries always exist — created when missing (a new
          instance), otherwise the save is loaded *into* them; an entry the save
          leaves out is reset,
        - ``granted``: refilled by grants, never loaded — left alone,
        - otherwise: the saved children, or the ``seed`` if nothing is saved.
        """
        if self.fixed:
            self._load_fixed(saved)
            return
        if self.granted:
            if saved is not None:
                raise ContainerError(f"'{self.path_str}' is filled by grants; it is not loaded from a save")
            return
        entries = self.shape.load(self, saved if saved is not None else self._seed_save())
        with self.owner.batch():
            for key in list(self._children):
                if key not in entries:
                    self._take(key)
            for key, data in entries.items():
                self._put(key, data)

    def _seed_save(self) -> Any:
        """The seed, shaped like a save of this container — what a new instance starts with."""
        return self.shape.save([(str(index), DbData(def_id)) for index, def_id in enumerate(self.seed)])

    def _load_fixed(self, saved: Any) -> None:
        """
        Fixed children are never regenerated: the save is loaded into them, so
        nothing bound to them is lost. (The old StaticContainer regenerated them,
        which is why the Entity's container order was load-bearing.)
        """
        fixed = self._fixed_entries()
        entries = self.shape.load(self, saved) if saved is not None else {}
        for key, data in entries.items():
            if key not in fixed:
                raise ContainerError(f"'{self.path_str}' has no fixed entry '{key}'{did_you_mean(key, fixed)}")
            if data.def_id != fixed[key]:
                raise ContainerError(f"'{self.path_str}:{key}' is a '{fixed[key]}', the save says '{data.def_id}'")
        with self.owner.batch():
            for key, def_id in fixed.items():
                data = entries[key] if key in entries else DbData(def_id)
                child = self._children.get(key)
                if child is None:
                    self._put(key, data)
                else:
                    child.load(data)

    def _fixed_entries(self) -> dict[str, str]:
        """Key → definition id of every fixed entry: the seed of a list, one ``of`` per key otherwise."""
        if self.shape.name == "list":
            return {str(index): def_id for index, def_id in enumerate(self.seed)}
        return {key: self.of for key in self.shape.fixed_keys(self)}

    def to_data(self) -> Any:
        """The saved form, shaped like the container; ``None`` when there is nothing to save."""
        if self.granted:
            return None  # rebuilt by the grants
        items = [(key, self._children[key]._save()) for key in self.shape.order(self._children)]
        if self.fixed:
            items = [(key, data) for key, data in items if not data.is_empty()]
            return self.shape.save(items) if items else None
        if not items and not self.seed:
            return None
        # Saved even when empty if there is a seed — otherwise removed seeds would come back.
        return self.shape.save(items)

    # ------------------------------------------------------------------ paths

    def path_of(self, instance: Instance) -> ContainerPath | None:
        key = self.key_of(instance)
        if key is None:
            return None
        return ContainerPath(upper_path=self.owner.path, container_id=self.id, component_key=key)

    @property
    def path_str(self) -> str:
        return f"{self.owner.path}/{self.id}"

    def __repr__(self) -> str:
        return f"<Container {self.path_str} ({self.shape.name} of {self.of})>"
