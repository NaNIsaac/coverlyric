"""One song, many outputs: a format 1 project loads as one output and renders the same frames; format 2
keeps the song once and each output's style, moving picture and video; the current output is mirrored
at the top level for the release before."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from coverlyric import project as model
from coverlyric import render
from coverlyric.project import Output, Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


def frame(p: Project, at: float) -> np.ndarray:
    return np.asarray(render.frame(at, p.preview_lines(), p.song(), p.style))


def saved(p: Project, folder: Path) -> Project:
    path = folder / "project.json"
    p.save(path)
    return Project.load(path)


def test_an_old_project_is_one_output_with_the_same_frames(tmp_path):
    old = Project.load(DEMO)
    assert [o.id for o in old.outputs] == ["wide"] and old.current == "wide"
    p = Project.from_dict(DEMO.parent, json.loads(json.dumps(old.to_dict())))
    assert p.style == old.style and p.song() == old.song()
    assert (frame(p, 5.0) == frame(old, 5.0)).all()


def test_an_old_upright_project_is_a_short(tmp_path):
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    data["style"] = {**data.get("style", {}), "shape": "tall", "clip_from": 2.0, "clip_to": 10.0}
    p = Project.from_dict(DEMO.parent, data)
    assert p.current == "short" and p.style.shape == "tall" and p.style.clip_to == 10.0
    again = Project.from_dict(DEMO.parent, json.loads(json.dumps(p.to_dict())))
    assert (frame(again, 4.0) == frame(p, 4.0)).all()


def test_the_file_keeps_the_song_once_and_each_output(tmp_path):
    p = Project(tmp_path, title="t", lines=[(1.0, "가"), (3.0, "나")])
    p.outputs.append(Output("short", render.Style(shape="tall"), ["a.png"], "clip.mp4"))
    again = saved(p, tmp_path)
    assert [o.id for o in again.outputs] == ["wide", "short"]
    assert again.outputs[1] == p.outputs[1]
    data = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert data["format"] == model.FORMAT and data["lines"] == [[1.0, "가"], [3.0, "나"]]


def test_the_current_output_is_the_one_worked_on(tmp_path):
    p = Project(tmp_path, lines=[(1.0, "가")])
    p.outputs.append(Output("short", render.Style(shape="tall")))
    p.current = "short"
    p.style = replace(p.style, clip_to=9.0)
    p.anim = ["walk.gif"]
    assert p.outputs[0].style == render.Style() and p.outputs[0].anim == []
    assert p.outputs[1].style.clip_to == 9.0 and p.outputs[1].anim == ["walk.gif"]
    again = saved(p, tmp_path)
    assert again.current == "short" and again.style.clip_to == 9.0
    p.current = "wide"
    assert p.style == render.Style() and p.lines == again.lines


def test_an_unknown_current_falls_back_to_the_first(tmp_path):
    data = Project(tmp_path).to_dict() | {"current": "gone"}
    assert Project.from_dict(tmp_path, data).current == "wide"


def test_the_top_level_mirror_reads_as_the_current_output(tmp_path):
    p = Project(tmp_path, title="t")
    p.outputs.append(Output("short", render.Style(shape="tall", lead=1.0), ["a.png"], "v.mp4"))
    p.current = "short"
    data = p.to_dict()
    older = {k: v for k, v in data.items() if k not in ("format", "outputs", "current")}
    assert older == p.flat()
    seen = Project.from_dict(tmp_path, older)
    assert (seen.style, seen.anim, seen.video) == (p.style, p.anim, p.video)
