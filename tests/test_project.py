from pathlib import Path

import pytest

from agent_history.project import project_name


def test_enclosing_git_repo_name(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "sub" / "deep").mkdir(parents=True)
    project_name.cache_clear()
    assert project_name(str(tmp_path / "repo" / "sub" / "deep")) == "repo"


def test_falls_back_to_basename(tmp_path):
    project_name.cache_clear()
    assert project_name(str(tmp_path / "gone" / "proj")) == "proj"
    assert project_name(None) is None


@pytest.mark.parametrize(
    "folder", ["Documents", "Desktop", "Downloads", "Library/Mobile Documents"]
)
def test_never_touches_tcc_protected_folders(folder, monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")

    # A background launchd job probing ~/Documents would trigger a macOS privacy prompt.
    def boom(self):
        raise AssertionError(f"filesystem probed: {self}")

    monkeypatch.setattr(Path, "exists", boom)
    project_name.cache_clear()
    cwd = str(Path.home() / folder / "Codex" / "2026-08-23" / "flight-search")
    assert project_name(cwd) == "flight-search"


def test_protection_is_macos_only(tmp_path, monkeypatch):
    # Windows/Linux have no TCC prompts; repos under Documents should resolve to the repo name.
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Documents" / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "Documents" / "repo" / "sub").mkdir()
    project_name.cache_clear()
    assert project_name(str(tmp_path / "Documents" / "repo" / "sub")) == "repo"
