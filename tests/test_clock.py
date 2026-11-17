import json
import shutil
import subprocess
from pathlib import Path

import pytest

CLOCK = Path(__file__).parents[1] / "src" / "coverlyric" / "web" / "clock.js"
NODE = shutil.which("node")

CASES = {
    "10": 10,
    "10.5": 10.5,
    "10,5": 10.5,
    " 7 ": 7,
    "1:05": 65,
    "1:05.3": 65.3,
    "0:01:05": 65,
    "1:00:00": 3600,
    "": None,
    "1:0x": None,
    "abc": None,
    "1:75": None,
    "1:65:00": None,
    "-3": None,
}


@pytest.mark.skipif(NODE is None, reason="needs node to run the page script")
def test_parse_clock():
    script = (
        f"const c = require({json.dumps(str(CLOCK))});"
        f"const cases = {json.dumps(list(CASES))};"
        "console.log(JSON.stringify(cases.map((t) => c.parseClock(t))));"
        "console.log(JSON.stringify([c.clockTenth(65.3), c.clockTenth(9.96), c.clockTenth(0)]));"
    )
    out = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True
    ).stdout.split("\n")
    got = json.loads(out[0])
    for (text, want), value in zip(CASES.items(), got, strict=True):
        assert value == pytest.approx(want) if want is not None else value is None, text
    assert json.loads(out[1]) == ["1:05.3", "0:10.0", "0:00.0"]
