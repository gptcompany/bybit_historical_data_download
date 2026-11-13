import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/check_workflow_runners.py"
spec = importlib.util.spec_from_file_location("check_workflow_runners", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

GENERIC = "${{ vars.CI_RUNS_ON }}"
PUBLIC = checker.EXPECTED["public"]


def make_repo(tmp_path, runs_on, policy):
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    (tmp_path / ".github/runner-policy.json").write_text(policy)
    (workflows / "ci.yml").write_text(f"jobs:\n  test:\n    runs-on: {runs_on}\n    steps:\n      - run: true\n")
    return tmp_path


def test_repository_workflows_pass():
    assert checker.main() == 0


@pytest.mark.parametrize(
    ("runs_on", "visibility", "expected"),
    [
        (PUBLIC, "public", 0),
        # Operator rule 2026-11-13: no job of a public repository may depend on GitHub-hosted minutes.
        ("ubuntu-latest", "public", 1),
        # Without the fork guard, fork pull request code would run on the self-hosted pool.
        (GENERIC, "public", 1),
        ("${{ vars.CI_RUNS_ON || 'sg-ci' }}", "public", 1),
        ("[self-hosted, sg-ci]", "public", 1),
        ("[ubuntu-latest]", "public", 1),
        ("ubuntu-24.04", "public", 1),
        (GENERIC, "private", 0),
        ("ubuntu-latest", "private", 1),
    ],
)
def test_runner_follows_declared_visibility(tmp_path, runs_on, visibility, expected):
    root = make_repo(tmp_path, runs_on, json.dumps({"visibility": visibility}))
    assert checker.main(root) == expected


@pytest.mark.parametrize(
    "policy",
    ["{", "[]", json.dumps({"visibility": "internal"}), json.dumps({"visibility": "public", "why": "x"}), "{}"],
)
def test_invalid_policy_fails(tmp_path, policy):
    root = make_repo(tmp_path, "ubuntu-latest", policy)
    with pytest.raises(ValueError):
        checker.main(root)


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        ("    uses: ./.github/workflows/reusable.yml\n", 0),
        # Review byb2-r2: a job-level reusable workflow call has no runs-on and escaped the check.
        ("    uses: ./.github/workflows/missing.yml\n", 1),
        ("    uses: gptcompany/.github/.github/workflows/_reusable-ai-review.yml@main\n", 1),
        ("    uses: ./other/reusable.yml\n", 1),
        (f"    uses: ./.github/workflows/reusable.yml\n    runs-on: {PUBLIC}\n", 1),
        ("    name: empty\n", 1),
        (f"    runs-on: {PUBLIC}\n    run-on: self-hosted\n", 1),
    ],
)
def test_reusable_workflows_must_be_local(tmp_path, job, expected):
    root = make_repo(tmp_path, PUBLIC, json.dumps({"visibility": "public"}))
    workflows = root / ".github/workflows"
    (workflows / "reusable.yml").write_text(
        f"on: workflow_call\njobs:\n  inner:\n    runs-on: {PUBLIC}\n    steps:\n      - run: true\n"
    )
    (workflows / "caller.yml").write_text(f"jobs:\n  call:\n{job}")
    assert checker.main(root) == expected


def test_local_reusable_workflow_is_analyzed(tmp_path):
    root = make_repo(tmp_path, PUBLIC, json.dumps({"visibility": "public"}))
    workflows = root / ".github/workflows"
    (workflows / "reusable.yml").write_text("on: workflow_call\njobs:\n  inner:\n    runs-on: [self-hosted]\n")
    (workflows / "caller.yml").write_text("jobs:\n  call:\n    uses: ./.github/workflows/reusable.yml\n")
    assert checker.main(root) == 1
