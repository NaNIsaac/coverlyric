import pytest

from coverlyric import auto


def words(*items):
    """(start, text) pairs as heard words, each lasting 0.4 s."""
    return [{"start": s, "end": s + 0.4, "word": w} for s, w in items]


def test_lines_start_at_their_first_heard_word():
    lyrics = ["첫 번째 줄", "두 번째 줄"]
    heard = words((3.0, "첫"), (3.4, "번째"), (3.8, "줄"), (6.0, "두"), (6.4, "번째"), (6.8, "줄"))
    lines, notes = auto.align(lyrics, heard)
    assert lines[:2] == [(3.0, "첫 번째 줄"), (6.0, "두 번째 줄")]
    assert lines[-1][1] == ""  # the band empties after the last line
    assert notes == []


def test_a_line_not_heard_goes_between_its_neighbours():
    lyrics = ["하나 둘", "전혀 안 들린 줄", "셋 넷"]
    heard = words((2.0, "하나"), (2.4, "둘"), (8.0, "셋"), (8.4, "넷"))
    lines, notes = auto.align(lyrics, heard)
    assert lines[0][0] == 2.0 and lines[2][0] == 8.0
    assert 2.8 < lines[1][0] < 8.0
    assert notes == [{"line": 1, "kind": "unplaced", "heard": ""}]


def test_a_misheard_line_keeps_the_given_text_and_is_noted():
    lyrics = ["바람이 분다"]
    heard = words((1.0, "바람이"), (1.4, "분가"))
    lines, notes = auto.align(lyrics, heard)
    assert lines[0] == (1.0, "바람이 분다")
    assert notes[0]["kind"] == "differs" and notes[0]["heard"] == "바람이분가"


def test_a_long_pause_gets_an_empty_line():
    lyrics = ["앞 줄", "뒤 줄"]
    heard = words((1.0, "앞"), (1.4, "줄"), (20.0, "뒤"), (20.4, "줄"))
    lines, _ = auto.align(lyrics, heard)
    assert [text for _, text in lines] == ["앞 줄", "", "뒤 줄", ""]


def test_transcribe_needs_the_auto_extra_and_a_downloaded_model():
    pytest.importorskip("faster_whisper", reason="the auto extra is not installed")
    if not auto.has_model("small"):
        pytest.skip("the small model is not downloaded; the test does not download 480 MB")
    from pathlib import Path

    from coverlyric.project import Project
    from coverlyric.render import __file__ as render_file

    demo = Project.load(Path(render_file).parent / "demo" / "demo.json")
    heard = auto.transcribe(demo.song().audio, "small")
    assert isinstance(heard, list)  # the demo is a tune without words


def test_found_lists_only_lines_heard_so_far():
    lyrics = ["첫 번째 줄", "두 번째 줄", "세 번째 줄"]
    heard = words((3.0, "첫"), (3.4, "번째"), (3.8, "줄"), (6.0, "두"), (6.4, "번째"), (6.8, "줄"))
    assert auto.found(lyrics, heard, until=7.2) == [[0, 3.0], [1, 6.0]]
    assert auto.found(lyrics, heard, until=4.0) == [[0, 3.0]]


def test_downloaded_mb_counts_partial_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    blobs = tmp_path / "models--Systran--faster-whisper-small" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "abc.incomplete").write_bytes(b"\0" * 2**20)
    assert auto.downloaded_mb("small") == 1.0
    assert not auto.has_model("small")
