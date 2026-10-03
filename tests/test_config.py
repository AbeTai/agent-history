from pathlib import Path

from agent_history.ingest import Config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_data_lives_under_repo_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_HISTORY_HOME", raising=False)
    cfg = Config.from_env()
    assert cfg.data_home == REPO_ROOT / "data"
    assert cfg.db_path == REPO_ROOT / "data" / "history.db"
    assert cfg.log_dir == REPO_ROOT / "data" / "logs"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HISTORY_HOME", str(tmp_path))
    assert Config.from_env().data_home == tmp_path


def test_data_home_falls_back_when_not_running_from_a_checkout(tmp_path):
    from agent_history.ingest import default_data_home

    checkout = tmp_path / "repo"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("[project]\nname='agent-history'\n", encoding="utf-8")
    assert default_data_home(checkout) == checkout / "data"
    # e.g. a non-editable install inside site-packages: the per-OS fallback is used
    # (its value per OS is covered by test_platforms.TestDefaultLocations).
    assert default_data_home(tmp_path / "site-packages", fallback="/fb") == Path("/fb")


def test_sources_listing(tmp_path):
    cfg = Config(
        claude_home=tmp_path / "c",
        claude_desktop=tmp_path / "d",
        codex_home=tmp_path / "x",
        data_home=tmp_path / "data",
    )
    (tmp_path / "x" / "sessions").mkdir(parents=True)
    assert cfg.sources() == {
        "claude": tmp_path / "c" / "projects",
        "codex": tmp_path / "x" / "sessions",
    }


def test_from_env_resolves_windows_locations():
    env = {"APPDATA": r"C:\Users\me\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\me\AppData\Local"}
    cfg = Config.from_env(platform="win32", env=env, home=r"C:\Users\me")
    assert str(cfg.claude_home) == r"C:\Users\me\.claude"
    assert str(cfg.claude_desktop) == r"C:\Users\me\AppData\Roaming\Claude\claude-code-sessions"
    assert cfg.data_home == REPO_ROOT / "data"  # running from a checkout


def test_from_env_data_home_override_and_fallback(tmp_path):
    from agent_history.ingest import default_data_home

    cfg = Config.from_env(platform="darwin", env={"AGENT_HISTORY_HOME": str(tmp_path)}, home="/h")
    assert cfg.data_home == tmp_path
    assert default_data_home(tmp_path / "not-a-checkout", fallback="X:/la/agent-history") == Path(
        "X:/la/agent-history"
    )
