"""The page's outputs: the state lists them, choosing a shape goes to the song's video of that shape or
adds one, and each output keeps its own video and moving picture files."""

import pytest

from coverlyric import overlay, server


@pytest.fixture()
def app(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    return app


def ids(state: dict) -> list[str]:
    return [o["id"] for o in state["outputs"]]


def test_the_state_lists_one_output_at_first(app):
    state = app.state()
    assert ids(state) == ["wide"] and state["current"] == "wide"
    assert state["outputs"][0]["file"].endswith(".mp4")


def test_a_shape_goes_to_its_output_or_adds_one(app):
    state = app.choose_output({"shape": "tall"})
    assert ids(state) == ["wide", "short"] and state["current"] == "short"
    assert state["style"]["shape"] == "tall" and state["style"]["fps"] == 30
    state = app.choose_output({"shape": "wide"})
    assert ids(state) == ["wide", "short"] and state["current"] == "wide"
    assert state["style"]["shape"] == "wide"
    state = app.choose_output({"shape": "tall"})
    assert ids(state) == ["wide", "short"] and state["current"] == "short"
    state = app.choose_output({"use": "wide"})
    assert state["current"] == "wide"


def test_page_changes_go_to_the_current_output_only(app):
    app.choose_output({"shape": "tall"})
    style = dict(app.state()["style"], lead=2.0)
    app.update({"style": style})
    assert app.project.outputs[1].style.lead == 2.0
    assert app.project.outputs[0].style.lead == 0.0


@pytest.mark.parametrize("choice", [{"use": "gone"}, {"shape": "round"}])
def test_a_wrong_choice_is_a_message(app, choice):
    with pytest.raises(ValueError):
        app.choose_output(choice)


def test_each_output_keeps_its_own_video(app, monkeypatch):
    monkeypatch.setattr(overlay, "streams", lambda path: (True, False))
    app.upload("video", "a.mp4", b"a")
    app.choose_output({"shape": "tall"})
    assert app.project.video == "video.mp4", "a new output starts with the same video"
    app.upload("video", "b.mp4", b"b")
    assert app.project.video == "video-short.mp4"
    assert (app.work / "video.mp4").read_bytes() == b"a"
    app.update({"video": ""})
    assert not (app.work / "video-short.mp4").exists() and (app.work / "video.mp4").exists()
    assert app.project.outputs[0].video == "video.mp4"


def test_a_moving_picture_another_output_uses_stays(app):
    folder = app.work / "anim"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"x")
    app.project.anim = ["anim/a.png"]
    app.choose_output({"shape": "tall"})
    assert app.project.anim == ["anim/a.png"]
    app.update({"anim": []})
    assert app.project.anim == [] and (folder / "a.png").exists()
    app.choose_output({"shape": "wide"})
    assert app.project.anim == ["anim/a.png"]


def test_a_save_made_before_a_switch_leaves_the_new_output_alone(app):
    before = app.state()
    app.choose_output({"shape": "tall"})
    app.update({"current": "wide", "title": "New", "style": before["style"], "anim": []})
    assert app.project.style.shape == "tall" and app.project.title == "New"


def test_a_switch_saves_the_page_first(app):
    style = dict(app.state()["style"], lead=2.0)
    state = app.choose_output({"current": "wide", "style": style, "shape": "tall"})
    assert state["current"] == "short" and app.project.outputs[0].style.lead == 2.0
