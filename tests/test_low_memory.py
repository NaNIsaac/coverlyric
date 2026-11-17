"""Automatic timing on a PC low on memory: smaller models, then a plain message (#13)."""

import json
import logging
import subprocess
import sys

import pytest

from coverlyric import __main__ as cli
from coverlyric import auto, server

NO_MEMORY = RuntimeError("mkl_malloc: failed to allocate memory")


@pytest.fixture()
def job(tmp_path):
    path = tmp_path / "auto-job.json"
    path.write_text(
        json.dumps({"audio": "song.wav", "lyrics": ["하나"], "model": "small"}), "utf-8"
    )
    return path


def fake_transcribe(fails: set[str], tried: list[str]):
    def transcribe(audio, name, report, heard):
        tried.append(name)
        if name in fails:
            raise NO_MEMORY
        return [{"start": 1.0, "end": 1.5, "word": "하나"}]

    return transcribe


def test_a_model_without_memory_falls_back_to_smaller_ones(job, monkeypatch, capsys):
    tried = []
    monkeypatch.setattr(auto, "transcribe", fake_transcribe({"small"}, tried))
    cli.run_auto(job)
    assert tried == ["small", "base"]
    assert "smaller base" in capsys.readouterr().out
    assert json.loads(job.with_name("auto-result.json").read_text("utf-8"))["lines"]


def test_when_no_model_gets_memory_the_job_says_so(job, monkeypatch, capsys):
    tried = []
    monkeypatch.setattr(auto, "transcribe", fake_transcribe({"small", "base", "tiny"}, tried))
    with pytest.raises(SystemExit) as e:
        cli.run_auto(job)
    assert e.value.code == auto.NO_MEMORY_EXIT
    assert tried == ["small", "base", "tiny"]
    assert "error memory" in capsys.readouterr().out


def test_other_errors_are_not_taken_for_memory(job, monkeypatch):
    def broken(audio, name, report, heard):
        raise FileNotFoundError("song.wav")

    monkeypatch.setattr(auto, "transcribe", broken)
    with pytest.raises(FileNotFoundError):
        cli.run_auto(job)


def run_watch(tmp_path, lines: list[str], code: int) -> server.App:
    app = server.App(tmp_path)
    script = tmp_path / "child.py"
    script.write_text(
        "import sys\n" + "".join(f"print({line!r})\n" for line in lines) + f"sys.exit({code})\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, text=True, encoding="utf-8"
    )
    app.auto_proc = proc
    app.auto = {"state": "running", "phase": "install"}
    app.watch_auto(proc)
    return app


LOG_LINES = [
    "Installed 42 packages in 2.1s",
    "UserWarning: The secret `HF_TOKEN` does not exist in your Colab secrets.",
    "phase load 0.0 0.0",
]


def test_the_page_says_memory_ran_out_without_the_logs(tmp_path, caplog):
    lines = [*LOG_LINES, "smaller base", "smaller tiny", "error memory"]
    with caplog.at_level(logging.ERROR, logger="coverlyric"):
        app = run_watch(tmp_path, lines, auto.NO_MEMORY_EXIT)
    assert app.auto == {"state": "error", "message": server.AUTO_NO_MEMORY}
    assert "HF_TOKEN" in caplog.text  # the log file keeps what the page leaves out


def test_other_failures_get_a_plain_message_too(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="coverlyric"):
        app = run_watch(tmp_path, [*LOG_LINES, "Traceback (most recent call last):"], 1)
    message = app.auto["message"]
    assert message.startswith("자동 맞추기를 하지 못했습니다")
    assert "HF_TOKEN" not in message and "Installed" not in message
    assert "Traceback" in caplog.text


def test_the_page_hears_about_the_smaller_model(tmp_path):
    app = server.App(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-c", "print('smaller base', flush=True); import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        text=True,
    )
    app.auto_proc = proc
    app.auto = {"state": "running", "phase": "load"}
    import threading

    watcher = threading.Thread(target=app.watch_auto, args=(proc,), daemon=True)
    watcher.start()
    try:
        for _ in range(100):
            if app.auto.get("smaller"):
                break
            watcher.join(0.05)
        assert app.auto["smaller"] == "base"
    finally:
        server.kill_tree(proc)
        watcher.join(5)


def test_the_child_does_not_look_for_a_hugging_face_token(tmp_path, monkeypatch):
    app = server.App(tmp_path)
    app.demo()
    monkeypatch.setenv("COVERLYRIC_UV", sys.executable)
    monkeypatch.setattr(server.App, "check_disk", lambda self, model: None)
    seen = {}

    class Fake:
        stdout = iter(())
        pid = 0

        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)

        def wait(self):
            return 1

        def poll(self):
            return 1

    monkeypatch.setattr(server.subprocess, "Popen", Fake)
    app.start_auto("small")
    assert seen["env"]["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
