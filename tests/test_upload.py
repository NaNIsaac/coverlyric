"""A file that cannot be read leaves the song or cover already in the project as it was (#14)."""

import pytest

from coverlyric import server


@pytest.fixture()
def app(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    return app


def test_a_bad_song_file_keeps_the_current_song(app):
    song = app.work / app.project.audio
    before = (app.project.audio, app.project.duration, song.read_bytes())
    with pytest.raises(ValueError) as e:
        app.upload("audio", "x.mp3", b"this is a text file, not a song")
    assert "노래 파일을 읽을 수 없습니다" in str(e.value)
    assert str(app.work) not in str(e.value) and ":" not in str(e.value)
    assert (app.project.audio, app.project.duration, song.read_bytes()) == before
    assert sorted(p.name for p in app.work.glob("*song*")) == [song.name]
    assert not list(app.work.glob("upload.*"))


def test_a_bad_cover_file_keeps_the_current_cover(app):
    cover = app.work / app.project.art
    before = (app.project.art, cover.read_bytes())
    with pytest.raises(ValueError) as e:
        app.upload("art", "x.png", b"not a picture")
    assert "그림 파일을 읽을 수 없습니다" in str(e.value)
    assert (app.project.art, cover.read_bytes()) == before
    assert sorted(p.name for p in app.work.glob("*cover*")) == [cover.name]


def test_a_good_song_replaces_the_old_one(app):
    app.upload("audio", "new.wav", (app.work / app.project.audio).read_bytes())
    assert [p.name for p in app.work.glob("song.*")] == [app.project.audio]
    assert app.project.duration > 0
