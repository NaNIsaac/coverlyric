"""The user's own video under the lyrics (`Song.video`), for the wide and the upright shapes. The video
fills the frame in place of the cover; over it go the title and the artist at the top and, at the
bottom or in the middle, the line being sung with the next one small under it. The text is drawn on a
clear layer that ffmpeg lays over the video when the render encodes (render.encode); a still lays it
over one frame of the video read here."""

from __future__ import annotations

import math
import subprocess
from dataclasses import replace
from functools import lru_cache

from PIL import Image, ImageDraw

from . import fonts, media, render, tall

PAPER, DARK = (246, 241, 230), (0, 0, 0)
BANDS = {"paper": PAPER, "dark": DARK}
# The wide frame's room: the text keeps clear of the edges by MARGIN and is drawn at TEXT times the
# Short's sizes, as the wide frame is a little more than half a Short's height.
WIDE_MARGIN, WIDE_TEXT = 160, 0.8
NEXT_ALPHA = 0.6
BOTTOM_GAP = 70  # px between the next line and the room's lower edge, at a Short's size
# video_text=low: the room's lower edge LOW_EDGE px above the frame's (or its bottom band), in the
# fifth of a Short its caption can cover, for a video that leaves room under its picture.
LOW_EDGE = 130
BAND_PAD = (48, 26)
# A line without letter times from align: its letters are spread from its start over at most
# SPREAD seconds each, and never past the next line.
SPREAD = 0.3


def room(style: render.Style) -> tall.Frame:
    """Where the text may go: the upright shapes' room (clear of a Short's buttons and of the
    bands), or the wide frame less its margins."""
    if render.is_upright(style):
        return tall.frame_of(style)
    w, h = render.W, render.H
    return tall.Frame(w, h, 0, h, WIDE_MARGIN, w - WIDE_MARGIN, 0, WIDE_TEXT, WIDE_TEXT)


def start(style: render.Style, song: render.Song) -> float:
    """The song time the video's first frame goes with: the start of a Short's part (the wide video
    starts with the song), moved by video_offset."""
    first = tall.span(style, song)[0] if render.is_upright(style) else 0.0
    return first + style.video_offset


@lru_cache(maxsize=4)
def _length(path: str, stamp: float) -> float:
    return media.duration(path)


def length(path: str) -> float:
    return _length(path, render.stamp(path))


def video_at(t: float, style: render.Style, song: render.Song) -> float:
    """The video's own time at the video clock's t (the song's clock moved by song.lead): before
    its start the first frame, after its end again from the start (loop) or the last frame (hold)."""
    at = t - song.lead - start(style, song)
    if at <= 0:
        return 0.0
    whole = length(song.video)
    if style.video_end == "hold":
        return min(at, whole)
    return math.fmod(at, whole) if whole > 0 else 0.0


def fit(w: int, h: int) -> str:
    """ffmpeg's filter that fills a w x h frame with the video, cut to its middle."""
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


@lru_cache(maxsize=8)
def _picture(path: str, stamp: float, at: float, w: int, h: int) -> Image.Image:
    # A seek at or past the last frame gives nothing; step back until a frame comes.
    for back in (0.0, 0.1, 0.3, 1.0):
        run = subprocess.run(
            [media.ffmpeg(), "-v", "error", "-ss", f"{max(0.0, at - back):.3f}", "-i", path]
            + ["-frames:v", "1", "-vf", fit(w, h), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
            capture_output=True,
            check=False,
            **media.quiet(),
        )
        if len(run.stdout) == w * h * 4:
            return Image.frombytes("RGBA", (w, h), run.stdout)
    raise ValueError(f"not a video file ffmpeg can read: {path}")


def picture(path: str, at: float, size: tuple[int, int]) -> Image.Image:
    """The video's frame at `at` seconds, filling `size`."""
    return _picture(path, render.stamp(path), round(at, 3), *size)


def spread(lines: tuple[tuple[float, str], ...], k: int, end: float) -> tuple[float, ...]:
    """Letter times for line k from its timing alone: its letters but spaces one after another from
    its start, SPREAD seconds each at most, all sung before the next line or `end`."""
    start, text = lines[k]
    marks = [ch for ch in text if not ch.isspace()]
    if not marks:
        return ()
    after = lines[k + 1][0] if k + 1 < len(lines) else end
    step = min(SPREAD, max(0.0, after - start) / len(marks))
    return tuple(start + j * step for j in range(len(marks)))


class Painter:
    """The text over the video for one song and style. raw() is the clear layer the render lays over
    the video; image() is a whole frame, the layer over the video's frame, for a still. A layer whose
    lines stand where they stood is the last one again."""

    def __init__(
        self, lines: tuple[tuple[float, str], ...], song: render.Song, style: render.Style
    ):
        self.song, self.style = song, style
        self.size = render.frame_size(style)
        self.fr = room(style)
        self.letter = style.highlight == "letter"
        given = {(begin, text): times for begin, text, times in song.letters}
        end = song.duration
        self.times = [
            (given.get(line) or spread(lines, k, end)) if self.letter else None
            for k, line in enumerate(lines)
        ]
        self.lines = tuple(
            (min(begin, times[0]) if times else begin, text)
            for (begin, text), times in zip(lines, self.times, strict=True)
        )
        edge = "shadow" if style.video_edge == "shadow" else "none"
        self.ink = replace(
            style, lyric_colour=style.video_ink, lyric_edge=edge, lyric_edge_colour="#000000"
        )
        self.lit = replace(self.ink, lyric_colour=style.video_lit)
        self.first = tall.span(style, song)[0] if render.is_upright(style) else 0.0
        self.base = self.top_layer()
        self.fps = render.rate(style)
        self.last: tuple = (None, b"")

    def top_layer(self) -> Image.Image:
        """What every frame has: the bands of a Short, the title and the artist."""
        style, fr, song = self.style, self.fr, self.song
        img = Image.new("RGBA", self.size, (0, 0, 0, 0))
        if render.is_upright(style) and fr.bar:
            tall.draw_bars(img, style, fr)
        if not tall.titled(style):
            return img
        face = fonts.resolve(style.font)
        d = ImageDraw.Draw(img)
        title = render.font(face, 44 * fr.text, 650)
        while (
            render.text_width(song.title, title, 0.04) > fr.right - fr.margin
            and title.size > 24 * fr.text
        ):
            title = render.font(face, title.size * 0.92, 650)
        artist = render.font(face, 30 * fr.text, 400)
        if self.style.video_band in BANDS:
            # Ink chosen for the band would be lost on the video: the title gets its own band.
            wide = render.text_width(song.title, title, 0.04)
            if song.artist:
                wide = max(wide, render.text_width(song.artist, artist, 0.12))
            low = fr.y(tall.ARTIST_Y if song.artist else tall.TITLE_Y)
            high = fr.y(tall.TITLE_Y) - title.size / 2
            part = {"box": (fr.cx - wide / 2, high, fr.cx + wide / 2, low + artist.size / 2)}
            self.band(d, [part], 1.0)
        render.lettered(d, (fr.cx, fr.y(tall.TITLE_Y)), song.title, title, 255, self.ink, 0.04)
        if song.artist:
            render.lettered(
                d, (fr.cx, fr.y(tall.ARTIST_Y)), song.artist, artist, 200, self.ink, 0.12
            )
        return img

    def blocks(self, k: int) -> tuple[dict | None, dict | None]:
        """Line k and the line after it, placed as a pair at the bottom of the room or in its middle."""
        fr, face = self.fr, fonts.resolve(self.style.font)
        if k < 0 or not self.lines[k][1]:
            return None, None
        now_px = (tall.LETTER_PX if self.letter else tall.NOW_PX) * fr.text
        size, rows = tall.fitted(self.lines[k][1], face, now_px, 700, 2, fr)
        n = tall.following(k, self.lines)
        nsize, nrows = (0.0, ())
        if n is not None:
            nsize, nrows = tall.fitted(self.lines[n][1], face, tall.NEXT_PX * fr.text, 500, 2, fr)
        high = len(rows) * size * tall.PITCH
        gap = tall.NEXT_GAP * fr.scale if nrows else 0.0
        low = len(nrows) * nsize * tall.PITCH
        whole = high + gap + low
        if self.style.video_text == "middle":
            top = (fr.top + fr.bottom - whole) / 2
        else:
            top = self.floor() - BOTTOM_GAP * fr.scale - whole
        now = tall.block(self.lines[k][1], face, size, 700, 2, top + high / 2, fr, rows)
        nxt = None
        if n is not None:
            nxt = tall.block(
                self.lines[n][1], face, nsize, 500, 2, top + high + gap + low / 2, fr, nrows
            )
        return now, nxt

    def floor(self) -> float:
        """The lower edge of the room the lines keep to."""
        fr = self.fr
        if self.style.video_text == "low":
            return max(fr.bottom, fr.h - fr.bar - LOW_EDGE * fr.scale)
        return fr.bottom

    def band(self, d: ImageDraw.ImageDraw, parts: list[dict], alpha: float) -> None:
        colour = BANDS.get(self.style.video_band)
        if colour is None or not parts:
            return
        fr = self.fr
        pad_x, pad_y = BAND_PAD[0] * fr.text, BAND_PAD[1] * fr.text
        top = min(p["box"][1] for p in parts) - pad_y
        bottom = max(p["box"][3] for p in parts) + pad_y
        left = min(p["box"][0] for p in parts) - pad_x
        right = max(p["box"][2] for p in parts) + pad_x
        box = (max(0, left), top, min(fr.w, right), bottom)
        shade = round(255 * min(1.0, max(0.0, self.style.video_band_alpha)) * alpha)
        d.rounded_rectangle(box, radius=round(12 * fr.text), fill=(*colour, shade))

    def text(self, layer: Image.Image, k: int, t: float, alpha: float) -> None:
        now, nxt = self.blocks(k)
        if now is None or alpha <= 0:
            return
        d = ImageDraw.Draw(layer)
        self.band(d, [p for p in (now, nxt) if p], alpha)
        face = fonts.resolve(self.style.font)
        times = self.times[k]
        if times:
            tall.letters(d, now, round(255 * alpha), times, t, self.fr.cx, self.ink, self.lit)
        else:
            self.rows(d, now, round(255 * alpha), face)
        if nxt:
            self.rows(d, nxt, round(255 * NEXT_ALPHA * alpha), face)

    def rows(self, d: ImageDraw.ImageDraw, part: dict, alpha: int, face: str) -> None:
        f = render.font(face, part["size"], part["weight"])
        pitch = part["size"] * tall.PITCH
        for i, row in enumerate(part["rows"]):
            y = part["centre"] + (i - (len(part["rows"]) - 1) / 2) * pitch
            render.lettered(d, (self.fr.cx, y), row, f, alpha, self.ink)

    def state(self, t: float) -> tuple:
        k = tall.current(t, self.lines)
        p = tall.moved(t, k, self.lines, self.first)
        times = self.times[k] if k >= 0 else None
        letters = (
            tuple(
                (tall.pop(t, times, j), times[j] <= t < tall.later(times, j))
                for j in range(len(times))
            )
            if times
            else ()
        )
        return (k, round(p * self.fps), letters)

    def layer(self, t: float) -> Image.Image:
        """The clear layer at t: the new line fades in over tall.CHANGE seconds while the one before
        it fades out."""
        img = self.base.copy()
        k = tall.current(t, self.lines)
        p = tall.moved(t, k, self.lines, self.first)
        if p < 1.0 and k > 0:
            self.text(img, k - 1, t, 1.0 - p)
        self.text(img, k, t, p)
        return img

    def image(self, t: float, state: tuple | None = None) -> Image.Image:
        """The whole frame at t, RGBA: the video's frame and the layer over it."""
        img = picture(self.song.video, video_at(t, self.style, self.song), self.size)
        img = img.copy()
        img.alpha_composite(self.layer(t))
        return img

    def raw(self, t: float) -> bytes:
        """The layer at t as RGBA bytes for ffmpeg, which lays it over the video."""
        state = self.state(t)
        if state == self.last[0]:
            return self.last[1]
        raw = self.layer(t).tobytes()
        self.last = (state, raw)
        return raw


_painters: dict = {}


def painter(
    lines: tuple[tuple[float, str], ...], song: render.Song, style: render.Style
) -> Painter:
    key = (lines, song, style, render.stamp(song.video))
    found = _painters.get(key)
    if found is None:
        if len(_painters) >= 2:
            _painters.pop(next(iter(_painters)))
        found = _painters[key] = Painter(lines, song, style)
    return found


def inputs(
    style: render.Style, song: render.Song, first: float, fps: int
) -> tuple[list[str], str, str]:
    """ffmpeg's input options for the video and the filters for its picture and its sound from the
    video clock's `first`: looped or held on its last frame, cut to start there, held on its first
    frame (and silent) while the song is before it, and the picture made the frame's size and rate.
    The cut is a trim rather than a seek, so a held video still has its last frame to hold."""
    at = first - song.lead - start(style, song)
    before = max(0.0, -at)
    at = max(0.0, at)
    picture, sound = [], []
    if style.video_end == "hold":
        opts = ["-i", song.video]
        picture.append("tpad=stop=-1:stop_mode=clone")
    else:
        whole = length(song.video)
        at = math.fmod(at, whole) if whole > 0 else 0.0
        opts = ["-stream_loop", "-1", "-i", song.video]
    picture += [f"trim=start={at:.3f}", "setpts=PTS-STARTPTS"]
    sound += [f"atrim=start={at:.3f}", "asetpts=PTS-STARTPTS"]
    if before:
        picture.append(f"tpad=start_duration={before:.3f}:start_mode=clone")
        sound.append(f"adelay={round(before * 1000)}:all=1")
    w, h = render.frame_size(style)
    picture += [f"fps={fps}", fit(w, h), "format=rgba"]
    return opts, ",".join(picture), ",".join([*sound, "apad"])


def streams(path: str) -> tuple[bool, bool]:
    """Whether the file has a picture and whether it has sound, from ffmpeg's banner."""
    run = subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", path],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        **media.quiet(),
    )
    return " Video: " in run.stderr, " Audio: " in run.stderr


def has_sound(path: str) -> bool:
    return streams(path)[1]


def boxes(style: render.Style) -> dict[str, tuple[int, ...]]:
    """The room the text keeps to, for tests; the page has nothing to drag over a video."""
    fr = room(style)
    return {"text": (fr.margin, fr.top, fr.right, fr.bottom)}
