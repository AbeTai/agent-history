from agent_history.diffstat import count_structured_patch, count_unified_diff


def test_unified_diff_counts_added_and_removed_lines_ignoring_headers():
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,4 @@\n ctx\n-old\n+new\n+more\n"
    assert count_unified_diff(diff) == (2, 1)


def test_unified_diff_none_or_empty():
    assert count_unified_diff("") == (0, 0)
    assert count_unified_diff(None) == (0, 0)


def test_structured_patch_from_claude_edit_result():
    patch = [
        {
            "oldStart": 1,
            "oldLines": 2,
            "newStart": 1,
            "newLines": 3,
            "lines": [" keep", "-gone", "+added", "+added2"],
        },
        {"oldStart": 9, "oldLines": 1, "newStart": 10, "newLines": 0, "lines": ["-x"]},
    ]
    assert count_structured_patch(patch) == (2, 2)
