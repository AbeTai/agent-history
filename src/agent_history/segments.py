"""Split activity timestamps into contiguous segments (the bars drawn on the calendar)."""

from collections.abc import Iterable

DEFAULT_GAP_MS = 30 * 60 * 1000


def split_segments(points: Iterable[int], gap_ms: int = DEFAULT_GAP_MS) -> list[tuple[int, int]]:
    """Merge epoch-ms points into (start, end) ranges, breaking where the gap exceeds gap_ms."""
    segments: list[tuple[int, int]] = []
    for t in sorted(points):
        if segments and t - segments[-1][1] <= gap_ms:
            segments[-1] = (segments[-1][0], t)
        else:
            segments.append((t, t))
    return segments
