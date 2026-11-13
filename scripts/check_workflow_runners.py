#!/usr/bin/env python3
"""Check workflow runner selectors against the repository visibility declared in .github/runner-policy.json."""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = ROOT / ".github/runner-policy.json"
# Operator rule 2026-11-13: GitHub-hosted minutes are never counted on, so public repositories run on the self-hosted
# pool too (this replaces F-491, which kept them on hosted runners while the runner group excluded them). Fork pull
# requests stay on ubuntu-latest: untrusted fork code never reaches a self-hosted runner.
FORK_PR = (
    "(github.event_name == 'pull_request' || github.event_name == 'pull_request_review')"
    " && github.event.pull_request.head.repo.full_name != github.repository && 'ubuntu-latest'"
)
EXPECTED = {"public": "${{ " + FORK_PR + " || vars.CI_RUNS_ON || 'sg-ci' }}", "private": "${{ vars.CI_RUNS_ON }}"}
# Job-level keys from the GitHub Actions workflow syntax; anything else fails closed.
JOB_KEYS = {
    "name",
    "permissions",
    "needs",
    "if",
    "runs-on",
    "snapshot",
    "environment",
    "concurrency",
    "outputs",
    "env",
    "defaults",
    "steps",
    "timeout-minutes",
    "strategy",
    "continue-on-error",
    "container",
    "services",
    "uses",
    "with",
    "secrets",
}
LOCAL_PREFIX = "./.github/workflows/"


def visibility(path=POLICY_FILE):
    """Declared, not read at runtime: the check must give the same answer offline and in CI."""
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"visibility"} or data["visibility"] not in EXPECTED:
        raise ValueError(f'{path.name} must be exactly {{"visibility": "public" | "private"}}')
    return data["visibility"]


def check_job(job, repo_visibility, local_workflows):
    """A reusable workflow is admitted only as a local file that this check also analyzes (F-492: an external one,
    gptcompany/.github included, can route a public repository job to a self-hosted runner)."""
    if not isinstance(job, dict):
        raise ValueError("job must be a mapping")
    unknown = set(job) - JOB_KEYS
    if unknown:
        raise ValueError(f"unknown job keys: {sorted(unknown)}")
    if "uses" in job:
        uses = job["uses"]
        if "runs-on" in job:
            raise ValueError("a reusable workflow call cannot have runs-on")
        if (
            not isinstance(uses, str)
            or not uses.startswith(LOCAL_PREFIX)
            or uses[len(LOCAL_PREFIX) :] not in local_workflows
        ):
            raise ValueError(f"reusable workflow must be a local analyzed file {LOCAL_PREFIX}<file>, found {uses!r}")
        return
    if "runs-on" not in job:
        raise ValueError("job must have runs-on or a local reusable workflow")
    expected = EXPECTED[repo_visibility]
    if job["runs-on"] != expected:
        raise ValueError(f"{repo_visibility} repository requires runs-on: {expected}, found {job['runs-on']!r}")


def main(root=ROOT):
    repo_visibility = visibility(root / ".github/runner-policy.json")
    paths = sorted((root / ".github/workflows").glob("*.y*ml"))
    if not paths:
        raise ValueError("no workflows found")
    local_workflows = {path.name for path in paths}
    failed = False
    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
            raise ValueError(f"invalid workflow: {path.name}")
        for name, job in workflow["jobs"].items():
            try:
                check_job(job, repo_visibility, local_workflows)
                print(f"{path.name}:{name} ok ({repo_visibility})")
            except ValueError as error:
                print(f"{path.name}:{name} ERROR: {error}")
                failed = True
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
