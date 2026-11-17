import io
import json
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image

from coverlyric import server


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
