"""The launcher repairs a virtual environment whose Python sits behind a junction the session may not
follow (os error 448) and starts once more; other failures are not retried (#17)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="junctions and the .bat are Windows only"
)

START = Path(__file__).parents[1] / "tools" / "start.ps1"

# Stands in for uv: fails the way uv does while the environment's home goes through a junction.
FAKE_UV = """
import os, sys
venv, log = sys.argv[1], sys.argv[2]
home = next(line.split("=", 1)[1].strip() for line in open(os.path.join(venv, "pyvenv.cfg"), encoding="utf-8")
            if line.startswith("home"))
with open(log, "a", encoding="utf-8") as f:
    f.write(home + "\\n")
through_junction = os.path.realpath(home) != os.path.abspath(home)
if through_junction or os.environ.get("FAKE_UV_FAIL"):
    print("error: failed to query Python interpreter: os error 448")
    sys.exit(2)
print("started")
"""


@pytest.fixture()
def setup(tmp_path):
    real = tmp_path / "python" / "cpython-3.14.2-windows-x86_64-none"
    real.mkdir(parents=True)
    link = tmp_path / "python" / "cpython-3.14-windows-x86_64-none"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real)], check=True, capture_output=True
    )
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text(
        f"home = {link}\ninclude-system-site-packages = false\nversion_info = 3.14.2\n",
        encoding="utf-8",
    )
    log = tmp_path / "uv.log"
    script = tmp_path / "fake_uv.py"
    script.write_text(FAKE_UV, encoding="utf-8")
    uv = tmp_path / "uv.cmd"
    uv.write_text(f'@"{sys.executable}" -I "{script}" "{venv}" "{log}"\n', encoding="utf-8")
    return uv, venv, log, real, link


def start(uv: Path, venv: Path, **env) -> subprocess.CompletedProcess:
    command = f". '{START}'; Start-Program '{uv}' '{venv}'; exit $LASTEXITCODE"
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, **env},
    )


def test_a_python_behind_a_junction_is_repaired_and_started_again(setup):
    uv, venv, log, real, link = setup
    run = start(uv, venv)
    assert run.returncode == 0, run.stdout + run.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [str(link), str(real)]
    cfg = (venv / "pyvenv.cfg").read_bytes()
    assert f"home = {real}".encode() in cfg and not cfg.startswith(b"\xef\xbb\xbf")
    assert b"version_info = 3.14.2" in cfg


def test_a_failure_with_a_plain_home_is_not_retried(setup):
    uv, venv, log, real, _link = setup
    (venv / "pyvenv.cfg").write_text(f"home = {real}\n", encoding="utf-8")
    run = start(uv, venv, FAKE_UV_FAIL="1")
    assert run.returncode == 2
    assert log.read_text(encoding="utf-8").splitlines() == [str(real)]
