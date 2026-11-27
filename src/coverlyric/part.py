"""A Short's part picked by hand: moving either end by a beat or a bar, and what the part holds.

With a beat grid (`sections.grid`, in the "align" extra) a beat is the next beat of the song and a
bar four of them. Without one, a beat is BEAT_STEP seconds and a bar the next line start."""

from __future__ import annotations

from collections.abc import Sequence

from .sections import BEATS_PER_BAR, SNAP

BEAT_STEP = 0.1  # seconds an end moves by "a beat" when the song has no beat grid
HOLD = 0.15  # seconds a line's last letter is taken to sound after it starts
PER_LETTER = 0.3  # seconds a letter is taken to last when a line has no letter times
MIN_LENGTH = 0.5
NEAR = 60.0  # seconds either side of the part whose beats and bar lines the page draws


def _on(t: float, beats: Sequence[float]) -> int | None:
    i = min(range(len(beats)), key=lambda k: abs(beats[k] - t))
    return i if abs(beats[i] - t) <= SNAP else None


def step(
    t: float,
    by: int,
    unit: str,
    duration: float,
    beats: Sequence[float] | None = None,
    starts: Sequence[float] = (),
) -> float:
    """`t` moved `by` beats or bars (`unit` "beat" or "bar"), kept within the song. An end off the
    grid moves to the next beat or bar line in that direction first, counting as the first step."""
    if not by:
        return t
    if beats:
        per = BEATS_PER_BAR if unit == "bar" else 1
        i = _on(t, beats)
        if i is not None:
            j = i + by * per
        elif by > 0:
            j = next((k for k, b in enumerate(beats) if b > t), len(beats)) + by * per - 1
        else:
            j = max((k for k, b in enumerate(beats) if b < t), default=-1) + by * per + 1
        if j < 0:
            return 0.0
        if j >= len(beats):
            return duration
        return float(beats[j])
    if unit == "beat":
        return round(min(duration, max(0.0, t + by * BEAT_STEP)), 3)
    marks = sorted({0.0, *starts, duration})
    for _ in range(abs(by)):
        if by > 0:
            t = next((m for m in marks if m > t + 1e-6), duration)
        else:
            t = max((m for m in marks if m < t - 1e-6), default=0.0)
    return t


def move(
    first: float,
    last: float,
    end: str,
    by: int,
    unit: str,
    duration: float,
    beats: Sequence[float] | None = None,
    starts: Sequence[float] = (),
) -> tuple[float, float]:
    """The part with its `end` ("from" or "to") moved; an end that would pass the other stays."""
    if end == "from":
        t = step(first, by, unit, duration, beats, starts)
        return (t, last) if t <= last - MIN_LENGTH else (first, last)
    t = step(last, by, unit, duration, beats, starts)
    return (first, t) if t >= first + MIN_LENGTH else (first, last)


def _spans(
    lines: Sequence[tuple[float | None, str]],
    letters: Sequence[tuple[float, str, Sequence[float]]],
    duration: float,
) -> list[tuple[int, str, float, float]]:
    """(place from 1, text, first sound, last sound) of each sung line. The last sound is the last
    letter's time plus HOLD; a line without letter times is taken to last PER_LETTER a letter, up
    to the next line."""
    timed = {(start, text): times for start, text, times in letters}
    sung = [(i + 1, t, text) for i, (t, text) in enumerate(lines) if t is not None and text.strip()]
    sung.sort(key=lambda row: row[1])
    out = []
    for k, (n, t, text) in enumerate(sung):
        nxt = sung[k + 1][1] if k + 1 < len(sung) else duration
        times = timed.get((t, text))
        if times:
            out.append((n, text, min(times), max(times) + HOLD))
        else:
            count = sum(ch.isalnum() for ch in text)
            out.append((n, text, t, min(nxt, t + PER_LETTER * count)))
    return out


def describe(
    first: float,
    last: float,
    lines: Sequence[tuple[float | None, str]],
    duration: float,
    beats: Sequence[float] | None = None,
    letters: Sequence[tuple[float, str, Sequence[float]]] = (),
) -> dict:
    """What the part from `first` to `last` holds: its length in seconds, in bars and beats when
    there is a grid, its first and last sung lines, and each end that falls while a line sounds."""
    spans = _spans(lines, letters, duration)
    held = [s for s in spans if first - SNAP <= s[2] < last - SNAP]
    info: dict = {
        "from": round(first, 3),
        "to": round(last, 3),
        "seconds": round(last - first, 2),
        "grid": bool(beats),
        "first": {"line": held[0][0], "text": held[0][1]} if held else None,
        "last": {"line": held[-1][0], "text": held[-1][1]} if held else None,
        "inside": [
            {"end": end, "line": n, "text": text}
            for end, t in (("from", first), ("to", last))
            for n, text, a, b in spans
            if a + SNAP < t < b - SNAP
        ],
    }
    if beats:
        count = sum(1 for b in beats if first - SNAP <= b < last - SNAP)
        info["bars"], info["beats"] = divmod(count, BEATS_PER_BAR)
        info["marks"] = marks(first, last, beats)
    return info


def marks(first: float, last: float, beats: Sequence[float]) -> dict:
    """The beats within NEAR seconds of the part, and which of them are bar lines: every fourth beat
    counted from the part's start (the beat it is on, or the next one), so the lines show where
    whole bars from that start fall."""
    i0 = _on(first, beats)
    if i0 is None:
        i0 = next((k for k, b in enumerate(beats) if b > first), len(beats) - 1)
    near = [(k, b) for k, b in enumerate(beats) if first - NEAR <= b <= last + NEAR]
    return {
        "beats": [round(b, 3) for _, b in near],
        "bars": [round(b, 3) for k, b in near if (k - i0) % BEATS_PER_BAR == 0],
    }
