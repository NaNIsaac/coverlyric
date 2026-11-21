"""Letter times the aligner got wrong are found and placed again (align.trouble, refill, repaired);
letter entries that no longer fit their line go on a line import; and a mark touching a letter lights
with it (tall.marked_by)."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from coverlyric import __main__ as entry
from coverlyric import align, cli, render, tall, timing
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo"
YELLOW = render.hex_rgb(tall.HIGHLIGHT)


def test_wrong_letter_times():
    assert align.trouble([10.0, 10.3, 10.6], 10.0, 13.0) is None
    assert align.trouble([10.8, 11.0, 11.2], 10.0, 13.0) == "late"
    assert align.trouble([10.0, 10.3, 13.0], 10.0, 13.0) == "past"
    assert align.trouble([10.0, 10.02, 10.04, 10.06], 10.0, 13.0) == "bunched"


def test_new_times_from_the_heard_words():
    heard = [(20.1, "하나"), (20.9, "둘이"), (25.0, "다음 줄")]
    times = align.refill("하나, 둘이", 20.0, 24.0, heard)
    assert len(times) == len("하나,둘이")
    assert times[0] == pytest.approx(20.1) and times[3] == pytest.approx(20.9)
    assert times == sorted(times) and times[-1] < 24.0


def test_without_heard_words_the_letters_are_spread():
    times = align.refill("하나 둘", 20.0, 24.0, [])
    assert times[0] == 20.0 and len(times) == 3
    gaps = np.diff(times)
    assert (gaps > 0.1).all() and times[-1] < 24.0


def test_only_wrong_lines_are_repaired_and_marked():
    lines = [(10.0, "가나다"), (13.0, "라마바"), (16.0, "끝")]
    found = [
        {"n": 1, "text": "가나다", "times": [10.0, 10.3, 10.6]},
        {"n": 2, "text": "라마바", "times": [14.4, 14.41, 14.42]},
    ]
    out, fixed = align.repaired(found, lines)
    assert out[0] == found[0]
    assert [e["n"] for e in fixed] == [2] and out[1]["repaired"] == "late"
    assert out[1]["times"][0] == 13.0
    assert align.trouble(out[1]["times"], 13.0, 16.0) is None


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*argv, "--json"])
    said = capsys.readouterr()
    data = json.loads(said.out.strip().splitlines()[-1])
    return done.value.code, {**data, "stderr": said.err}


@pytest.fixture()
def song(tmp_path) -> Path:
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("가나다\n라마바\n끝", encoding="utf-8")
    folder = tmp_path / "노래"
    p = cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", lyrics, "노래")
    p.lines = [(1.0, "가나다"), (4.0, "라마바"), (7.0, "끝")]
    p.save(folder / "project.json")
    return folder


def test_align_repairs_and_says_so(capsys, song, monkeypatch):
    monkeypatch.setattr(align, "missing", lambda *a: None)
    bad = [
        {"n": 1, "text": "가나다", "times": [1.0, 1.3, 1.6]},
        {"n": 2, "text": "라마바", "times": [4.0, 4.01, 4.02]},
    ]
    monkeypatch.setattr(align, "align", lambda *a, **k: [dict(e) for e in bad])
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: None)
    code, data = run(capsys, "align", str(song))
    assert code == 0 and data["repaired"] == [2], data
    assert "repaired the letter times of 1 lines: 2 (bunched)" in data["stderr"]
    code, shown = run(capsys, "project", "show", str(song))
    rows = {row["n"]: row for row in shown["lines"]}
    assert rows[2]["letters"] == "repaired (bunched)" and "letters" not in rows[1]


def test_a_line_import_drops_letters_that_no_longer_fit(capsys, song, tmp_path):
    p = Project.load(song / "project.json")
    p.letters = [
        {"n": 1, "text": "가나다", "times": [1.0, 1.3, 1.6]},
        {"n": 2, "text": "라마바", "times": [4.0, 4.3, 4.6]},
    ]
    p.save(song / "project.json")
    srt = tmp_path / "new.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\n가나다\n\n"
        "2\n00:00:04,000 --> 00:00:05,000\n새 줄\n\n"
        "3\n00:00:05,000 --> 00:00:07,000\n라마바\n",
        encoding="utf-8",
    )
    code, _ = run(capsys, "project", "lines", str(song), "--import", str(srt))
    assert code == 0
    assert [e["n"] for e in Project.load(song / "project.json").letters] == [1]


@pytest.mark.parametrize(
    ("row", "owners"),
    [
        ("냥, 있어?", [0, 0, None, 2, 3, 3]),
        ("'반 냥", [1, 1, None, 2]),
        ("가 - 나", [0, None, None, None, 2]),
        ("(가나)", [1, 1, 2, 2]),
    ],
)
def test_a_mark_goes_with_the_letter_it_touches(row, owners):
    assert tall.marked_by(row, 0) == owners


def yellow(img) -> int:
    rgb = np.asarray(img.convert("RGB"), dtype=np.int16)
    return int((np.abs(rgb - YELLOW).sum(axis=2) < 30).sum())


def test_the_mark_lights_with_its_letter():
    p = Project.load(DEMO / "demo.json")
    style = replace(tall.shorts(p.style), highlight="letter", clip_from=0.0, clip_to=6.0)

    def lit(text: str) -> int:
        times = timing.letter_times(text, [1.0, 3.0])
        song = replace(p.song(), letters=((1.0, text, times),))
        return yellow(tall.Painter(((1.0, text),), song, style).image(1.5))

    assert lit("냥!! 가") > lit("냥 !! 가") + 50, "the marks after 냥 light with it"
