"""Loop sections for a Short: parts of the song that are a whole number of bars long, so a video on
repeat keeps time across its seam, ranked by how strongly their first seconds open.

The beat grid, loudness and onsets come from librosa, in the "align" extra (`grid`); choosing and
ranking the sections is plain numpy (`sections`)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import media, tall

RATE, HOP = 22050, 512
BEATS_PER_BAR = 4
HOOK = 3.0  # seconds of a section's start that are scored
BEFORE = 1.5  # seconds before the start it is compared with
SNAP = 0.05  # a line start this close after a beat is on it
TOP = 8


@dataclass(frozen=True)
class Grid:
    """What the song's sound says: beat times in seconds, and loudness (RMS) and onset strength per
    frame, `fps` frames a second."""

    beats: np.ndarray
    rms: np.ndarray
    onset: np.ndarray
    fps: float

    @property
    def beat(self) -> float:
        return float(np.median(np.diff(self.beats)))

    @property
    def bar(self) -> float:
        return BEATS_PER_BAR * self.beat


def grid(path: str) -> Grid:
    import librosa

    y = np.ascontiguousarray(media.samples(path, RATE)[:, 0])
    _, beats = librosa.beat.beat_track(y=y, sr=RATE, hop_length=HOP, units="time")
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    onset = librosa.onset.onset_strength(y=y, sr=RATE, hop_length=HOP)
    if len(beats) < 2 * BEATS_PER_BAR:
        raise ValueError("no steady beat found in the song")
    return Grid(np.asarray(beats, dtype=float), rms, onset, RATE / HOP)


def _mean(a: np.ndarray, fps: float, t0: float, t1: float) -> float:
    i0 = max(0, int(t0 * fps))
    return float(a[i0 : max(int(t1 * fps), i0 + 1)].mean()) if i0 < len(a) else 0.0


def _db(x: float, ref: float) -> float:
    return 20 * math.log10(max(x, 1e-9) / max(ref, 1e-9))


def opening(g: Grid, start: float, repeated: bool) -> float:
    """How strongly a section starting at `start` opens: the loudness and the onsets of its first
    HOOK seconds against the song's medians, how much louder it gets than the moment before, and 2
    more when its first line comes back elsewhere (a chorus)."""
    loud = _db(_mean(g.rms, g.fps, start, start + HOOK), float(np.median(g.rms)))
    busy = _mean(g.onset, g.fps, start, start + HOOK) / max(float(np.median(g.onset)), 1e-9)
    before = _db(_mean(g.rms, g.fps, start - BEFORE, start), float(np.median(g.rms)))
    return loud + 3 * (busy - 1) + (2 if repeated else 0) + 0.5 * max(0.0, loud - before)


def sections(
    lines: tuple[tuple[float, str], ...], g: Grid, duration: float, length: float
) -> list[dict]:
    """The best TOP sections about `length` seconds long. Each starts on the beat a sung line starts
    on (or the beat before it, so a pickup stays in) and lasts whole bars: as many as fit `length`,
    one more or one fewer when that ends it just before the next line comes in, so the seam falls
    between lines. Highest `score` first; `line` is the line's place in `lines` from 1."""
    sung = [(i, t, text) for i, (t, text) in enumerate(lines) if text.strip()]
    keys = [tall._key(text) for _, _, text in sung]
    starts = sorted(t for t, text in lines if text.strip())
    bar, beat = g.bar, g.beat
    whole = max(1, round(length / bar))
    found: dict[float, dict] = {}
    for (i, t, text), key in zip(sung, keys, strict=True):
        on = g.beats[g.beats <= t + SNAP]
        if not len(on):
            continue
        start = float(on[-1])

        def seam(n: int, start: float = start) -> tuple[bool, int]:
            end = start + n * bar
            nxt = next((s for s in starts if s >= end - SNAP), duration)
            return (0 <= nxt - end <= beat or abs(duration - end) <= beat, -abs(n - whole))

        fits = [n for n in (whole, whole - 1, whole + 1) if n >= 1 and start + n * bar <= duration]
        if not fits:
            continue
        n = max(fits, key=seam)
        score = opening(g, start, keys.count(key) > 1) + (1.5 if seam(n)[0] else 0.0)
        if start not in found or score > found[start]["score"]:
            found[start] = {
                "from": round(start, 3),
                "to": round(start + n * bar, 3),
                "bars": n,
                "line": i + 1,
                "text": text,
                "score": round(score, 2),
            }
    ranked = sorted(found.values(), key=lambda s: -s["score"])[:TOP]
    return [{"n": k + 1, **s} for k, s in enumerate(ranked)]
