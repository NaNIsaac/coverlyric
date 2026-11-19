"""The installer ships the program files only, and the user's data goes to its own folder, out of the
program folder once (tools/start.ps1)."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).parents[1]
ISS = REPO / "installer" / "coverlyric.iss"
START = REPO / "tools" / "start.ps1"
USER_DATA = ("작업 중", "만든 영상", "settings.json", "coverlyric.log", ".venv")


def sources() -> list[str]:
    text = ISS.read_text(encoding="utf-8-sig")
    files = text.split("[Files]", 1)[1].split("\n[", 1)[0]
    return re.findall(r'^Source: "([^"]+)"', files, re.MULTILINE)


def test_the_installer_ships_what_the_launcher_needs():
    shipped = sources()
    for needed in (
        "src\\*",
        "tools\\start.ps1",
        "pyproject.toml",
        "uv.lock",
        "가사영상 만들기.bat",
    ):
        assert needed in shipped
    for name in shipped:
        if name == "installer\\uv\\uv.exe":
            continue  # downloaded by the workflow before the build
        path = REPO / name.replace("\\", "/").removesuffix("/*")
        assert path.exists(), name


def test_the_installer_ships_no_user_data():
    for name in sources():
        assert not any(part in name for part in USER_DATA), name


def test_the_installer_keeps_one_app_id_and_installs_per_user():
    text = ISS.read_text(encoding="utf-8-sig")
    assert "AppId={{4297D240-C551-4ACA-A335-915B65192ED2}" in text
    assert "PrivilegesRequired=lowest" in text
    assert "DefaultDirName={localappdata}\\Programs\\coverlyric" in text


def test_the_icon_has_every_size():
    sizes = Image.open(REPO / "installer" / "icon.ico").info["sizes"]
    assert {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)} <= set(sizes)


windows = pytest.mark.skipif(sys.platform != "win32", reason="the launcher is Windows only")


def powershell(command: str, **env) -> subprocess.CompletedProcess:
    run = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; . '{START}'; {command}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**{k: v for k, v in os.environ.items() if k != "COVERLYRIC_HOME"}, **env},
    )
    assert run.returncode == 0, run.stderr
    return run


@windows
def test_the_data_folder_is_documents_coverlyric_by_default(tmp_path):
    got = powershell(f"Get-DataFolder '{tmp_path / 'none.txt'}'").stdout.strip()
    docs = powershell("[Environment]::GetFolderPath('MyDocuments')").stdout.strip()
    assert got == str(Path(docs) / "coverlyric")


@windows
def test_the_chosen_data_folder_and_coverlyric_home_win(tmp_path):
    saved = tmp_path / "data-folder.txt"
    saved.write_text("\ufeffD:\\노래 작업\n", encoding="utf-8")
    assert powershell(f"Get-DataFolder '{saved}'").stdout.strip() == "D:\\노래 작업"
    got = powershell(f"Get-DataFolder '{saved}'", COVERLYRIC_HOME=str(tmp_path / "h"))
    assert got.stdout.strip() == str(tmp_path / "h")


@windows
def test_old_data_moves_out_of_the_program_folder_once(tmp_path):
    root, data = tmp_path / "program", tmp_path / "data"
    (root / "만든 영상").mkdir(parents=True)
    (root / "만든 영상" / "노래.mp4").write_text("video", encoding="utf-8")
    (root / "작업 중").mkdir()
    (root / "작업 중" / "project.json").write_text("{}", encoding="utf-8")
    (root / "settings.json").write_text(
        json.dumps({"output": str(root / "만든 영상")}), encoding="utf-8"
    )
    (root / "src").mkdir()
    run = powershell(f"Move-OldData '{root}' '{data}'")
    assert (data / "만든 영상" / "노래.mp4").read_text(encoding="utf-8") == "video"
    assert (data / "작업 중" / "project.json").exists()
    assert not (root / "만든 영상").exists() and (root / "src").exists()
    saved = json.loads((data / "settings.json").read_text(encoding="utf-8-sig"))
    assert saved["output"] == str(data / "만든 영상")
    assert "만든 영상 을" in run.stdout
    assert powershell(f"Move-OldData '{root}' '{data}'").stdout.strip() == ""


@windows
def test_data_already_in_the_data_folder_is_never_overwritten(tmp_path):
    root, data = tmp_path / "program", tmp_path / "data"
    (root / "작업 중").mkdir(parents=True)
    (root / "작업 중" / "project.json").write_text("old", encoding="utf-8")
    (data / "작업 중").mkdir(parents=True)
    (data / "작업 중" / "project.json").write_text("new", encoding="utf-8")
    run = powershell(f"Move-OldData '{root}' '{data}'")
    assert (data / "작업 중" / "project.json").read_text(encoding="utf-8") == "new"
    assert (root / "작업 중" / "project.json").read_text(encoding="utf-8") == "old"
    assert "두 곳에 있어" in run.stdout


@windows
def test_a_program_folder_used_as_the_data_folder_stays(tmp_path):
    (tmp_path / "작업 중").mkdir()
    assert powershell(f"Move-OldData '{tmp_path}' '{tmp_path}'").stdout.strip() == ""
    assert (tmp_path / "작업 중").exists()
