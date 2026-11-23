"""A looping Short that ends with the song just before its clip (loop_lead, tall.lead)."""

import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from coverlyric import media, render, tall

DEMO = Path(render.__file__).parent / "demo"
LINES = ((2.0, "첫 줄"), (5.0, "앞 줄"), (8.0, "처음 줄"), (12.0, "가운데 줄"), (16.0, "뒤 줄"))
SHORT = render.Style(shape="tall", fps=30, clip_from=8.0, clip_to=14.0, loop=True)


@pytest.fixture(scope="module")
def song(tmp_path_factory) -> render.Song:
    """Twenty seconds of a rising tone, so every moment sounds different."""
    wav = tmp_path_factory.mktemp("lead") / "song.wav"
    subprocess.run(
        [media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
         "aevalsrc=0.5*sin(2*PI*(200+40*t)*t):s=44100:d=20", str(wav)],
        check=True,
    )  # fmt: skip
    return render.Song(str(wav), str(DEMO / "cover.png"), "t", duration=20.0)


def test_how_long_the_lead_is(song):
    assert tall.lead(replace(SHORT, loop_lead=2.0), song, LINES) == 2.0
    assert tall.lead(replace(SHORT, loop_lead_line=True), song, LINES) == 3.0, "5.0 to 8.0"
    assert tall.lead(replace(SHORT, loop_lead=30.0), song, LINES) == 8.0, "not before the song"
    assert tall.lead(replace(SHORT, loop_lead=0.4), song, LINES) == 0.0, "within the blend"
    assert tall.lead(replace(SHORT, loop_lead=2.0, loop=False), song, LINES) == 0.0
    assert tall.lead(replace(SHORT, loop_lead=2.0), replace(song, video="v.mp4"), LINES) == 0.0


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """How alike two stretches of sound are, 1 at best, allowing the AAC encoder's few ms of shift."""
    a, b = a[:, 0] - a.mean(), b[:, 0] - b.mean()
    best = -1.0
    for lag in range(-400, 401, 2):
        x, y = (a[lag:], b) if lag >= 0 else (a, b[-lag:])
        n = min(len(x), len(y), 1200)
        best = max(
            best, float(np.dot(x[:n], y[:n]) / np.sqrt(np.dot(x[:n], x[:n]) * np.dot(y[:n], y[:n])))
        )
    return best


def test_the_video_ends_with_the_song_before_the_clip(song, tmp_path):
    style = replace(SHORT, loop_lead_line=True)
    out = tmp_path / "lead.mp4"
    render.render(out, LINES, song, style, 2, quick=True, report=lambda *a: None)
    assert media.duration(str(out)) == pytest.approx(6.0 + 3.0 - 0.5, abs=0.05)
    # The last moments are the song just before the clip's start, and the first the clip's own
    # start, both at full strength: neither end of the file fades.
    end = media.samples(str(out), 8000, start=8.2, length=0.25)
    assert correlation(end, media.samples(song.audio, 8000, start=7.7, length=0.25)) > 0.9
    start = media.samples(str(out), 8000, start=0.0, length=0.25)
    assert correlation(start, media.samples(song.audio, 8000, start=8.0, length=0.25)) > 0.9
    assert abs(end).max() > 0.4 and abs(start[:400]).max() > 0.4


def test_without_a_lead_the_video_is_as_before(song, tmp_path):
    for lead in (0.0, 0.4):
        out = tmp_path / f"plain{lead}.mp4"
        style = replace(SHORT, loop_lead=lead)
        render.render(out, LINES, song, style, 2, quick=True, report=lambda *a: None)
        assert media.duration(str(out)) == pytest.approx(6.0, abs=0.05)
    plain = tall.Painter(LINES, song, SHORT)
    short = tall.Painter(LINES, song, replace(SHORT, loop_lead=0.4))
    for t in (8.0, 13.7, 13.95):
        assert plain.image(t).tobytes() == short.image(t).tobytes()


def test_the_last_frame_is_the_one_before_the_first(song):
    style = replace(SHORT, loop_lead=3.0)
    p = tall.Painter(LINES, song, style)
    fps = render.rate(style)
    assert p.length() == pytest.approx(8.5)
    last = 8.0 + p.length() - 1 / fps
    assert p.image(last).tobytes() == p.plain(8.0 - 1 / fps).tobytes()


def test_the_lead_shows_its_own_line_and_the_clip_s_first_next(song):
    p = tall.Painter(LINES, song, replace(SHORT, loop_lead_line=True))
    during = p.before(14.5)
    assert 5.0 <= during < 8.0
    k = tall.current(during, p.lines)
    assert p.lines[k][1] == "앞 줄" and p.lines[tall.following(k, p.lines)][1] == "처음 줄"


def test_no_line_after_the_clip_shows(song):
    p = tall.Painter(LINES, song, replace(SHORT, loop_lead=3.0))
    k = tall.current(13.4, p.lines)
    assert p.lines[k][1] == "가운데 줄" and tall.following(k, p.lines) is None
    assert tall.layout(13.4, p.lines, song, p.style)["next"] is None


def test_the_lead_replaces_the_plain_loop_blend(song):
    """Both set: the lead's ending wins; the clip's last LOOP seconds blend into the lead, not into
    the moment just before the clip."""
    p = tall.Painter(LINES, song, replace(SHORT, loop_lead=3.0))
    assert p.before(14.0 - 0.5) == pytest.approx(5.0)
    plain = tall.Painter(LINES, song, SHORT)
    assert plain.before(14.0 - 0.5) == pytest.approx(8.0 - 0.5)


@pytest.mark.parametrize("blend", [0.3, 0.9])
def test_one_blend_for_the_picture_the_sound_and_the_subtitles(song, blend):
    plain = replace(SHORT, loop_blend=blend)
    p = tall.Painter(LINES, song, plain)
    assert p.overlap == tall.loop_length(plain, song) == blend, "picture and sound (loop_graph)"
    assert p.length() == pytest.approx(6.0)
    led = replace(plain, loop_lead_line=True)
    q = tall.Painter(LINES, song, led)
    assert q.overlap == blend and q.length() == pytest.approx(6.0 + 3.0 - blend)
    assert tall.cues(led, song, list(LINES))[1] == pytest.approx(q.length())
    graph = tall.lead_graph(6.0, 3.0, tall.blend(led))
    assert f"adelay={round((6.0 - blend) * 1000)}:all=1" in graph
    assert tall.lead(replace(plain, loop_lead=blend), song, LINES) == 0.0, "within the blend"


def test_a_zero_blend_still_lets_the_lead_in(song):
    led = replace(SHORT, loop_lead_line=True, loop_blend=0.0)
    assert tall.Painter(LINES, song, led).overlap == tall.MIN_BLEND
    assert tall.loop_length(replace(SHORT, loop_blend=0.0), song) == tall.MIN_BLEND


def test_a_lead_video_is_as_long_as_its_blend_says(song, tmp_path):
    style = replace(SHORT, loop_lead_line=True, loop_blend=0.3)
    out = tmp_path / "lead.mp4"
    render.render(out, LINES, song, style, 2, quick=True, report=lambda *a: None)
    assert media.duration(str(out)) == pytest.approx(6.0 + 3.0 - 0.3, abs=0.05)


def test_a_loop_does_not_dip_at_its_repeat(song, tmp_path):
    style = replace(SHORT, loop_blend=0.3)
    out = tmp_path / "loop.mp4"
    render.render(out, LINES, song, style, 2, quick=True, report=lambda *a: None)
    start = media.samples(str(out), 8000, start=0.02, length=0.2)[:, 0]
    same = media.samples(song.audio, 8000, start=8.02, length=0.2)[:, 0]
    level = float(np.sqrt(np.mean(start**2)) / np.sqrt(np.mean(same**2)))
    assert level > 0.8, f"the start is {20 * np.log10(level):.1f} dB under the song (#72)"
