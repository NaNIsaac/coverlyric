"""Letter times by forced alignment, for highlight=letter: the vocals of the part are separated from the
band (demucs), and each letter of the lines is placed on them by torchaudio's MMS_FA model. A Korean
letter is one sung syllable, so each one goes to the aligner as its own romanised word (uroman) and
gets its own start. A punctuation mark, with nothing to sing, takes the time of the letter before it.

Everything here needs the "align" extra (`missing` says what is not installed). The models are
downloaded once, about 1.2 GB, into torch's cache (`downloads`)."""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import media

LEAD = 0.04  # seconds before the aligned start: the letter lights as its syllable sounds
AROUND = 5.0  # seconds of song kept on each side of the part, so the separation hears the context
SEPARATOR = "htdemucs"
MODULES = ("torch", "torchaudio", "demucs", "uroman", "librosa")
MODEL_FILES = ("model.pt", "955717e8-8726e21a.th")  # MMS_FA, htdemucs; in torch's hub checkpoints
INSTALL = "uv run --isolated --python 3.13 --extra align coverlyric"


def missing(names: tuple[str, ...] = MODULES) -> str | None:
    """Why alignment cannot run here, or None."""
    gone = [name for name in names if importlib.util.find_spec(name) is None]
    if not gone:
        return None
    return (
        f"this needs the 'align' extra ({', '.join(gone)} not installed): "
        f"{INSTALL} <command> ... (torch 2.7 runs on Python 3.12 or 3.13)"
    )


def downloads() -> bool:
    """Whether the models still have to be downloaded."""
    import torch

    hub = Path(torch.hub.get_dir()) / "checkpoints"
    return not all((hub / name).exists() for name in MODEL_FILES)


def chosen(
    lines: list[tuple[float | None, str]], start: float, end: float
) -> list[tuple[int, float, str]]:
    """The sung lines that start from `start` to `end`: (index in lines, start, text)."""
    return [
        (i, t, text)
        for i, (t, text) in enumerate(lines)
        if t is not None and text.strip() and start <= t <= end
    ]


def tokens(
    picked: list[tuple[int, float, str]], romanise: Callable[[str], str]
) -> tuple[list[str], dict[int, list[int | None]]]:
    """What the aligner reads, one romanised word per letter, and for each line, per letter but
    spaces, which of those words it is; None for punctuation."""
    words: list[str] = []
    marks: dict[int, list[int | None]] = {}
    for i, _, text in picked:
        for ch in text:
            if ch.isspace():
                continue
            word = re.sub(r"[^a-z']", "", romanise(ch).lower())
            marks.setdefault(i, []).append(len(words) if word else None)
            if word:
                words.append(word)
    return words, marks


def entries(
    picked: list[tuple[int, float, str]],
    marks: dict[int, list[int | None]],
    starts: list[float],
) -> list[dict]:
    """The project's `letters` for the picked lines from each aligned word's start (song seconds):
    LEAD earlier, punctuation on the letter before it, a line's opening mark on its first letter."""
    out = []
    for i, _, text in picked:
        row: list[float | None] = []
        last = None
        for ref in marks.get(i, []):
            if ref is not None:
                last = round(starts[ref] - LEAD, 3)
            row.append(last)
        first = next((x for x in row if x is not None), None)
        if first is None:
            continue
        out.append({"n": i + 1, "text": text, "times": [first if x is None else x for x in row]})
    return out


def merged(old: list[dict], new: list[dict]) -> list[dict]:
    """`old` with the lines in `new` replaced, by line number."""
    done = {entry["n"] for entry in new}
    return sorted([e for e in old if e.get("n") not in done] + new, key=lambda e: e["n"])


def vocals(path: str, start: float, length: float) -> tuple[np.ndarray, int]:
    """The singing alone, mono, from `start` for `length` seconds, and its sample rate."""
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model(SEPARATOR)
    model.eval()
    wave = torch.from_numpy(media.samples(path, model.samplerate, 2, start, length).T.copy())
    ref = wave.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    with torch.inference_mode():
        parts = apply_model(model, ((wave - mean) / std)[None], device="cpu", progress=False)[0]
    voice = parts[model.sources.index("vocals")] * std + mean
    return voice.mean(0).numpy(), model.samplerate


def word_starts(voice: np.ndarray, rate: int, words: list[str]) -> list[float]:
    """Where each word starts in `voice`, in seconds."""
    import torch
    import torchaudio

    bundle = torchaudio.pipelines.MMS_FA
    wave = torchaudio.functional.resample(torch.from_numpy(voice)[None], rate, bundle.sample_rate)
    model = bundle.get_model(with_star=False)
    with torch.inference_mode():
        emission, _ = model(wave)
    spans = bundle.get_aligner()(emission[0], bundle.get_tokenizer()(words))
    step = wave.size(1) / emission.size(1) / bundle.sample_rate
    return [span[0].start * step for span in spans]


def align(
    path: str, lines: list[tuple[float | None, str]], start: float, end: float, note=print
) -> list[dict]:
    """Letter times of the lines sung from `start` to `end` in the song at `path`."""
    import uroman

    picked = chosen(lines, start, end)
    if not picked:
        raise ValueError("no timed line starts in that part")
    if downloads():
        note("the first alignment downloads its models, about 1.2 GB, once")
    words, marks = tokens(picked, uroman.Uroman().romanize_string)
    begin = max(0.0, picked[0][1] - AROUND)
    nxt = [t for t, text in lines if t is not None and t > picked[-1][1]]
    stop = (min(nxt) if nxt else end) + AROUND
    note("separating the vocals")
    voice, rate = vocals(path, begin, stop - begin)
    note("placing the letters")
    starts = [begin + s for s in word_starts(voice, rate, words)]
    return entries(picked, marks, starts)
