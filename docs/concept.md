# Content-as-data rules engine — concept

Design for a rewrite of the rules engine (Rust or Go). The spike in this folder
([README.md](README.md)) tested it against the hardest existing content.

## 1. Idea

Today every item, spell or enchantment is a subclass of `ComponentDefinition`.
Content therefore carries engine logic: entries are verbose, each one can break
the engine (e.g. read or write a value past the observer pattern), and all
content is locked to TypeScript.

The new design separates the two completely:

- **Content is data.** An entry only *describes* a thing: its properties, what it
  can hold, and how it changes other values. It contains no code and cannot reach
  the engine.
- **The engine is code without content.** It knows how to read, validate, store
  and evaluate any entry — but not a single concrete item.

Nothing is instantiated as a class per entry. The engine reads a definition as a
recipe; an instance's actual values (choices, state, children) are plain data.

### Why

| Gain | Because |
| --- | --- |
| Errors before runtime | a validator checks every reference, path, type and override up front, like a compiler |
| The observer pattern cannot be bypassed | content changes values only through effects; there is no code to bypass it with |
| Content outlives the engine | the same files serve a TS, Rust or Go engine |
| AI-friendly | give the AI the schema and the function list; the validator answers with precise errors (`'levle' … did you mean 'level'?`) |
| Explainable values | every value is a base plus a sorted list of effects, so the sheet can show a breakdown |
| Wiki for free | filters, classification and descriptions come from the data |

**Cost:** an expression language and a validator must be built, and a few
procedural mechanics stay code (§2). Content can do only what the schema and the
kernel functions allow — on purpose.

## 2. Layers

| Layer | Lives in | Contains |
| --- | --- | --- |
| Kernel | code | value types, expression language, builtin functions, effect evaluation, containers, grants, events, validator, and a few one-off mechanics |
| Model | data | the game's taxonomy: entity, attribute, item → equipment → weapon, enchantment, condition, spell, … |
| Content | data | concrete entries: Battleaxe, Fireball, Haste, … |

Rule of thumb: what exists many times (content) or describes shape (model) is
data. A rule that exists once and is procedural is kernel code — damage hits
temporary HP first, paying falls back along the resource chain, a spell is
resolved. Content may call such a mechanic, never change it.

Model and content share one format; the model is simply the abstract top of the
inheritance tree.

**Pipeline:** `YAML (authored) → validate → JSON (IR) → engine`. YAML allows
comments and is pleasant to write; JSON is the stable format the engine loads. A
JSON Schema generated from the model gives IDE autocompletion. A typed config
language (Pkl) or an own DSL can later replace the YAML front end without
touching the engine.

## 3. Example

```yaml
# model
- id: weapon
  extends: equipment
  abstract: true
  props:
    martial: { type: bool }
    damage:  { type: Damage, modifiable: true }

- id: weapon-power
  extends: enchantment
  abstract: true
  appliesTo: [weapon]
  props:
    dmgType: { type: DamageType, source: choice, default: fire, options: [fire, cold, lightning] }
  set: { maxLevel: 5, group: offensive }
  effects:
    - target: owner.damage
      add: "damage(diceByLevel(level), dmgType)"

# content
- id: battleaxe
  name: Battleaxe
  extends: weapon
  set: { martial: true, requiredMaterial: metal, baseValue: 10, weight: 4, damage: 1d8 physical }

- id: elemental-weapon-power
  name: Elemental Weapon Power
  extends: weapon-power
  set: { power: "1.25 * level + 2" }
```

## 4. Schema

### 4.1 Entry

| Key | Meaning |
| --- | --- |
| `id` / `name` | identity (§4.2) |
| `extends` / `traits` / `abstract` | inheritance (§4.3) |
| `props` / `set` / `refine` | declare props / give inherited props a value / change their constraints (§4.4) |
| `contains` / `appliesTo` | what it can hold / where it may be put (§4.5) |
| `effects` | continuous changes to other values (§4.8) |
| `active` | guard for all its effects and grants (§4.9) |
| `grants` | structural changes (§4.10) |
| `on` | one-time steps on events (§4.11) |
| `args` / `cost` / `steps` / `applicable` | actions and action modifications (§4.12) |
| `always` | seeded into every entity (state-driven conditions, basic actions) |
| `text` | flavor text only; mechanics lines are generated from effects |

### 4.2 Identity

- `id`: stable slug. Saves store it; it is never shown.
- `name`: display text, may be a template (`"Shadow {roman(level)}"`).

They are separate so renaming or translating never breaks a saved character. Ids
are globally unique (open decision, §7).

### 4.3 Inheritance

- `extends`: exactly one parent. Model types and content entries are the same
  kind of thing: `item → equipment → weapon → battleaxe`.
- `traits`: mixins that add props / containers across branches. A name defined
  twice is an error, so no diamond rules are needed. (Multiple `extends` would
  need rules for which parent wins.)
- `abstract: true`: may leave props without a value; cannot be instantiated or
  picked.

A child inherits everything and may:

- `set` an inherited prop's value (for a `choice`: its default),
- `refine` its constraints: `range`, `options`, `default`, or `lock` a choice to
  one fixed value.

It may **not** change `type`, `source` or `modifiable`, nor redeclare an
inherited prop under `props` — that is reported as an accidental override.

### 4.4 Props

```yaml
props:
  weight:  { type: number, modifiable: true }
  stat:    { type: Attribute, source: choice, default: str }
  level:   { type: int, source: choice, default: 1, range: [1, maxLevel] }
  current: { type: int, source: state, default: max, range: [0, max] }
  value:   { type: number, derive: "power > 0 ? power ^ 2 : baseValue" }
```

**`source`** — where the value comes from:

| Source | Value | Saved | Example |
| --- | --- | --- | --- |
| `const` (default) | fixed by the definition chain | no | weight, base damage |
| `choice` | picked per instance in Wiki / sheet, within `range` / `options` | yes | enchantment level, chosen attribute |
| `state` | changes during play; written only by steps (§4.11) | yes | current HP, stack size |
| derived (`derive:`) | computed from other values | no | item value, carry limit |
| `granted` | folded by the kernel from grants | no | ability level |
| `param` | bound by whoever creates the instance | no | the spell a cast action belongs to |

**`modifiable: true`** — effects may change the value. Everything else is
read-only to effects.

This is the original *static / dynamic* × *selectable / default* split
(dynamic = `modifiable`, selectable = `choice`), plus `state` for values that
change in play and `derived` for computed ones.

- **Constraints:** `range: [min, max]` (bounds may be expressions), `options`
  (a list or an expression), `clamp` (applied after all effects), `optional`
  (may be null). On `state` props `range` is enforced on every write.
- **Abstract props:** no `default`, no `derive`, not `optional`. A concrete
  entry must `set` it somewhere in its chain.
- **Values are expressions:** `power: 3` and `power: "1.25 * level + 2"` are the
  same thing; a literal is a constant expression.
- **Types** (defined by the kernel): `int`, `number`, `bool`, `text`, `Dice`
  (`2d6+1`), `Damage` (`1d8 fire + 1d4 cold`), `Die`, kernel enums (`Attribute`,
  `DamageType`, `Slot`, …), `ref<kind>`, `list<T>`.

### 4.5 Containers

```yaml
contains:
  material:     { of: material, optional: true, accepts: "it.category in [.metal, .any]" }
  enchantments: { of: enchantment, list: true }
  attributes:   { of: attribute, map: Attribute, fixed: true }
  known:        { of: metamagic-option, list: true, unique: true, limit: knownCount }
```

| Key | Meaning |
| --- | --- |
| `of` | least common type; every descendant fits (`of: power-enchantment` excludes plain enchantments) |
| shape | single (default), `list: true`, or `map: <KeyType>` |
| `accepts` | extra predicate on the candidate `it` |
| `unique` / `limit` | no duplicates / max count (exceeding it is reported, not blocked — it's a GM tool) |
| `fixed` | the kernel creates the entries (e.g. one per map key); nobody adds or removes them |
| `seed` | entries every new instance starts with |
| `granted` | filled only by grants (§4.10) |
| `activates` | whether the children's effects apply (worn equipment: yes; backpack: no) |

On the child side, `appliesTo: [weapon]` narrows where an entry may be put. It
only ever restricts: without it, an entry fits every container whose `of` it
extends.

### 4.6 Paths

A path addresses values from the entry's point of view. A filter matches *every*
entry that fits.

| Form | Meaning |
| --- | --- |
| `level`, `this.level` | own prop |
| `owner.range`, `owner.owner.x` | the instance whose container holds this one |
| `entity.hp.max` | the root entity; while unattached, the effect is inert |
| `entity.attributes.dex.mod` | static map key |
| `entity.attributes[stat].mod` | key taken from an own prop |
| `entity.attributes[.str, .dex].advantage` | several literal keys |
| `entity.inventory[is weapon].weight` | type filter: every entry extending `weapon` (a concrete id works too) |
| `entity.inventory[*]`, `[where it.weight > 5]` | all / predicate |
| `entity?.level`, `material?.power` | may be absent: yields `null` instead of failing (see below) |
| `previous` | the value before this effect (`transform` only) |
| `action`, `args` | the action being executed and its arguments |

- **Brackets:** in `entity.items.powerItem.value`, `powerItem` could be a type,
  a key or a prop — and the meaning would change as soon as an id happens to look
  like a type. Brackets make every segment's role explicit; maps need no
  `value:` prefix.
- **`owner`, not `super`:** `super` means "parent class" in OOP; here it is the
  holder. The possible types of `owner` are `appliesTo` (and their descendants)
  — or, without it, every type with a fitting container.

#### Absent values

A path can be valid and still not resolve at runtime:

| May be absent | When |
| --- | --- |
| `entity`, `owner` | the entry is not attached (Wiki, an item in a chest) |
| optional containers, `optional` props, `ref<…>` | nothing is set |
| dynamic map keys, `first(…)` of a filter | the key or match is missing |
| a segment that exists on only some possible types | `owner.damage` while owner may be a weapon or a piece of armor |

The validator checks two different things:

1. **Can the path make sense?** Every segment must exist on at least one possible
   type. A typo or a prop that exists nowhere is an error.
2. **Is absence handled?** Only where it matters:
   - **Targets** (of effects and steps) need nothing. If a target does not
     resolve, the effect is inert or the step is skipped. This lets one enchantment
     carry both `owner.damage` and `owner.baseAC` effects and work on weapons and
     armor alike.
   - **Values** must say what happens. A segment that may be absent is written
     `?.` — the whole path then yields `null` instead of failing — and the null
     must be replaced with `??` before it is used:
     `(entity?.level ?? 0) * 2`, `material?.power ?? 0`.
     A missing `?.` or an unhandled null is an error.

No `?.` is needed where presence is already proven:

- the target resolved it — with `target: entity.hp.max`, `entity` is safe in the
  same effect's value,
- a null check came first — `when: "material != null"`, or
  `entity != null and entity.level > 3`,
- the entry cannot exist without it — sub-components in an entity's `fixed`
  containers always have an `entity`.

Lists are never `null`: a filter that matches nothing — or a `?.` path that
breaks before it — yields an empty list, and `sum` / `count` of an empty list
is 0.

### 4.7 Expressions

Strings, parsed into a typed AST during validation:

```
2 * level + 1
15 + (previous - power)
(2 * (level + 1) - 3) / 2
category == .heavy ? 0 : 2
(entity?.level ?? 0) * 2
sum(entity?.classes[*], c => (faces(c.hitDie) / 2 + 1) * c.classLevel)
convertDamage(previous, from: .physical, to: .psychic, times: 2)
```

- Arithmetic, comparison, `and / or / not`, `in`, `? :`, `?.` and `??`
  (§4.6), lambdas, named arguments, templates
  (`"Your {stat} rises by {2 * level + 1}"`).
- **Parentheses** group freely and nest to any depth. Without them, the usual
  precedence applies (high → low):

  | | Operators |
  | --- | --- |
  | 1 | `( … )`, calls, `.` `?.` `[ ]` |
  | 2 | `^` (right-associative) |
  | 3 | unary `-` |
  | 4 | `*` `/` `%` |
  | 5 | `+` `-` |
  | 6 | `==` `!=` `<` `<=` `>` `>=` `in` `is` |
  | 7 | `not` |
  | 8 | `and` |
  | 9 | `or` |
  | 10 | `??` |
  | 11 | `? :` |

  `??` must be parenthesized when combined with another operator:
  `entity?.level ?? 0 * 2` is an error, `(entity?.level ?? 0) * 2` is not.
  Precedence surprises are too likely there.
- **Enum literals** carry a leading dot (`.action`), so they never collide with a
  prop or a path root.
- **Functions** come from the kernel, each with a typed signature: generic ones
  (`min`, `max`, `sum`, `floor`, `avg`, …) and game-specific ones (`diceByLevel`,
  `convertDamage`). A kernel function is the escape hatch for logic the
  expression language should not grow into — it stays pure, typed and checkable.
- **Conversions are explicit** (`avg(dice)`, `faces(die)`); implicit ones would
  hide type errors.

Why strings instead of nested objects (`{ method: add, value1: … }`): the same AST
and the same checks at a fraction of the size — far easier to read and write,
for people and AI alike.

### 4.8 Effects

```yaml
effects:
  - target: entity.attributes[stat].value
    add: "2 * level + 1"
    priority: normal                    # optional
    when: "level >= 2"                  # optional
    label: "+{2 * level + 1} {stat}"    # optional; generated otherwise
```

An effect continuously changes one or more `modifiable` props while its source is
attached and active. Effects never write `state` and never change structure.

**Operations:** `add`, `mul`, `atLeast` (max), `atMost` (min), `override`,
`transform` (any expression of `previous`). No `sub` / `div`: use a negative
`add` or a fractional `mul`.

**Order.** Every prop is *base value → sorted effects*, sorted by:

1. **`priority`** — named stages, internally numbers with gaps so stages can be
   inserted later: `base` (adjust the starting value) → `normal` (default) →
   `final` (caps and overrides after everything else).
2. **Operation** — `transform → add → mul → atLeast → atMost → override`:
   compute, then clamp, then override, so an override really wins.
3. **Tie-break** — source id → instance path → effect index. The result never
   depends on the order in which things were added.

`add`, `mul`, `atLeast` and `atMost` give the same result in any order; there the
tie-break only keeps the sheet's breakdown stable. For `transform` and `override`
it would decide the result — renaming an id could change game values — so the
validator warns when two of them can hit the same prop at the same priority.

Example — Mage Armor raises the unarmored base before Dex is added:

```yaml
- target: entity.ac.armor
  atLeast: "12 + level"
  priority: base
  when: "entity.ac.category <= .clothing"
```

Priority orders the effects on **one** prop. Reading another prop always yields
its fully computed value; there is no global order (§5).

### 4.9 Guards

- `when:` gates a single effect, grant or step.
- `active:` gates everything an entry does and is AND-ed down the `extends`
  chain, so a whole family shares one rule:

```yaml
- id: enchantment          # anti-magic, written once for every enchantment
  active: "not magic or (entity?.magic.antiMagic ?? 0) <= (owner?.power ?? 10)"

- id: overloaded           # state-driven condition
  always: true
  active: "entity != null and entity.carryWeight > entity.carryLimit"
```

Guards are values, so absent paths need `?.` and a fallback, or a null check
(§4.6). `?.` short-circuits the rest of the path: in `entity?.magic.antiMagic`,
`magic` needs no second `?.`.

### 4.10 Grants

Grants change structure: they put instances into `granted` containers.

```yaml
grants:
  - { ability: metamagic, level: classLevel, when: "classLevel >= 3" }   # ability levels are folded
  - { to: entity.actions, make: cast-spell, with: { spell: this } }    # create with params
  - { to: entity.actionModifications, each: "known[*]" }               # expose own children
```

The kernel knows which values a grant reads and re-runs it when one changes — no
manual re-sync.

**Stratification:** grants, and `when`s on grants, may read only `const`,
`choice` and `state` values, never derived ones. Structure then never depends on
a computed value, so evaluation needs no fixpoint loop and always terminates. The
validator enforces this. (Something like Overloaded stays attached and uses
`active` instead.)

### 4.11 Events and steps

Effects are continuous; some things happen once. Those are **steps**, triggered
by an event:

```yaml
on:
  applied:                 # once when attached, never on reload
    - add: { target: "entity.resources[is action-pool].current", value: 1 }
  long-rest:
    - set: { target: current, value: max }
```

Steps are `set`, `add` and `call` (a kernel mechanic), each with an optional
`when`. They may write only `state` props, and `range` clamps every write.
Events: `applied`, `removed`, `new-turn`, `short-rest`, `long-rest`,
`end-combat`.

### 4.12 Actions and action modifications

- An **action** has `args` (chosen per use, e.g. the spell slot), a `cost` and
  `steps`.
- An **action modification** (e.g. metamagic) has `applicable` (when it can be
  picked), effects on `action.*` that last for **one execution** (the kernel
  reverts them), and `cost` operations:

```yaml
- id: quickened-spell
  extends: metamagic-option
  applicable: "action is cast-spell and action.castTime == .action"
  cost:
    action-pool:       { override: 0 }
    bonus-action-pool: { add: 1 }
    sorcery-points:    { add: 2 }
```

### 4.13 Saved instances

A save stores only what the definitions cannot know:

```yaml
def: battleaxe
state: { stack: 1 }
children:
  material: { def: shadow, choices: { level: 2 } }
  enchantments:
    - { def: elemental-weapon-power, choices: { level: 3, dmgType: fire } }
```

Everything else is rebuilt from the definitions. The validator can check saves
too (unknown def, choice out of range) — the hook for migrations when content
changes.

## 5. Evaluation

- Values are computed lazily and cached. The engine records which values each
  computation read and invalidates exactly those when an input changes — like
  today's dependency buffer, but derived from the AST instead of wired by hand.
- Grant inputs are tracked the same way.
- Cycles (A's effect reads B, B's effect reads A) are caught by the validator
  where paths are static, and by a runtime guard where filters make them dynamic.

## 6. Validation

`verify` runs before the engine loads anything — the "compiler". It checks:

- **structure:** unknown keys (with "did you mean"), duplicate ids
- **inheritance:** parents exist, no cycles, no redeclared props, `set` /
  `refine` only on existing props, no open abstract prop on a concrete entry
- **references:** `ref<…>`, `of`, `appliesTo`, `seed`, grants and cost
  resources exist and have the right type
- **paths:** every path can make sense — each segment exists on at least one
  possible type of `owner` / filter
- **absent values:** in values, every segment that may be absent uses `?.` and
  its `null` is handled with `??` (or presence is proven); targets may stay
  unresolved
- **permissions:** effects only on `modifiable`, steps only on `state`,
  `previous` only in `transform`
- **expressions:** syntax incl. parentheses and the `??` rule; known functions;
  operand and argument types (`add` only combines compatible types)
- **order:** warning on colliding `transform` / `override`
- **stratification** (§4.10)

The ~420-line prototype ([verify.mjs](verify.mjs)) already covers most of it.
Missing: a real expression parser (types, parentheses, `??` rule), absent
values, the order warning, stratification and `refine`. It is also stricter on
paths than §4.6: a segment must exist on *every* possible owner type.

Content tests as data (`given` an entity and entries, `expect` a value) close the
loop: the validator proves an entry is well-formed, the test proves it does the
right thing.

## 7. Open decisions

- **Id namespaces:** globally unique (current) or unique per kind. The spike hit
  three collisions in 22 entries (e.g. Mage Armor as spell and as condition).
- **Authoring format:** YAML or Pkl.
- **Priority stages:** final names; whether the model layer may use raw numbers.
- **Text:** generated labels read stiffly — how much hand-written `label` is
  acceptable.
- **Kernel size:** spell resolution, damage, payment and ability folding are
  code. The line between *mechanic* (kernel) and *content* (data) has to stay
  sharp.
- **Actions:** Das Konzept muss bei den Aktionen und events etwas erweitert und verbessert werden. 
- **Charakter Sheet Konzept:** wie das ganze dann auf dem Charakter Sheet angezeigt wird ist auch noch zu kären.
  vielleicht ebenfalls wieder über diese Gruppen?