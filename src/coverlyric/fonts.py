"""Fonts the user can pick: the free fonts shipped in this package, the fonts installed on the PC, or any
font file."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

HERE = Path(__file__).parent / "fonts"

BUNDLED = {
    "noto-sans-kr": ("Noto Sans KR", "NotoSansKR-VF.ttf"),
    "nanum-gothic": ("나눔고딕 (NanumGothic Bold)", "NanumGothic-Bold.ttf"),
    "do-hyeon": ("도현 (Do Hyeon)", "DoHyeon-Regular.ttf"),
    "black-han-sans": ("검은고딕 (Black Han Sans)", "BlackHanSans-Regular.ttf"),
    "nanum-brush": ("나눔손글씨 붓 (Nanum Brush Script)", "NanumBrushScript-Regular.ttf"),
    "east-sea-dokdo": ("동해 독도 (East Sea Dokdo)", "EastSeaDokdo-Regular.ttf"),
}
DEFAULT = "noto-sans-kr"
SUFFIXES = {".ttf", ".otf", ".ttc"}


def resolve(choice: str) -> str:
    """A bundled key, or a path to a font file, as a path Pillow can open."""
    if choice in BUNDLED:
        return str(HERE / BUNDLED[choice][1])
    return choice


def font_dirs() -> list[Path]:
    if sys.platform == "win32":
        dirs = [Path(os.environ.get("WINDIR", "")) / "Fonts"]
        if local := os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return dirs
    if sys.platform == "darwin":
        return [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
        ]
    return [Path("/usr/share/fonts"), Path.home() / ".local/share/fonts", Path.home() / ".fonts"]


def can_write_korean(f: ImageFont.FreeTypeFont) -> bool:
    """True if the font draws Hangul: a font without it shows empty boxes for Korean lyrics."""
    try:
        return f.getmask("가").getbbox() is not None and f.getlength("가") > 0
    except OSError:
        return False


@lru_cache(maxsize=1)
def installed() -> tuple[dict, ...]:
    """Fonts on this PC that can write Korean, one entry per family and style."""
    seen, out = set(), []
    for folder in font_dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() not in SUFFIXES:
                continue
            try:
                f = ImageFont.truetype(str(path), 24)
            except OSError:
                continue
            family, style = f.getname()
            name = f"{family} {style}".strip() if style and style != "Regular" else family
            if name in seen or not can_write_korean(f):
                continue
            seen.add(name)
            out.append({"id": str(path), "name": name})
    return tuple(sorted(out, key=lambda e: e["name"].lower()))


def choices() -> dict:
    return {
        "bundled": [{"id": key, "name": name} for key, (name, _) in BUNDLED.items()],
        "installed": list(installed()),
    }
