import pytest

from agent_history.gitdetect import extract_commit_sha, is_commit_command


@pytest.mark.parametrize(
    "cmd",
    [
        "git commit -m 'x'",
        "git add a && git commit -q -F - <<'EOF'\nmsg\nEOF",
        "cd repo; git -C sub commit --amend --no-edit",
        '/bin/zsh -lc git add README.md && git commit -m "fix" && git push',
    ],
)
def test_detects_commit_commands(cmd):
    assert is_commit_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "git log --grep commit",
        "git status",
        "echo commit",
        "git show HEAD:commit.txt",
        "",
        "cat > notes.md <<'EOF'\n手順:\n  git commit -m x\nEOF\nwc -l notes.md",
    ],
)
def test_ignores_non_commit_commands(cmd):
    assert not is_commit_command(cmd)


def test_sha_from_commit_summary_line():
    assert extract_commit_sha("[main abc1234] docs: fix\n 1 file changed") == "abc1234"
    assert extract_commit_sha("[feat/x (root-commit) 0f1e2d3] init") == "0f1e2d3"


def test_sha_from_oneline_log_after_quiet_commit():
    assert extract_commit_sha("bac57c2 Web UIを刷新\n1eb3094 older") == "bac57c2"


def test_no_sha_when_output_has_none():
    assert extract_commit_sha("To github.com:me/x.git\n   8042064..e8a43fc  main -> main") is None
    assert extract_commit_sha("") is None
    assert extract_commit_sha(None) is None
