"""F-649: merging cold downloader code must not dispatch a GitOps deployment."""
from pathlib import Path


def test_legacy_progressive_deploy_trigger_is_retired():
    workflows = Path(__file__).parents[1] / ".github/workflows"
    assert not (workflows / "trigger-progressive-deploy.yml").exists()
    assert (workflows / "ci.yml").is_file()
