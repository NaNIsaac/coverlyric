"""업데이트.bat replaces only the program files and keeps what the user made; a failed update puts the
old program back. Run in Windows PowerShell 5.1, as the .bat runs it."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the .bat is Windows only")

REPO = Path(__file__).parents[1]
UPDATE = REPO / "tools" / "update.ps1"

USER_FILES = {
    "만든 영상/노래.mp4": "video",
    "작업 중/project.json": "{}",
    "settings.json": '{"output": ""}',
    "coverlyric.log": "log",
    "coverlyric.log.1": "old log",
    ".venv/pyvenv.cfg": "home = x",
    "업데이트 백업/20260101-000000/src/old.py": "older backup",
    "내 노래/song.mp3": "the user's own folder",
}
OLD_PROGRAM = {
    "pyproject.toml": 'version = "0.1.0"\n',
    "src/coverlyric/__init__.py": "old",
    "tools/start.ps1": "old start",
    "README.md": "old readme",
    "가사영상 만들기.bat": "old bat",
}
NEW_PROGRAM = {
    "pyproject.toml": 'version = "0.2.0"\n',
    "src/coverlyric/__init__.py": "new",
    "tools/start.ps1": "new start",
    "README.md": "new readme",
    "가사영상 만들기.bat": "new bat",
    "업데이트.bat": "new update bat",
    "added.txt": "a name the new version adds",
}


def powershell(command: str, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, **env},
    )


def lines(command: str) -> list[str]:
    run = powershell(f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; . '{UPDATE}'; {command}")
    assert run.returncode == 0, run.stderr
    return run.stdout.splitlines()


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture()
def folders(tmp_path):
    root, new = tmp_path / "coverlyric", tmp_path / "coverlyric-main"
    write(root, USER_FILES | OLD_PROGRAM)
    write(new, NEW_PROGRAM)
    return root, new


def test_kept_paths_are_never_program_files(folders):
    _, new = folders
    write(new, {"만든 영상/x.mp4": "", "settings.json": ""})
    names = lines(f"Get-ProgramPaths '{new}'")
    kept = lines("$KeepPaths")
    assert not set(names) & set(kept)
    assert {"src", "tools", "README.md", "가사영상 만들기.bat", "업데이트.bat", "added.txt"} <= set(
        names
    )
    assert {
        "만든 영상",
        "작업 중",
        "settings.json",
        "coverlyric.log",
        ".venv",
        "업데이트 백업",
    } <= set(kept)
    assert "내 노래" not in names


def test_an_update_replaces_the_program_and_keeps_the_rest(folders, tmp_path):
    root, new = folders
    backup = root / "업데이트 백업" / "20261119-120000"
    lines(
        f"$c = [Collections.Generic.List[string]]::new(); Install-Program '{root}' '{new}' '{backup}' $c"
    )
    got = tree(root)
    for name, text in USER_FILES.items():
        assert got[name] == text, name
    for name, text in NEW_PROGRAM.items():
        assert got[name] == text, name
    for name, text in OLD_PROGRAM.items():
        assert got[f"업데이트 백업/20261119-120000/{name}"] == text, name


def test_a_failed_update_puts_the_old_program_back(folders):
    root, new = folders
    before = tree(root)
    backup = root / "업데이트 백업" / "20261119-120000"
    # The third copy fails, as a full disk or a file held open would make it.
    run = powershell(
        f". '{UPDATE}'; $script:n = 0; "
        "function Copy-Item { $script:n++; if ($script:n -eq 3) { throw 'disk full' }; "
        "Microsoft.PowerShell.Management\\Copy-Item @args }; "
        "$c = [Collections.Generic.List[string]]::new(); "
        f"try {{ Install-Program '{root}' '{new}' '{backup}' $c }} "
        f"catch {{ Restore-Program '{root}' '{backup}' $c; 'restored' }}"
    )
    assert "restored" in run.stdout, run.stderr
    assert tree(root) == before


def test_the_version_is_read_from_pyproject(folders):
    root, new = folders
    assert lines(f"Get-ProgramVersion '{root}'; Get-ProgramVersion '{new}'") == ["0.1.0", "0.2.0"]


def test_the_whole_update_from_a_zip(folders, tmp_path):
    root, new = folders
    (root / "tools" / "update.ps1").write_bytes(UPDATE.read_bytes())
    archive = tmp_path / "main.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, text in NEW_PROGRAM.items():
            z.writestr(f"coverlyric-main/{name}", text)
        z.writestr("coverlyric-main/src/coverlyric/render.py", "")
        z.write(UPDATE, "coverlyric-main/tools/update.ps1")
    run = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "tools/update.ps1"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "COVERLYRIC_UPDATE_ZIP": str(archive)},
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "지금 버전: 0.1.0" in run.stdout
    assert "새 버전: 0.2.0 (이전 0.1.0)" in run.stdout
    assert run.stdout.rstrip().endswith("업데이트 끝")
    got = tree(root)
    for name, text in USER_FILES.items():
        assert got[name] == text, name
    assert got["src/coverlyric/__init__.py"] == "new"
    backups = [p for p in (root / "업데이트 백업").iterdir() if p.name != "20260101-000000"]
    assert len(backups) == 1 and (backups[0] / "src" / "coverlyric" / "__init__.py").exists()


def test_a_zip_that_is_not_coverlyric_changes_nothing(folders, tmp_path):
    root, _ = folders
    (root / "tools" / "update.ps1").write_bytes(UPDATE.read_bytes())
    before = tree(root)
    archive = tmp_path / "other.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("something-main/readme.txt", "not this program")
    run = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "tools/update.ps1"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "COVERLYRIC_UPDATE_ZIP": str(archive)},
    )
    assert run.returncode == 1
    assert "프로그램은 바뀌지 않았습니다" in run.stdout
    assert tree(root) == before


def test_the_bat_runs_in_one_line():
    """The update replaces 업데이트.bat while it runs, and cmd reads a batch file line by line."""
    bat = (REPO / "업데이트.bat").read_text(encoding="ascii")
    run = [line for line in bat.splitlines() if line and not line.startswith(("@echo", "rem "))]
    assert len(run) == 1 and "tools\\update.ps1" in run[0] and "pause" in run[0]
