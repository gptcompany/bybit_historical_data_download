import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/check_workflow_runners.py"
spec = importlib.util.spec_from_file_location("check_workflow_runners", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

GENERIC = "${{ vars.CI_RUNS_ON }}"


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
        ("ubuntu-latest", "public", 0),
        # F-491: a public repository job on a self-hosted selector stays queued forever.
        (GENERIC, "public", 1),
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
