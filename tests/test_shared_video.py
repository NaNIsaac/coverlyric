"""A video two outputs share: replacing one output's leaves the other's as it was."""

import pytest

from coverlyric import cli, overlay, server


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "streams", lambda path: (True, False))
    monkeypatch.setattr(overlay, "length", lambda path: 10.0)
    app = server.App(tmp_path)
    app.demo()
    app.upload("video", "a.mp4", b"a")
    cli.add_output(app.project, "short", None, "tall")
    app.project.current = "wide"
    return app


def check(app, wide: bytes) -> None:
    first, short = app.project.outputs
    assert (app.work / short.video).read_bytes() == b"a"
    assert (app.work / first.video).read_bytes() == wide


def test_the_page_keeps_the_shared_video(app):
    app.upload("video", "b.mp4", b"b")
    check(app, b"b")


def test_the_command_keeps_the_shared_video(app, tmp_path):
    source = tmp_path / "b.mp4"
    source.write_bytes(b"b")
    app.project.video = cli.put_video(app.project, str(source))
    check(app, b"b")
