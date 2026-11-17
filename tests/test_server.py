import io
import json
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image

from coverlyric import render, server


@pytest.fixture()
def base(tmp_path):
    app = server.App(tmp_path)
    ref: list = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(app, ref))
    ref.append(httpd)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(url, data=None, headers=None):
    body = data if isinstance(data, bytes) or data is None else json.dumps(data).encode()
    headers = headers or {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url, data=body, headers=headers or {}, method="POST" if body is not None else "GET"
    )
    with urllib.request.urlopen(req) as res:
        return res.read(), dict(res.headers)


def test_demo_preview_and_line_edits(base, tmp_path):
    state = json.loads(call(f"{base}/api/demo", b"")[0])
    assert state["has_audio"] and len(state["lines"]) == 4
    lines = state["lines"]
    lines[1][0] += 0.1
    lines.append([None, "새 줄"])
    jpeg, headers = call(f"{base}/api/preview?t=7", {"lines": lines, "style": {"bar": True}})
    assert jpeg[:2] == b"\xff\xd8"
    assert set(json.loads(headers["X-Boxes"])) == {"album", "panel", "title", "bar"}
    saved = json.loads((tmp_path / "작업 중" / "project.json").read_text(encoding="utf-8"))
    assert saved["lines"][1][0] == pytest.approx(6.6) and saved["lines"][-1] == [None, "새 줄"]
    with pytest.raises(urllib.error.HTTPError):
        call(f"{base}/api/render", b"")  # the new line has no time yet


def test_import_marks_lines_that_differ(base):
    call(f"{base}/api/demo", b"")
    srt = "1\n00:00:03,000 --> 00:00:05,000\n첫 번째 줄이에요\n\n2\n00:00:06,000 --> 00:00:08,000\n두번째 줄\n"
    data = json.loads(call(f"{base}/api/import", srt.encode(), {"X-Name": "a.srt"})[0])
    assert [t for t, _ in data["lines"]] == [3.0, 6.0]
    assert data["diff"] == [None, "두 번째 줄은 조금 길어요"]


def test_audio_is_served_with_ranges(base):
    call(f"{base}/api/demo", b"")
    req = urllib.request.Request(f"{base}/media/audio", headers={"Range": "bytes=0-99"})
    with urllib.request.urlopen(req) as res:
        assert res.status == 206 and len(res.read()) == 100


def test_anim_frames_are_served_only_when_listed(base, tmp_path):
    call(f"{base}/api/demo", b"")
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(buf, "PNG")
    state = json.loads(call(f"{base}/api/upload?kind=anim", buf.getvalue(), {"X-Name": "a.png"})[0])
    name = state["anim"][0]
    png, _ = call(f"{base}/media/anim?name={urllib.parse.quote(name)}")
    assert png[:4] == b"\x89PNG"
    for other in ("project.json", "../작업 중/project.json", "anim/missing.png"):
        with pytest.raises(urllib.error.HTTPError):
            call(f"{base}/media/anim?name={urllib.parse.quote(other)}")


@pytest.mark.parametrize(
    ("header", "status", "length"),
    [("bytes=999999999-", 416, None), ("bytes=-999999999", 206, "all"), ("bytes=10-19", 206, 10)],
)
def test_audio_ranges_are_clamped(base, header, status, length):
    call(f"{base}/api/demo", b"")
    size = len(call(f"{base}/media/audio")[0])
    req = urllib.request.Request(f"{base}/media/audio", headers={"Range": header})
    try:
        with urllib.request.urlopen(req) as res:
            got, data = res.status, res.read()
    except urllib.error.HTTPError as e:
        got, data = e.code, None
    assert got == status
    if length is not None:
        assert len(data) == (size if length == "all" else length)


def test_two_quick_render_clicks_start_one_render(tmp_path, monkeypatch):
    app = server.App(tmp_path)
    app.demo()
    started = []

    class Slow:
        stdout = iter(())
        pid = 0

        def __init__(self, *args, **kwargs):
            started.append(1)
            time.sleep(0.3)

        def wait(self):
            return 0

        def poll(self):
            return None

    monkeypatch.setattr(server.subprocess, "Popen", Slow)
    monkeypatch.setattr(server.App, "watch", lambda self, proc, out: None)
    clicks = [threading.Thread(target=app.start_render) for _ in range(2)]
    for t in clicks:
        t.start()
    for t in clicks:
        t.join()
    assert len(started) == 1


def test_band_from_cover_is_the_cover_colour_kept_readable(base):
    with pytest.raises(urllib.error.HTTPError):
        call(f"{base}/api/band-from-cover")  # no cover yet
    call(f"{base}/api/demo", b"")
    band = json.loads(call(f"{base}/api/band-from-cover")[0])["band"]
    assert len(band) == 7 and band.startswith("#")
    rgb = [int(band[k : k + 2], 16) for k in (1, 3, 5)]
    need = server.contrast(render.hex_rgb(render.Style().band), (255, 255, 255))
    assert server.contrast(rgb, (255, 255, 255)) >= need - 0.01


def test_a_bright_cover_gives_a_band_as_readable_as_the_default(base):
    call(f"{base}/api/demo", b"")
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (250, 215, 70)).save(buf, "PNG")
    call(f"{base}/api/upload?kind=art", buf.getvalue(), {"X-Name": "bright.png"})
    band = json.loads(call(f"{base}/api/band-from-cover")[0])["band"]
    rgb = [int(band[k : k + 2], 16) for k in (1, 3, 5)]
    need = server.contrast(render.hex_rgb(render.Style().band), (255, 255, 255))
    assert server.contrast(rgb, (255, 255, 255)) >= need - 0.01
    assert rgb[0] > rgb[2]  # still the cover's yellow, only darker


def test_dark_lyrics_on_a_dark_cover_get_a_lighter_band(base):
    call(f"{base}/api/demo", b"")
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (20, 30, 90)).save(buf, "PNG")
    call(f"{base}/api/upload?kind=art", buf.getvalue(), {"X-Name": "navy.png"})
    call(f"{base}/api/state", {"style": {"lyric_colour": "#111111"}})
    band = json.loads(call(f"{base}/api/band-from-cover")[0])["band"]
    rgb = [int(band[k : k + 2], 16) for k in (1, 3, 5)]
    need = server.contrast(render.hex_rgb(render.Style().band), (255, 255, 255))
    assert server.contrast(rgb, (17, 17, 17)) >= need - 0.01
    assert server.luminance(rgb) > server.luminance((20, 30, 90))
    assert rgb[2] > rgb[0]  # still blue, only lighter


def test_the_preview_says_which_lines_are_too_wide(base):
    state = json.loads(call(f"{base}/api/demo", b"")[0])
    lines = state["lines"]
    lines[1][1] = (
        "오늘도 나는 같은 자리에서 너를 기다리고 또 기다리다가 잠이 들어 꿈에서라도 만나길"
    )
    _, headers = call(f"{base}/api/preview?t=7", {"lines": lines})
    fits = json.loads(headers["X-Fit"])
    assert len(fits) == len(lines)
    assert fits[0] == [1.0, 1] and fits[1][1] == 2
