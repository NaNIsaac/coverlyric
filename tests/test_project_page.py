"""The page opened on a project folder of the user's: it deletes only files the project lists, and
never writes over a change another program made to project.json."""

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from coverlyric import cli, overlay, project, server
from coverlyric.project import Project

DEMO = Path(cli.__file__).parent / "demo"
TONE = (DEMO / "tone.wav").read_bytes()
COVER = (DEMO / "cover.png").read_bytes()
OWN = ("song.mp4", "song.srt", "cover.psd", "title.txt", "video.srt", "notes.txt", "upload.wav")


@pytest.fixture()
def folder(tmp_path) -> Path:
    folder = tmp_path / "project"
    cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", None, "song")
    for name in OWN:
        (folder / name).write_bytes(b"the user's")
    return folder


@pytest.fixture()
def app(tmp_path, folder):
    return server.App(tmp_path / "home", folder)


def untouched(folder: Path) -> bool:
    return all((folder / name).read_bytes() == b"the user's" for name in OWN)


def elsewhere(folder: Path, **look) -> None:
    other = Project.load(folder / "project.json")
    other.style = replace(other.style, **look)
    other.save(folder / "project.json")


# 1. start over


@pytest.mark.parametrize("action", ["reset", "demo"])
def test_start_over_and_demo_are_refused_on_a_project_folder(app, folder, action):
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    with pytest.raises(ValueError):
        getattr(app, action)()
    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()} == before
    assert app.state()["own_folder"] is True


# 2. a file put in or taken out


def test_a_new_song_deletes_only_the_song_the_project_lists(app, folder):
    (folder / "song.flac").write_bytes(b"not listed")
    app.upload("audio", "new.wav", TONE)
    assert untouched(folder) and (folder / "song.flac").read_bytes() == b"not listed"
    assert (folder / app.project.audio).read_bytes() == TONE


def test_a_new_cover_deletes_only_the_cover_the_project_lists(app, folder):
    (folder / "cover.jpg").write_bytes(b"not listed")
    app.upload("art", "new.jpg", COVER)
    assert untouched(folder) and (folder / "cover.jpg").read_bytes() == b"not listed"
    assert app.project.art != "cover.jpg" and not (folder / "cover.png").exists()


def test_taking_the_title_picture_out_deletes_only_that_picture(app, folder):
    (folder / "title.png").write_bytes(COVER)
    other = Project.load(folder / "project.json")
    other.title_image = "title.png"
    other.save(folder / "project.json")
    app.update({"title_image": ""})
    assert untouched(folder) and not (folder / "title.png").exists()


def test_a_new_video_replaces_no_file_the_project_does_not_list(app, folder, monkeypatch):
    monkeypatch.setattr(overlay, "streams", lambda path: (True, False))
    (folder / "video.mp4").write_bytes(b"a finished video titled video")
    app.upload("video", "b.mp4", b"b")
    assert untouched(folder)
    assert (folder / "video.mp4").read_bytes() == b"a finished video titled video"
    assert (folder / app.project.video).read_bytes() == b"b"


def test_a_listed_name_outside_the_folder_is_never_deleted(tmp_path, folder):
    (tmp_path / "keep.wav").write_bytes(TONE)
    other = Project.load(folder / "project.json")
    other.audio = "../keep.wav"
    other.save(folder / "project.json")
    server.App(tmp_path / "home", folder).upload("audio", "new.wav", TONE)
    assert (tmp_path / "keep.wav").exists()


# 3. opening after an unfinished render


def test_opening_after_an_unfinished_render_leaves_every_making_file(tmp_path, folder):
    app = server.App(tmp_path / "home", folder)
    for name in ("song.making.mp4", "other.making.mp4"):
        (folder / name).write_bytes(b"may be another program's render")
    app.marker.write_text(json.dumps({"out": str(folder / "song.mp4")}), encoding="utf-8")
    again = server.App(tmp_path / "home", folder)
    assert again.job["state"] == "interrupted" and not again.marker.exists()
    assert (folder / "song.making.mp4").exists() and (folder / "other.making.mp4").exists()
    assert untouched(folder)


def test_the_pages_job_files_stay_out_of_the_folder(app, folder):
    assert app.marker.parent == folder / ".cache" / "page"
    assert app.clip_file.parent == folder / ".cache" / "page"


# 4. two writers


def test_a_save_older_than_the_file_is_refused(app, folder):
    seen = app.state()
    elsewhere(folder, lead=2.0)
    with pytest.raises(project.Changed):
        app.update({"rev": seen["rev"], "title": "page", "style": seen["style"]})
    saved = Project.load(folder / "project.json")
    assert saved.style.lead == 2.0 and saved.title == "song"
    assert app.state()["style"]["lead"] == 2.0, "the refusal leaves the page the file's state"


def test_the_pages_own_saves_do_not_make_it_stale(app):
    rev = app.state()["rev"]
    app.update({"rev": rev, "title": "one"})
    app.update({"rev": rev, "title": "two"})
    assert app.project.title == "two" and app.state()["rev"] == rev


def test_a_change_elsewhere_is_in_the_next_state(app, folder):
    rev = app.state()["rev"]
    elsewhere(folder, lead=2.0)
    state = app.state()
    assert state["style"]["lead"] == 2.0 and state["rev"] != rev


def test_a_command_does_not_write_over_a_change_made_while_it_ran(folder):
    slow = Project.load(folder / "project.json")
    elsewhere(folder, lead=2.0)
    slow.title = "slow"
    with pytest.raises(project.Changed):
        slow.save(folder / "project.json")
    assert Project.load(folder / "project.json").style.lead == 2.0


def test_over_http_a_stale_save_is_a_409(app, folder):
    ref: list = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(app, ref))
    ref.append(httpd)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        seen = app.state()
        elsewhere(folder, lead=2.0)
        body = json.dumps({"rev": seen["rev"], "title": "page"}).encode()
        url = f"http://127.0.0.1:{httpd.server_address[1]}/api/state"
        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as said:
            urllib.request.urlopen(req)
        assert said.value.code == 409
        assert json.loads(said.value.read())["state"]["style"]["lead"] == 2.0
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_automatic_timing_does_not_write_over_lyrics_changed_during_the_run(app, folder):
    app.update({"lines": [[None, "one"], [None, "two"]]})
    app.auto_texts = ["one", "two"]
    other = Project.load(folder / "project.json")
    other.lines = [(None, "one"), (None, "changed")]
    other.save(folder / "project.json")
    result = {"lines": [[1.0, "one"], [2.0, "two"]], "notes": []}
    (app.scratch / "auto-result.json").write_text(json.dumps(result), "utf-8")
    proc = subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.PIPE, text=True)
    app.auto_proc, app.auto = proc, {"state": "running"}
    app.watch_auto(proc)
    assert Project.load(folder / "project.json").lines == [(None, "one"), (None, "changed")]
