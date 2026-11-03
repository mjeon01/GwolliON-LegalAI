#!/usr/bin/env python3
"""Turn logo.png (dark on white, opaque) into transparent assets for the dark site theme."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "frontend/src/assets"
INK = (247, 249, 252)
BACKGROUND = (23, 28, 35)
# The scan-like white background is 245-255; anything darker than 70 is solid ink.
PAPER, SOLID = 235, 70
LOCKUP_HEIGHT = 192
FAVICON = 128


def ink_mask(source):
    return source.convert("L").point(lambda v: max(0, min(255, round((PAPER - v) * 255 / (PAPER - SOLID)))))


def icon_edge(mask):
    """The widest empty column run separates the shield from the wordmark."""
    box = mask.getbbox()
    columns = mask.crop(box).point(lambda v: 255 if v > 40 else 0).resize((box[2] - box[0], 1), Image.BOX).getdata()
    best, run, edge = 0, 0, None
    for x, value in enumerate(columns):
        run = run + 1 if value == 0 else 0
        if run > best:
            best, edge = run, x - run + 1
    return box[0] + edge


def tinted(mask):
    image = Image.new("RGBA", mask.size, (*INK, 0))
    image.putalpha(mask)
    return image


def main():
    mask = ink_mask(Image.open(ROOT / "resources/branding/logo.png"))
    box = mask.point(lambda v: 255 if v > 40 else 0).getbbox()
    lockup = tinted(mask.crop(box))
    width = round(lockup.width * LOCKUP_HEIGHT / lockup.height)
    lockup.resize((width, LOCKUP_HEIGHT), Image.LANCZOS).save(ASSETS / "logo.webp", quality=95, method=6)

    icon_mask = mask.crop((box[0], box[1], icon_edge(mask), box[3]))
    icon_mask = icon_mask.crop(icon_mask.point(lambda v: 255 if v > 40 else 0).getbbox())
    side = round(max(icon_mask.size) * 1.16)
    tile = Image.new("RGBA", (side, side), (*BACKGROUND, 255))
    tile.alpha_composite(tinted(icon_mask), ((side - icon_mask.width) // 2, (side - icon_mask.height) // 2))
    tile.resize((FAVICON, FAVICON), Image.LANCZOS).save(ASSETS / "favicon.png")
    print(f"logo.webp {width}x{LOCKUP_HEIGHT}, favicon.png {FAVICON}x{FAVICON}")


if __name__ == "__main__":
    main()
