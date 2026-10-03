"""Count added/removed lines from the diff formats each tool records."""


def _count(lines) -> tuple[int, int]:
    added = removed = 0
    for line in lines:
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def count_unified_diff(diff: str | None) -> tuple[int, int]:
    """Codex FileChange.unified_diff."""
    return _count(diff.splitlines()) if diff else (0, 0)


def count_structured_patch(patch: list[dict] | None) -> tuple[int, int]:
    """Claude Edit/Write toolUseResult.structuredPatch (hunk lines carry no file headers)."""
    added = removed = 0
    for hunk in patch or []:
        for line in hunk.get("lines", []):
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    return added, removed
