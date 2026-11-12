"""
Demo of the engine prototype: a character built from the test definitions in
tests/fixtures.py (the stand-in for the generator's JSON).

Run:  python main.py        Tests:  python -m unittest
"""
import json

from Instance import Instance
from tests.fixtures import TEST_GAME


def breakdown(prop) -> str:
    """Base value and every bound effect — what the sheet could show for one value."""
    lines = [f"{prop.path_str} = {prop.resolve()}", f"    base {prop.base_value()}"]
    for manipulation in prop.get_manipulation_trace():
        state = "" if manipulation.is_applicable() else "   (inactive)"
        lines.append(f"    {manipulation.description}{state}")
    return "\n".join(lines)


if __name__ == '__main__':
    hero = Instance.new("character", TEST_GAME)
    hero.container("attributes").get("str").prop("value").choose(12)

    axe = hero.container("equipment").add("battleaxe", "mainHand")
    axe.container("material").add("steel")
    axe.container("enchantments").add({"def": "keen", "props": {"level": "2"}})
    boost = axe.container("enchantments").add("ability-score-boost")
    boost.prop("stat").choose("dex")
    hero.container("feats").add("fleet-footed")
    hero.container("inventory").add("rope").prop("stack").write(12)

    print(breakdown(axe.prop("damage")))
    print(breakdown(hero.container("attributes").get("dex").prop("value")))
    print(breakdown(hero.container("speed").get().prop("walking")))
    print(f"carry {hero.get('carryWeight')} / {hero.get('carryLimit')}")

    print("\n-- anti-magic field: the boost (magic) is suppressed, keen is not --")
    hero.container("conditions").add("anti-magic-field")
    print(breakdown(axe.prop("damage")))
    print(breakdown(hero.container("attributes").get("dex").prop("value")))

    print("\n-- save --")
    save = hero.to_data()
    print(json.dumps(save.to_dict(), indent=2))
    print("rebuilt from the save alone:", Instance(save).to_data() == save)
    print("issues:", hero.issues() or "none")
