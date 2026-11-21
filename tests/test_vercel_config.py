import json
import re
from pathlib import Path

from airwise.middleware import SECURITY_HEADERS

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
RULES = [rule for rule in CONFIG.get("headers", []) if rule.get("source") == "/(.*)"]


def _rule_pairs() -> list[tuple[str, str]]:
    assert len(RULES) == 1
    return [(h["key"], h["value"]) for h in RULES[0]["headers"]]


def test_vercel_json_keeps_functions_without_rewrites():
    assert "rewrites" not in CONFIG
    function = CONFIG["functions"]["api/index.py"]
    assert function["maxDuration"] == 30
    assert function["includeFiles"] == "public/**"


def test_vercel_headers_match_security_headers():
    expected = {(k.decode("latin-1"), v.decode("latin-1")) for k, v in SECURITY_HEADERS}
    assert set(_rule_pairs()) == expected


def test_vercel_headers_have_no_duplicates_or_empty_values():
    pairs = _rule_pairs()
    keys = [key.lower() for key, _ in pairs]
    assert len(keys) == len(set(keys))
    assert all(value.strip() for _, value in pairs)


def test_vercel_headers_are_valid_http_fields():
    for key, value in _rule_pairs():
        assert re.fullmatch(r"[A-Za-z0-9-]+", key)
        assert "\r" not in value
        assert "\n" not in value
