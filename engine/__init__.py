"""
The rule engine: builds live instances from the definition JSON and keeps their
values current (the prototype of ``packages/engine`` in STACK.md).

Deliberately imports nothing — like every package ``__init__`` here, so that a
module can be imported without pulling in the rest (that would cause import
cycles). The engine never imports anything outside this package; tools around
it (the YAML → JSON compiler, a server) depend on the engine, not the other way.
"""
