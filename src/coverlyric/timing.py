"""Lyric lines with start times: read from plain text, LRC, SRT or WebVTT, written as LRC or SRT.

A line is ``(start, text)``. ``start`` is seconds, or None while the line has no time yet. An empty
text is a gap: the band moves on but no words show.
"""

from __future__ import annotations

import re

Line = tuple[float | None, str]

TAG = re.compile(r"<[^>]+>")
STAMP = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
CUE_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})"
)
SECTION = re.compile(
    r"^\s*[\[(](?:verse|chorus|bridge|intro|outro|hook|pre-chorus|inst)[^\])]*[\])]\s*$", re.I
)


def from_text(text: str) -> list[Line]:
    """One line per non-empty line of the pasted lyrics, without times. Section tags such as [Chorus]
    are dropped: they are not sung."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not SECTION.match(line):
            out.append((None, line))
    return out


def parse_lrc(text: str) -> list[Line]:
    rows = []
    for raw in text.splitlines():
        stamps = list(STAMP.finditer(raw))
        if not stamps:
            continue
        words = raw[stamps[-1].end() :].strip()
        words = re.sub(r"<\d+:\d+(?:\.\d+)?>", "", words).strip()  # enhanced LRC word stamps
        for m in stamps:
            rows.append((int(m[1]) * 60 + float(m[2].replace(":", ".")), words))
    return sorted(rows, key=lambda r: r[0])


def cue_seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_cues(text: str) -> list[Line]:
    """SRT and WebVTT: each cue's start and its text joined on one line; a gap between cues longer than
    a second becomes an empty line, so the band leaves the last line when the singing stops."""
    rows: list[Line] = []
    ends: list[float] = []
    block: list[str] = []

    def flush() -> None:
        for i, raw in enumerate(block):
            if m := CUE_TIME.search(raw):
                start = cue_seconds(*m.groups()[:4])
                end = cue_seconds(*m.groups()[4:])
                words = " ".join(TAG.sub("", b).strip() for b in block[i + 1 :] if b.strip())
                if ends and start - ends[-1] > 1.0:
                    rows.append((ends[-1], ""))
                rows.append((start, words))
                ends.append(end)
                break
        block.clear()

    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.strip():
            block.append(raw)
        else:
            flush()
    flush()
    return rows


def parse(name: str, text: str) -> list[Line]:
    """Read a timing file by its extension, or by its look when the extension says nothing."""
    text = text.lstrip("﻿")
    lower = name.lower()
    if lower.endswith(".lrc"):
        return parse_lrc(text)
    if lower.endswith((".srt", ".vtt")) or "-->" in text:
        return parse_cues(text)
    if STAMP.search(text):
        return parse_lrc(text)
    return from_text(text)


def stamp(seconds: float) -> str:
    cs = round(seconds * 100)
    return f"{cs // 6000:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def to_lrc(lines: list[Line], title: str = "", artist: str = "") -> str:
    head = []
    if artist:
        head.append(f"[ar:{artist}]")
    if title:
        head.append(f"[ti:{title}]")
    body = [f"[{stamp(t)}]{text}" for t, text in lines if t is not None]
    return "\n".join(head + body) + "\n"


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(lines: list[Line], duration: float | None = None) -> str:
    """Each line lasts until the next one starts (at most 8 s); gaps are not written."""
    timed = [(t, text) for t, text in lines if t is not None]
    out, n = [], 0
    for i, (t, text) in enumerate(timed):
        if not text:
            continue
        nxt = timed[i + 1][0] if i + 1 < len(timed) else (duration or t + 5)
        end = min(nxt, t + 8)
        n += 1
        out.append(f"{n}\n{srt_time(t)} --> {srt_time(end)}\n{text}\n")
    return "\n".join(out)


def ready(lines: list[Line]) -> list[tuple[float, str]]:
    """The lines a render can use: every line timed, in time order. Raises ValueError naming the first
    line without a time."""
    for i, (t, text) in enumerate(lines):
        if t is None:
            raise ValueError(f"line {i + 1} has no time: {text}")
    return sorted(((float(t), text) for t, text in lines), key=lambda r: r[0])


def plain(text: str) -> str:
    """Text reduced for comparison: no spaces, punctuation or case."""
    return re.sub(r"[\W_]+", "", text).lower()


def check(own: list[str], got: list[Line]) -> list[str | None]:
    """For each imported line, None if it matches one of the user's own lines in order, else the own
    line it most likely stands for ("" when there is none). Empty imported lines are gaps and match."""
    from difflib import SequenceMatcher

    texts = [text for _, text in got]
    a = [plain(t) for t in own]
    b = [plain(t) for t in texts]
    out: list[str | None] = [None] * len(b)
    sm = SequenceMatcher(None, a, [t for t in b if t], autojunk=False)
    index = [i for i, t in enumerate(b) if t]
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        for k, j in enumerate(range(j1, j2)):
            out[index[j]] = own[i1 + k] if i1 + k < i2 else ""
    return out


def ai_prompt(lyrics: list[str], title: str = "") -> str:
    """The request the user gives her own chat AI together with the song file."""
    body = "\n".join(lyrics)
    name = f" '{title}'" if title else ""
    return (
        f"첨부한 노래{name}의 가사 자막을 SRT 형식으로 만들어 주세요.\n"
        "\n"
        "규칙:\n"
        "- 아래 가사의 한 줄이 자막 하나입니다. 줄을 합치거나 나누지 마세요.\n"
        f"- 자막은 모두 {len(lyrics)}개, 아래 순서 그대로입니다.\n"
        "- 가사 글자는 한 글자도 바꾸지 마세요. 맞춤법도 고치지 마세요.\n"
        "- 시작 시간은 그 줄을 부르기 시작하는 순간, 끝 시간은 다음 줄이 시작하기 전입니다.\n"
        "- 답은 SRT 내용만 주세요. 설명이나 다른 말은 넣지 마세요.\n"
        "\n"
        "가사:\n"
        f"{body}\n"
    )
