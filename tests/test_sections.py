"""Loop sections: whole bars, the seam between lines, ranked by how the start opens (COVER-SHORTS-V2)."""

import argparse
import json

import numpy as np
import pytest

from coverlyric import cli, media, sections
from coverlyric.sections import Grid

FPS = 20.0


def steady(
    seconds: float = 120.0, beat: float = 0.5, loud: tuple[float, float] | None = None
) -> Grid:
    """A song with a beat every `beat` seconds, louder and busier from loud[0] to loud[1]."""
    frames = int(seconds * FPS)
    rms, onset = np.ones(frames), np.ones(frames)
    if loud:
        rms[int(loud[0] * FPS) : int(loud[1] * FPS)] = 4.0
        onset[int(loud[0] * FPS) : int(loud[1] * FPS)] = 3.0
    return Grid(np.arange(0.0, seconds, beat), rms, onset, FPS)


LINES = tuple((8.0 * k + 4.0, f"line {k}") for k in range(13))


def test_every_section_is_a_whole_number_of_bars():
    g = steady()
    for s in sections.sections(LINES, g, 120.0, 30):
        assert (s["to"] - s["from"]) / g.bar == pytest.approx(s["bars"])
        assert s["bars"] in (14, 15, 16)


def test_a_section_starts_on_the_beat_its_line_starts_on_or_just_before():
    g = steady()
    lines = ((10.2, "a pickup"), (20.0, "on the beat"), (60.0, "end"))
    found = {s["text"]: s["from"] for s in sections.sections(lines, g, 120.0, 10)}
    assert found["a pickup"] == 10.0
    assert found["on the beat"] == 20.0


def test_the_seam_falls_just_before_a_line_comes_in():
    g = steady()
    for s in sections.sections(LINES, g, 120.0, 30):
        nxt = min((t for t, _ in LINES if t >= s["to"] - sections.SNAP), default=120.0)
        assert 0 <= nxt - s["to"] <= g.beat, s


def test_the_loud_busy_start_ranks_first():
    g = steady(loud=(52.0, 60.0))
    best = sections.sections(LINES, g, 120.0, 30)[0]
    assert best["from"] == 52.0
    assert best["n"] == 1 and best["line"] == 7


def test_a_repeated_line_counts_as_a_chorus():
    g = steady()
    lines = ((4.0, "once"), (20.0, "again and again"), (36.0, "other"), (52.0, "Again, and again!"))
    ranked = [s["text"] for s in sections.sections(lines, g, 120.0, 8)]
    assert ranked[:2] == ["again and again", "Again, and again!"]


def test_no_section_runs_past_the_end():
    g = steady(seconds=40.0)
    lines = ((4.0, "a"), (30.0, "late"))
    found = sections.sections(lines, g, 40.0, 30)
    assert [s["text"] for s in found] == ["a"]
    assert all(s["to"] <= 40.0 for s in found)


def test_clicks_at_120_bpm_give_half_second_beats(tmp_path):
    pytest.importorskip("librosa")
    rate = 22050
    y = np.zeros(rate * 20, np.float32)
    for k in range(40):
        i = int(k * 0.5 * rate)
        y[i : i + 200] = np.hanning(200) * (1.0 if k % 4 == 0 else 0.6)
    path = tmp_path / "clicks.wav"
    import wave

    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((y * 32767).astype("<i2").tobytes())
    g = sections.grid(str(path))
    assert g.beat == pytest.approx(0.5, abs=0.02)
    assert len(media.samples(str(path), rate)) == pytest.approx(len(y), abs=rate // 10)


def test_without_the_extra_the_command_says_how_to_install_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("coverlyric.align.missing", lambda names=(): "this needs the 'align' extra")
    project = tmp_path / "p"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({"lines": [[1.0, "a"]]}), encoding="utf-8")
    args = cli_args(["sections", str(project), "--json"])
    assert cli.main(args) == 1
    assert "align" in json.loads(capsys.readouterr().out.splitlines()[-1])["error"]


def test_apply_makes_a_looping_short_of_the_section(tmp_path, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    lines = [[t, text] for t, text in LINES]
    data = {"lines": lines, "duration": 120.0, "audio": "song.wav"}
    (project / "project.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("coverlyric.align.missing", lambda names=(): None)
    monkeypatch.setattr(sections, "grid", lambda path: steady(loud=(52.0, 60.0)))
    assert cli.main(cli_args(["sections", str(project), "--apply", "1", "--json"])) == 0
    style = json.loads((project / "project.json").read_text(encoding="utf-8"))["style"]
    assert (style["shape"], style["clip_from"], style["loop"]) == ("tall", 52.0, True)
    assert (style["clip_to"] - style["clip_from"]) / 2.0 == round((style["clip_to"] - 52.0) / 2.0)


def cli_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    cli.add_commands(parser.add_subparsers(dest="command"))
    return parser.parse_args(argv)


def test_the_cli_parser_knows_both_commands():
    for argv in (["sections", "x"], ["align", "x", "--from", "1:00", "--to", "1:30"]):
        assert cli_args(argv).command == argv[0]


@pytest.fixture(autouse=True)
def _no_audio(monkeypatch):
    monkeypatch.setattr(media, "duration", lambda path: 120.0)


def test_the_page_finds_sections_once_per_song(tmp_path, monkeypatch):
    from coverlyric import server

    app = server.App(tmp_path)
    app.demo()
    monkeypatch.setattr("coverlyric.align.missing", lambda names=(): None)
    calls = []
    monkeypatch.setattr(sections, "grid", lambda path: calls.append(path) or steady(seconds=20.0))
    monkeypatch.setattr(media, "duration", lambda path: 20.0)
    first = app.find_sections(4)["sections"]
    assert first and all(s["bars"] == 2 for s in first)
    app.find_sections(8)
    assert len(calls) == 1, "the beat grid is kept for the same song"


def test_the_page_says_what_to_install(tmp_path, monkeypatch):
    from coverlyric import server

    app = server.App(tmp_path)
    app.demo()
    monkeypatch.setattr("coverlyric.align.missing", lambda names=(): "this needs the 'align' extra")
    with pytest.raises(ValueError, match="추가 설치"):
        app.find_sections(30)
