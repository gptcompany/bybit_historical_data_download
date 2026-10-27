#!/usr/bin/env python3
"""Check workflow runner selectors against the repository visibility declared in .github/runner-policy.json."""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = ROOT / ".github/runner-policy.json"
# F-491: the org runner group holding sg-ci and dell-ci excludes public repositories, so a public repository job on a
# self-hosted selector stays queued forever without an error; public repositories get free hosted minutes instead.
EXPECTED = {"public": "ubuntu-latest", "private": "${{ vars.CI_RUNS_ON }}"}


def visibility(path=POLICY_FILE):
    """Declared, not read at runtime: the check must give the same answer offline and in CI."""
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"visibility"} or data["visibility"] not in EXPECTED:
        raise ValueError(f"{path.name} must be exactly {{\"visibility\": \"public\" | \"private\"}}")
    return data["visibility"]


def check_job(job, repo_visibility):
    if not isinstance(job, dict):
        raise ValueError("job must be a mapping")
    if "runs-on" not in job:
        if "uses" in job:
            return
        raise ValueError("job must have a runs-on selector")
    expected = EXPECTED[repo_visibility]
    if job["runs-on"] != expected:
        raise ValueError(f"{repo_visibility} repository requires runs-on: {expected}, found {job['runs-on']!r}")


def main(root=ROOT):
    repo_visibility = visibility(root / ".github/runner-policy.json")
    paths = sorted((root / ".github/workflows").glob("*.y*ml"))
    if not paths:
        raise ValueError("no workflows found")
    failed = False
    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
            raise ValueError(f"invalid workflow: {path.name}")
        for name, job in workflow["jobs"].items():
            try:
                check_job(job, repo_visibility)
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
