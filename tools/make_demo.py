"""Write the demo song (a generated tune), the demo cover and the demo project into src/lyricvideo/demo.

uv run python tools/make_demo.py
"""

import json
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "lyricvideo" / "demo"
RATE = 22050
NOTES = [  # (start s, length s, MIDI note)
    (0.0, 2.0, 57), (2.0, 2.0, 60), (4.0, 2.0, 64), (6.0, 2.0, 62),
    (8.0, 1.0, 64), (9.0, 1.0, 67), (10.0, 2.0, 69), (12.0, 1.0, 67),
    (13.0, 1.0, 64), (14.0, 2.0, 62), (16.0, 2.0, 60),
]  # fmt: skip
LINES = [
    (3.0, "첫 번째 줄이에요"),
    (6.5, "두 번째 줄은 조금 길어요"),
    (10.0, "세 번째 줄"),
    (13.5, "마지막 줄입니다"),
]


def tune() -> np.ndarray:
    total = int(RATE * 18.0)
    t = np.arange(total) / RATE
    out = np.zeros(total)
    for start, length, note in NOTES:
        f = 440 * 2 ** ((note - 69) / 12)
        a, b = int(start * RATE), int((start + length) * RATE)
        local = t[a:b] - start
        env = np.minimum(1, local / 0.02) * np.exp(-local * 1.6)
        out[a:b] += env * (np.sin(2 * np.pi * f * local) + 0.3 * np.sin(4 * np.pi * f * local))
    return (out / np.abs(out).max() * 0.6 * 32767).astype("<i2")


def cover(size: int = 800) -> Image.Image:
    y, x = np.mgrid[0:size, 0:size] / size
    rgb = np.dstack([40 + 120 * x, 50 + 60 * y, 110 + 100 * (1 - x) * y]).clip(0, 255)
    img = Image.fromarray(rgb.astype("uint8"), "RGB")
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    for cx, cy, r, a in ((0.68, 0.32, 0.18, 150), (0.3, 0.7, 0.1, 110), (0.5, 0.5, 0.36, 40)):
        d.ellipse(
            ((cx - r) * size, (cy - r) * size, (cx + r) * size, (cy + r) * size),
            fill=(255, 230, 190, a),
        )
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(24)))
    return img.convert("RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / "tone.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(tune().tobytes())
    cover().save(OUT / "cover.png", optimize=True)
    project = {
        "audio": "tone.wav",
        "art": "cover.png",
        "title": "데모 노래",
        "artist": "가사 영상 만들기",
        "duration": 18.0,
        "lines": [list(line) for line in LINES],
        "style": {},
    }
    (OUT / "demo.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )


if __name__ == "__main__":
    main()
