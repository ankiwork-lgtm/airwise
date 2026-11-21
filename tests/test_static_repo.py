import json
import re
from pathlib import Path

from airwise.config import LLM_TIMEOUT_S

ROOT = Path(__file__).resolve().parent.parent


def test_no_requirements_txt():
    assert not (ROOT / "requirements.txt").exists()


def test_env_example_lists_vars_without_real_key():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^ANTHROPIC_API_KEY=", text, re.M)
    assert re.search(r"^ANTHROPIC_BASE_URL=", text, re.M)
    assert re.search(r"^LLM_MODEL=", text, re.M)
    value = re.search(r"^ANTHROPIC_API_KEY=(.*)$", text, re.M).group(1).strip()
    # Placeholder only: no long key-like token.
    assert not re.search(r"sk-[A-Za-z0-9_\-]{20,}", text)
    assert value in ("", "sk-") or "your" in value.lower() or "here" in value.lower()


def test_vercel_json_no_api_rewrite_and_duration():
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    # A rewrite to /api/index changes the path FastAPI sees and makes every /api/* call 404.
    assert "rewrites" not in cfg
    max_duration = cfg["functions"]["api/index.py"]["maxDuration"]
    assert LLM_TIMEOUT_S + 2 <= max_duration


def test_pyproject_declares_runtime_dependencies():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.M | re.S).group(1)
    names = {
        re.match(r"[A-Za-z0-9_.\-]+", item.strip().strip('",')).group(0).lower()
        for item in block.splitlines()
        if item.strip().strip(",")
    }
    assert {"fastapi", "httpx", "pydantic"} <= names
