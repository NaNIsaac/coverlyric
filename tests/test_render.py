import json
import subprocess
from pathlib import Path

import pytest

from lyricvideo import media, render
from lyricvideo.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


@pytest.fixture(scope="module")
def demo() -> Project:
    return Project.load(DEMO)


def test_default_style_keeps_the_original_geometry():
    g = render.geometry(render.Style())
    assert g.case == render.CASE
    assert g.panel == render.PANEL
    assert g.disc_x == 676  # the CD's hole sits just behind the cover


def test_style_round_trip_ignores_unknown_keys():
    style = render.Style.from_dict({"album_scale": "1.2", "bar": 1, "nope": 3})
    assert style.album_scale == 1.2 and style.bar is True
    assert render.Style.from_dict(style.to_dict()) == style


def test_moved_and_scaled_boxes():
    style = render.Style(album_x=40, panel_scale=0.5, bar=True)
    boxes = render.boxes(style)
    assert boxes["album"][0] == render.CASE[0] + 40
    p = boxes["panel"]
    assert p[2] - p[0] == (render.PANEL[2] - render.PANEL[0]) // 2
    assert "bar" in boxes and "bar" not in render.boxes(render.Style())


@pytest.mark.parametrize(
    "style",
    [
        render.Style(),
        render.Style(layout="disc", bar=True, show_title=False),
        render.Style(show_cd=False, spin=0),
        render.Style(album_x=-900, album_y=500, album_scale=1.8, panel_x=700, title_y=-300),
    ],
)
def test_frames_draw_for_any_style(demo, style):
    img = render.frame(7.0, demo.preview_lines(), demo.song(), style)
    assert img.size == (1920, 1080)


def test_intro_shows_an_empty_panel(demo):
    song, lines = demo.song(), demo.preview_lines()
    empty = render.lyric_panel(0.0, lines, render.Style())
    sung = render.lyric_panel(lines[0][0] + 0.3, lines, render.Style())
    assert empty.getchannel("A").getbbox() is None
    assert sung.getchannel("A").getbbox() is not None
    assert song.duration == pytest.approx(18.0, abs=0.05)


def test_five_second_clip(demo, tmp_path):
    out = tmp_path / "clip.mp4"
    render.render(
        out,
        demo.preview_lines(),
        demo.song(),
        render.Style(bar=True),
        workers=2,
        span=(2.0, 7.0),
        report=lambda *_: None,
    )
    probe = subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", str(out)], capture_output=True, text=True
    ).stderr
    assert "Video: h264" in probe and "1920x1080" in probe and "Audio: aac" in probe
    assert media.duration(str(out)) == pytest.approx(5.0, abs=0.1)


def test_project_file_round_trip(demo, tmp_path):
    path = tmp_path / "p.json"
    demo.save(path)
    again = Project.load(path)
    assert again.lines == demo.lines and again.style == demo.style
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == demo.title
