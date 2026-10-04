import shutil
from pathlib import Path

import pytest

from agent_history.ingest import Config, run_ingest
from agent_history.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_SID = "11111111-1111-4111-8111-111111111111"
ALL = (0, 10**14)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    shutil.copytree(FIXTURES / "claude" / "projects", tmp_path / "claude" / "projects")
    shutil.copytree(FIXTURES / "claude" / "sessions", tmp_path / "claude" / "sessions")
    shutil.copytree(FIXTURES / "claude" / "desktop", tmp_path / "desktop")
    shutil.copytree(FIXTURES / "codex", tmp_path / "codex")
    return Config(
        claude_home=tmp_path / "claude",
        claude_desktop=tmp_path / "desktop",
        codex_home=tmp_path / "codex",
        data_home=tmp_path / "data",
    )


@pytest.fixture
def store(config: Config):
    s = Store(config.db_path)
    yield s
    s.close()


def ids(store: Store) -> set[str]:
    return {r["id"] for r in store.session_summaries(*ALL, include_subagents=True)}


def claude_file(config: Config) -> Path:
    return config.claude_home / "projects" / "-Users-me-dev-demo" / f"{CLAUDE_SID}.jsonl"


def test_first_run_ingests_everything(config, store):
    report = run_ingest(config, store, pid_alive=lambda pid: False)
    assert report.parsed == 3
    assert report.failed == []
    assert ids(store) == {
        f"claude:{CLAUDE_SID}",
        "codex:019faaaa-0000-7000-8000-000000000001",
        "codex:019faaaa-0000-7000-8000-000000000002",
    }


def test_second_run_skips_unchanged_files(config, store):
    run_ingest(config, store, pid_alive=lambda pid: False)
    report = run_ingest(config, store, pid_alive=lambda pid: False)
    assert (report.parsed, report.skipped) == (0, 3)


def test_changed_file_is_reparsed(config, store):
    run_ingest(config, store, pid_alive=lambda pid: False)
    with claude_file(config).open("a", encoding="utf-8") as f:
        f.write('{"type":"custom-title","customTitle":"改名","sessionId":"x"}\n')
    report = run_ingest(config, store, pid_alive=lambda pid: False)
    assert report.parsed == 1
    titles = {r["id"]: r["title"] for r in store.session_summaries(*ALL)}
    assert titles[f"claude:{CLAUDE_SID}"] == "改名"


def test_desktop_meta_and_running_flag(config, store):
    run_ingest(config, store, pid_alive=lambda pid: pid == 4242)
    row = next(r for r in store.session_summaries(*ALL) if r["source"] == "claude")
    assert row["work_state"] == "completed"
    assert row["is_running"] is True


def test_session_survives_source_deletion(config, store):
    run_ingest(config, store, pid_alive=lambda pid: False)
    claude_file(config).unlink()
    run_ingest(config, store, pid_alive=lambda pid: False)
    assert f"claude:{CLAUDE_SID}" in ids(store)


def test_rebuild_from_archive_after_source_deleted(config, tmp_path):
    with Store(config.db_path) as s:
        run_ingest(config, s, pid_alive=lambda pid: False)
    claude_file(config).unlink()
    config.db_path.unlink()
    with Store(config.db_path) as fresh:
        run_ingest(config, fresh, pid_alive=lambda pid: False)
        assert f"claude:{CLAUDE_SID}" in ids(fresh)


def test_bad_file_is_reported_and_others_still_ingested(config, store):
    bad = config.claude_home / "projects" / "-Users-me-dev-demo" / "broken.jsonl"
    bad.write_text("[1, 2, 3]\n", encoding="utf-8")
    report = run_ingest(config, store, pid_alive=lambda pid: False)
    assert report.parsed == 3
    assert [Path(p).name for p, _ in report.failed] == ["broken.jsonl"]


def test_missing_homes_are_fine(tmp_path):
    cfg = Config(
        claude_home=tmp_path / "none",
        claude_desktop=tmp_path / "none2",
        codex_home=tmp_path / "none3",
        data_home=tmp_path / "data",
    )
    with Store(cfg.db_path) as s:
        report = run_ingest(cfg, s)
    assert (report.parsed, report.skipped, report.failed) == (0, 0, [])
    assert report.missing_sources == ["claude", "codex"]


def test_sources_found_are_not_reported_missing(config, store):
    assert run_ingest(config, store, pid_alive=lambda pid: False).missing_sources == []


def test_archive_copy_failure_is_reported_and_retried(config, store, monkeypatch):
    # On Windows a transcript being written can be locked; one locked file must not abort
    # the run, and the copy must be retried next time.
    real_copy = shutil.copy2
    calls = []

    def flaky_copy(src, dst):
        calls.append(src)
        if len(calls) == 1:
            raise PermissionError(32, "The process cannot access the file")
        return real_copy(src, dst)

    monkeypatch.setattr("agent_history.ingest.shutil.copy2", flaky_copy)
    first = run_ingest(config, store, pid_alive=lambda pid: False)
    assert first.parsed == 3  # the session itself is still saved
    assert [Path(p).name for p, _ in first.failed] == [f"{CLAUDE_SID}.jsonl"]
    assert "archive" in first.failed[0][1]
    second = run_ingest(config, store, pid_alive=lambda pid: False)
    assert second.parsed == 1 and second.failed == []
    assert (config.archive_dir / "claude" / "-Users-me-dev-demo" / f"{CLAUDE_SID}.jsonl").exists()


def test_parser_version_change_forces_reparse(config, store, monkeypatch):
    # New parser features (e.g. compaction tracking) must reach files ingested earlier.
    run_ingest(config, store, pid_alive=lambda pid: False)
    assert run_ingest(config, store, pid_alive=lambda pid: False).parsed == 0
    monkeypatch.setattr("agent_history.ingest.PARSER_VERSION", 999)
    assert run_ingest(config, store, pid_alive=lambda pid: False).parsed == 3
