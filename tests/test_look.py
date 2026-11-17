"""The faster render draws the same video: frames at fixed times against the render it replaced.

`old_frame` is the frame function from before the render-speed work, kept here as the look to match.
Outside the lyric panel the frames are the same pixel for pixel; the panel is now scaled down by
averaging instead of LANCZOS and must stay above 40 dB PSNR.
"""

import math
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageChops, ImageDraw

from coverlyric import render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"
TIMES = (0.0, 1.0, 2.5, 3.1, 7.0, 10.05, 14.0, 17.9)
STYLES = {
    "default": render.Style(),
    "bar": render.Style(bar=True),
    "case only": render.Style(show_cd=False),
    "still cd": render.Style(spin=0),
    "round": render.Style(layout="disc", show_title=False),
    "moved": render.Style(
        album_x=-200, album_y=120, album_scale=1.3, panel_x=-300, panel_scale=0.8
    ),
}


def old_disc(face, radius, turn):
    size = radius * 2
    disc = render.silver(radius).copy()
    disc.alpha_composite(face.rotate(-turn, Image.BICUBIC))
    d = ImageDraw.Draw(disc)
    for frac, colour, width in (
        (0.36, (225, 228, 235, 160), 2),
        (0.33, (120, 124, 132, 120), 1),
        (0.17, (235, 238, 244, 140), 2),
    ):
        r = radius * frac
        d.ellipse((radius - r, radius - r, radius + r, radius + r), outline=colour, width=width)
    rim = Image.new("RGBA", (size, size), (206, 210, 218, 255))
    rim.putalpha(render.circle_mask(size, 0.982, 1.0))
    disc.alpha_composite(rim)
    disc.putalpha(
        ImageChops.multiply(disc.getchannel("A"), render.circle_mask(size, render.HOLE, 1.0))
    )
    return disc


def old_panel(t, lines, style):
    """The panel as it was: the same drawing, scaled down with LANCZOS."""
    reduce = Image.Image.reduce
    try:
        Image.Image.reduce = lambda self, f: self.resize(
            (self.width // f, self.height // f), Image.LANCZOS
        )
        return render.panel_at.__wrapped__(render.panel_position(t, lines, style), lines, style)
    finally:
        Image.Image.reduce = reduce


def old_frame(t, lines, song, style):
    bg, disc, case = render.scene(song, style, render.stamp(song.art))
    img = bg.copy()
    g = render.geometry(style)
    if case is not None and not style.show_cd:
        img.alpha_composite(case)
    elif case is not None:
        cy = (g.case[1] + g.case[3]) // 2
        inside = (g.case[0] + g.case[2]) // 2
        x = inside + (g.disc_x - inside) * render.ease(
            (t - render.SLIDE[0]) / (render.SLIDE[1] - render.SLIDE[0])
        )
        turn = 360 * t / style.spin if style.spin > 0 else 0.0
        render.place(img, old_disc(disc, g.disc_r, turn), round(x) - g.disc_r, cy - g.disc_r)
        img.alpha_composite(case)
    render.place(img, old_panel(t, lines, style), *g.panel[:2])
    if style.bar:
        render.place(img, render.progress_bar(t, song, style), *g.bar[:2])
    return img.convert("RGB")


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = ((a.astype(np.float64) - b.astype(np.float64)) ** 2).mean()
    return math.inf if mse == 0 else 10 * math.log10(255**2 / mse)


def compare(new: Image.Image, old: Image.Image, style: render.Style) -> None:
    a, b = np.asarray(new.convert("RGB")), np.asarray(old)
    x0, y0, x1, y1 = (max(0, v) for v in render.geometry(style).panel)
    outside = np.ones(a.shape[:2], bool)
    outside[y0:y1, x0:x1] = False
    assert np.array_equal(a[outside], b[outside]), "outside the lyric panel"
    assert psnr(a[y0:y1, x0:x1], b[y0:y1, x0:x1]) > 40


@pytest.fixture(scope="module")
def demo() -> Project:
    return Project.load(DEMO)


@pytest.mark.parametrize("name", STYLES)
def test_frames_look_as_before(demo, name):
    style, song, lines = STYLES[name], demo.song(), demo.preview_lines()
    for t in TIMES:
        compare(render.frame(t, lines, song, style), old_frame(t, lines, song, style), style)


def test_shared_turn_pictures_look_as_before(demo):
    """The render path: the CD out of the case comes from the pictures of one turn the workers share,
    so a frame one turn later is copied, not drawn, and still matches."""
    style, song, lines = render.Style(), demo.song(), demo.preview_lines()
    box, period = render.turn_set(style)
    memory = shared_memory.SharedMemory(create=True, size=render.turns_bytes(box, period))
    p = render.Painter(lines, song, style, memory.name)
    try:
        assert p.turns is not None
        for n in (75, 75 + period, 300, 300 + period):
            raw = p.raw(n / render.FPS)
            new = Image.frombytes("RGBA", (render.W, render.H), raw)
            compare(new, old_frame(n / render.FPS, lines, song, style), style)
    finally:
        p.turns.memory.close()
        memory.close()
        memory.unlink()


def test_a_still_frame_is_not_drawn_again(demo):
    style, song, lines = render.Style(spin=0), demo.song(), demo.preview_lines()
    p = render.Painter(lines, song, style)
    # Between 7.0 s and 9.0 s no line starts and the CD stands still: one picture.
    first = p.raw(7.0)
    assert all(
        p.raw(n / render.FPS) is first
        for n in range(round(7 * render.FPS) + 1, round(9 * render.FPS))
    )


def test_background_tones(demo):
    song = demo.song()
    plain = np.asarray(render.backdrop(song.art, 0.0, 30, 0.0, "none"))[..., :3].astype(float)

    def mean(tone):
        return (
            np.asarray(render.backdrop(song.art, 0.0, 30, 0.0, tone))[..., :3]
            .astype(float)
            .mean((0, 1))
        )

    r, _, b = plain.mean((0, 1))
    warm, cool = mean("warm"), mean("cool")
    assert warm[0] / warm[2] > r / b > cool[0] / cool[2]
    mono = np.asarray(render.backdrop(song.art, 0.0, 30, 0.0, "mono"))[..., :3]
    assert (mono[..., 0] == mono[..., 1]).all() and (mono[..., 1] == mono[..., 2]).all()
    tint = np.array(render.cover_colour(song.art))
    cover = mean("cover")
    cos = cover @ tint / (np.linalg.norm(cover) * np.linalg.norm(tint))
    assert cos > 0.98


def test_an_unknown_tone_leaves_the_background_as_it_is(demo):
    song = demo.song()
    a = render.backdrop(song.art, 0.0, 30, 0.5, "none")
    b = render.backdrop(song.art, 0.0, 30, 0.5, "sepia")
    assert ImageChops.difference(a, b).getbbox() is None
