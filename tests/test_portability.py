"""Static guards for Windows portability."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_IO = {"open", "read_text", "write_text"}


def _calls_without_encoding(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in TEXT_IO:
            continue
        if any(k.arg == "encoding" for k in node.keywords):
            continue
        mode = next((a for a in node.args if isinstance(a, ast.Constant)), None)
        if name == "open" and mode is not None and "b" in str(mode.value):
            continue  # binary mode
        yield f"{path.relative_to(ROOT)}:{node.lineno}"


def test_text_io_always_names_its_encoding():
    # Without encoding=, Python uses the ANSI code page on Windows (cp932 on Japanese
    # systems) and Japanese transcripts either fail to decode or turn into mojibake.
    offenders = [
        hit
        for folder in ("src", "tests")
        for path in sorted((ROOT / folder).rglob("*.py"))
        for hit in _calls_without_encoding(path)
    ]
    assert offenders == []
