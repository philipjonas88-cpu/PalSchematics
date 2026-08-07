"""Regenerate PalSchematics' bundled data from paldb.cc.

Run this only when the game (or paldb) adds new schematics:

    python tools/build_data.py

It writes:
    palschematics/data/schematics.json   -- the catalog
    palschematics/data/icons/*.png       -- one icon per distinct artwork

Icons are converted to PNG at build time so the app itself needs no image
library at runtime (Tk reads PNG natively).

Data source: https://paldb.cc/en/Schematic  (community database).
"""
from __future__ import annotations

import collections
import io
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "palschematics", "data")
ICONS = os.path.join(DATA, "icons")
LIST_URL = "https://paldb.cc/en/Schematic"
# cdn.paldb.cc serves icons only to requests that look like they came from a
# page on paldb.cc -- without the Referer it answers 403 no matter how slowly
# you ask.
UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://paldb.cc/",
    "Accept": "image/webp,image/*,text/html,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- category rules -------------------------------------------------------
# paldb classifies items by the icon-atlas token in the artwork filename
# (T_itemicon_<TOKEN>_Name). We use that as the primary category so the
# grouping matches what people see on paldb, with two overrides.
TOKEN_CATEGORY = {
    "Weapon": "Weapons",
    "Armor": "Armor",
    "Accessory": "Accessories",
    "Consume": "Consumables",
    "Material": "Materials",
    "Salvage": "Materials",
    "QuestItem": "Cosmetics",
    "Blueprint": "Other",
}
HEAD_WORDS = ("Helmet", "Head", "Crown", "Hat", "Mask", "Cap", "Hood")


def fetch_bytes(url: str, tries: int = 15) -> bytes:
    """GET with backoff.

    paldb's CDN answers bursts with 403 and keeps refusing for a while, so this
    waits minutes rather than seconds before giving up.
    """
    for attempt in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception as exc:
            if attempt == tries - 1:
                raise
            wait = min(90, 10 * 2 ** attempt)
            print(f"    {type(exc).__name__} on {url.rsplit('/', 1)[-1]}, "
                  f"retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def fetch(url: str) -> str:
    return fetch_bytes(url).decode("utf-8", "replace")


def categorize(code: str, token: str | None, name: str) -> tuple[str, str]:
    """Return (category, subcategory)."""
    if code.startswith("PalSummon_"):
        return "Raid Slabs", "Slab Fragments"
    if token is None:
        return "Structures & Decor", "Base Building"
    cat = TOKEN_CATEGORY.get(token, "Other")
    if cat == "Armor":
        return cat, "Head" if any(w in code for w in HEAD_WORDS) else "Body"
    if cat == "Accessories" and "Otomo" in code:
        return cat, "Pal Gear"
    return cat, cat


def prettify(name: str, code: str) -> str:
    """paldb leaves a handful of entries without a display name -- build one."""
    if not name.startswith("Blueprint_"):
        return name
    stem = re.sub(r"^Blueprint_(Salvage_)?", "", code)
    stem = re.sub(r"_(\d+)$", r" \1", stem)
    stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem).replace("_", " ")
    return stem.strip() + " Schematic"


def family_of(name: str) -> str:
    """'Mechanical Bow Schematic 4' -> 'Mechanical Bow' (groups the tiers together)."""
    return re.sub(r"\s*Schematic(\s+\d+)?$", "", name).strip() or name


def main() -> None:
    os.makedirs(ICONS, exist_ok=True)
    print("fetching", LIST_URL)
    html = fetch(LIST_URL)
    cards = html.split('<div class="card itemPopup">')[1:]
    print(f"  {len(cards)} cards")

    records, unresolved = [], []
    for c in cards:
        m = re.search(r'<a class="itemname" data-hover="([^"]*)"\s*href="([^"]+)">([^<]+)</a>', c)
        if not m:
            continue
        hover, slug, name = m.group(1), m.group(2), m.group(3).strip()
        cm = re.match(r"\?s=Items%2F(.+)$", hover)
        rar = re.search(r'hover_text_rarity(\d+)"[^>]*>([^<]+)<', c)
        icon = re.search(r'<img loading="lazy" src="(https://cdn\.paldb\.cc/[^"]+)" class="align-self-center size128"', c)
        unlocks = re.search(r'unlocks recipe for <a class="itemname" data-hover="[^"]*"\s*href="[^"]+">([^<]+)</a>', c)
        bench = re.search(r'crafted at <a class="itemname" data-hover="[^"]*" href="[^"]+">([^<]+)</a>', c)
        tier = re.search(r"Schematic (\d+)$", name)
        rec = {
            "code": cm.group(1) if cm else None,
            "slug": slug,
            "name": name,
            "rarity": rar.group(2).strip() if rar else "Unknown",
            "rarity_idx": int(rar.group(1)) if rar else -1,
            "tier": int(tier.group(1)) if tier else 0,
            "icon_url": icon.group(1) if icon else None,
            "unlocks": unlocks.group(1).strip() if unlocks else None,
            "bench": bench.group(1).strip() if bench else None,
        }
        records.append(rec)
        if not rec["code"]:
            unresolved.append(rec)

    # paldb hides some codes behind a hashed hover url; those need the item page,
    # which carries an authoritative "Code" row.
    print(f"  resolving {len(unresolved)} codes from item pages")
    for rec in unresolved:
        page = fetch("https://paldb.cc/en/" + rec["slug"])
        m = re.search(r"<div>Code</div>\s*<div>([A-Za-z0-9_]+)</div>", page)
        rec["code"] = m.group(1) if m else None
        print(f"    {rec['slug']:46} -> {rec['code']}")
        time.sleep(0.4)

    records = [r for r in records if r["code"]]
    if len(records) != len({r["code"] for r in records}):
        dupes = [c for c, n in collections.Counter(r["code"] for r in records).items() if n > 1]
        raise SystemExit(f"duplicate codes in catalog: {dupes}")

    # --- icons: many tiers share one artwork, so fetch each distinct url once ---
    urls = sorted({r["icon_url"] for r in records if r["icon_url"]})
    print(f"  {len(urls)} distinct icons")
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("build-time dependency missing: pip install pillow")
    url_to_file, failed = {}, []
    for i, url in enumerate(urls, 1):
        fname = re.sub(r"[^A-Za-z0-9_.-]", "_", url.rsplit("/", 1)[-1]).replace(".webp", ".png")
        path = os.path.join(ICONS, fname)
        if os.path.exists(path):
            url_to_file[url] = fname
            continue
        try:
            img = Image.open(io.BytesIO(fetch_bytes(url))).convert("RGBA")
        except Exception as exc:  # noqa: BLE001
            # One unreachable icon must not cost us the whole catalog. Re-running
            # the builder later picks up whatever is still missing.
            print(f"    SKIPPED {fname}: {exc}", flush=True)
            failed.append(fname)
            continue
        img.thumbnail((48, 48), Image.LANCZOS)
        img.save(path, "PNG", optimize=True)
        url_to_file[url] = fname
        if i % 25 == 0:
            print(f"    {i}/{len(urls)}", flush=True)
        time.sleep(0.3)  # be a polite guest on someone else's bandwidth

    out = []
    for r in records:
        token = None
        if r["icon_url"]:
            m = re.search(r"T_itemicon_([A-Za-z0-9]+)_", r["icon_url"])
            token = m.group(1) if m else None
        name = prettify(r["name"], r["code"])
        cat, sub = categorize(r["code"], token, name)
        out.append({
            "code": r["code"],
            "name": name,
            "family": family_of(name),
            "category": cat,
            "subcategory": sub,
            "tier": r["tier"],
            "rarity": r["rarity"],
            "rarity_idx": r["rarity_idx"],
            "bench": r["bench"],
            "unlocks": r["unlocks"],
            "icon": url_to_file.get(r["icon_url"]),
            "slug": r["slug"],
        })
    out.sort(key=lambda r: (r["category"], r["family"], r["tier"], r["name"]))

    with open(os.path.join(DATA, "schematics.json"), "w", encoding="utf-8") as f:
        json.dump({"source": LIST_URL, "count": len(out), "schematics": out},
                  f, indent=1, ensure_ascii=False)

    print(f"\nwrote {len(out)} schematics")
    for cat, n in sorted(collections.Counter(r["category"] for r in out).items()):
        print(f"  {cat:22} {n}")
    without = sum(1 for r in out if not r["icon"])
    if without:
        print(f"\n{without} schematics have no icon yet ({len(failed)} downloads failed).")
        print("Re-run this script to fetch the rest; existing icons are kept.")


if __name__ == "__main__":
    main()
