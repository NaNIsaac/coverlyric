"""Shorts: a 1080x1920 video of part of the song, made for a phone (COVER-SHORTS)."""

import re
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from coverlyric import cli, jobs, media, render, server, tall
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


def demo() -> tuple[tuple[tuple[float, str], ...], render.Song, render.Style]:
    p = Project.load(DEMO)
    return p.preview_lines(), p.song(), tall.shorts(p.style)


def pixels(img) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.int16)


def test_the_wide_video_stays_the_default():
    assert render.Style().shape == "wide"
    assert render.frame_size(render.Style()) == (1920, 1080)


def test_the_shorts_preset_is_tall_30_fps_with_an_outline_and_no_title_card():
    style = tall.shorts(replace(render.Style(), intro=3.0, fps=24, band="#123456"))
    assert (style.shape, style.fps, style.lyric_edge, style.intro) == ("tall", 30, "outline", 0.0)
    assert style.band == "#123456", "the rest of the look is kept"
    assert render.frame_size(style) == (1080, 1920)
    assert tall.wide(style).shape == "wide"


def test_a_frame_is_tall_and_leaves_the_bottom_and_right_edge_to_the_phone():
    lines, song, style = demo()
    img = render.frame(8.0, lines, song, style)
    assert img.size == (1080, 1920)
    bare = pixels(tall.backdrop(song, style))
    got = pixels(img)
    bottom = round(1920 * (1 - tall.SAFE_BOTTOM))
    assert np.abs(got[bottom:] - bare[bottom:]).max() <= 1, "nothing in the bottom fifth"
    assert np.abs(got[:, -tall.SAFE_RIGHT :] - bare[:, -tall.SAFE_RIGHT :]).max() <= 1, (
        "nothing at the right edge"
    )


def test_the_cover_sits_in_the_top_third_under_the_title():
    lines, song, style = demo()
    spots = tall.layout(8.0, lines, song, style)
    x0, y0, x1, y1 = spots["cover"]
    assert y1 <= 1920 / 3 and x1 - x0 == y1 - y0 >= 440
    assert spots["title"][3] <= y0, "the title and the artist are above the cover"
    got = pixels(render.frame(8.0, lines, song, style))
    bare = pixels(tall.backdrop(song, style))
    assert (
        np.abs(
            got[y0 + 20 : y1 - 20, x0 + 20 : x1 - 20] - bare[y0 + 20 : y1 - 20, x0 + 20 : x1 - 20]
        ).mean()
        > 20
    )


def test_the_current_line_is_big_in_the_middle_and_the_next_small_under_it():
    lines, song, style = demo()
    spots = tall.layout(8.0, lines, song, style)  # line 2 began at 6.5
    now, nxt = spots["now"], spots["next"]
    assert now["text"] == lines[1][1] and nxt["text"] == lines[2][1]
    assert now["size"] >= 1.5 * nxt["size"] and now["size"] >= 70
    middle = (now["box"][1] + now["box"][3]) / 2
    assert 1920 * 0.42 <= middle <= 1920 * 0.62
    assert nxt["box"][1] >= now["box"][3]
    assert now["band"], "the current line is on a band"
    # The band is drawn in the band colour behind the line.
    img = pixels(render.frame(8.0, lines, song, style))
    bx0, by0, _, by1 = now["band"]
    edge = img[(by0 + by1) // 2, bx0 + 6]
    band = np.array(render.hex_rgb(style.band))
    bare = pixels(tall.backdrop(song, style))[(by0 + by1) // 2, bx0 + 6]
    assert np.abs(edge - band).sum() < np.abs(bare - band).sum()


def test_a_long_line_wraps_inside_the_safe_width():
    _, song, style = demo()
    long = (
        (0.0, "아주 긴 가사 한 줄이 휴대폰 화면 폭을 넘어서 여러 줄로 나뉘어야 합니다"),
        (9.0, "다음"),
    )
    spots = tall.layout(2.0, long, song, style)
    x0, _, x1, _ = spots["now"]["box"]
    assert len(spots["now"]["rows"]) >= 2
    assert x0 >= tall.MARGIN and x1 <= 1080 - tall.SAFE_RIGHT


def test_before_the_first_line_only_the_first_line_waits_small():
    lines, song, style = demo()
    spots = tall.layout(1.0, lines, song, style)
    assert spots["now"] is None and spots["next"]["text"] == lines[0][1]


def test_shorts_fade_only_the_sound_by_a_third_of_a_second():
    style = tall.shorts(render.Style())
    vf, af = render.fades(style, 18.0, 6.0, 10.0)
    assert vf == []
    assert af == ["afade=t=in:st=0:d=0.3", "afade=t=out:st=3.700:d=0.3"]


def test_the_clip_range_is_part_of_the_style_and_snaps_into_the_song():
    _, song, style = demo()
    assert tall.span(replace(style, clip_from=6.0, clip_to=10.0), song) == (6.0, 10.0)
    assert tall.span(replace(style, clip_from=6.0, clip_to=0.0), song) == (6.0, song.duration)
    assert tall.span(replace(style, clip_from=-2.0, clip_to=99.0), song) == (0.0, song.duration)


def test_the_loop_end_blends_into_the_moments_before_the_start():
    lines, song, style = demo()
    style = replace(style, clip_from=6.0, clip_to=10.0, loop=True)
    first = pixels(render.frame(6.0, lines, song, style))
    last = pixels(render.frame(10.0 - 1e-3, lines, song, style))
    assert np.abs(last - first).mean() < 4, "the last frame is the first one again"
    plain = pixels(render.frame(10.0 - 1e-3, lines, song, replace(style, loop=False)))
    assert np.abs(plain - first).mean() > np.abs(last - first).mean()


def test_the_loop_sound_graph_crossfades_the_end_into_the_start():
    graph = tall.loop_graph(4.0, 0.5)
    assert "afade=t=out:st=3.500:d=0.500" in graph and "afade=t=in:st=0:d=0.500" in graph
    assert "adelay=3500:all=1" in graph and "amix=inputs=2:duration=first:normalize=0" in graph


def probe(path: Path) -> str:
    return subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        text=True,
    ).stderr


@pytest.mark.parametrize("loop", [False, True])
def test_a_shorts_video_is_1080x1920_h264_30_fps_of_the_clip(tmp_path, loop):
    lines, song, style = demo()
    style = replace(style, clip_from=6.0, clip_to=9.0, loop=loop)
    out = tmp_path / "s.mp4"
    render.render(out, lines, song, style, 2, report=lambda *_: None)
    info = probe(out)
    assert re.search(r"Video: h264.*1080x1920", info), info
    assert re.search(r"\b30 fps\b", info), info
    seconds = re.search(r"Duration: 00:00:(\d+\.\d+)", info)[1]
    assert abs(float(seconds) - 3.0) < 0.1


def test_the_shorts_file_is_named_title_shorts(tmp_path):
    p = Project.load(DEMO)
    p.style = tall.shorts(p.style)
    assert cli.video_name(p) == f"{server.safe_name(p.title)}_shorts.mp4"


def test_the_files_beside_a_shorts_video_are_on_the_clip_clock(tmp_path):
    p = Project.load(DEMO)
    p.style = replace(tall.shorts(p.style), clip_from=6.0, clip_to=12.0)
    out = tmp_path / "x_shorts.mp4"
    out.write_bytes(b"")
    song = p.song()
    jobs.beside(out, p, tuple(p.lines), song)
    from PIL import Image

    assert Image.open(out.with_suffix(".png")).size == (720, 1280)
    srt = out.with_suffix(".srt").read_text(encoding="utf-8")
    assert "00:00:00,500 -->" in srt, srt  # line 2 at 6.5 is 0.5 s into the clip
    assert lines_in(srt) == ["두 번째 줄은 조금 길어요", "세 번째 줄"]


def lines_in(srt: str) -> list[str]:
    return [b.split("\n")[2] for b in srt.strip().split("\n\n")]
