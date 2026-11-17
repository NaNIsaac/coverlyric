"""The launcher repairs a virtual environment whose Python sits behind a junction the session may not
follow (os error 448) and starts once more (#17); when Python still cannot start, or there is no
environment yet, it makes the environment again with a full-version Python and names it to uv (#18,
#19). Other failures are not retried. Run in Windows PowerShell 5.1 with 'Stop', as the .bat
runs it."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="junctions and the .bat are Windows only"
)

START = Path(__file__).parents[1] / "tools" / "start.ps1"

# Stands in for uv: fails the way uv does while the environment's home goes through a junction, or,
# with FAKE_UV_NEEDS_PYTHON, while no Python is named. `uv python dir` prints FAKE_UV_PYTHON_DIR.
FAKE_UV = """
import os, sys
venv, log, args = sys.argv[1], sys.argv[2], sys.argv[3:]
if args[:2] == ["python", "dir"]:
    print(os.environ.get("FAKE_UV_PYTHON_DIR", ""))
    sys.exit(0)
cfg = os.path.join(venv, "pyvenv.cfg")
home = "-"
if os.path.exists(cfg):
    home = next(line.split("=", 1)[1].strip() for line in open(cfg, encoding="utf-8")
                if line.startswith("home"))
named = os.environ.get("UV_PYTHON")
with open(log, "a", encoding="utf-8") as f:
    f.write(home + (f" python={named}" if named else "") + "\\n")
through_junction = home != "-" and os.path.realpath(home) != os.path.abspath(home)
missing = os.environ.get("FAKE_UV_NEEDS_PYTHON") and not named
if (through_junction and not named) or missing or os.environ.get("FAKE_UV_FAIL"):
    print("error: failed to query Python interpreter: os error 448")
    sys.exit(2)
print("started")
"""


def junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True
    )


@pytest.fixture()
def setup(tmp_path):
    real = tmp_path / "python" / "cpython-3.14.2-windows-x86_64-none"
    real.mkdir(parents=True)
    link = tmp_path / "python" / "cpython-3.14-windows-x86_64-none"
    junction(link, real)
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text(
        f"home = {link}\ninclude-system-site-packages = false\nversion_info = 3.14.2\n",
        encoding="utf-8",
    )
    log = tmp_path / "uv.log"
    script = tmp_path / "fake_uv.py"
    script.write_text(FAKE_UV, encoding="utf-8")
    uv = tmp_path / "uv.cmd"
    uv.write_text(f'@"{sys.executable}" -I "{script}" "{venv}" "{log}" %*\n', encoding="utf-8")
    return uv, venv, log, real, link


def powershell(command: str, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**{k: v for k, v in os.environ.items() if k != "UV_PYTHON"}, **env},
    )


def start(uv: Path, venv: Path, **env) -> subprocess.CompletedProcess:
    command = (
        f". '{START}'; $ErrorActionPreference = 'Stop'; "
        f"Start-Program '{uv}' '{venv}'; exit $LASTEXITCODE"
    )
    return powershell(command, **env)


def make_venv(venv: Path, home: Path) -> None:
    """A real environment whose python.exe reads its home from pyvenv.cfg and, when the home has no
    Python, fails with a message on stderr, as a Python behind a junction it cannot follow does."""
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    cfg = venv / "pyvenv.cfg"
    lines = cfg.read_text(encoding="utf-8").splitlines()
    cfg.write_text(
        "\n".join(f"home = {home}" if x.startswith("home") else x for x in lines) + "\n",
        encoding="utf-8",
    )


def pythons(root: Path, *names: str) -> Path:
    for name in names:
        (root / name).mkdir(parents=True)
        (root / name / "python.exe").write_bytes(b"")
    return root


def full_python(root: Path, name: str) -> Path:
    """A Python that runs, standing in for a full-version folder of uv's: the venv launcher with a
    pyvenv.cfg beside it naming the Python these tests run on."""
    source = root.parent / "launcher"
    make_venv(source, Path(os.path.realpath(sys.base_prefix)))
    folder = root / name
    folder.mkdir(parents=True)
    shutil.copy(source / "Scripts" / "python.exe", folder / "python.exe")
    shutil.copy(source / "pyvenv.cfg", folder / "pyvenv.cfg")
    return folder / "python.exe"


def home(venv: Path) -> str:
    cfg = (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    return next(x.split("=", 1)[1].strip() for x in cfg.splitlines() if x.startswith("home"))


def test_a_python_behind_a_junction_is_repaired_and_started_again(setup):
    uv, venv, log, real, link = setup
    run = start(uv, venv)
    assert run.returncode == 0, run.stdout + run.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [str(link), str(real)]
    cfg = (venv / "pyvenv.cfg").read_bytes()
    assert f"home = {real}".encode() in cfg and not cfg.startswith(b"\xef\xbb\xbf")
    assert b"version_info = 3.14.2" in cfg


def test_a_python_that_writes_to_stderr_does_not_end_the_launcher(setup):
    # Windows PowerShell 5.1 with 'Stop' ended the script on the failing Python's stderr (#18).
    uv, venv, log, real, link = setup
    make_venv(venv, link)
    run = start(uv, venv)
    assert run.returncode == 0, run.stdout + run.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [str(link), str(real)]


def test_with_no_environment_one_is_made_with_a_full_version_python(setup, tmp_path):
    uv, venv, log, _real, _link = setup
    (venv / "pyvenv.cfg").unlink()  # uv stopped before making the environment
    managed = pythons(
        tmp_path / "managed",
        "cpython-3.11.9-windows-x86_64-none",
        "cpython-3.13.5-windows-x86_64-none",
        "cpython-3.14.3+freethreaded-windows-x86_64-none",
        "cpython-3.15.0b4-windows-x86_64-none",
    )
    chosen = full_python(managed, "cpython-3.14.2-windows-x86_64-none")
    junction(
        managed / "cpython-3.15-windows-x86_64-none",
        managed / "cpython-3.15.0b4-windows-x86_64-none",
    )
    run = start(uv, venv, FAKE_UV_NEEDS_PYTHON="1", FAKE_UV_PYTHON_DIR=str(managed))
    assert run.returncode == 0, run.stdout + run.stderr
    assert log.read_text(encoding="utf-8").splitlines() == ["-", f"{home(venv)} python={chosen}"]
    assert (venv / "Scripts" / "python.exe").is_file()


def test_a_uv_trampoline_is_made_again_without_the_cfg_repair(setup, tmp_path):
    # uv's trampoline names the junction inside the executable and ignores pyvenv.cfg (#19).
    uv, venv, log, _real, link = setup
    (venv / "Scripts").mkdir()
    (venv / "Scripts" / "python.exe").write_bytes(b"MZ\0\0uv trampoline failed to spawn\0")
    (venv / "old.txt").write_text("left by the old environment", encoding="utf-8")
    chosen = full_python(tmp_path / "managed", "cpython-3.13.15-windows-x86_64-none")
    run = start(uv, venv, FAKE_UV_PYTHON_DIR=str(tmp_path / "managed"))
    assert run.returncode == 0, run.stdout + run.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [
        str(link),
        f"{home(venv)} python={chosen}",
    ]
    assert home(venv) != str(link) and not (venv / "old.txt").exists()


def test_a_python_still_broken_after_the_repair_gets_a_new_environment(setup, tmp_path):
    uv, venv, log, real, link = setup
    make_venv(venv, link)  # the repaired home has no python.exe either
    chosen = full_python(tmp_path / "managed", "cpython-3.12.10-windows-x86_64-none")
    run = start(uv, venv, FAKE_UV_FAIL="1", FAKE_UV_PYTHON_DIR=str(tmp_path / "managed"))
    assert run.returncode == 2
    assert log.read_text(encoding="utf-8").splitlines() == [
        str(link),
        str(real),
        f"{home(venv)} python={chosen}",
    ]


def test_a_failure_with_a_plain_home_is_not_retried(setup, tmp_path):
    uv, venv, log, _real, _link = setup
    base = Path(sys.base_prefix)
    make_venv(venv, base)  # a Python that starts: the program itself failed
    managed = pythons(tmp_path / "managed", "cpython-3.14.2-windows-x86_64-none")
    run = start(uv, venv, FAKE_UV_FAIL="1", FAKE_UV_PYTHON_DIR=str(managed))
    assert run.returncode == 2
    assert log.read_text(encoding="utf-8").splitlines() == [str(base)]


def test_only_a_folder_named_venv_is_made_again(tmp_path):
    other = tmp_path / "work"
    other.mkdir()
    (other / "keep.txt").write_text("not the program's", encoding="utf-8")
    run = powershell(f". '{START}'; Reset-Venv '{other}' '{sys.executable}'")
    assert run.stdout.strip() == "False"
    assert (other / "keep.txt").is_file()


@pytest.mark.parametrize(
    ("names", "least", "chosen"),
    [
        (["cpython-3.12.9", "cpython-3.12.10", "cpython-3.13.0rc1"], "3.12", "cpython-3.12.10"),
        (["cpython-3.11.9", "cpython-3.15.0b4", "cpython-3.14.1+freethreaded"], "3.12", None),
        ([], "3.12", None),
    ],
)
def test_find_managed_python(tmp_path, names, least, chosen):
    managed = pythons(tmp_path / "managed", *(f"{n}-windows-x86_64-none" for n in names))
    managed.mkdir(exist_ok=True)
    run = powershell(f". '{START}'; Find-ManagedPython '{managed}' '{least}'")
    assert run.returncode == 0, run.stderr
    expected = str(managed / f"{chosen}-windows-x86_64-none" / "python.exe") if chosen else ""
    assert run.stdout.strip() == expected
