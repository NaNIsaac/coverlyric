import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from coverlyric import fonts, server


@pytest.fixture()
def port(tmp_path):
    app = server.App(tmp_path)
    ref: list = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(app, ref))
    ref.append(httpd)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def send(port, method, path, body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body if method == "POST" else None, headers=headers or {})
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res.status, data


JSON = {"Content-Type": "application/json"}


def test_the_page_itself_is_served(port):
    assert send(port, "GET", "/api/state")[0] == 200
    assert send(port, "POST", "/api/demo", b"{}", JSON)[0] == 200
    own = {**JSON, "Origin": f"http://127.0.0.1:{port}", "Host": f"localhost:{port}"}
    assert send(port, "POST", "/api/state", b"{}", own)[0] == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:{port}", "127.0.0.1:1"])
def test_a_foreign_host_is_refused(port, host):
    """A DNS-rebinding page reaches 127.0.0.1 with its own name in the Host header."""
    headers = {"Host": host.format(port=port)}
    assert send(port, "GET", "/api/state", headers=headers)[0] == 403
    assert send(port, "POST", "/api/quit", b"{}", {**JSON, **headers})[0] == 403


def test_a_foreign_origin_is_refused(port):
    headers = {**JSON, "Origin": "http://evil.example"}
    assert send(port, "POST", "/api/new", b"{}", headers)[0] == 403


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", None])
def test_a_post_without_a_preflighted_type_is_refused(port, ctype):
    """A form or a no-cors fetch from another site sends these without asking the server first."""
    headers = {"Content-Type": ctype} if ctype else {}
    assert send(port, "POST", "/api/auto", b'{"model": "small"}', headers)[0] == 403


def test_uploads_with_their_name_header_are_allowed(port):
    status, _ = send(port, "POST", "/api/import", "1줄\n".encode(), {"X-Name": "a.txt"})
    assert status == 200


@pytest.mark.parametrize(
    "font",
    [r"\\host\share\x.ttf", "//host/share/x.ttf", r"\\?\UNC\host\share\x.ttf", "{tmp}/x.ttf"],
)
def test_fonts_outside_the_font_folders_are_refused(port, font, tmp_path):
    body = json.dumps({"style": {"font": font.format(tmp=tmp_path)}}).encode()
    status, data = send(port, "POST", "/api/state", body, JSON)
    assert status == 400 and "글꼴" in json.loads(data)["error"]


def test_font_choices_are_allowed(tmp_path):
    work = tmp_path / "작업 중"
    assert fonts.allowed(fonts.DEFAULT, work)
    assert fonts.allowed(str(work / "fonts" / "mine.ttf"), work)
    assert not fonts.allowed(str(work / "fonts" / "mine.exe"), work)
    assert not fonts.allowed(str(work / ".." / ".." / "x.ttf"), work)
    if os.name == "nt":
        assert fonts.allowed(str(Path(os.environ["WINDIR"]) / "Fonts" / "malgun.ttf"), work)
    for choice in fonts.choices()["installed"]:
        assert fonts.allowed(choice["id"], work)
