"""A picture of the title lettered by hand takes the title's place in the opening panel: its dark ink
in the title's grey on clear, the artist under it (render.title_lettering, opening_panel); it is set
with `project set title_image=` and on the page, and taken out again."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from coverlyric import __main__ as entry
from coverlyric import cli, render, server
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo"


def lettering(path: Path, clear: bool = False) -> Path:
    """A dark bar on white (or on clear) with room around it."""
    img = Image.new("RGBA", (400, 200), (255, 255, 255, 0 if clear else 255))
    ImageDraw.Draw(img).rectangle((100, 80, 299, 119), fill=(0, 0, 0, 255))
    img.save(path)
    return path


def blank(path: Path) -> Path:
    Image.new("RGB", (100, 100), "white").save(path)
    return path


@pytest.mark.parametrize("clear", [False, True])
def test_the_ink_is_cut_out_and_coloured(tmp_path, clear):
    out = render.title_lettering(str(lettering(tmp_path / "t.png", clear)), 20, 1000, (10, 20, 30))
    assert out.size == (100, 20), "cut to the ink, then scaled to the height"
    a = np.asarray(out)
    assert (a[..., 3] > 250).mean() > 0.9
    assert (a[..., :3] == (10, 20, 30)).all()


def test_a_wide_lettering_fits_the_width(tmp_path):
    out = render.title_lettering(str(lettering(tmp_path / "t.png")), 1000, 50, (0, 0, 0))
    assert out.size == (50, 10)


def test_no_lettering_from_a_blank_or_broken_file(tmp_path):
    assert render.title_lettering(str(blank(tmp_path / "b.png")), 20, 20, (0, 0, 0)) is None
    (tmp_path / "x.png").write_bytes(b"not a picture")
    assert render.title_lettering(str(tmp_path / "x.png"), 20, 20, (0, 0, 0)) is None


def test_the_panel_draws_the_lettering_in_the_title_grey(tmp_path):
    song = Project.load(DEMO / "demo.json").song()
    style = render.Style()
    typed = np.asarray(render.opening_panel(song, style))
    hand = np.asarray(
        render.opening_panel(replace(song, title_image=str(lettering(tmp_path / "t.png"))), style)
    )
    assert (typed != hand).any()
    solid = hand[hand[..., 3] == 255][:, :3]
    assert {0xD2, 0xB4} <= set(np.unique(solid)), (
        "the lettering in the title grey, the artist dimmer"
    )
    rows = np.flatnonzero((hand[..., 3] == 255).any(axis=1))
    bar = rows[(hand[rows][..., :3] == 0xD2).all(axis=2).any(axis=1)]
    artist = rows[(hand[rows][..., :3] == 0xB4).all(axis=2).any(axis=1)]
    assert bar.max() < artist.min(), "the artist under the lettering"


def test_a_lettering_that_cannot_be_read_leaves_the_typed_title(tmp_path):
    song = Project.load(DEMO / "demo.json").song()
    style = render.Style()
    typed = np.asarray(render.opening_panel(song, style))
    gone = replace(song, title_image=str(tmp_path / "gone.png"))
    assert (np.asarray(render.opening_panel(gone, style)) == typed).all()


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*argv, "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return done.value.code, json.loads(out[-1])


@pytest.fixture()
def song(tmp_path) -> Path:
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("첫 줄\n둘째 줄", encoding="utf-8")
    folder = tmp_path / "노래"
    cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", lyrics, "노래")
    return folder


def test_set_and_drop_the_title_image(capsys, song, tmp_path):
    code, _ = run(
        capsys, "project", "set", str(song), f"title_image={lettering(tmp_path / 'a.png')}"
    )
    assert code == 0
    assert [p.name for p in song.glob("title.*")] == ["title.png"]
    code, shown = run(capsys, "project", "show", str(song))
    assert Path(shown["title_image"]).name == "title.png"
    assert Project.load(song / "project.json").song().title_image.endswith("title.png")
    code, _ = run(capsys, "project", "set", str(song), "title_image=")
    assert code == 0 and not list(song.glob("title.*"))
    assert Project.load(song / "project.json").title_image == ""


def test_a_picture_with_no_lettering_is_refused(capsys, song, tmp_path):
    code, _ = run(capsys, "project", "set", str(song), f"title_image={blank(tmp_path / 'b.png')}")
    assert code == 2
    assert not list(song.glob("title.*"))


@pytest.fixture()
def app(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    return app


def test_the_page_uploads_and_drops_the_lettering(app, tmp_path):
    body = lettering(tmp_path / "a.png").read_bytes()
    app.upload("title", "글씨.png", body)
    assert app.project.title_image == "title.png" and app.state()["has_title_image"]
    assert (app.work / "title.png").read_bytes() == body
    app.update({"title_image": ""})
    assert app.project.title_image == "" and not list(app.work.glob("title.*"))
    assert not app.state()["has_title_image"]


def test_the_page_refuses_a_picture_with_no_lettering(app, tmp_path):
    with pytest.raises(ValueError) as e:
        app.upload("title", "b.png", blank(tmp_path / "b.png").read_bytes())
    assert "글씨를 찾을 수 없습니다" in str(e.value)
    assert app.project.title_image == ""
    assert not list(app.work.glob("upload.*")) and not list(app.work.glob("title.*"))
