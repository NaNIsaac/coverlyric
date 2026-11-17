"""Lyric colour and the optional outline or shadow that keeps the lyrics readable on a light cover."""

from pathlib import Path

import numpy as np
import pytest

from coverlyric import render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


@pytest.fixture(scope="module")
def lines() -> tuple[tuple[float, str], ...]:
    return Project.load(DEMO).preview_lines()


def panel(lines, **style) -> np.ndarray:
    return np.asarray(render.lyric_panel(lines[1][0] + 0.3, lines, render.Style(**style)))


def ink(px: np.ndarray, rgb: tuple[int, int, int], tol: int = 40, opaque: int = 200) -> int:
    """Pixels close to ``rgb`` that are mostly opaque."""
    near = np.abs(px[..., :3].astype(int) - rgb).max(axis=2) <= tol
    return int((near & (px[..., 3] > opaque)).sum())


def test_default_is_plain_white():
    s = render.Style()
    assert (s.lyric_colour, s.lyric_edge) == ("#ffffff", "none")


def test_style_round_trip():
    s = render.Style.from_dict(
        {"lyric_colour": "#202020", "lyric_edge": "outline", "lyric_edge_colour": "#ffee00"}
    )
    assert render.Style.from_dict(s.to_dict()) == s


def test_colour_paints_the_lyrics(lines):
    white = panel(lines)
    red = panel(lines, lyric_colour="#e02020")
    assert ink(white, (255, 255, 255)) > 500
    assert ink(red, (224, 32, 32)) > 500
    assert ink(red, (255, 255, 255)) == 0


@pytest.mark.parametrize("edge", ["outline", "shadow"])
def test_edge_draws_dark_pixels_only_when_asked(lines, edge):
    plain = panel(lines)
    edged = panel(lines, lyric_edge=edge)
    # The band and plain lyrics hold no near-black pixel, an outline or shadow holds many.
    assert ink(plain, (0, 0, 0), 60, 120) == 0
    assert ink(edged, (0, 0, 0), 60, 120) > 300  # the shadow is drawn at 70 %
    assert ink(edged, (255, 255, 255)) > 200


def test_edge_colour_is_used(lines):
    edged = panel(lines, lyric_colour="#101010", lyric_edge="outline", lyric_edge_colour="#ffffff")
    assert ink(edged, (255, 255, 255)) > 300
    assert ink(edged, (16, 16, 16)) > 300


def test_outline_grows_the_text(lines):
    plain = panel(lines)[..., 3] > 0
    edged = panel(lines, lyric_edge="outline")[..., 3] > 0
    assert edged.sum() > plain.sum()


def title_strip(**style) -> np.ndarray:
    s = render.Style(**style)
    _, top, scale = render.geometry(s).title
    bg = render.background(Project.load(DEMO).song(), s)
    return np.asarray(bg.crop((0, top, render.W, top + round(render.TITLE_BOX * scale))))


def test_title_and_artist_follow_the_lyric_colour_and_edge():
    assert ink(title_strip(), (255, 255, 255)) > 300
    red = title_strip(lyric_colour="#e02020")
    assert ink(red, (224, 32, 32)) > 300
    assert ink(red, (255, 255, 255)) == 0
    assert (
        ink(title_strip(lyric_edge="outline"), (0, 0, 0), 60)
        > ink(title_strip(), (0, 0, 0), 60) + 300
    )
