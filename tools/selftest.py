"""End-to-end check of PalSchematics against a real save.

    python tools/selftest.py <path to a Level.sav>   (works on a COPY)

Never point this at a save you care about: it writes to the file it is given.
It copies nothing itself -- make the copy first.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palschematics import inventory, saveio  # noqa: E402
from palschematics.catalog import Catalog  # noqa: E402

CHECKS = 0
FAILS = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global CHECKS, FAILS
    CHECKS += 1
    if not cond:
        FAILS += 1
    print(f"  [{'ok' if cond else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")


def main() -> int:
    path = sys.argv[1]
    print(f"save: {path}\n")

    print("catalog")
    cat = Catalog.load()
    check("loads", len(cat) > 500, f"{len(cat)} schematics")
    check("no duplicate codes", len({e.code for e in cat.entries}) == len(cat))
    check("every entry has a category", all(e.category for e in cat.entries))
    missing_icons = [e.code for e in cat.entries if not e.icon_path]
    check("every entry has an icon on disk", not missing_icons,
          f"{len(missing_icons)} missing" if missing_icons else "")
    for name in ("Category", "Tier", "Rarity", "Workbench", "Item"):
        groups = cat.grouped(cat.entries, name)
        check(f"grouping by {name}", bool(groups), f"{len(groups)} groups")

    print("\nload + round-trip")
    save = saveio.Save.load(path)
    check("format recognised", save.magic in (b"PlM", b"PlZ"),
          f"{save.magic.decode()} type {save.save_type:#x}")
    save.verify_roundtrip()
    check("re-encodes byte-identically", True, f"{len(save.original_gvas):,} bytes")

    print("\nplayers")
    players = inventory.find_players(save, os.path.join(os.path.dirname(path), "Players"))
    check("found players", bool(players), ", ".join(p.name for p in players))
    with_bags = [p for p in players if p.backpack_id]
    check("players have containers", bool(with_bags), f"{len(with_bags)}/{len(players)}")
    player = with_bags[0]

    containers = inventory.containers_by_guid(save)
    bag = containers[player.backpack_id]
    free_before = len(bag.free_indices())
    print(f"  using {player.name}: {bag.slot_num - free_before}/{bag.slot_num} slots used")

    print("\nsafety policy")
    owned_now = {s.static_id for s in bag.slots()}
    picks = [e.code for e in cat.entries if e.code not in owned_now][:400]
    safe = inventory.Policy()
    plan = inventory.plan_add(bag, picks, safe)
    check("safe mode fills the free slots", len(plan.to_add) == free_before - safe.reserve_slots,
          f"{len(plan.to_add)} to add of {free_before} free")
    check("safe mode leaves slots free",
          free_before - len(plan.to_add) == safe.reserve_slots)
    check("the rest is reported, not silently dropped",
          len(plan.to_add) + len(plan.no_space) + len(plan.over_limit) == len(picks))

    loose = inventory.plan_add(bag, picks, inventory.Policy(enabled=False))
    check("unsafe mode uses every free slot", len(loose.to_add) == free_before,
          f"{len(loose.to_add)} to add")
    check("unsafe mode still bounded by capacity", len(loose.to_add) <= free_before)

    capped = inventory.plan_add(bag, picks, inventory.Policy(max_per_apply=3))
    check("an optional hard ceiling still applies", len(capped.to_add) == 3,
          f"{len(capped.over_limit)} deferred")

    dupes = inventory.plan_add(bag, [s.static_id for s in bag.slots()][:3], safe)
    check("items already held are skipped",
          not dupes.to_add and bool(dupes.already_present))

    full = inventory.Container("x", {"value": {
        "SlotNum": {"value": bag.slot_num},
        "Slots": {"value": {"values": bag.entry["value"]["Slots"]["value"]["values"]}}}})
    tight = inventory.plan_add(full, picks, inventory.Policy(reserve_slots=999))
    check("a nearly full bag is blocked", tight.blocked is not None)

    print("\nwrite + verify")
    plan = inventory.plan_add(bag, picks[:6], safe)
    placed = inventory.execute(plan)
    backup = saveio.write_save(save, backup=True,
                               expect=(bag.guid, [c for c, _ in placed]))
    check("backup written", bool(backup) and os.path.exists(backup),
          os.path.basename(backup or ""))

    reread = saveio.Save.load(path)
    rebag = inventory.containers_by_guid(reread)[player.backpack_id]
    ids = {s.static_id for s in rebag.slots()}
    check("added items present after reload", all(c in ids for c, _ in placed),
          ", ".join(c for c, _ in placed))
    check("format preserved", reread.magic == save.magic, reread.magic.decode())
    check("slot count grew by exactly the additions",
          len(rebag.slots()) == (bag.slot_num - free_before) + len(placed))
    reread.verify_roundtrip()
    check("written file itself round-trips", True)

    print("\nlocalised-change proof")
    orig = saveio.Save.load(backup)
    slots = rebag.entry["value"]["Slots"]["value"]["values"]
    codes = {c for c, _ in placed}
    rebag.entry["value"]["Slots"]["value"]["values"] = [
        s for s in slots
        if inventory.parse_slot(s["RawData"]["value"]["values"]).static_id not in codes]
    check("removing the additions reproduces the original file byte-for-byte",
          reread.gvas.write(saveio.CUSTOM) == orig.original_gvas)

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main())
