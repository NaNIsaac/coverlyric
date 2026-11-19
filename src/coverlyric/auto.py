"""Automatic timing on this computer: faster-whisper listens to the song on the CPU, then the user's own
lyrics are placed on the times of the words it heard. The text on screen is always the user's text; the
transcription only gives times. Nothing leaves the computer.

faster-whisper is the optional "auto" extra, installed the first time the user asks for it.
"""

from __future__ import annotations

import difflib
import gc
import itertools
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

from .timing import Line

GAP = 6.0  # seconds of no singing after a line that get an empty entry, so the band is empty
PLACED = 0.5  # share of a line's letters that must be heard for its time to count
SHORTEST = 1.0  # seconds a line stays on the band at least
MODELS = {  # MB in the cache once downloaded
    "small": ("small", 464),
    "base": ("base", 139),
    "tiny": ("tiny", 72),
}
SMALLER = {"small": "base", "base": "tiny"}  # tried in turn when a model cannot get memory
NO_MEMORY_EXIT = 3  # the auto job's exit code when no listening model could get memory
# Peak commit in MB of the job process that loads each model (int8, one BLAS thread) and listens to a
# song, with the transcriber's own imports; loading converts the weights and briefly needs more.
PEAK_MB = {"small": 730, "base": 430, "tiny": 320}
MARGIN_MB = 50  # other programs move while the model loads


def fitting(model: str, free_mb: float | None) -> str | None:
    """The largest model from `model` down that fits in the free commit, or None when none does.
    With the free commit unknown the model asked for is used, and a failed load still falls back."""
    if free_mb is None:
        return model
    name: str | None = model
    while name and PEAK_MB[name] + MARGIN_MB > free_mb:
        name = SMALLER.get(name)
    return name


class NoMemory(Exception):
    """No listening model, down to the smallest, could get the memory it needs."""


def out_of_memory(error: BaseException) -> bool:
    """CTranslate2 reports a failed allocation as a RuntimeError naming the allocator."""
    text = str(error).lower()
    return isinstance(error, MemoryError) or (
        "alloc" in text and ("memory" in text or "malloc" in text)
    )


def letters(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def matched(
    own: list[str],
    line_of: list[int],
    heard: list[str],
    lines: set[int],
    lo: int,
    hi: int,
    least: int = 1,
) -> dict[int, int]:
    """The letters of `lines` matched in order to the heard letters lo to hi: {own: heard}, from
    runs of at least `least` letters."""
    picked = [n for n, i in enumerate(line_of) if i in lines]
    matcher = difflib.SequenceMatcher(None, [own[n] for n in picked], heard[lo:hi], autojunk=False)
    return {
        picked[a + j]: lo + b + j
        for a, b, size in matcher.get_matching_blocks()
        if size >= least
        for j in range(size)
    }


def placed_lines(hit: dict[int, int], line_of: list[int], lines: set[int]) -> list[int]:
    """The lines of `lines` with enough of their letters heard."""
    return [
        i
        for i in sorted(lines)
        if (own := [n for n, li in enumerate(line_of) if li == i])
        and sum(n in hit for n in own) / len(own) >= PLACED
    ]


def hits(lyrics: list[str], own: list[str], line_of: list[int], heard: list[str]) -> dict[int, int]:
    """Which heard letter each lyric letter is. A repeated chorus is the same letters each time,
    and one match over the whole song can give the first written chorus the second sung one when
    the first was not heard (#37). So the lines written once are placed first, and each run of
    other lines is matched only to what was heard between its placed neighbours."""
    texts = [letters(line) for line in lyrics]
    once = {i for i, t in enumerate(texts) if t and texts.count(t) == 1}
    if len(once) == sum(1 for t in texts if t):
        return matched(own, line_of, heard, once, 0, len(heard))
    # A single letter heard far off (a 요 in the next chorus) would stretch a line over the gap.
    hit = matched(own, line_of, heard, once, 0, len(heard), least=2)
    # A line written once that shares words with a repeated line can match where the repeated
    # line was sung, when the rest of it was misheard; it is placed with its neighbours instead (#41).
    repeated = {t for t in texts if t and texts.count(t) > 1}
    anchors = [
        i
        for i in placed_lines(hit, line_of, once)
        if not any(
            "".join(own[n] for n, li in enumerate(line_of) if li == i and n in hit) in t
            for t in repeated
        )
    ]
    if len(anchors) < len(placed_lines(hit, line_of, once)):
        # Matched again without those lines, which pulled their neighbours' letters with them.
        hit = matched(own, line_of, heard, set(anchors), 0, len(heard), least=2)
        anchors = placed_lines(hit, line_of, set(anchors))
    hit = {n: b for n, b in hit.items() if line_of[n] in anchors}
    first = {i: min(b for n, b in hit.items() if line_of[n] == i) for i in anchors}
    last = {i: max(b for n, b in hit.items() if line_of[n] == i) for i in anchors}
    bounds = [-1, *anchors, len(lyrics)]
    for before, after in itertools.pairwise(bounds):
        gap = set(range(before + 1, after))
        if gap:
            lo = last[before] + 1 if before >= 0 else 0
            hi = first[after] if after < len(lyrics) else len(heard)
            hit |= matched(own, line_of, heard, gap, lo, hi)
    return hit


def align(
    lyrics: list[str], words: list[dict], duration: float | None = None
) -> tuple[list[Line], list[dict]]:
    """Times for `lyrics` from heard `words` ({start, end, word}). Returns the lines (with an empty line
    after each line followed by a long pause) and one note per lyric line: {"line": i, "kind":
    "unplaced" | "doubtful" | "differs", "heard": text}. Unplaced lines get a time between their
    neighbours; after the last placed line they share what is left of the song's `duration`."""
    heard, at = [], []
    for k, w in enumerate(words):
        for ch in letters(w["word"]):
            heard.append(ch)
            at.append(k)
    own, line_of = [], []
    for i, line in enumerate(lyrics):
        for ch in letters(line):
            own.append(ch)
            line_of.append(i)
    hit = hits(lyrics, own, line_of, heard)
    rows = []
    for i in range(len(lyrics)):
        idx = [n for n, li in enumerate(line_of) if li == i]
        got = [hit[n] for n in idx if n in hit]
        share = len(got) / len(idx) if idx else 0.0
        if share >= PLACED:
            first, last = at[min(got)], at[max(got)]
            rows.append(
                {
                    "start": words[first]["start"],
                    "end": words[last]["end"],
                    "heard": "".join(w["word"] for w in words[first : last + 1]).strip(),
                }
            )
        else:
            rows.append({"start": None, "end": None, "heard": ""})
    for i, row in enumerate(rows):
        prev = rows[i - 1] if i else None
        later = row["start"] is not None and prev and prev["start"] is not None
        if later and row["start"] <= prev["start"]:
            row.update(start=None, end=None)
    placed = [r["start"] is not None for r in rows]
    i = 0
    while i < len(rows):
        if placed[i]:
            i += 1
            continue
        j = i
        while j < len(rows) and not placed[j]:
            j += 1
        before = rows[i - 1]["end"] if i else 0.0
        if j < len(rows):
            after = rows[j]["start"]
        elif duration and duration > before:
            after = min(before + 3.0 * (j - i + 1), duration)
        else:
            after = before + 3.0 * (j - i + 1)
        step = (after - before) / (j - i + 1)
        for n in range(i, j):
            start = round(before + step * (n - i + 1), 2)
            rows[n].update(start=start, end=round(start + min(step, 3.0), 2), unplaced=True)
        i = j
    for i in range(len(rows) - 1, 0, -1):
        row, nxt = rows[i - 1], rows[i]
        prev = rows[i - 2] if i > 1 else None
        if nxt["start"] - row["start"] < SHORTEST:
            earliest = prev["end"] if prev else 0.0
            row["start"] = round(max(earliest, nxt["start"] - SHORTEST), 2)
            row["doubtful"] = True
    lines: list[Line] = []
    notes = []
    for i, (text, row) in enumerate(zip(lyrics, rows, strict=True)):
        lines.append((round(row["start"], 2), text))
        if row.get("unplaced"):
            notes.append({"line": i, "kind": "unplaced", "heard": ""})
        elif row.get("doubtful"):
            notes.append({"line": i, "kind": "doubtful", "heard": row["heard"]})
        elif letters(row["heard"]) != letters(text):
            notes.append({"line": i, "kind": "differs", "heard": row["heard"]})
        nxt = rows[i + 1]["start"] if i + 1 < len(rows) else None
        if nxt is None or nxt - row["end"] >= GAP:
            gone = row["end"] + 1.0
            lines.append((round(min(gone, duration) if duration else gone, 2), ""))
    return lines, notes


def found(lyrics: list[str], words: list[dict], until: float) -> list[list[float]]:
    """[lyric index, start] for the lines placed so far, for the live list while the song is heard.
    Lines after `until` and lines only guessed between neighbours are left out."""
    lines, notes = align(lyrics, words)
    guessed = {n["line"] for n in notes if n["kind"] == "unplaced"}
    starts = [t for t, text in lines if text]
    return [[i, t] for i, t in enumerate(starts) if i not in guessed and t <= until]


def model_cache() -> Path:
    """The Hugging Face cache faster-whisper downloads into, shared with other tools on the computer."""
    if hub := os.environ.get("HF_HUB_CACHE"):
        return Path(hub)
    home = os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface"
    return Path(home) / "hub"


def has_model(name: str) -> bool:
    pattern = f"models--Systran--faster-whisper-{name}/snapshots/*/model.bin"
    return any(model_cache().glob(pattern))


def downloaded_mb(name: str) -> float:
    """MB of the model in the cache so far, partial files included. Linked snapshot files point at
    blobs and are not counted twice."""
    folder = model_cache() / f"models--Systran--faster-whisper-{name}"
    if not folder.exists():
        return 0.0
    files = (f for f in folder.rglob("*") if f.is_file() and not f.is_symlink())
    return sum(f.stat().st_size for f in files) / 2**20


def transcribe(
    audio: str,
    name: str = "small",
    language: str = "ko",
    report: Callable[[str, float, float], None] = lambda phase, done, total: None,
    heard: Callable[[list[dict], float], None] = lambda words, until: None,
    clip: tuple[float, float] | None = None,
) -> list[dict]:
    """Words heard in the song, each {start, end, word, prob}. VAD stays off: on sung vocals it drops
    most lines. `report` gets (phase, done, total): MB while the model downloads, seconds of the song
    while listening; `heard` gets the words so far after each segment. `clip` listens to that stretch
    only (seconds)."""
    from faster_whisper import WhisperModel

    done = threading.Event()
    if not has_model(name):
        total = MODELS[name][1]

        def watch() -> None:
            while not done.wait(0.5):
                got = downloaded_mb(name)
                if got >= total * 0.99:
                    report("load", 0.0, 0.0)
                    return
                report("download", got, total)

        report("download", 0.0, total)
        threading.Thread(target=watch, daemon=True).start()
    else:
        report("load", 0.0, 0.0)
    try:
        model = WhisperModel(
            MODELS[name][0],
            device="cpu",
            compute_type="int8",
            cpu_threads=os.cpu_count() or 4,
        )
    finally:
        done.set()
    segments, info = model.transcribe(
        audio,
        language=language,
        beam_size=5,
        word_timestamps=True,
        vad_filter=False,
        no_speech_threshold=0.9,
        condition_on_previous_text=False,
        **({"clip_timestamps": [clip[0], clip[1]]} if clip else {}),
    )
    report("listen", 0.0, info.duration)
    words = []
    for s in segments:
        words.extend(
            {
                "start": round(w.start, 2),
                "end": round(w.end, 2),
                "word": w.word,
                "prob": round(w.probability, 2),
            }
            for w in s.words or []
        )
        report("listen", s.end, info.duration)
        heard(words, s.end)
    return words


def listen(
    audio: str,
    model: str = "small",
    report: Callable[[str, float, float], None] = lambda phase, done, total: None,
    heard: Callable[[list[dict], float], None] = lambda words, until: None,
    smaller: Callable[[str], None] = lambda name: None,
    clip: tuple[float, float] | None = None,
) -> tuple[list[dict], str]:
    """The words heard and the model that heard them. A model that cannot get memory gives way to the
    next smaller one (`smaller` is told which); when none can, NoMemory."""
    name = model
    while True:
        try:
            extra = {"clip": clip} if clip else {}
            return transcribe(audio, name, report=report, heard=heard, **extra), name
        except (MemoryError, RuntimeError) as e:
            if not out_of_memory(e):
                raise
            gc.collect()  # let the model that failed go before a smaller one loads
            following = SMALLER.get(name)
            if following is None:
                raise NoMemory(f"no listening model could get memory (last tried: {name})") from e
            name = following
            smaller(name)
