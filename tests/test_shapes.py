"""Upright shapes beside 9:16 (1:1 and 4:5) and the optional bands across the top and the bottom."""

import re
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from coverlyric import cli, jobs, media, render, server, tall
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"
LONG = "아주 길고 긴 노랫말이 한 줄에 다 들어가지 않아서 여러 줄로 나뉘어야 하는 경우입니다"
SIZES = {"tall": (1080, 1920), "square": (1080, 1080), "portrait": (1080, 1350)}


def demo(shape: str = "tall", **style):
    p = Project.load(DEMO)
    return p.preview_lines(), p.song(), replace(tall.shorts(p.style, shape), **style)


def pixels(img) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.int16)


def test_a_short_without_bands_keeps_the_9_16_sizes():
    fr = tall.frame_of(demo()[2])
    assert (fr.top, fr.bottom, fr.right, fr.scale, fr.text) == (0, 1536, 960, 1.0, 1.0)


@pytest.mark.parametrize("shape", SIZES)
def test_each_shape_is_drawn_at_its_size(shape):
    lines, song, style = demo(shape)
    assert render.frame_size(style) == SIZES[shape]
    assert render.frame(8.0, lines, song, style).size == SIZES[shape]


@pytest.mark.parametrize("bars", [False, True])
@pytest.mark.parametrize("shape", SIZES)
def test_everything_fits_between_the_bands_and_the_covered_edges(shape, bars):
    lines, song, style = demo(shape, bars=bars)
    lines = ((3.0, "짧은 줄"), (6.0, LONG), (9.0, LONG))
    fr = tall.frame_of(style)
    for t in (3.1, 6.15, 7.0):
        spots = tall.layout(t, lines, song, style)
        boxes = [spots["cover"], spots["title"], spots["now"]["band"], spots["next"]["box"]]
        for x0, y0, x1, y1 in boxes:
            assert fr.margin <= x0 and x1 <= fr.right, (t, x0, x1)
            assert fr.top <= y0 and y1 <= fr.bottom, (t, y0, y1)


def test_the_text_shrinks_less_than_the_room():
    fr = tall.frame_of(demo("square")[2])
    assert fr.scale < fr.text < 1.0
    assert tall.NOW_PX * fr.text >= 70, "the sung line stays large on a 1:1 frame"


@pytest.mark.parametrize("shape", SIZES)
def test_bands_are_solid_in_their_colour_and_off_by_default(shape):
    lines, song, style = demo(shape)
    assert not style.bars
    bare = pixels(render.frame(8.0, lines, song, style))
    style = replace(style, bars=True, bars_colour="#203040", bars_height=0.1)
    got = pixels(render.frame(8.0, lines, song, style))
    bar = round(SIZES[shape][1] * 0.1)
    assert (got[:bar] == (0x20, 0x30, 0x40)).all()
    assert (got[-bar:] == (0x20, 0x30, 0x40)).all()
    assert not (bare[:bar] == (0x20, 0x30, 0x40)).all()


def test_a_band_text_is_drawn_in_a_colour_that_reads_on_the_band():
    lines, song, style = demo("square", bars=True, bars_colour="#ffffff", bars_top="아리랑 - 민요")
    got = pixels(render.frame(8.0, lines, song, style))
    bar = round(1080 * style.bars_height)
    top = got[:bar]
    assert top.min() < 80, "dark letters on a white band"
    assert (got[-bar:] == 255).all(), "no bottom text, a plain band"
    assert tall.bar_ink("#000000") == (255, 255, 255)


def test_a_top_band_text_takes_the_place_of_the_title():
    lines, song, style = demo("tall", bars=True, bars_top="아리랑 - 민요")
    x0, y0, x1, y1 = tall.layout(8.0, lines, song, style)["title"]
    with_text = pixels(render.frame(8.0, lines, song, style))[y0:y1, x0:x1]
    untitled = pixels(render.frame(8.0, lines, song, replace(style, show_title=False)))[
        y0:y1, x0:x1
    ]
    titled = pixels(render.frame(8.0, lines, song, replace(style, bars_top="")))[y0:y1, x0:x1]
    assert (with_text == untitled).all()
    assert not (titled == untitled).all()


def test_a_band_takes_at_most_a_quarter_of_the_height():
    fr = tall.frame_of(demo("portrait", bars=True, bars_height=0.9)[2])
    assert fr.bar == round(1350 * tall.BARS_MOST)


def test_a_wide_text_on_a_band_is_made_smaller_to_fit():
    lines, song, style = demo("tall", bars=True, bars_bottom=LONG * 2)
    got = pixels(render.frame(8.0, lines, song, style))
    bar = round(1920 * style.bars_height)
    ink = np.where((got[-bar:] > 128).all(axis=2))[1]
    assert ink.size and ink.min() >= tall.MARGIN - 2 and ink.max() <= 1080 - tall.SAFE_RIGHT + 2


@pytest.mark.parametrize(
    ("shape", "suffix"), [("tall", "_shorts"), ("square", "_1x1"), ("portrait", "_4x5")]
)
def test_each_shape_has_its_own_file_name(shape, suffix):
    p = Project.load(DEMO)
    p.style = tall.shorts(p.style, shape)
    assert cli.video_name(p) == f"{server.safe_name(p.title)}{suffix}.mp4"


def test_the_thumbnail_keeps_the_shape(tmp_path):
    p = Project.load(DEMO)
    p.style = replace(tall.shorts(p.style, "portrait"), clip_from=6.0, clip_to=12.0)
    out = tmp_path / "x_4x5.mp4"
    out.write_bytes(b"")
    jobs.beside(out, p, tuple(p.lines), p.song())
    assert Image.open(out.with_suffix(".png")).size == (720, 900)


def test_a_4_5_video_with_bands_renders(tmp_path):
    lines, song, style = demo("portrait", bars=True, bars_top="아리랑", clip_from=6.0, clip_to=8.0)
    out = tmp_path / "p.mp4"
    render.render(out, lines, song, style, 2, report=lambda *_: None)
    info = subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", str(out)],
        check=False,
        capture_output=True,
        text=True,
    ).stderr
    assert re.search(r"Video: h264.*1080x1350", info), info
    assert re.search(r"\b30 fps\b", info), info
