"""A long intro is not a still frame: the title and the artist show in the lyric panel and go before
the lines come in, and a light drifts over the frame."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from coverlyric import render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"
LINES = ((16.0, "두 발은 멀쩡한데"), (19.0, "엔진이 과열됐어"), (22.0, ""), (40.0, "저기까지만"))


@pytest.fixture(scope="module")
def song():
    return Project.load(DEMO).song()


def test_the_title_steps_stretch_with_the_intro():
    assert render.opening_steps(LINES, render.Style()) == render.OPENING
    assert render.opening_steps(LINES, render.Style(opening=False)) is None
    assert render.opening_steps(LINES, render.Style(intro=3.0)) is None  # the card fills it instead
    assert render.opening_steps(((7.0, "a"),), render.Style()) is None
    assert render.opening_steps(((32.0, "a"),), render.Style())[0] == (10.0, 13.0)


def test_the_title_comes_in_holds_and_goes_before_the_lines():
    steps = render.opening_steps(LINES, render.Style())
    assert render.opening_at(4.0, steps) == 0.0
    assert 0 < render.opening_at(5.75, steps) < 1
    assert render.opening_at(8.0, steps) == 1.0
    assert render.opening_at(10.6, steps) == 0.0
    assert render.opening_at(8.0, None) == 0.0


def test_the_panel_shows_the_title_and_otherwise_what_it_showed_before(song):
    style = render.Style(drift=False)
    painter = render.Painter(LINES, song, style)
    plain = render.Painter(LINES, song, replace(style, opening=False))
    g = render.geometry(style)

    def panel(p, t):
        return np.asarray(p.image(t).convert("RGB").crop(g.panel), dtype=int)

    assert np.abs(panel(painter, 8.0) - panel(plain, 8.0)).max() > 100
    for t in (2.0, 11.0, 15.5, 17.0, 30.0):
        assert np.array_equal(panel(painter, t), panel(plain, t))


def test_the_light_drifts_slowly_and_softly(song):
    style = render.Style(spin=0)  # only the light changes from frame to frame
    still = render.Painter(LINES, song, replace(style, drift=False))
    moving = render.Painter(LINES, song, style)
    a = np.asarray(moving.image(30.0), dtype=int)
    b = np.asarray(moving.image(30.0 + 1 / 24), dtype=int)
    plain = np.asarray(still.image(30.0), dtype=int)
    assert 0 < np.abs(a - plain).max() <= render.LIGHT_PEAK
    # One frame later it has moved by at most a pixel: no step can be seen.
    assert np.abs(a - b).max() <= 1
    centres = {render.light_at(t) for t in range(0, 180, 10)}
    assert len(centres) > 10


def test_the_new_keys_load_from_a_project():
    style = render.Style.from_dict({"opening": 0, "drift": True})
    assert (style.opening, style.drift) == (False, True)
