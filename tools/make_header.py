"""Render the mod-page header banner.

    python tools/make_header.py

Writes into docs/:
    header-1300x372.png   mod page header (the size Nexus recommends)
    header-1920x480.png   the same design, wider
    social-1280x640.png   GitHub social preview

The look is a blueprint sheet: grid paper, drafting frame, and the game's own
schematic icons drawn into it like parts on a plan.
"""
from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
ICONS = os.path.join(ROOT, "palschematics", "data", "icons")
FONTS = r"C:\Windows\Fonts"

PAPER = (10, 30, 56)          # blueprint navy
PAPER_LOW = (7, 22, 42)
GRID = (44, 96, 148)
GRID_FINE = (26, 62, 100)
INK = (226, 240, 252)
CYAN = (104, 200, 255)
GOLD = (245, 198, 106)


def font(name: str, size: int):
    path = os.path.join(FONTS, name)
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.truetype(os.path.join(FONTS, "segoeui.ttf"), size)


def blueprint(w: int, h: int) -> Image.Image:
    """Grid paper with a soft radial lift in the middle."""
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)
    cx, cy = w * 0.42, h * 0.5
    maxd = math.hypot(max(cx, w - cx), max(cy, h - cy))
    for y in range(h):
        for band in (0,):
            _ = band
        k = 1 - abs(y - cy) / (h * 0.9)
        c = tuple(int(PAPER_LOW[i] + (PAPER[i] - PAPER_LOW[i]) * max(0.0, k)) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)

    for x in range(0, w, 20):                      # fine grid
        d.line([(x, 0), (x, h)], fill=GRID_FINE)
    for y in range(0, h, 20):
        d.line([(0, y), (w, y)], fill=GRID_FINE)
    for x in range(0, w, 100):                     # major grid
        d.line([(x, 0), (x, h)], fill=GRID)
    for y in range(0, h, 100):
        d.line([(0, y), (w, y)], fill=GRID)

    # vignette so the edges fall away
    vig = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-w * 0.15, -h * 0.6, w * 1.15, h * 1.6], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(w // 12))
    img = Image.composite(img, Image.new("RGB", (w, h), PAPER_LOW), vig)
    _ = maxd
    return img


def scatter_icons(img: Image.Image, seed: int = 7, cols: int = 5, rows: int = 3,
                  left: float = 0.46, keep_clear=None) -> None:
    """Lay real schematic icons out on a loose grid, like parts on a plan.

    Grid placement rather than random scatter: the icons have wildly different
    silhouettes, and overlapping them just reads as clutter.
    """
    if not os.path.isdir(ICONS):
        return
    names = sorted(os.listdir(ICONS))
    weapons = [n for n in names if "_Weapon_" in n]
    others = [n for n in names if "_Armor_" in n or "_Accessory_" in n]
    rng = random.Random(seed)
    rng.shuffle(weapons)
    rng.shuffle(others)
    # weapons read best at a glance, so lead with them
    picks = (weapons + others)[:cols * rows]

    w, h = img.size
    x0 = int(w * left)
    cell_w = (w - x0 - 30) / cols
    cell_h = h / rows
    d = ImageDraw.Draw(img, "RGBA")

    for idx, name in enumerate(picks):
        cx = x0 + cell_w * (idx % cols) + cell_w / 2
        cy = cell_h * (idx // cols) + cell_h / 2
        cx += rng.uniform(-cell_w * 0.12, cell_w * 0.12)
        cy += rng.uniform(-cell_h * 0.10, cell_h * 0.10)
        size = int(min(cell_w, cell_h) * rng.uniform(0.46, 0.60))
        x, y = int(cx - size / 2), int(cy - size / 2)
        if keep_clear and not (x + size < keep_clear[0] or x > keep_clear[2]
                               or y + size < keep_clear[1] or y > keep_clear[3]):
            continue
        try:
            ic = Image.open(os.path.join(ICONS, name)).convert("RGBA")
        except Exception:  # noqa: BLE001
            continue
        ic = ic.resize((size, size), Image.LANCZOS)
        alpha = rng.randint(120, 205)
        faded = ic.copy()
        faded.putalpha(ic.getchannel("A").point(lambda a, m=alpha: a * m // 255))
        pad = max(8, size // 6)
        d.rectangle([x - pad, y - pad, x + size + pad, y + size + pad],
                    outline=(GRID[0], GRID[1], GRID[2], 110))
        d.line([(x - pad, y - pad), (x - pad + 10, y - pad)], fill=(*CYAN, 130))
        d.line([(x - pad, y - pad), (x - pad, y - pad + 10)], fill=(*CYAN, 130))
        img.paste(faded, (x, y), faded)


def frame(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Drafting border with corner ticks."""
    m = 18
    d.rectangle([m, m, w - m, h - m], outline=(GRID[0], GRID[1], GRID[2]))
    d.rectangle([m + 6, m + 6, w - m - 6, h - m - 6], outline=GRID_FINE)
    t = 34
    for (cx, cy, dx, dy) in ((m, m, 1, 1), (w - m, m, -1, 1),
                             (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
        d.line([(cx, cy), (cx + dx * t, cy)], fill=CYAN, width=3)
        d.line([(cx, cy), (cx, cy + dy * t)], fill=CYAN, width=3)


def glow_text(img: Image.Image, xy, text: str, fnt, fill, glow=CYAN, radius=14) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=fnt, fill=glow + (150,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius)))
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill)


def header(w: int, h: int, out: str, compact: bool = False) -> None:
    img = blueprint(w, h).convert("RGBA")
    tb_w, tb_h = 300, 62
    title_block = (w - 24 - tb_w - 14, h - 24 - tb_h - 14, w, h)
    scatter_icons(img, cols=5, rows=3, left=0.44, keep_clear=title_block)

    # keep the left side readable under the scattered parts
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(int(w * 0.62)):
        a = int(210 * (1 - x / (w * 0.62)) ** 1.4)
        sd.line([(x, 0), (x, h)], fill=(PAPER_LOW[0], PAPER_LOW[1], PAPER_LOW[2], a))
    img.alpha_composite(shade)

    d = ImageDraw.Draw(img)
    frame(d, w, h)

    title_size = 96 if not compact else 74
    x = 78
    y = h // 2 - (86 if not compact else 62)
    glow_text(img, (x, y), "PalSchematics", font("seguibl.ttf", title_size), INK)
    ty = y + title_size + 6
    d.text((x + 4, ty), "ADD ANY SCHEMATIC TO YOUR PALWORLD SAVE",
           font=font("seguisb.ttf", 27 if not compact else 22), fill=CYAN)

    if not compact:
        d.line([(x + 4, ty + 52), (x + 470, ty + 52)], fill=(GRID[0], GRID[1], GRID[2]))
        d.text((x + 4, ty + 66),
               "602 schematics  ·  single player & dedicated servers  ·  backups and verified writes",
               font=font("segoeui.ttf", 22), fill=(168, 190, 214))

    # title block, bottom right, like a real drawing sheet
    tx, ty2 = w - 18 - 6 - tb_w, h - 18 - 6 - tb_h
    d.rectangle([tx, ty2, tx + tb_w, ty2 + tb_h], fill=(6, 20, 38), outline=GRID)
    d.line([(tx, ty2 + 26), (tx + tb_w, ty2 + 26)], fill=GRID)
    d.line([(tx + 196, ty2), (tx + 196, ty2 + tb_h)], fill=GRID)
    d.text((tx + 12, ty2 + 5), "PALSCHEMATICS", font=font("seguisb.ttf", 17), fill=INK)
    d.text((tx + 206, ty2 + 5), "REV 1.0", font=font("seguisb.ttf", 17), fill=GOLD)
    d.text((tx + 12, ty2 + 33), "PHILIP JONAS", font=font("segoeui.ttf", 15), fill=(150, 176, 202))
    d.text((tx + 206, ty2 + 33), "MIT", font=font("segoeui.ttf", 15), fill=(150, 176, 202))

    img.convert("RGB").save(os.path.join(DOCS, out))
    print("docs/" + out, f"{w}x{h}")


def social(out: str = "social-1280x640.png") -> None:
    w, h = 1280, 640
    img = blueprint(w, h).convert("RGBA")
    scatter_icons(img, seed=11, cols=4, rows=3, left=0.06)
    shade = Image.new("RGBA", (w, h), (PAPER_LOW[0], PAPER_LOW[1], PAPER_LOW[2], 150))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    frame(d, w, h)
    ic_path = os.path.join(ROOT, "palschematics", "data", "app.png")
    if os.path.exists(ic_path):
        ic = Image.open(ic_path).convert("RGBA").resize((150, 150), Image.LANCZOS)
        img.paste(ic, ((w - 150) // 2, 128), ic)
    t = font("seguibl.ttf", 84)
    tw = d.textlength("PalSchematics", font=t)
    glow_text(img, ((w - tw) / 2, 310), "PalSchematics", t, INK)
    s = font("seguisb.ttf", 28)
    sw = d.textlength("ADD ANY SCHEMATIC TO YOUR PALWORLD SAVE", font=s)
    d.text(((w - sw) / 2, 410), "ADD ANY SCHEMATIC TO YOUR PALWORLD SAVE", font=s, fill=CYAN)
    c = font("segoeui.ttf", 23)
    cw = d.textlength("602 schematics · single player & dedicated servers", font=c)
    d.text(((w - cw) / 2, 458), "602 schematics · single player & dedicated servers",
           font=c, fill=(168, 190, 214))
    img.convert("RGB").save(os.path.join(DOCS, out))
    print("docs/" + out, f"{w}x{h}")


if __name__ == "__main__":
    os.makedirs(DOCS, exist_ok=True)
    # 1300x372 is what Nexus recommends for a mod page header.
    header(1300, 372, "header-1300x372.png", compact=True)
    header(1920, 480, "header-1920x480.png")
    social()
