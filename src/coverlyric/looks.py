"""The looks on the 꾸미기 step. Each sets the same background and band keys of Style, so picking one
replaces the last one completely and leaves the album, text and places as they are."""

from __future__ import annotations

from dataclasses import replace

from .render import Style

KEYS = ("tone", "dim", "blur", "vignette", "band")
_DEFAULT = Style()

LOOKS: dict[str, dict] = {
    "기본": {key: getattr(_DEFAULT, key) for key in KEYS},
    "어둡게": {"tone": "none", "dim": 0.75, "blur": 40, "vignette": 0.5, "band": "#8a6d4e"},
    "따뜻하게": {"tone": "warm", "dim": 0.5, "blur": 30, "vignette": 0.2, "band": "#c4825a"},
    "흑백": {"tone": "mono", "dim": 0.55, "blur": 30, "vignette": 0.3, "band": "#8c8c8c"},
    "밝게": {"tone": "none", "dim": 0.25, "blur": 30, "vignette": 0.0, "band": "#d8b27e"},
    "차갑게": {"tone": "cool", "dim": 0.55, "blur": 30, "vignette": 0.2, "band": "#6d8193"},
}


def apply(style: Style, name: str) -> Style:
    if name not in LOOKS:
        raise ValueError(f"unknown look {name!r}; looks: {', '.join(LOOKS)}")
    return replace(style, **LOOKS[name])


def current(style: Style) -> str | None:
    """The look the style has now, or None after a change by hand."""
    for name, keys in LOOKS.items():
        if all(getattr(style, key) == value for key, value in keys.items()):
            return name
    return None
