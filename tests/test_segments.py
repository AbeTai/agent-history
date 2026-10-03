from agent_history.segments import split_segments

MIN = 60_000


def test_empty_input_gives_no_segments():
    assert split_segments([], gap_ms=30 * MIN) == []


def test_points_within_gap_merge_into_one_segment():
    points = [0, 5 * MIN, 29 * MIN]
    assert split_segments(points, gap_ms=30 * MIN) == [(0, 29 * MIN)]


def test_gap_longer_than_threshold_splits():
    points = [0, 10 * MIN, 41 * MIN, 50 * MIN]
    assert split_segments(points, gap_ms=30 * MIN) == [(0, 10 * MIN), (41 * MIN, 50 * MIN)]


def test_unsorted_input_and_single_point_segment():
    points = [100 * MIN, 0, 5 * MIN]
    assert split_segments(points, gap_ms=30 * MIN) == [(0, 5 * MIN), (100 * MIN, 100 * MIN)]
