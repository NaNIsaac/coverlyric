"""Automatic timing on this computer: faster-whisper listens to the song on the CPU, then the user's own
lyrics are placed on the times of the words it heard. The text on screen is always the user's text; the
transcription only gives times. Nothing leaves the computer.

faster-whisper is the optional "auto" extra, installed the first time the user asks for it.
"""

from __future__ import annotations

import difflib
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


def out_of_memory(error: BaseException) -> bool:
    """CTranslate2 reports a failed allocation as a RuntimeError naming the allocator."""
    text = str(error).lower()
    return isinstance(error, MemoryError) or (
        "alloc" in text and ("memory" in text or "malloc" in text)
    )


def letters(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def align(lyrics: list[str], words: list[dict]) -> tuple[list[Line], list[dict]]:
    """Times for `lyrics` from heard `words` ({start, end, word}). Returns the lines (with an empty line
    after each line followed by a long pause) and one note per lyric line: {"line": i, "kind":
    "unplaced" | "doubtful" | "differs", "heard": text}. Unplaced lines get a time between their
    neighbours."""
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
    hit = {}
    matcher = difflib.SequenceMatcher(None, own, heard, autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for j in range(size):
            hit[a + j] = b + j
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
        after = rows[j]["start"] if j < len(rows) else before + 3.0 * (j - i + 1)
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
            lines.append((round(row["end"] + 1.0, 2), ""))
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
) -> list[dict]:
    """Words heard in the song, each {start, end, word}. VAD stays off: on sung vocals it drops most
    lines. `report` gets (phase, done, total): MB while the model downloads, seconds of the song
    while listening; `heard` gets the words so far after each segment."""
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
    )
    report("listen", 0.0, info.duration)
    words = []
    for s in segments:
        words.extend(
            {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word}
            for w in s.words or []
        )
        report("listen", s.end, info.duration)
        heard(words, s.end)
    return words
