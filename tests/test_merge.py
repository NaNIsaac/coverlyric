"""The page's merge when project.json changed elsewhere: the file's change and the page's own both
stay, and a field both changed is named for the user to choose."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MERGE = Path(__file__).parents[1] / "src" / "coverlyric" / "web" / "merge.js"
NODE = shutil.which("node")
BASE = {
    "current": "wide",
    "title": "song",
    "artist": "",
    "album": "",
    "released": "",
    "clean_tags": True,
    "lines": [[1.0, "one"], [2.0, "two"]],
    "style": {"lead": 0.0, "fps": 25},
}


def merge(mine: dict, fresh: dict, keep: bool = False) -> tuple[dict, list[str]]:
    script = (
        f"const m = require({json.dumps(str(MERGE))});"
        f"const r = m.mergeState({json.dumps(BASE)}, {json.dumps(mine)}, {json.dumps(fresh)});"
        f"if ({json.dumps(keep)}) r.both.forEach((b) => b.keep());"
        "console.log(JSON.stringify([r.out, r.both.map((b) => b.name)]));"
    )
    out = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    got, names = json.loads(out.stdout)
    return got, names


def changed(**fields) -> dict:
    data = json.loads(json.dumps(BASE))
    for key, value in fields.items():
        if key in data["style"]:
            data["style"][key] = value
        else:
            data[key] = value
    return data


pytestmark = pytest.mark.skipif(NODE is None, reason="needs node to run the page script")


def test_each_side_keeps_its_own_change():
    mine = changed(title="page", lines=[[1.0, "one"], [2.5, "two"]])
    fresh = changed(lead=2.0, lines=[[1.2, "one"], [2.0, "two"]])
    out, both = merge(mine, fresh)
    assert both == []
    assert out["title"] == "page" and out["style"]["lead"] == 2.0
    assert out["lines"] == [[1.2, "one"], [2.5, "two"]]


def test_a_field_both_changed_is_named_and_the_file_wins_unless_kept():
    mine, fresh = changed(title="page", fps=30), changed(title="tool", fps=30)
    out, both = merge(mine, fresh)
    assert both == ["제목"] and out["title"] == "tool" and out["style"]["fps"] == 30
    out, _ = merge(mine, fresh, keep=True)
    assert out["title"] == "page"


def test_lines_added_on_one_side_and_changed_on_the_other_are_named():
    mine = changed(lines=[[1.0, "one"], [2.0, "two"], [3.0, "three"]])
    fresh = changed(lines=[[1.0, "uno"], [2.0, "two"]])
    out, both = merge(mine, fresh)
    assert both == ["가사"] and out["lines"] == fresh["lines"]


def test_another_output_on_screen_takes_the_file_as_it_is():
    mine = changed(title="page", current="short")
    fresh = changed(lead=2.0)
    out, both = merge(mine, fresh)
    assert both == [] and out == fresh
