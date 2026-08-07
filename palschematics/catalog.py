"""The schematic catalog: 600-odd entries scraped from paldb, with grouping.

Regenerate the bundled data with ``python tools/build_data.py``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")
ICON_DIR = os.path.join(DATA_DIR, "icons")

# Order categories the way a player thinks about them, not alphabetically.
CATEGORY_ORDER = [
    "Weapons", "Armor", "Accessories", "Structures & Decor",
    "Consumables", "Materials", "Cosmetics", "Raid Slabs", "Other",
]
RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Unknown"]
TIER_LABEL = {0: "-", 1: "1", 2: "2", 3: "3", 4: "4"}


@dataclass(frozen=True)
class Schematic:
    code: str
    name: str
    family: str
    category: str
    subcategory: str
    tier: int
    rarity: str
    rarity_idx: int
    bench: str | None
    unlocks: str | None
    icon: str | None
    slug: str

    @property
    def icon_path(self) -> str | None:
        if not self.icon:
            return None
        p = os.path.join(ICON_DIR, self.icon)
        return p if os.path.exists(p) else None

    @property
    def paldb_url(self) -> str:
        return "https://paldb.cc/en/" + self.slug

    @property
    def tier_label(self) -> str:
        return TIER_LABEL.get(self.tier, str(self.tier))


class Catalog:
    def __init__(self, entries: list[Schematic]):
        self.entries = entries
        self.by_code = {e.code: e for e in entries}

    @classmethod
    def load(cls, path: str | None = None) -> "Catalog":
        path = path or os.path.join(DATA_DIR, "schematics.json")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"catalog missing: {path}\nRun: python tools/build_data.py")
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
        return cls([Schematic(**row) for row in blob["schematics"]])

    def __len__(self) -> int:
        return len(self.entries)

    # -- axes the UI can group / filter by ---------------------------------
    def categories(self) -> list[str]:
        seen = {e.category for e in self.entries}
        ordered = [c for c in CATEGORY_ORDER if c in seen]
        return ordered + sorted(seen - set(ordered))

    def rarities(self) -> list[str]:
        seen = {e.rarity for e in self.entries}
        return [r for r in RARITY_ORDER if r in seen]

    def tiers(self) -> list[int]:
        return sorted({e.tier for e in self.entries})

    def benches(self) -> list[str]:
        return sorted({e.bench for e in self.entries if e.bench})

    def filter(self, *, text: str = "", category: str | None = None,
               tier: int | None = None, rarity: str | None = None,
               bench: str | None = None) -> list[Schematic]:
        text = text.strip().lower()
        out = []
        for e in self.entries:
            if category and e.category != category:
                continue
            if tier is not None and e.tier != tier:
                continue
            if rarity and e.rarity != rarity:
                continue
            if bench and e.bench != bench:
                continue
            if text and text not in e.name.lower() and text not in e.code.lower() \
                    and not (e.unlocks and text in e.unlocks.lower()):
                continue
            out.append(e)
        return out

    def grouped(self, entries: list[Schematic], by: str) -> list[tuple[str, list[Schematic]]]:
        """Group entries for the tree. ``by`` is one of the GROUPINGS keys."""
        keyfn = GROUPINGS[by]
        buckets: dict[str, list[Schematic]] = {}
        for e in entries:
            buckets.setdefault(keyfn(e), []).append(e)

        def order(name: str) -> tuple:
            if by == "Category":
                idx = CATEGORY_ORDER.index(name) if name in CATEGORY_ORDER else 99
                return (idx, name)
            if by == "Rarity":
                idx = RARITY_ORDER.index(name) if name in RARITY_ORDER else 99
                return (idx, name)
            return (0, name)

        for items in buckets.values():
            items.sort(key=lambda e: (e.family.lower(), e.tier, e.name.lower()))
        return sorted(buckets.items(), key=lambda kv: order(kv[0]))


GROUPINGS = {
    "Category": lambda e: e.category,
    "Category / type": lambda e: f"{e.category} - {e.subcategory}",
    "Tier": lambda e: f"Schematic {e.tier}" if e.tier else "No tier",
    "Rarity": lambda e: e.rarity,
    "Workbench": lambda e: e.bench or "No workbench listed",
    "Item": lambda e: e.family,
}
