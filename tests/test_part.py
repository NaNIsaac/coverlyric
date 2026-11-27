"""A Short's part picked by hand: ends moved by a beat or a bar, and the line under the wave."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from coverlyric import media, part, sections, server
from coverlyric.sections import Grid

BEATS = tuple(0.5 * k for k in range(240))  # 120 bpm, a bar every 2 s
LINES = ((4.0, "first line"), (8.0, "second line"), (None, "untimed"), (12.0, ""), (16.0, "third"))


def test_a_beat_and_a_bar_follow_the_grid():
    assert part.step(10.0, 1, "beat", 120.0, BEATS) == 10.5
    assert part.step(10.0, -1, "bar", 120.0, BEATS) == 8.0
    assert part.step(10.0, 2, "bar", 120.0, BEATS) == 14.0


def test_an_end_off_the_grid_lands_on_the_next_line_of_it_first():
    assert part.step(10.2, 1, "beat", 120.0, BEATS) == 10.5
    assert part.step(10.2, -1, "beat", 120.0, BEATS) == 10.0
    assert part.step(10.2, 1, "bar", 120.0, BEATS) == 12.0
    assert part.step(10.2, -1, "bar", 120.0, BEATS) == 8.5


def test_an_end_stays_within_the_song():
    assert part.step(0.5, -1, "bar", 120.0, BEATS) == 0.0
    assert part.step(119.0, 1, "bar", 120.0, BEATS) == 120.0


def test_without_a_grid_a_beat_is_a_tenth_and_a_bar_the_next_line():
    starts = [4.0, 8.0, 16.0]
    assert part.step(10.0, 1, "beat", 60.0, None, starts) == 10.1
    assert part.step(10.0, -2, "beat", 60.0, None, starts) == 9.8
    assert part.step(10.0, 1, "bar", 60.0, None, starts) == 16.0
    assert part.step(8.0, -1, "bar", 60.0, None, starts) == 4.0
    assert part.step(16.0, 1, "bar", 60.0, None, starts) == 60.0


def test_an_end_never_passes_the_other():
    assert part.move(10.0, 11.0, "from", 1, "bar", 120.0, BEATS) == (10.0, 11.0)
    assert part.move(10.0, 11.0, "to", -1, "bar", 120.0, BEATS) == (10.0, 11.0)
    assert part.move(10.0, 20.0, "to", -1, "bar", 120.0, BEATS) == (10.0, 18.0)


def test_the_line_gives_seconds_bars_and_the_sung_lines():
    info = part.describe(4.0, 18.0, LINES, 60.0, BEATS)
    assert info["seconds"] == 14.0
    assert (info["bars"], info["beats"]) == (7, 0)
    assert info["first"] == {"line": 1, "text": "first line"}
    assert info["last"] == {"line": 5, "text": "third"}
    assert part.describe(4.0, 17.5, LINES, 60.0, BEATS)["beats"] == 3
    assert "bars" not in part.describe(4.0, 18.0, LINES, 60.0)


def test_an_end_while_a_line_is_sung_is_marked():
    letters = ((8.0, "second line", (8.1, 8.4, 8.8, 9.2)),)
    inside = part.describe(4.0, 8.6, LINES, 60.0, BEATS, letters)["inside"]
    assert inside == [{"end": "to", "line": 2, "text": "second line"}]
    assert part.describe(4.0, 9.6, LINES, 60.0, BEATS, letters)["inside"] == []
    start = part.describe(8.5, 16.0, LINES, 60.0, BEATS, letters)["inside"]
    assert [hit["end"] for hit in start] == ["from"]


def test_a_line_without_letter_times_lasts_by_its_letters():
    # "first line": 9 letters at 0.3 s each, so it sounds until 6.7 s.
    assert part.describe(2.0, 6.0, LINES, 60.0)["inside"][0]["line"] == 1
    assert part.describe(2.0, 7.0, LINES, 60.0)["inside"] == []


@pytest.fixture
def app(tmp_path, monkeypatch):
    a = server.App(tmp_path)
    a.demo()
    a.project.lines = list(LINES)
    a.project.letters = []
    monkeypatch.setattr("coverlyric.align.missing", lambda names=(): None)
    monkeypatch.setattr(
        sections, "grid", lambda path: Grid(np.asarray(BEATS), *[np.ones(9)] * 2, 20.0)
    )
    monkeypatch.setattr(media, "duration", lambda path: 60.0)
    return a


def test_the_page_moves_an_end_by_a_bar(app):
    info = app.pick_part(4.0, 12.0, "to", 1, "bar")
    assert (info["from"], info["to"], info["bars"]) == (4.0, 14.0, 5)
    assert info["grid"]


def test_the_page_falls_back_without_the_extra(app, monkeypatch):
    monkeypatch.setattr("coverlyric.align.missing", lambda names=(): "librosa not installed")
    info = app.pick_part(4.0, 12.0, "to", 1, "beat")
    assert info["to"] == 12.1
    assert not info["grid"] and "bars" not in info


SEAM = Path(__file__).parents[1] / "src" / "coverlyric" / "web" / "seam.js"
NODE = shutil.which("node")


def seam(channels, rate, first, last, blend):
    script = (
        f"const {{ seamLoop }} = require({json.dumps(str(SEAM))});"
        f"const out = seamLoop({json.dumps(channels)}.map((c) => Float32Array.from(c)), "
        f"{rate}, {first}, {last}, {blend});"
        "console.log(JSON.stringify(out.map((c) => Array.from(c))));"
    )
    run = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return np.asarray(json.loads(run.stdout))


@pytest.mark.skipif(NODE is None, reason="needs node to run the page script")
def test_the_page_seam_crosses_at_equal_power_into_the_sound_before_the_start():
    rate = 100
    song = np.arange(1000, dtype=float) / 1000
    out = seam([song.tolist()], rate, 3.0, 5.0, 0.5)[0]
    assert len(out) == 200
    assert out[:150] == pytest.approx(song[300:450], abs=1e-6)
    th = np.arange(50) / 50 * np.pi / 2
    want = song[450:500] * np.cos(th) + song[250:300] * np.sin(th)
    assert out[150:] == pytest.approx(want, abs=1e-6)


@pytest.mark.skipif(NODE is None, reason="needs node to run the page script")
def test_the_page_seam_is_a_jump_without_a_blend_and_short_before_an_early_start():
    rate = 100
    song = (np.arange(1000, dtype=float) / 1000).tolist()
    plain = seam([song], rate, 3.0, 5.0, 0.0)[0]
    assert plain == pytest.approx(np.asarray(song[300:500]), abs=1e-6)
    early = seam([song], rate, 0.2, 2.0, 0.5)[0]
    th = np.arange(20) / 20 * np.pi / 2
    want = np.asarray(song[180:200]) * np.cos(th) + np.asarray(song[0:20]) * np.sin(th)
    assert early[-20:] == pytest.approx(want, abs=1e-6)
    tiny = seam([song], rate, 0.03, 2.0, 0.5)[0]
    assert tiny == pytest.approx(np.asarray(song[3:200]), abs=1e-6)


def test_the_first_line_is_the_first_one_that_starts_in_the_part():
    letters = ((4.0, "first line", (4.0, 4.5, 5.0)),)
    info = part.describe(5.3, 12.0, LINES, 60.0, BEATS, letters)
    assert info["first"]["line"] == 2
    assert info["inside"] == []
