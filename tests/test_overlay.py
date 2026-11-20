"""The user's own video under the lyrics (Song.video, overlay.py)."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from coverlyric import __main__ as entry
from coverlyric import media, overlay, render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo"
LENGTH = 6.0
CORNER = (4, 4, 24, 24)  # clear of the text in every shape


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    """Six seconds whose grey says the time (brighter by 40 levels a second) with a tone."""
    out = tmp_path_factory.mktemp("video") / "clip.mp4"
    subprocess.run(
        [media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
         f"color=c=gray:s=320x180:r=10:d={LENGTH},geq=lum='min(T*40\\,255)':cb=128:cr=128",
         "-f", "lavfi", "-i", f"sine=f=330:d={LENGTH}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )  # fmt: skip
    return out


@pytest.fixture(scope="module")
def demo() -> Project:
    p = Project.load(DEMO / "demo.json")
    p.folder = DEMO
    return p


def seconds_in(img: Image.Image) -> float:
    """The clip's time a frame shows, from the grey of its corner (studio range to full range)."""
    grey = float(np.asarray(img.convert("L").crop(CORNER)).mean())
    return (grey / 1.164 + 16) / 40


@pytest.mark.parametrize(
    ("t", "keys", "at"),
    [
        (2.5, {}, 2.5),
        (7.5, {}, 1.5),
        (7.5, {"video_end": "hold"}, LENGTH),
        (3.0, {"video_offset": 2.0}, 1.0),
        (1.0, {"video_offset": 2.0}, 0.0),
    ],
)
def test_the_video_time_at_a_song_time(clip, t, keys, at):
    song = render.Song("a.wav", "c.png", "t", duration=30.0, video=str(clip))
    assert overlay.video_at(t, render.Style(**keys), song) == pytest.approx(at, abs=0.05)


def test_a_short_starts_the_video_with_its_part(clip):
    song = render.Song("a.wav", "c.png", "t", duration=30.0, video=str(clip))
    style = render.Style(shape="tall", clip_from=10.0, clip_to=20.0)
    assert overlay.video_at(11.0, style, song) == pytest.approx(1.0)
    assert overlay.video_at(11.0, render.Style(clip_from=10.0), song) == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("t", "keys", "at"),
    [
        (2.0, {}, 2.0),
        (7.0, {}, 1.0),
        (7.0, {"video_end": "hold"}, 5.9),
        (3.0, {"video_offset": 2.0}, 1.0),
    ],
)
def test_a_still_shows_that_frame_of_the_video(demo, clip, t, keys, at):
    song = replace(demo.song(), video=str(clip))
    img = render.frame(t, demo.preview_lines(), song, render.Style(**keys))
    assert img.size == (render.W, render.H)
    assert seconds_in(img) == pytest.approx(at, abs=0.15)


def frames(path: Path, size: tuple[int, int]) -> list[Image.Image]:
    run = subprocess.run(
        [media.ffmpeg(), "-v", "error", "-i", str(path), "-vf", f"scale={size[0]}:{size[1]}"]
        + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    )
    n = size[0] * size[1] * 3
    return [
        Image.frombytes("RGB", size, run.stdout[k : k + n]) for k in range(0, len(run.stdout), n)
    ]


def test_a_short_over_the_video_has_every_frame_on_time(demo, clip, tmp_path):
    song = replace(demo.song(), video=str(clip))
    style = render.Style(
        shape="tall", highlight="letter", clip_from=2.0, clip_to=6.0, video_offset=-0.5
    )
    out = tmp_path / "short.mp4"
    render.render(out, demo.preview_lines(), song, style, 2, report=lambda *a: None)
    shown = frames(out, (108, 192))
    fps = render.rate(style)
    assert len(shown) == 4 * fps
    # The part starts at 2 s of the song, half a second into the video (black is not a time).
    big = [f.resize((1080, 1920), Image.NEAREST) for f in (shown[0], shown[fps], shown[3 * fps])]
    assert [round(seconds_in(f), 1) for f in big] == pytest.approx([0.5, 1.5, 3.5], abs=0.15)


def test_a_wide_video_holds_the_last_frame_and_takes_its_sound(demo, clip, tmp_path):
    song = replace(demo.song(), video=str(clip))
    style = render.Style(video_end="hold", video_sound=True, fade=False)
    out = tmp_path / "wide.mp4"
    render.render(
        out, demo.preview_lines(), song, style, 2, span=(0.0, 8.0), report=lambda *a: None
    )
    shown = frames(out, (192, 108))
    assert len(shown) == 8 * render.FPS
    last = shown[-1].resize((render.W, render.H), Image.NEAREST)
    assert seconds_in(last) == pytest.approx(LENGTH - 0.1, abs=0.15)
    assert media.duration(str(out)) == pytest.approx(8.0, abs=0.1)
    heard = media.samples(str(out), 8000, start=1.0, length=1.0)
    assert abs(heard).max() > 0.05, "the video's tone, where the demo song is quiet at first"


def test_the_video_sound_must_be_there(demo, clip, tmp_path):
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        [media.ffmpeg(), "-v", "error", "-i", str(clip), "-an", "-c", "copy", str(silent)],
        check=True,
    )
    song = replace(demo.song(), video=str(silent))
    with pytest.raises(ValueError, match="소리가 없습니다"):
        render.render(
            tmp_path / "x.mp4", demo.preview_lines(), song, render.Style(video_sound=True), 1
        )


@pytest.mark.parametrize("shape", ["wide", "tall", "square", "portrait"])
@pytest.mark.parametrize("place", ["bottom", "middle", "low"])
def test_the_text_stays_inside_the_frame(demo, clip, shape, place):
    long = "아주 긴 줄이 두 줄로 나뉘어도 화면 안에 들어가야 합니다 정말로 길게 씁니다"
    lines = ((1.0, long), (5.0, long))
    style = render.Style(shape=shape, video_text=place, highlight="letter", video_band="paper")
    p = overlay.Painter(lines, replace(demo.song(), video=str(clip)), style)
    w, h = render.frame_size(style)
    fr = overlay.room(style)
    for part in p.blocks(0):
        x0, y0, x1, y1 = part["box"]
        floor = h - fr.bar if place == "low" else fr.bottom
        assert fr.margin <= x0 < x1 <= fr.right and fr.top <= y0 < y1 <= floor <= h, part
    layer = p.layer(2.0)
    assert layer.size == (w, h)
    assert layer.getchannel("A").crop(CORNER).getextrema() == (0, 0), "the video shows around"


def test_lines_without_letter_times_are_lit_in_turn():
    lines = ((1.0, "가 나다"), (2.0, "라"))
    assert overlay.spread(lines, 0, 10.0) == pytest.approx((1.0, 1.3, 1.6))
    assert overlay.spread(((1.0, "가나다라마"), (2.0, "")), 0, 10.0) == pytest.approx(
        (1.0, 1.2, 1.4, 1.6, 1.8)
    )


def test_without_a_video_the_render_is_as_before(demo):
    p = render.painter(demo.preview_lines(), demo.song(), render.Style())
    assert isinstance(p, render.Painter)
    assert demo.song().video == ""


def test_the_command_line_takes_and_drops_the_video(capsys, clip, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    Project(folder, title="t").save(folder / "project.json")

    def run(*pairs):
        with pytest.raises(SystemExit) as done:
            entry.main(["project", "set", str(folder), *pairs, "--json"])
        return done.value.code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    code, data = run(f"video={clip}", "video_end=hold", "video_band=paper")
    assert code == 0 and Path(data["video"]) == folder / "video.mp4"
    assert data["style"]["video_end"] == "hold" and (folder / "video.mp4").exists()
    code, data = run("video=")
    assert code == 0 and data["video"] == "" and not (folder / "video.mp4").exists()
    (folder / "notes.txt").write_text("no video", encoding="utf-8")
    code, data = run(f"video={folder / 'notes.txt'}")
    assert code == 2 and "not a video" in data["error"]


def test_the_page_takes_and_drops_the_video(clip, tmp_path):
    from coverlyric import server

    app = server.App(tmp_path)
    app.demo()
    state = app.upload("video", "story.mp4", clip.read_bytes())
    assert state["has_video"] and state["video"] == "video.mp4"
    with pytest.raises(ValueError, match="영상 파일을 읽을 수 없습니다"):
        app.upload("video", "story.mp4", b"not a video")
    assert app.state()["has_video"], "a bad file keeps the video already there"
    app.update({"video": ""})
    assert not app.state()["has_video"] and not list(tmp_path.glob("video.*"))


def test_a_looping_short_and_a_quick_look_over_the_video(demo, clip, tmp_path):
    song = replace(demo.song(), video=str(clip))
    style = render.Style(shape="tall", clip_from=2.0, clip_to=6.0, loop=True)
    out = tmp_path / "loop.mp4"
    render.render(out, demo.preview_lines(), song, style, 2, quick=True, report=lambda *a: None)
    assert len(frames(out, (54, 96))) == 4 * render.rate(style) // render.QUICK_STEP
    wide = render.Style(height=720)
    out = tmp_path / "wide720.mp4"
    render.render(out, demo.preview_lines(), song, wide, 2, span=(0.0, 3.0), report=lambda *a: None)
    probe = subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "1280x720" in probe.stderr


def test_low_lines_sit_under_the_short_safe_area_but_inside_the_frame(demo, clip):
    song = replace(demo.song(), video=str(clip))
    lines = ((1.0, "아리랑 아리랑 아라리요"), (3.0, "아리랑 고개로 넘어간다"))
    tall = render.Style(shape="tall", highlight="letter")
    bottom = overlay.Painter(lines, song, tall).blocks(0)
    low = overlay.Painter(lines, song, replace(tall, video_text="low")).blocks(0)
    assert low[0]["box"][1] > bottom[0]["box"][1]
    assert low[1]["box"][3] > overlay.room(tall).bottom, "in the fifth a Short's caption covers"
    assert low[1]["box"][3] <= render.UPRIGHT["tall"][1] - 100
    banded = replace(tall, video_text="low", bars=True)
    edge = overlay.Painter(lines, song, banded).blocks(0)[1]["box"][3]
    assert edge <= render.UPRIGHT["tall"][1] - overlay.room(banded).bar, "above the bottom band"
    wide = render.Style()
    assert overlay.Painter(lines, song, replace(wide, video_text="low")).blocks(0) == (
        overlay.Painter(lines, song, wide).blocks(0)
    ), "the wide frame has no covered part: low is bottom"
