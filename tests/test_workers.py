import pytest

from coverlyric import __main__ as cli
from coverlyric import media


@pytest.mark.parametrize(
    ("cores", "available", "expected"),
    [
        (12, 890, 2),  # 8 GB installed but only 890 MB free: the free memory decides
        (12, 1400, 2),  # under 2 GB free: two at most, the encoder sets the pace
        (12, 2047, 2),
        (12, 2048, 6),
        (12, 500, 1),
        (4, 3000, 3),  # cores minus one
        (2, 8000, 1),
        (16, 32000, 6),
        (8, 300, 1),  # less than the encoder needs: still one worker
        (8, 0.0, 6),  # memory unknown: cores decide
    ],
)
def test_workers_follow_cores_and_free_memory(monkeypatch, cores, available, expected):
    monkeypatch.delenv("COVERLYRIC_WORKERS", raising=False)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: cores)
    monkeypatch.setattr(media, "memory_mb", lambda: (8000.0, available))
    assert cli.workers() == expected


def test_workers_can_be_set(monkeypatch):
    monkeypatch.setenv("COVERLYRIC_WORKERS", "3")
    assert cli.workers() == 3


def test_memory_is_read():
    total, available = media.memory_mb()
    assert total > available > 0


@pytest.mark.parametrize(("given", "expected"), [("abc", None), ("0", None), ("50", 8), (" 3 ", 3)])
def test_a_bad_worker_setting_does_not_break_the_render(monkeypatch, given, expected):
    monkeypatch.setenv("COVERLYRIC_WORKERS", given)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(media, "memory_mb", lambda: (8000.0, 4000.0))
    assert cli.workers() == (expected or 3)
