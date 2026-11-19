"""Builds installer/icon.ico (16 to 256 px) for the installer and the shortcuts.

With a PNG it uses that picture, cut to a square; without one it draws the placeholder disc that
stands in until the logo is chosen. `uv run python tools/make_icon.py [logo.png]`
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parents[1] / "installer" / "icon.ico"
SIZES = [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]
SIDE = 1024


def placeholder() -> Image.Image:
    """A disc in the page's accent colour on a dark rounded square."""
    img = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, SIDE - 1, SIDE - 1), radius=SIDE // 5, fill=(30, 32, 37, 255))
    m = SIDE // 8
    d.ellipse((m, m, SIDE - m, SIDE - m), fill=(126, 156, 186, 255))
    for r, colour in ((SIDE * 0.17, (30, 32, 37, 255)), (SIDE * 0.06, (126, 156, 186, 255))):
        c = SIDE / 2
        d.ellipse((c - r, c - r, c + r, c + r), fill=colour)
    return img


def square(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    return img.crop((left, top, left + side, top + side)).resize((SIDE, SIDE), Image.LANCZOS)


def main(argv: list[str]) -> None:
    img = square(Path(argv[0])) if argv else placeholder()
    OUT.parent.mkdir(exist_ok=True)
    img.save(OUT, sizes=SIZES)
    print(OUT)


if __name__ == "__main__":
    main(sys.argv[1:])
