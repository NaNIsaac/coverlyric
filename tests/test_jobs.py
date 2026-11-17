import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from coverlyric import server

# A parent that starts a child which touches a file every 0.1 s, the way `uv run` starts the
# transcriber and the render starts its workers and ffmpeg.
PARENT = """
import subprocess, sys, time
beat = sys.argv[1]
child = "import sys, time, pathlib\\nwhile True:\\n    pathlib.Path(sys.argv[1]).write_text(str(time.time()))\\n    time.sleep(0.1)"
subprocess.Popen([sys.executable, "-c", child, beat])
print("started", flush=True)
time.sleep(60)
"""


def start_tree(tmp_path: Path) -> tuple[subprocess.Popen, Path]:
    beat = tmp_path / "beat.txt"
    script = tmp_path / "parent.py"
    script.write_text(PARENT, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(script), str(beat)],
        stdout=subprocess.PIPE,
        text=True,
        **server.new_group(),
    )
    for _ in range(100):
        if beat.exists():
            break
        time.sleep(0.1)
    assert beat.exists()
    return proc, beat


def still_beating(beat: Path) -> bool:
    before = beat.read_text()
    time.sleep(0.5)
    return beat.read_text() != before


def test_cancel_ends_the_transcriber_under_uv(tmp_path):
    app = server.App(tmp_path)
    app.auto_proc, beat = start_tree(tmp_path)
    app.auto = {"state": "running"}
    app.stop_auto()
    app.auto_proc.wait(timeout=10)
    assert not still_beating(beat)


def test_stop_ends_the_render_workers(tmp_path):
    app = server.App(tmp_path)
    app.proc, beat = start_tree(tmp_path)
    app.job = {"state": "running"}
    app.stop_render()
    app.proc.wait(timeout=10)
    assert not still_beating(beat)


def ending(code: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import time; time.sleep(0.5); print('boom'); raise SystemExit({code})",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_an_old_transcriber_does_not_overwrite_the_new_run(tmp_path):
    app = server.App(tmp_path)
    old = ending(1)
    app.auto_proc = old
    watcher = threading.Thread(target=app.watch_auto, args=(old,))
    watcher.start()
    app.auto_proc = ending(0)
    app.auto = {"state": "running", "phase": "listen"}
    watcher.join(timeout=10)
    assert app.auto == {"state": "running", "phase": "listen"}
    app.auto_proc.wait()


def test_an_old_render_does_not_overwrite_the_new_one(tmp_path):
    app = server.App(tmp_path)
    old = ending(1)
    app.proc = old
    watcher = threading.Thread(target=app.watch, args=(old, tmp_path / "x.mp4"))
    watcher.start()
    app.proc = ending(0)
    app.job = {"state": "running", "done": 1.0}
    watcher.join(timeout=10)
    assert app.job == {"state": "running", "done": 1.0}
    app.proc.wait()


def test_a_render_waits_for_automatic_timing(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    app.auto = {"state": "running", "phase": "listen"}
    try:
        with pytest.raises(ValueError, match="자동 맞추기"):
            app.start_render()
    finally:
        if app.proc:
            server.kill_tree(app.proc)
