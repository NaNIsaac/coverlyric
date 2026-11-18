"""Where finished videos and saved timing files go: a folder the user picks, kept across runs."""

import json
import subprocess

import pytest

from coverlyric import server


def test_the_default_folder_is_in_the_program_folder(tmp_path):
    app = server.App(tmp_path)
    assert app.output == tmp_path / "만든 영상" and app.output.is_dir()
    assert app.state()["output_default"] is True


def test_a_picked_folder_is_kept_after_a_restart(tmp_path):
    folder = tmp_path / "videos"
    state = server.App(tmp_path / "home").set_output(str(folder))
    assert state["output"] == str(folder.resolve()) and state["output_default"] is False
    again = server.App(tmp_path / "home")
    assert again.output == folder.resolve()
    assert again.set_output("")["output_default"] is True
    assert server.App(tmp_path / "home").output == tmp_path / "home" / "만든 영상"


def test_a_folder_that_is_gone_falls_back_to_the_default(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"output": str(tmp_path / "usb")}), "utf-8")
    assert server.App(home).output == home / "만든 영상"
    (home / "settings.json").write_text("not json", "utf-8")
    assert server.App(home).output == home / "만든 영상"


def test_a_folder_that_takes_no_files_is_refused(tmp_path, monkeypatch):
    app = server.App(tmp_path)

    def refuse(**_):
        raise PermissionError("read-only")

    monkeypatch.setattr(server.tempfile, "TemporaryFile", refuse)
    with pytest.raises(ValueError, match="저장할 수 없습니다"):
        app.set_output(str(tmp_path / "locked"))
    assert app.output == tmp_path / "만든 영상"


def test_the_dialog_picks_or_cancels(tmp_path, monkeypatch):
    app = server.App(tmp_path)
    monkeypatch.setattr(server, "ask_folder", lambda start: None)
    assert app.pick_output()["output_default"] is True
    monkeypatch.setattr(server, "ask_folder", lambda start: tmp_path / "picked")
    assert app.pick_output()["output"] == str((tmp_path / "picked").resolve())


@pytest.mark.parametrize(
    ("code", "out", "picked"), [(0, "D:/songs\n", "D:/songs"), (0, "\n", None), (1, "", None)]
)
def test_the_dialog_child_answers_with_one_line(tmp_path, monkeypatch, code, out, picked):
    def run(cmd, **_):
        assert cmd[-2:] == ["pick-folder", str(tmp_path)]
        return subprocess.CompletedProcess(cmd, code, out, "")

    monkeypatch.setattr(server.subprocess, "run", run)
    found = server.ask_folder(tmp_path)
    assert (str(found).replace("\\", "/") if found else None) == picked


def test_timing_files_are_saved_into_the_folder(tmp_path):
    app = server.App(tmp_path)
    app.update({"title": "봄 노래", "lines": [[None, "첫 줄"]]})
    with pytest.raises(ValueError, match="시간이 맞춰진 줄이 없습니다"):
        app.save_timing("srt")
    app.update({"lines": [[1.0, "첫 줄"], [3.0, "둘째 줄"]]})
    app.set_output(str(tmp_path / "videos"))
    saved = app.save_timing("srt")
    path = tmp_path / "videos" / "봄 노래.srt"
    assert saved["path"] == str(path.resolve())
    assert "00:00:01,000 --> 00:00:03,000\n첫 줄" in path.read_text("utf-8")
    assert app.save_timing("lrc")["name"] == "봄 노래.lrc"


class Done:
    stdout = iter(())

    def wait(self):
        return 0


def test_a_finished_render_names_the_files_beside_the_video(tmp_path):
    app = server.App(tmp_path)
    out = app.output / "봄 노래.mp4"
    for suffix in (".mp4", ".srt", ".lrc"):
        out.with_suffix(suffix).write_bytes(b"x")
    app.proc = proc = Done()
    app.job = {"state": "running", "started": 0}
    app.watch(proc, out)
    assert app.job["state"] == "done"
    assert app.job["files"] == ["봄 노래.mp4", "봄 노래.srt", "봄 노래.lrc"]
    assert app.job["folder"] == str(app.output)
