"""The page shows the running version, the same one `coverlyric --version` prints."""

from pathlib import Path

from coverlyric import __version__, server

WEB = Path(server.__file__).parent / "web"


def test_the_page_state_carries_the_version(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    assert app.state()["version"] == __version__


def test_the_page_has_a_place_for_it():
    assert 'id="version"' in (WEB / "index.html").read_text(encoding="utf-8")
    assert "state.version" in (WEB / "app.js").read_text(encoding="utf-8")
