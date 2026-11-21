"""Static checks of .github/workflows/ci.yml (text-based: PyYAML is not a project dependency)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _jobs() -> dict[str, str]:
    """Split the text of the `jobs:` section into one block per job (two-space-indented keys)."""
    section = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\s*$", section, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


JOBS = _jobs()


def _uses_lines() -> list[str]:
    return re.findall(r"^\s*(?:-\s+)?uses:\s*(\S.*)$", WORKFLOW, flags=re.MULTILINE)


def test_jobs_are_checks_and_browser():
    assert set(JOBS) == {"checks", "browser"}


def test_every_action_is_pinned_to_a_full_commit_sha():
    uses = _uses_lines()
    assert len(uses) >= 5
    for line in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line), line


def test_only_expected_actions_are_used():
    names = {line.split("@", 1)[0] for line in _uses_lines()}
    assert names == {
        "actions/checkout",
        "actions/setup-python",
        "actions/upload-artifact",
    }


def test_same_pin_is_used_for_the_same_action():
    pins: dict[str, set[str]] = {}
    for line in _uses_lines():
        name, ref = line.split("@", 1)
        pins.setdefault(name, set()).add(ref)
    assert all(len(refs) == 1 for refs in pins.values()), pins


def test_permissions_are_read_only_and_not_widened():
    assert re.search(r"^permissions:\n  contents: read\n", WORKFLOW, flags=re.MULTILINE)
    assert len(re.findall(r"^\s*permissions:", WORKFLOW, flags=re.MULTILINE)) == 1
    assert not re.search(r":\s*write\b", WORKFLOW)


def test_triggers_and_concurrency_unchanged():
    assert "pull_request:" in WORKFLOW
    assert "pull_request_target" not in WORKFLOW
    assert "branches: [main]" in WORKFLOW
    assert "cancel-in-progress: true" in WORKFLOW


def test_no_secrets_or_tokens_are_referenced():
    assert not re.search(r"secrets\.|GITHUB_TOKEN|ANTHROPIC", WORKFLOW)


def test_no_unpinned_downloads():
    assert not re.search(r"curl|wget|\|\s*(ba)?sh\b", WORKFLOW)


@pytest.mark.parametrize("job", ["checks", "browser"])
def test_jobs_install_from_the_hash_checked_lock(job: str):
    block = JOBS[job]
    assert "pip install --require-hashes -r requirements-dev.lock" in block
    assert "pip install --no-deps -e ." in block
    assert "persist-credentials: false" in block
    assert "shell: bash" in block
    assert re.search(r"timeout-minutes: \d+", block)


def test_checks_job_excludes_browser_tests_and_keeps_the_coverage_gate():
    block = JOBS["checks"]
    assert 'pytest -m "not browser" --cov=airwise --cov-report=term-missing' in block
    assert "pip-audit -r requirements-dev.lock --require-hashes --strict" in block
    assert "playwright" not in block
    assert "AIRWISE_REQUIRE_BROWSER" not in block


def test_browser_job_runs_chromium_tests_without_coverage():
    block = JOBS["browser"]
    assert "python -m playwright install --with-deps chromium" in block
    assert 'AIRWISE_REQUIRE_BROWSER: "1"' in block
    assert "AIRWISE_BROWSER_CHANNEL" not in block
    run = re.search(r"run: (pytest tests/browser .*)", block)
    assert run
    assert "-m browser" in run.group(1)
    assert "--no-cov" in run.group(1)
    assert "--cov=" not in run.group(1)
    assert "matrix" not in block


def test_browser_job_uploads_failure_artifacts_only_on_failure():
    block = JOBS["browser"]
    step = block.split("Upload failure artifacts", 1)[1]
    assert "if: failure()" in step
    assert "path: test-results/" in step
    assert "retention-days: 7" in step
    assert "if-no-files-found: ignore" in step
    assert "actions/upload-artifact@" in step
