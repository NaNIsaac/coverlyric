"""The command line: project folders, one fix per command, JSON answers and exit codes."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from coverlyric import __main__ as entry
from coverlyric import cli, media

DEMO = Path(cli.__file__).parent / "demo"
LYRICS = (
    "[Verse 1]\n첫 번째 줄이에요\n# 메모\n두 번째 줄은 조금 길어요\n\n세 번째 줄\n마지막 줄입니다\n"
)
SRT = (
    "1\n00:00:03,000 --> 00:00:06,000\n첫 번째 줄이에요\n\n"
    "2\n00:00:06,500 --> 00:00:10,000\n두 번째 줄은 조금 길어요\n\n"
    "3\n00:00:10,000 --> 00:00:13,500\n세 번째 줄\n\n"
    "4\n00:00:13,500 --> 00:00:17,000\n마지막 줄입니다\n"
)


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*argv, "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return done.value.code, json.loads(out[-1])


@pytest.fixture()
def song(tmp_path) -> Path:
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text(LYRICS, encoding="utf-8")
    folder = tmp_path / "데모 노래"
    cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", lyrics, "데모 노래")
    return folder


@pytest.mark.parametrize(
    ("text", "value"),
    [("72.4", 72.4), ("1:12.4", 72.4), ("1:02:03", 3723.0), ("-0.3", -0.3), ("+1", 1.0)],
)
def test_times_as_people_type_them(text, value):
    assert cli.seconds(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "1:", "a", "1:2:3:4"])
def test_a_time_that_is_not_one(text):
    with pytest.raises(cli.Usage):
        cli.seconds(text)


def test_a_new_project_is_a_folder_with_copies(capsys, tmp_path):
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text(LYRICS, encoding="utf-8")
    code, data = run(
        capsys,
        "project", "new", str(tmp_path / "p"), "--audio", str(DEMO / "tone.wav"),
        "--cover", str(DEMO / "cover.png"), "--lyrics", str(lyrics), "--title", "데모 노래",
    )  # fmt: skip
    assert code == 0
    assert {p.name for p in (tmp_path / "p").iterdir()} == {"project.json", "song.wav", "cover.png"}
    assert [row["text"] for row in data["lines"]] == [
        "첫 번째 줄이에요",
        "두 번째 줄은 조금 길어요",
        "세 번째 줄",
        "마지막 줄입니다",
    ]
    assert data["duration"] == pytest.approx(media.duration(str(DEMO / "tone.wav")))
    code, again = run(capsys, "project", "new", str(tmp_path / "p"), "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png"))  # fmt: skip
    assert code == 1 and "already holds a project" in again["error"]


def test_keep_tags_keeps_the_lyrics_as_typed(tmp_path):
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text(LYRICS, encoding="utf-8")
    project = cli.new_project(
        tmp_path / "p", DEMO / "tone.wav", DEMO / "cover.png", lyrics, clean=False
    )
    assert project.lines[0] == (None, "[Verse 1]") and not project.clean_tags


def test_set_changes_title_and_style_keys(capsys, song):
    code, data = run(
        capsys, "project", "set", str(song), "artist=가수", "lead=1", "fade=off", "height=720"
    )
    assert code == 0 and data["changed"] == ["artist", "lead", "fade", "height"]
    assert data["artist"] == "가수"
    assert data["style"] == {"lead": 1.0, "fade": False, "height": 720}
    code, data = run(capsys, "project", "set", str(song), "colour=red")
    assert code == 2 and "unknown key 'colour'" in data["error"] and "lead" in data["error"]
    code, data = run(capsys, "project", "set", str(song), "lead=soon")
    assert code == 2 and "lead takes a float" in data["error"]


def test_lines_take_one_fix_per_command(capsys, song, tmp_path):
    srt = tmp_path / "t.srt"
    srt.write_text(SRT, encoding="utf-8")
    code, data = run(capsys, "project", "lines", str(song), "--import", str(srt))
    assert code == 0 and [row["time"] for row in data["lines"]] == [3.0, 6.5, 10.0, 13.5]
    _, data = run(capsys, "project", "lines", str(song), "--shift", "-0.5")
    assert [row["time"] for row in data["lines"]] == [2.5, 6.0, 9.5, 13.0]
    _, data = run(capsys, "project", "lines", str(song), "--set", "2=0:05.2", "--text", "4=끝 줄")
    assert data["lines"][1]["time"] == 5.2 and data["lines"][3]["text"] == "끝 줄"
    code, data = run(capsys, "project", "lines", str(song), "--set", "9=1")
    assert code == 2 and "line 9 does not exist" in data["error"]
    code, data = run(capsys, "project", "lines", str(song))
    assert code == 2


def test_a_fixed_line_loses_its_note(capsys, song):
    project, file = cli.load(song)
    project.lines = [(3.0, a) for _, a in project.lines]
    project.notes = [{"n": 2, "kind": "unplaced"}, {"n": 3, "kind": "differs", "heard": "세 번 줄"}]
    project.save(file)
    _, data = run(capsys, "project", "show", str(song))
    assert data["notes"] == 2 and data["lines"][2] == {"n": 3, "time": 3.0, "text": "세 번째 줄", "note": "differs", "heard": "세 번 줄"}  # fmt: skip
    _, data = run(capsys, "project", "lines", str(song), "--set", "2=5")
    assert data["notes"] == 1 and "note" not in data["lines"][1]


def test_show_in_words(capsys, song):
    with pytest.raises(SystemExit):
        entry.main(["project", "show", str(song)])
    out = capsys.readouterr().out
    assert out.startswith("데모 노래  (0:18.00, 4 lines, 0 timed, 0 to check)")
    assert "  1          -  첫 번째 줄이에요" in out


def test_render_writes_the_video_and_the_files_beside_it(capsys, song, tmp_path):
    srt = tmp_path / "t.srt"
    srt.write_text(SRT, encoding="utf-8")
    run(capsys, "project", "lines", str(song), "--import", str(srt))
    run(capsys, "project", "set", str(song), "height=720")
    code, data = run(capsys, "render", str(song), "--quick")
    assert code == 0
    video = song / "데모 노래.mp4"
    assert data["video"] == str(video) and video.stat().st_size > 0
    for kind in ("srt", "lrc", "png"):
        assert Path(data[kind]) == video.with_suffix(f".{kind}") and Path(data[kind]).exists()
    assert "00:00:03,000 --> 00:00:06,500" in video.with_suffix(".srt").read_text("utf-8")
    code, data = run(capsys, "render", str(song), "--clip", "0:02,0:04", "--quick", "--out", str(tmp_path / "c.mp4"))  # fmt: skip
    assert code == 0 and "srt" not in data
    assert media.duration(data["video"]) == pytest.approx(2.0, abs=0.2)


def test_render_refuses_lines_without_times(capsys, song):
    code, data = run(capsys, "render", str(song))
    assert code == 1 and "line 1 has no time" in data["error"]


def test_still_at_a_typed_time(capsys, song):
    code, data = run(capsys, "still", str(song), "--at", "0:07")
    assert code == 0 and data["at"] == 7.0 and (song / "still.png").exists()


def test_a_missing_project_is_exit_1(capsys, tmp_path):
    code, data = run(capsys, "project", "show", str(tmp_path / "none"))
    assert code == 1 and "no project at" in data["error"]


def test_korean_goes_through_a_pipe_on_any_console(song):
    done = subprocess.run(
        [sys.executable, "-I", "-m", "coverlyric", "project", "show", str(song)],
        capture_output=True,
        check=True,
    )
    assert "첫 번째 줄이에요" in done.stdout.decode("utf-8")


def test_new_never_replaces_files_already_in_the_folder(capsys, tmp_path):
    folder = tmp_path / "mine"
    folder.mkdir()
    (folder / "song.wav").write_bytes(b"my own recording")
    (folder / "song.mp3").write_bytes(b"another one")
    code, data = run(capsys, "project", "new", str(folder), "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png"))  # fmt: skip
    assert code == 2 and "song.wav already exists" in data["error"]
    assert (folder / "song.wav").read_bytes() == b"my own recording"
    assert (folder / "song.mp3").read_bytes() == b"another one"
    assert not (folder / "project.json").exists()


def test_new_in_the_folder_that_holds_the_song(capsys, tmp_path):
    folder = tmp_path / "here"
    folder.mkdir()
    (folder / "song.wav").write_bytes((DEMO / "tone.wav").read_bytes())
    (folder / "song.mp3").write_bytes(b"kept")
    code, _ = run(capsys, "project", "new", str(folder), "--audio", str(folder / "song.wav"), "--cover", str(DEMO / "cover.png"))  # fmt: skip
    assert code == 0 and (folder / "song.mp3").read_bytes() == b"kept"
