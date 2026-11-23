"""`coverlyric mcp --config`: the setting an AI client pastes to start this coverlyric's server."""

import json
from pathlib import Path

from coverlyric import __main__ as main


def entry(config: dict) -> dict:
    return config["mcpServers"]["coverlyric"]


def test_a_source_folder_runs_the_server_with_uv_in_that_folder(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("")
    monkeypatch.delenv("COVERLYRIC_UV", raising=False)
    monkeypatch.setattr(main.shutil, "which", lambda name: f"/bin/{name}")
    got = entry(main.client_config(tmp_path))
    assert got["command"] == "/bin/uv"
    assert got["args"][:3] == ["run", "--directory", str(tmp_path)]
    assert got["args"][-2:] == ["coverlyric", "mcp"] and "mcp" in got["args"][-4:-2]


def test_the_installed_program_uses_its_own_uv(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "uv").mkdir()
    (tmp_path / "uv" / "uv.exe").write_bytes(b"")
    monkeypatch.delenv("COVERLYRIC_UV", raising=False)
    assert entry(main.client_config(tmp_path))["command"] == str(tmp_path / "uv" / "uv.exe")
    monkeypatch.setenv("COVERLYRIC_UV", "/start/uv.exe")
    assert entry(main.client_config(tmp_path))["command"] == "/start/uv.exe", (
        "the one start.ps1 set"
    )


def test_without_a_source_folder_the_program_on_path_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: f"/bin/{name}")
    assert entry(main.client_config(tmp_path)) == {"command": "/bin/coverlyric", "args": ["mcp"]}


def test_the_command_prints_the_setting_as_json(capsys):
    main.main(["mcp", "--config"])
    got = json.loads(capsys.readouterr().out)
    assert Path(entry(got)["args"][2], "pyproject.toml").is_file(), "this checkout's folder"
