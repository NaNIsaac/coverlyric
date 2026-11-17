import pytest

from coverlyric import __main__ as cli
from coverlyric import media


@pytest.mark.parametrize(
    ("cores", "gb", "expected"),
    [
        (4, 3.8, 2),  # a 4 GB PC reports a little under 4 GB
        (2, 4.0, 1),  # two cores: one is left for the encoder
        (16, 32.0, 6),
        (8, 1.5, 1),
        (8, 0.0, 6),  # memory unknown: cores decide
    ],
)
def test_workers_follow_cores_and_memory(monkeypatch, cores, gb, expected):
    monkeypatch.delenv("COVERLYRIC_WORKERS", raising=False)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: cores)
    monkeypatch.setattr(media, "memory_gb", lambda: gb)
    assert cli.workers() == expected


def test_workers_can_be_set(monkeypatch):
    monkeypatch.setenv("COVERLYRIC_WORKERS", "3")
    assert cli.workers() == 3


def test_memory_is_read():
    assert media.memory_gb() > 0
