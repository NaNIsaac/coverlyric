"""output import: another project's video of the same song becomes an output here, with its files, and
only when the lines and their letter times are the same."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from coverlyric import __main__ as entry
from coverlyric import cli, render, tall
from coverlyric.project import Project

DEMO = Path(cli.__file__).parent / "demo"
LINES = [(3.0, "첫 줄"), (6.0, "둘째 줄")]
LETTERS = [{"n": 1, "text": "첫 줄", "times": [3.0, 3.5]}]


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*map(str, argv), "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return done.value.code, json.loads(out[-1])


def files(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }


def change(folder: Path, **keys) -> None:
    project = Project.load(folder / "project.json")
    for key, value in keys.items():
        setattr(project, key, value)
    project.save(folder / "project.json")


@pytest.fixture()
def song(tmp_path) -> Path:
    folder = tmp_path / "song"
    cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", None, "노래")
    change(folder, lines=list(LINES), letters=list(LETTERS))
    return folder


@pytest.fixture()
def short(tmp_path, song) -> Path:
    """The Short as it was made before outputs: a copy of the folder, saved as format 1."""
    folder = tmp_path / "copy"
    shutil.copytree(song, folder)
    copy = Project.load(folder / "project.json")
    copy.style = replace(tall.shorts(copy.style, "tall"), clip_from=3.0, clip_to=9.0)
    (folder / "project.json").write_text(json.dumps(copy.flat()), encoding="utf-8")
    return folder


def test_a_short_copy_becomes_an_output(capsys, song, short):
    before = files(short)
    code, data = run(capsys, "output", "import", song, short)
    assert code == 0 and data["imported"] == "short" and data["not_imported"] == []
    assert [(o["id"], o["file"], o["current"]) for o in data["outputs"]] == [
        ("wide", "노래.mp4", False),
        ("short", "노래_shorts.mp4", True),
    ]
    joined, copy = Project.load(song / "project.json"), Project.load(short / "project.json")
    assert joined.style == copy.style and joined.outputs[0].style.shape == "wide"
    assert joined.lines == LINES and joined.letters == LETTERS
    assert files(short) == before, "the other project is only read"


def test_the_imported_output_draws_the_same_frame(capsys, song, short):
    run(capsys, "output", "import", song, short)
    frames = []
    for folder in (short, song):
        p = Project.load(folder / "project.json")
        frames.append(render.frame(4.0, p.preview_lines(), p.song(), p.style).tobytes())
    assert frames[0] == frames[1]


def test_the_other_projects_current_output_is_the_one_taken(capsys, song, short):
    other = Project.load(short / "project.json")
    cli.add_output(other, "square", None, "square")
    other.save(short / "project.json")
    code, data = run(capsys, "output", "import", song, short)
    assert code == 0 and data["imported"] == "square" and len(data["outputs"]) == 2


def test_a_second_import_of_a_shape_gets_the_next_id(capsys, song, short):
    run(capsys, "output", "import", song, short)
    code, data = run(capsys, "output", "import", song, short)
    assert code == 0 and data["imported"] == "short-2"
    assert data["outputs"][2]["file"] == "노래_shorts-2.mp4"


@pytest.mark.parametrize(
    ("lines", "said"),
    [
        ([(3.0, "첫 줄"), (6.2, "둘째 줄")], ["line 2"]),
        ([(3.0, "첫줄"), (None, "둘째 줄")], ["line 1", "line 2"]),
        ([*LINES, (8.0, "셋째 줄")], ["line 3"]),
        (LINES[:1], ["line 2"]),
    ],
)
def test_other_lines_are_refused_and_listed(capsys, song, short, lines, said):
    change(short, lines=lines, letters=[])
    change(song, letters=[])
    before = files(song)
    code, data = run(capsys, "output", "import", song, short)
    assert code == 2 and all(line in data["error"] for line in said)
    assert data["error"].count("\n") == len(said), "one row for each line that differs"
    assert files(song) == before


@pytest.mark.parametrize("letters", [[], [{"n": 1, "text": "첫 줄", "times": [3.0, 3.9]}]])
def test_other_letter_times_are_refused(capsys, song, short, letters):
    change(short, letters=letters)
    before = files(song)
    code, data = run(capsys, "output", "import", song, short)
    assert code == 2 and "line 1" in data["error"] and "letter" in data["error"]
    assert files(song) == before


def test_rounding_and_outdated_letters_are_no_difference(capsys, song, short):
    stale = {"n": 2, "text": "예전 줄", "times": [6.0, 6.2, 6.4]}
    change(short, lines=[(3.0004, "첫 줄"), LINES[1]], letters=[*LETTERS, stale])
    assert run(capsys, "output", "import", song, short)[0] == 0


def test_files_come_in_without_replacing_any(capsys, song, short):
    for folder, mark in ((song, b"mine"), (short, b"theirs")):
        (folder / "anim").mkdir()
        (folder / "anim" / "a.png").write_bytes(mark)
        (folder / "anim" / "same.png").write_bytes(b"same")
        (folder / "video.mp4").write_bytes(mark)
        change(folder, video="video.mp4", anim=["anim/a.png", "anim/same.png"])
    (song / "video-short.mp4").write_bytes(b"left by a removed output")
    before = files(song)
    assert run(capsys, "output", "import", song, short)[0] == 0
    after = files(song)
    assert all(after[name] == body for name, body in before.items() if name != "project.json")
    joined = Project.load(song / "project.json")
    assert (song / joined.video).read_bytes() == b"theirs"
    assert joined.anim[1] == "anim/same.png", "the same file is not copied twice"
    assert (song / joined.anim[0]).read_bytes() == b"theirs"
    assert joined.outputs[0].video == "video.mp4"


def test_a_video_both_hold_is_shared(capsys, song, short):
    for folder in (song, short):
        (folder / "video.mp4").write_bytes(b"same")
        change(folder, video="video.mp4")
    assert run(capsys, "output", "import", song, short)[0] == 0
    assert Project.load(song / "project.json").video == "video.mp4"
    assert not list(song.glob("video-*"))


def test_a_font_kept_in_the_other_folder_comes_along(capsys, song, short):
    (short / "fonts").mkdir()
    font = short / "fonts" / "own.ttf"
    font.write_bytes(b"font")
    copy = Project.load(short / "project.json")
    change(short, style=replace(copy.style, font=str(font)))
    assert run(capsys, "output", "import", song, short)[0] == 0
    taken = Path(Project.load(song / "project.json").style.font)
    assert taken.is_relative_to(song.resolve()) and taken.read_bytes() == b"font"


def test_a_missing_file_changes_nothing(capsys, song, short):
    (short / "video.mp4").write_bytes(b"video")
    change(short, video="video.mp4", anim=["anim/gone.png"])
    before = files(song)
    code, data = run(capsys, "output", "import", song, short)
    assert code == 1 and "gone.png" in data["error"]
    assert files(song) == before


def test_what_the_project_keeps_of_its_own_is_named(capsys, song, short):
    Image.new("RGB", (8, 8), "red").save(short / "cover.png")
    change(short, title="다른 제목")
    code, data = run(capsys, "output", "import", song, short)
    assert code == 0 and data["not_imported"] == ["title", "art"]
    assert Project.load(song / "project.json").title == "노래"


def test_a_project_is_not_imported_into_itself(capsys, song):
    code, data = run(capsys, "output", "import", song, song / "project.json")
    assert code == 2 and "itself" in data["error"]


def test_a_file_outside_the_other_project_is_not_copied(capsys, song, short):
    (short.parent / "private.png").write_bytes(b"private")
    change(short, anim=["../private.png"])
    before = files(song)
    code, data = run(capsys, "output", "import", song, short)
    assert code == 1 and "outside" in data["error"]
    assert files(song) == before
