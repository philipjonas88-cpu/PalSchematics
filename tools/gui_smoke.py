"""Build the whole UI, drive the widgets, and tear it down -- without mainloop.

Catches the things that only break once Tk is involved: missing widgets, bad
column ids, icons that will not load, filter/selection logic.

    python tools/gui_smoke.py
"""
from __future__ import annotations

import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palschematics import inventory  # noqa: E402
from palschematics.catalog import GROUPINGS  # noqa: E402
from palschematics.gui import App  # noqa: E402

FAILS = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILS
    if not cond:
        FAILS += 1
    print(f"  [{'ok' if cond else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    root.update()

    print("startup")
    check("catalog loaded", len(app.catalog) > 500, f"{len(app.catalog)} entries")
    groups = app.tree.get_children()
    check("tree populated", bool(groups), f"{len(groups)} groups")
    check("apply disabled with no save", str(app.btn_apply["state"]) == "disabled")

    print("\ngrouping")
    for name in GROUPINGS:
        app.var_group.set(name)
        app.refresh_tree()
        root.update()
        check(f"group by {name}", bool(app.tree.get_children()),
              f"{len(app.tree.get_children())} groups")

    print("\nfilters")
    app.var_group.set("Category")
    app.var_search.set("ancient helm")
    app.refresh_tree()
    leaves = len(app.node_code)
    check("search narrows the list", 0 < leaves < 40, f"{leaves} matches")
    app.var_search.set("")
    app.var_cat.set("Weapons")
    app.var_tier.set("4")
    app.refresh_tree()
    only = {app.catalog.by_code[c] for c in app.node_code.values()}
    check("category+tier filter is exact",
          all(s.category == "Weapons" and s.tier == 4 for s in only), f"{len(only)} shown")
    app.reset_filters()
    root.update()
    check("reset restores everything", len(app.node_code) == len(app.catalog),
          f"{len(app.node_code)} leaves")

    print("\nicons")
    with_icon = [s for s in app.catalog.entries if s.icon_path]
    loaded = sum(1 for s in with_icon[:60] if app.icon_for(s) is not None)
    check("icons load into Tk", loaded == len(with_icon[:60]),
          f"{loaded}/{len(with_icon[:60])} sampled")
    check("catalog has icons for most entries",
          len(with_icon) >= 0.9 * len(app.catalog),
          f"{len(with_icon)}/{len(app.catalog)} - run tools/build_data.py again if low")

    print("\nselection")
    app.var_cat.set("Weapons")
    app.refresh_tree()
    first_group = app.tree.get_children()[0]
    app.toggle_group(first_group)
    n = len(app.selected)
    check("group toggle selects children", n > 0, f"{n} selected")
    check("selection list mirrors it", app.lst_sel.size() == n)
    app.toggle_group(first_group)
    check("group toggle clears again", not app.selected)

    code = next(iter(app.node_code.values()))
    app.toggle(code)
    check("single toggle", app.selected == {code})
    check("checkbox glyph drawn", "☑" in app.tree.item(app.code_node[code], "text"))
    app.clear_selection()
    check("clear works", not app.selected and app.lst_sel.size() == 0)

    print("\npolicy")
    app.var_safe.set(True)
    check("safe policy defaults", app.policy() == inventory.Policy(True, 5, 0))
    check("batch scales with free slots", app.policy().budget(30) == 25,
          f"30 free -> {app.policy().budget(30)}")
    check("a nearly full bag yields nothing", app.policy().budget(4) == 0)
    app.var_safe.set(False)
    check("unsafe policy uses every slot",
          app.policy().enabled is False and app.policy().budget(30) == 30)

    root.destroy()
    print(f"\n{'FAILED' if FAILS else 'all GUI checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
