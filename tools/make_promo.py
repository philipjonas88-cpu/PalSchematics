"""Build the 1920x1080 promo images used on mod pages.

    python tools/make_promo.py

Reads docs/screenshot*.png (see tools/winshot in the repo history for how those
are captured) and writes docs/promo-*.png. Pure Pillow, no screen capture.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
W, H = 1920, 1080

BG = (18, 22, 30)
PANEL = (26, 31, 42)
TEXT = (238, 241, 246)
MUTED = (150, 160, 176)
ACCENT = (86, 166, 255)
GOLD = (240, 190, 90)

FONTS = r"C:\Windows\Fonts"


def font(name: str, size: int):
    for candidate in (name, "segoeui.ttf"):
        path = os.path.join(FONTS, candidate)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


BOLD = lambda s: font("seguibl.ttf", s)      # noqa: E731
SEMI = lambda s: font("seguisb.ttf", s)      # noqa: E731
REG = lambda s: font("segoeui.ttf", s)       # noqa: E731


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(H):                        # soft vertical gradient
        k = y / H
        d.line([(0, y), (W, y)],
               fill=(int(BG[0] + 14 * k), int(BG[1] + 16 * k), int(BG[2] + 22 * k)))
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    return img, d


def paste_shot(img: Image.Image, shot_path: str, box: tuple[int, int, int, int]) -> None:
    """Fit a screenshot inside box, centred, with a thin border."""
    x, y, bw, bh = box
    shot = Image.open(shot_path).convert("RGB")
    scale = min(bw / shot.width, bh / shot.height)
    shot = shot.resize((int(shot.width * scale), int(shot.height * scale)), Image.LANCZOS)
    px, py = x + (bw - shot.width) // 2, y + (bh - shot.height) // 2
    ImageDraw.Draw(img).rectangle(
        [px - 2, py - 2, px + shot.width + 1, py + shot.height + 1], outline=(70, 82, 102))
    img.paste(shot, (px, py))


def icon(size: int):
    p = os.path.join(ROOT, "palschematics", "data", "app.png")
    return Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS) \
        if os.path.exists(p) else None


def main_card() -> None:
    img, d = canvas()
    ic = icon(112)
    if ic:
        img.paste(ic, (120, 96), ic)
    d.text((260, 96), "PalSchematics", font=BOLD(76), fill=TEXT)
    d.text((264, 186), "Add any schematic to your Palworld save", font=REG(34), fill=ACCENT)

    bullets = [
        ("602 schematics", "every one paldb lists, with its own icon"),
        ("Sorted your way", "category, tier, rarity, workbench or item"),
        ("Servers too", "picks any player in the world by name"),
        ("Safe by default", "backups, verified writes, inventory limits"),
    ]
    y = 292
    for title, sub in bullets:
        d.rectangle([120, y + 6, 126, y + 46], fill=GOLD)
        d.text((150, y), title, font=SEMI(32), fill=TEXT)
        d.text((150, y + 42), sub, font=REG(24), fill=MUTED)
        y += 104

    paste_shot(img, os.path.join(DOCS, "screenshot.png"), (700, 250, 1120, 700))
    d.text((120, H - 96), "github.com/philipjonas88-cpu/PalSchematics",
           font=REG(26), fill=MUTED)
    d.text((120, H - 58), "Fan-made tool - not affiliated with Pocketpair",
           font=REG(22), fill=(110, 120, 136))
    img.save(os.path.join(DOCS, "promo-main.png"))
    print("docs/promo-main.png")


def shot_card(src: str, out: str, title: str, sub: str) -> None:
    img, d = canvas()
    d.text((120, 70), title, font=BOLD(52), fill=TEXT)
    d.text((122, 140), sub, font=REG(30), fill=ACCENT)
    paste_shot(img, os.path.join(DOCS, src), (120, 220, W - 240, H - 320))
    d.text((120, H - 78), "PalSchematics - github.com/philipjonas88-cpu/PalSchematics",
           font=REG(24), fill=MUTED)
    img.save(os.path.join(DOCS, out))
    print("docs/" + out)


if __name__ == "__main__":
    main_card()
    shot_card("screenshot.png", "promo-browse.png",
              "Every schematic, grouped and searchable",
              "Weapons, armor, accessories, structures - by tier, rarity or workbench")
    shot_card("screenshot-search.png", "promo-search.png",
              "Find what you want in seconds",
              "Search by name or by the item it unlocks; all four tiers sit together")
