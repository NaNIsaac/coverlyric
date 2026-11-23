"""coverlyric mcp, driven in process: each tool runs its command on the project folder, keeps
nothing between calls, prints nothing to stdout, and opens the page only when asked."""

import asyncio
import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from coverlyric import cli, mcp_server
from coverlyric.project import Project

DEMO = Path(cli.__file__).parent / "demo"


@pytest.fixture()
def folder(tmp_path) -> Path:
    folder = tmp_path / "project"
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("one\ntwo\nthree\n", encoding="utf-8")
    project = cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", lyrics, "song")
    project.lines = [(1.0, "one"), (2.0, "two"), (3.0, "three")]
    project.save(folder / "project.json")
    return folder


def call(name: str, **arguments):
    result = asyncio.run(mcp_server.server.call_tool(name, arguments))
    return result


def answer(name: str, **arguments) -> dict:
    result = call(name, **arguments)
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


def saved(folder: Path) -> Project:
    return Project.load(folder / "project.json")


def test_the_tools_are_listed():
    names = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert names == {
        "project_show",
        "project_set",
        "lines_get",
        "lines_set_text",
        "lines_set_time",
        "lines_shift",
        "output_list",
        "output_add",
        "output_use",
        "still",
        "clip_render",
        "render",
        "open_page",
    }


def test_show_and_set_go_through_the_file(folder, capsys):
    assert answer("project_show", project=str(folder))["title"] == "song"
    answer("project_set", project=str(folder), pairs=["title=new", "lead=2"])
    assert saved(folder).title == "new" and saved(folder).style.lead == 2.0
    assert capsys.readouterr().out == "", "stdout belongs to the protocol"


def test_a_refused_key_is_an_error_with_the_commands_words(folder):
    with pytest.raises(ToolError, match="unknown key 'nosuch'"):
        call("project_set", project=str(folder), pairs=["nosuch=1"])


def test_lines(folder):
    got = answer("lines_get", project=str(folder), first=2, last=3)
    assert [row["text"] for row in got["lines"]] == ["two", "three"] and got["count"] == 3
    answer("lines_set_text", project=str(folder), line=2, text="zwei")
    answer("lines_set_time", project=str(folder), line=1, time="0:01.5")
    answer("lines_shift", project=str(folder), by="0.5", lines="2-3")
    assert saved(folder).lines == [(1.5, "one"), (2.5, "zwei"), (3.5, "three")]
    answer("lines_shift", project=str(folder), by="-1")
    assert saved(folder).lines == [(0.5, "one"), (1.5, "zwei"), (2.5, "three")]


def test_outputs(folder):
    answer("output_add", project=str(folder), id="short", shape="tall")
    assert [o["id"] for o in answer("output_list", project=str(folder))["outputs"]] == [
        "wide",
        "short",
    ]
    answer("output_use", project=str(folder), id="wide")
    assert saved(folder).current == "wide"
    answer("project_set", project=str(folder), pairs=["fps=24"], output="short")
    assert saved(folder).outputs[1].style.fps == 24


def test_a_change_made_while_the_page_is_open_reaches_the_page(tmp_path, folder):
    from coverlyric import server

    app = server.App(tmp_path / "home", folder)
    rev = app.state()["rev"]
    answer("project_set", project=str(folder), pairs=["title=from a tool"])
    state = app.state()
    assert state["title"] == "from a tool" and state["rev"] != rev


def test_still_is_a_png_image_kept_out_of_the_project(folder):
    result = call("still", project=str(folder), at="1")
    assert not result.is_error and result.content[0].type == "image"
    assert result.content[0].mime_type == "image/png"
    assert (
        not (folder / "still.png").exists() and (folder / ".cache" / "mcp" / "still.png").exists()
    )


def test_clip_render_answers_its_path(folder, monkeypatch):
    made = {}

    def fake(project, out, clip=None, quick=False, report=None):
        made.update(out=out, clip=clip, quick=quick)
        return {"video": str(out)}

    monkeypatch.setattr(cli, "make_video", fake)
    got = answer("clip_render", project=str(folder), start="1", end="2")
    assert made["clip"] == (1.0, 2.0) and made["quick"]
    assert Path(got["video"]).parent == folder / ".cache" / "mcp"


def test_render_reports_and_answers_the_files(folder, monkeypatch):
    def fake(project, out, clip=None, quick=False, report=None):
        report(5.0, 10.0)
        report(10.0, 10.0)
        return {"video": str(project.folder / "song.mp4")}

    monkeypatch.setattr(cli, "make_video", fake)
    assert answer("render", project=str(folder))["video"].endswith("song.mp4")


def test_open_page_reuses_the_page_open_on_the_project(folder, monkeypatch):
    opened, started = [], []
    monkeypatch.setattr(mcp_server.webbrowser, "open", opened.append)
    monkeypatch.setattr(mcp_server.subprocess, "Popen", lambda *a, **k: started.append(a))
    monkeypatch.setattr(mcp_server, "running_page", lambda f: "http://127.0.0.1:1/")
    assert answer("open_page", project=str(folder)) == {
        "url": "http://127.0.0.1:1/",
        "started": False,
    }
    assert opened == ["http://127.0.0.1:1/"] and started == []


def test_open_page_starts_one_on_its_own(folder, monkeypatch):
    started = []
    answers = iter([None, None, "http://127.0.0.1:2/"])
    monkeypatch.setattr(mcp_server.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    monkeypatch.setattr(mcp_server, "running_page", lambda f: next(answers))
    assert answer("open_page", project=str(folder))["started"] is True
    assert started[0][-2:] == ["app", str(folder.resolve())]


def test_a_page_on_another_folder_is_not_taken_for_this_one(tmp_path, folder, monkeypatch):
    page = folder / ".cache" / "page"
    page.mkdir(parents=True)
    (page / "page.json").write_text(json.dumps({"url": "http://127.0.0.1:3/"}), encoding="utf-8")

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"folder": str(tmp_path / "other")}).encode()

    monkeypatch.setattr(mcp_server.urllib.request, "urlopen", lambda *a, **k: Answer())
    assert mcp_server.running_page(folder.resolve()) is None
