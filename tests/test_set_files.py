"""project set video= and title_image=: only the file the project listed is replaced or deleted, and
only once the project is saved."""

import json
from pathlib import Path

import pytest

from coverlyric import __main__ as entry
from coverlyric import cli, overlay, render
from coverlyric.project import Project

DEMO = Path(cli.__file__).parent / "demo"
OWN = ("title.txt", "title.psd", "title.png", "video.srt", "video.mp4", "video-2.txt")
KEYS = [("video", ".mp4"), ("title_image", ".png")]


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*map(str, argv), "--json"])
    return done.value.code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


@pytest.fixture()
def folder(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(overlay, "length", lambda path: 10.0)
    monkeypatch.setattr(render, "title_lettering", lambda *args: object())
    folder = tmp_path / "project"
    cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", None, "demo")
    for name in OWN:
        (folder / name).write_bytes(b"the user's")
    return folder


def untouched(folder: Path) -> bool:
    return all(
        (folder / name).is_file() and (folder / name).read_bytes() == b"the user's" for name in OWN
    )


def listed(folder: Path, key: str) -> str:
    return getattr(Project.load(folder / "project.json"), key)


def put(capsys, folder: Path, key: str, suffix: str, body: bytes = b"new") -> str:
    source = folder.parent / f"given{suffix}"
    source.write_bytes(body)
    assert run(capsys, "project", "set", folder, f"{key}={source}")[0] == 0
    return listed(folder, key)


@pytest.mark.parametrize(("key", "suffix"), KEYS)
def test_taking_out_what_is_not_there_deletes_nothing(capsys, folder, key, suffix):
    assert run(capsys, "project", "set", folder, f"{key}=")[0] == 0
    assert untouched(folder)


@pytest.mark.parametrize(("key", "suffix"), KEYS)
def test_putting_one_in_writes_over_no_file_of_the_users(capsys, folder, key, suffix):
    name = put(capsys, folder, key, suffix)
    assert untouched(folder) and (folder / name).read_bytes() == b"new"


@pytest.mark.parametrize(("key", "suffix"), KEYS)
def test_replacing_and_taking_out_touch_only_the_listed_file(capsys, folder, key, suffix):
    first = put(capsys, folder, key, suffix)
    again = put(capsys, folder, key, suffix, b"newer")
    assert again == first and (folder / again).read_bytes() == b"newer"
    other = ".mov" if key == "video" else ".jpg"
    moved = put(capsys, folder, key, other)
    assert untouched(folder) and not (folder / first).exists()
    assert run(capsys, "project", "set", folder, f"{key}=")[0] == 0
    assert untouched(folder) and not (folder / moved).exists()


@pytest.mark.parametrize(("key", "suffix"), KEYS)
def test_the_listed_file_given_again_stays(capsys, folder, key, suffix):
    name = put(capsys, folder, key, suffix)
    assert run(capsys, "project", "set", folder, f"{key}={folder / name}")[0] == 0
    assert listed(folder, key) == name and (folder / name).read_bytes() == b"new"


@pytest.mark.parametrize(("key", "suffix"), KEYS)
@pytest.mark.parametrize("given", ["", "file"])
def test_a_bad_key_later_in_the_command_changes_no_file(capsys, folder, key, suffix, given):
    name = put(capsys, folder, key, suffix)
    source = folder.parent / f"given{suffix}"
    source.write_bytes(b"other")
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    value = source if given else ""
    assert run(capsys, "project", "set", folder, f"{key}={value}", "nosuch=1")[0] == 2
    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()} == before
    assert listed(folder, key) == name


@pytest.mark.parametrize(("key", "suffix"), KEYS)
def test_a_listed_name_outside_the_folder_is_not_deleted(capsys, folder, key, suffix):
    outside = folder.parent / f"keep{suffix}"
    outside.write_bytes(b"keep")
    project = Project.load(folder / "project.json")
    setattr(project, key, f"../{outside.name}")
    project.save(folder / "project.json")
    assert run(capsys, "project", "set", folder, f"{key}=")[0] == 0
    assert outside.read_bytes() == b"keep"


def test_a_save_that_fails_keeps_the_listed_file(capsys, folder, monkeypatch):
    name = put(capsys, folder, "video", ".mp4")

    def full(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(Project, "save", full)
    assert run(capsys, "project", "set", folder, "video=")[0] == 1
    assert (folder / name).exists()


def test_a_video_another_output_uses_stays(capsys, folder):
    name = put(capsys, folder, "video", ".mp4")
    assert run(capsys, "output", "add", folder, "short", "--shape", "tall")[0] == 0
    assert run(capsys, "project", "set", folder, "video=")[0] == 0
    assert untouched(folder) and (folder / name).exists()
    assert Project.load(folder / "project.json").outputs[0].video == name
