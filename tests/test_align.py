"""Letter times by forced alignment, with the models mocked: no download, no torch (COVER-SHORTS-V2)."""

import argparse
import json
import sys
import types

import pytest

from coverlyric import align, cli, media

ROMAN = {"가": "ga", "나": "na", "다": "da", "라": "ra"}


def romanise(ch: str) -> str:
    return ROMAN.get(ch, ch if ch.isalnum() else "")


def test_each_letter_is_its_own_word_and_punctuation_is_none():
    picked = [(0, 1.0, "가나, 다!"), (2, 5.0, "라라")]
    words, marks = align.tokens(picked, romanise)
    assert words == ["ga", "na", "da", "ra", "ra"]
    assert marks == {0: [0, 1, None, 2, None], 2: [3, 4]}


def test_punctuation_takes_the_letter_before_and_times_lead():
    picked = [(0, 1.0, "가나, 다!"), (1, 4.0, '"라"')]
    _, marks = align.tokens(picked, romanise)
    starts = [1.0, 1.5, 2.0, 4.2]
    got = align.entries(picked, marks, starts)
    lead = align.LEAD
    assert got[0] == {
        "n": 1,
        "text": "가나, 다!",
        "times": [1.0 - lead, 1.5 - lead, 1.5 - lead, 2.0 - lead, 2.0 - lead],
    }
    assert got[1]["times"] == [round(4.2 - lead, 3)] * 3, "an opening mark takes the first letter"


def test_a_repeated_letter_keeps_each_start():
    picked = [(0, 1.0, "라라라")]
    _, marks = align.tokens(picked, romanise)
    got = align.entries(picked, marks, [1.0, 1.4, 1.9])
    assert got[0]["times"] == [round(x - align.LEAD, 3) for x in (1.0, 1.4, 1.9)]


def test_only_the_lines_in_the_part_are_aligned():
    lines = [(1.0, "가"), (None, "나"), (5.0, " "), (9.0, "다"), (20.0, "라")]
    assert align.chosen(lines, 0.0, 10.0) == [(0, 1.0, "가"), (3, 9.0, "다")]


def test_new_letter_times_replace_old_ones_for_the_same_line():
    old = [{"n": 1, "times": [0]}, {"n": 3, "times": [0]}]
    new = [{"n": 3, "times": [1]}, {"n": 2, "times": [2]}]
    assert align.merged(old, new) == [{"n": 1, "times": [0]}, new[1], new[0]]


def test_align_places_letters_on_the_separated_vocals(monkeypatch):
    seen = {}

    def vocals(path, start, length):
        seen["part"] = (start, length)
        return [0.0], 16000

    def word_starts(voice, rate, words):
        seen["words"] = words
        return [5.5 + 0.3 * k for k in range(len(words))]

    monkeypatch.setitem(
        sys.modules,
        "uroman",
        types.SimpleNamespace(Uroman=lambda: types.SimpleNamespace(romanize_string=romanise)),
    )
    monkeypatch.setattr(align, "downloads", lambda: True)
    monkeypatch.setattr(align, "vocals", vocals)
    monkeypatch.setattr(align, "word_starts", word_starts)
    notes = []
    lines = [(2.0, "가나"), (12.0, "다"), (30.0, "라")]
    got = align.align("song.wav", lines, 10.0, 20.0, note=notes.append)
    assert seen["part"] == (12.0 - align.AROUND, 30.0 - 12.0 + 2 * align.AROUND)
    assert seen["words"] == ["da"]
    assert got == [{"n": 2, "text": "다", "times": [round(7.0 + 5.5 - align.LEAD, 3)]}]
    assert any("1.2 GB" in n for n in notes), "the first run says it downloads"


def test_a_part_without_lines_is_refused(monkeypatch):
    monkeypatch.setitem(sys.modules, "uroman", types.SimpleNamespace(Uroman=lambda: None))
    with pytest.raises(ValueError, match="no timed line"):
        align.align("song.wav", [(1.0, "가")], 5.0, 9.0)


def test_missing_modules_are_named_with_the_install_command(monkeypatch):
    monkeypatch.setattr(align.importlib.util, "find_spec", lambda name: None)
    why = align.missing()
    assert "torch" in why and align.INSTALL in why


def parse(argv):
    parser = argparse.ArgumentParser()
    cli.add_commands(parser.add_subparsers(dest="command"))
    return parser.parse_args(argv)


def test_the_command_saves_letters_into_the_project(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "p"
    folder.mkdir()
    data = {
        "audio": "song.wav",
        "duration": 60.0,
        "lines": [[2.0, "가나"], [12.0, "다"]],
        "letters": [{"n": 1, "text": "가나", "times": [1, 2]}],
        "style": {"shape": "tall", "clip_from": 10.0, "clip_to": 20.0},
    }
    (folder / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(media, "duration", lambda path: 60.0)
    monkeypatch.setattr(align, "missing", lambda names=(): None)
    asked = {}

    def fake(path, lines, start, end, note=print):
        asked["span"] = (start, end)
        return [{"n": 2, "text": "다", "times": [12.1]}]

    monkeypatch.setattr(align, "align", fake)
    assert cli.main(parse(["align", str(folder), "--json"])) == 0
    assert asked["span"] == (10.0, 20.0), "an upright project aligns its part"
    saved = json.loads((folder / "project.json").read_text(encoding="utf-8"))["letters"]
    assert [e["n"] for e in saved] == [1, 2]
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["aligned"] == [2]


def test_without_the_extra_align_exits_1(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps({"lines": [[1.0, "가"]]}), encoding="utf-8")
    monkeypatch.setattr(align, "missing", lambda names=(): "this needs the 'align' extra")
    assert cli.main(parse(["align", str(folder), "--json"])) == 1
    assert "align" in json.loads(capsys.readouterr().out.splitlines()[-1])["error"]


def test_a_stray_letter_goes_between_its_neighbours():
    assert align.settled([10.0, 3.0, 10.4], 10.0, 20.0) == [10.0, 10.2, 10.4]
    assert align.settled([10.0, 25.0, 10.4], 10.0, 20.0) == [10.0, 10.2, 10.4]


def test_letters_aligned_before_their_line_start_from_it():
    got = align.settled([142.85, 143.05, 152.3, 152.6], 152.16, 160.0)
    assert got[2:] == [152.3, 152.6]
    assert 152.16 < got[0] < got[1] < 152.3


def test_letters_aligned_past_the_next_line_stop_before_it():
    got = align.settled([10.0, 10.3, 30.0, 31.0], 10.0, 11.0)
    assert got[:2] == [10.0, 10.3]
    assert 10.3 < got[2] < got[3] <= 11.0


def test_a_line_with_no_letter_inside_it_is_left_out():
    picked = [(0, 10.0, "가나")]
    _, marks = align.tokens(picked, romanise)
    assert align.entries(picked, marks, [1.0, 2.0], {0: 20.0}) == []


def test_entries_keep_letters_inside_the_line():
    picked = [(0, 10.0, "가나다")]
    _, marks = align.tokens(picked, romanise)
    got = align.entries(picked, marks, [10.04, 2.0, 10.6], {0: 20.0})
    assert got[0]["times"] == [10.0, 10.28, 10.56], "the stray is halfway, after the lead"
