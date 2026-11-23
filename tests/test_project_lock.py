"""The project lock gives up with a clear error instead of waiting for ever (#75)."""

import time
from pathlib import Path

import pytest

from coverlyric import project
from coverlyric.project import Busy, Project

DEMO = Path(project.__file__).parent / "demo" / "demo.json"


def test_a_held_lock_is_busy_after_the_wait(tmp_path):
    with project.locked(tmp_path):
        began = time.monotonic()
        busy = pytest.raises(Busy, match="project.json is being saved by another coverlyric")
        with busy, project.locked(tmp_path, wait=0.2):
            pass
        assert 0.2 <= time.monotonic() - began < 2.0


def test_the_lock_is_taken_again_once_let_go(tmp_path):
    with project.locked(tmp_path):
        pass
    with project.locked(tmp_path, wait=0.2):
        pass


def test_a_save_while_the_lock_is_held_says_so(tmp_path, monkeypatch):
    file = tmp_path / "project.json"
    file.write_bytes(DEMO.read_bytes())
    for name in ("tone.wav", "cover.png"):
        (tmp_path / name).write_bytes((DEMO.parent / name).read_bytes())
    p = Project.load(file)
    p.title = "x"
    monkeypatch.setattr(project, "LOCK_WAIT", 0.2)
    with project.locked(tmp_path), pytest.raises(Busy, match=str(file).replace("\\", "\\\\")):
        p.save(file)
    p.save(file)
    assert Project.load(file).title == "x"
