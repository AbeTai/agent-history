"""Recognise `git commit` invocations in shell commands and pull the SHA out of their output."""

import re

_COMMIT_CMD = re.compile(r"(?:^|[\s;&|(])git(?:\s+-[Cc]\s+\S+)*\s+commit\b")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?^\s*\2\s*$", re.S | re.M)
_SUMMARY_SHA = re.compile(r"^\[[^\]\n]*?\b([0-9a-f]{7,40})\]", re.M)
_LEADING_SHA = re.compile(r"^([0-9a-f]{7,40})(?:\s|$)", re.M)


def is_commit_command(command: str | None) -> bool:
    """True if the shell command runs `git commit` (text inside heredoc bodies is ignored)."""
    if not command:
        return False
    return bool(_COMMIT_CMD.search(_HEREDOC.sub("", command)))


def extract_commit_sha(output: str | None) -> str | None:
    """SHA from `[branch abc1234] msg`, or from a following `git log --oneline`/`rev-parse`."""
    if not output:
        return None
    if m := _SUMMARY_SHA.search(output):
        return m.group(1)
    if m := _LEADING_SHA.search(output):
        return m.group(1)
    return None
