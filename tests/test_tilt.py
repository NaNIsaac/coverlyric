"""The album's 3D tilt: one perspective for the case, the cover and the turning CD."""

import math
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from coverlyric import render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


@pytest.fixture(scope="module")
def demo() -> Project:
    return Project.load(DEMO)


def test_no_tilt_draws_the_album_flat():
    assert render.tilt_of(render.Style()) is None
    assert render.tilt_of(render.Style(tilt=0.01)) is None


def test_tilt_is_held_to_the_limit():
    tilted = render.tilt_of(render.Style(tilt=60))
    assert tilted.cos == pytest.approx(math.cos(math.radians(render.TILT_MAX)))


@pytest.mark.parametrize("layout", ["case", "disc"])
@pytest.mark.parametrize("tilt", [-20, 20])
def test_the_warp_matches_the_projection(layout, tilt):
    t = render.tilt_of(render.Style(layout=layout, tilt=tilt))
    a, b, c, d, e, f, g, h = t.coeffs
    for x in (t.region[0], t.region[2]):
        for y in (t.region[1], t.region[3]):
            px, py = t.point(x, y)
            px, py = px - t.box[0], py - t.box[1]
            w = g * px + h * py + 1
            assert (a * px + b * py + c) / w == pytest.approx(x - t.region[0], abs=1e-6)
            assert (d * px + e * py + f) / w == pytest.approx(y - t.region[1], abs=1e-6)


def test_positive_tilt_turns_the_right_edge_away():
    t = render.tilt_of(render.Style(tilt=20))
    g = render.geometry(render.Style(tilt=20))
    x0, y0, x1, y1 = g.case

    def height(x):
        return t.point(x, y1)[1] - t.point(x, y0)[1]

    assert height(x1) < height(x0) <= y1 - y0
    flat, tilted = (
        render.boxes(render.Style())["album"],
        render.boxes(render.Style(tilt=20))["album"],
    )
    assert tilted[2] - tilted[0] < flat[2] - flat[0]


@pytest.mark.parametrize("layout", ["case", "disc"])
def test_tilt_changes_only_the_album(demo, layout):
    song, lines = demo.song(), demo.preview_lines()
    flat = np.asarray(render.frame(5.0, lines, song, render.Style(layout=layout)), int)
    tilted = np.asarray(render.frame(5.0, lines, song, render.Style(layout=layout, tilt=20)), int)
    changed = np.abs(flat - tilted).max(axis=2) > 8
    xs = np.nonzero(changed)[1]
    assert changed.sum() > 10000
    panel = render.geometry(render.Style()).panel
    assert xs.max() < panel[0]  # the lyrics stay as they were


def test_shared_turn_pictures_carry_the_tilt(demo):
    """In the render the turning CD comes from the shared pictures of one turn; tilted, they must
    match a frame drawn whole."""
    style, song, lines = render.Style(tilt=-18), demo.song(), demo.preview_lines()
    box, period = render.turn_set(style)
    memory = shared_memory.SharedMemory(create=True, size=render.turns_bytes(box, period))
    memory.buf[: len(memory.buf)] = bytes(len(memory.buf))
    p = render.Painter(lines, song, style, memory.name)
    whole = render.Painter(lines, song, style)
    try:
        assert p.turns is not None
        for n in (75, 75 + period, 300):
            t = n / render.FPS
            got = np.asarray(Image.frombytes("RGBA", (render.W, render.H), p.raw(t)), int)
            want = np.asarray(whole.image(t), int)
            assert np.abs(got - want).max() <= 1
    finally:
        p.turns.memory.close()
        memory.close()
        memory.unlink()


@pytest.mark.parametrize("layout", ["case", "disc"])
@pytest.mark.parametrize("tilt", [-40, -20, 20, 40])
def test_the_tilted_album_stays_in_its_flat_place(layout, tilt):
    """Turned, the album only shrinks: it never reaches the lyrics, and the CD keeps a turn box."""
    style = render.Style(layout=layout, tilt=tilt)
    t = render.tilt_of(style)
    x0, y0, x1, y1 = t.region
    bx0, by0, bx1, by1 = t.box
    assert x0 - 1 <= bx0 and y0 - 1 <= by0 and bx1 <= x1 + 1 and by1 <= y1 + 1
    assert render.boxes(style)["album"][2] < render.geometry(style).panel[0]
    if layout == "case":
        flat_box = render.turn_set(render.Style())[0]
        box = render.turn_set(style)[0]
        assert (box[2] - box[0]) * (box[3] - box[1]) <= (flat_box[2] - flat_box[0] + 4) * (
            flat_box[3] - flat_box[1] + 4
        )


@pytest.mark.parametrize("tilt", [-40, 30])
def test_floor_shadow_and_reflection_follow_the_tilt(demo, tilt):
    song = demo.song()
    stamp = render.stamp(song.art)
    plain = np.asarray(render.scene(song, render.Style(tilt=tilt), stamp)[0], int)
    t = render.tilt_of(render.Style(tilt=tilt))
    below = t.bounds(render.geometry(render.Style()).case)[3] + 4
    for extra in ({"reflection": True}, {"floor": 0.8}):
        bg = np.asarray(render.scene(song, render.Style(tilt=tilt, **extra), stamp)[0], int)
        assert np.abs(bg - plain)[below:].max() > 10
