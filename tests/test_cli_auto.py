"""auto, words and make on the command line, with a stand-in for the listening model."""

import importlib.util
import json
from pathlib import Path

import pytest

from coverlyric import __main__ as entry
from coverlyric import auto, cli, media

DEMO = Path(cli.__file__).parent / "demo"
LYRICS = "[Verse]\n아리랑 아리랑 아라리요\n아리랑 고개로 넘어간다\n나를 버리고 가시는 님은\n십리도 못 가서 발병 난다\n"
HEARD = [  # the third line is not heard
    (3.0, 4.0, "아리랑"),
    (4.0, 4.6, "아리랑"),
    (4.6, 5.5, "아라리요"),
    (6.5, 7.4, "아리랑"),
    (7.4, 8.0, "고개로"),
    (8.0, 9.0, "넘어간다"),
    (13.5, 14.2, "십리도"),
    (14.2, 14.6, "못"),
    (14.6, 15.0, "가서"),
    (15.0, 15.5, "발병"),
    (15.5, 16.0, "난다"),
]


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*argv, "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return done.value.code, json.loads(out[-1])


@pytest.fixture()
def listener(monkeypatch):
    """faster-whisper present, memory unknown, and a transcriber that hears HEARD."""
    found = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: object() if name == "faster_whisper" else found(name, *a),
    )
    monkeypatch.setattr(media, "commit_mb", lambda: None)
    asked = []

    def transcribe(audio, name, report, heard, clip=None):
        asked.append({"audio": audio, "model": name, "clip": clip})
        report("listen", 18.0, 18.0)
        return [{"start": a, "end": b, "word": f" {w}", "prob": 0.9} for a, b, w in HEARD]

    monkeypatch.setattr(auto, "transcribe", transcribe)
    return asked


@pytest.fixture()
def lyrics(tmp_path) -> Path:
    path = tmp_path / "lyrics.txt"
    path.write_text(LYRICS, encoding="utf-8")
    return path


@pytest.fixture()
def song(tmp_path, lyrics) -> Path:
    folder = tmp_path / "아리랑"
    cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", lyrics, "아리랑")
    return folder


def test_auto_shows_times_and_saves_them_only_when_asked(capsys, listener, song):
    code, data = run(capsys, "auto", str(song), "--model", "base")
    assert code == 0 and data["model"] == "base" and not data["applied"]
    assert [row["time"] for row in data["lines"][:4]] == [3.0, 6.5, 11.25, 13.5]
    assert data["unplaced"] == [{"n": 3, "time": 11.25, "text": "나를 버리고 가시는 님은"}]
    assert data["lines"][2]["note"] == "unplaced"
    _, shown = run(capsys, "project", "show", str(song))
    assert shown["timed"] == 0 and shown["notes"] == 0
    run(capsys, "auto", str(song), "--apply")
    _, shown = run(capsys, "project", "show", str(song))
    assert shown["timed"] >= 4 and shown["lines"][2]["note"] == "unplaced"


def test_strict_exits_4_when_a_line_needs_a_look(capsys, listener, song):
    code, data = run(capsys, "auto", str(song), "--strict")
    assert code == 4 and data["unplaced"]


def test_words_in_a_stretch_of_a_project_song(capsys, listener, song):
    code, data = run(capsys, "words", str(song), "--from", "0:06", "--to", "0:09")
    assert code == 0 and listener[-1]["clip"] == (6.0, 9.0)
    assert listener[-1]["audio"].endswith("song.wav")
    assert [w["word"] for w in data["words"]] == ["아리랑", "고개로", "넘어간다"]
    assert data["words"][0] == {"start": 6.5, "end": 7.4, "word": "아리랑", "prob": 0.9}
    code, _ = run(capsys, "words", str(song), "--from", "9", "--to", "6")
    assert code == 2


def test_without_the_auto_extra_it_says_how_to_add_it(capsys, monkeypatch, song):
    found = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "faster_whisper" else found(name, *a),
    )
    code, data = run(capsys, "auto", str(song))
    assert code == 1 and "--extra auto" in data["error"]


def test_no_memory_for_any_model_is_exit_3(capsys, listener, monkeypatch, song):
    monkeypatch.setattr(media, "commit_mb", lambda: 100.0)
    code, data = run(capsys, "auto", str(song))
    assert code == 3 and "memory" in data["error"]


def test_make_puts_everything_in_one_folder(capsys, listener, lyrics, tmp_path):
    out = tmp_path / "videos"
    code, data = run(
        capsys, "make", "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png"),
        "--lyrics", str(lyrics), "--title", "아리랑", "--lead", "1", "--height", "720",
        "--out", str(out),
    )  # fmt: skip
    folder = out / "아리랑"
    assert code == 0 and data["folder"] == str(folder)
    names = {p.name for p in folder.iterdir()}
    assert {"project.json", "song.wav", "cover.png", "아리랑.mp4", "아리랑.srt", "아리랑.lrc", "아리랑.png"} <= names  # fmt: skip
    assert data["sung"] == 4 and data["placed"] == 3 and data["model"] == "small"
    assert [row["n"] for row in data["unplaced"]] == [3]
    assert set(data["seconds"]) == {"auto", "render"}
    project = json.loads((folder / "project.json").read_text("utf-8"))
    assert project["style"]["lead"] == 1.0 and project["notes"]
    assert "00:00:04,000" in (folder / "아리랑.srt").read_text("utf-8")  # song 3.0 + lead 1
    assert media.duration(data["video"]) == pytest.approx(19.0, abs=0.2)


def test_make_with_timed_lines_does_not_listen(capsys, listener, monkeypatch, tmp_path):
    timed = tmp_path / "t.lrc"
    timed.write_text(
        "[00:03.00]아리랑 아리랑 아라리요\n[00:06.50]아리랑 고개로 넘어간다\n", "utf-8"
    )
    monkeypatch.setattr(cli, "make_video", lambda project, out: {"video": "v.mp4", "seconds": 0.1})
    code, data = run(
        capsys, "make", "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png"),
        "--timing", str(timed), "--title", "아리랑", "--out", str(tmp_path / "v"), "--strict",
    )  # fmt: skip
    assert code == 0 and not listener and "model" not in data
    assert data["placed"] == 2 and data["unplaced"] == []


def test_make_with_a_wrong_value_makes_no_folder(capsys, listener, lyrics, tmp_path):
    out = tmp_path / "v"
    code, data = run(
        capsys, "make", "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png"),
        "--lyrics", str(lyrics), "--title", "아리랑", "--lead", "soon", "--out", str(out),
    )  # fmt: skip
    assert code == 2 and "lead takes a float" in data["error"] and not out.exists()
    code, data = run(
        capsys, "make", "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png"),
        "--lyrics", str(lyrics), "--title", "아리랑", "--style", '{"colour": 1}', "--out", str(out),
    )  # fmt: skip
    assert code == 2 and "unknown style key 'colour'" in data["error"] and not out.exists()
