"""Static checks for the chat panel in public/index.html.

Validates: Requirements 8.8, 11.4
"""

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "public" / "index.html").read_text(
    encoding="utf-8"
)


def test_starter_question_count_is_3_to_5():
    m = re.search(r"var\s+STARTERS\s*=\s*\[(.*?)\]\s*;", HTML, re.S)
    assert m, "STARTERS array not found"
    questions = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    assert 3 <= len(questions) <= 5, questions
    assert all(q.strip() for q in questions)


def test_no_forbidden_dom_assignments():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML"):
        assert sink not in HTML, sink
    assert not re.search(r"document\.write\s*\(", HTML)


def test_history_trimmed_to_10_in_script():
    assert re.search(r"var\s+MAX_HISTORY\s*=\s*10\s*;", HTML)
    # Request payload and stored history both use the last MAX_HISTORY entries.
    assert re.search(r"history\s*:\s*history\.slice\(\s*-MAX_HISTORY\s*\)", HTML)
    assert re.search(r"history\s*=\s*history\.slice\(\s*-MAX_HISTORY\s*\)", HTML)
