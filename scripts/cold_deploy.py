"""Versioned cold deployment contract; rendering has no host side effects."""
from datetime import date
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["image", "image_source_sha", "user", "uid", "gid", "cold_root"],
    "properties": {
        "image": {"type": "string", "pattern": "^ghcr[.]io/gptcompany/bybit-downloader@sha256:[0-9a-f]{64}$"},
        "image_source_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "user": {"type": "string", "pattern": "^[a-z_][a-z0-9_-]*$"},
        "uid": {"type": "integer", "minimum": 0}, "gid": {"type": "integer", "minimum": 0},
        "cold_root": {"type": "string", "pattern": "^/[A-Za-z0-9_./-]+$"},
    },
}


def inventory(config):
    """Reject unknown fields, mobile versions and ambiguous unit substitutions."""
    Draft202012Validator(SCHEMA).validate(config)
    for key in ("image", "image_source_sha", "user", "cold_root"):
        if any(character.isspace() for character in config[key]):
            raise ValueError(f"Whitespace forbidden in {key}")
    path = config["cold_root"]
    if str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts:
        raise ValueError("Cold path must be normalized and absolute")
    return config


def render_units(config, release):
    """Render exactly one downloader timer and an independent daily drift check."""
    config = inventory(config)
    release = str(release)
    if (not Path(release).is_absolute() or any(c not in "/._-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in release)
            or ".." in Path(release).parts):
        raise ValueError("Require a safe absolute release directory")
    units = {}
    for name, action, hour in (("bybit-cold", "run", "03:15"), ("bybit-cold-drift", "drift", "02:45")):
        dependencies = (f"RequiresMountsFor={config['cold_root']}\nAfter=docker.service network-online.target\n"
                        "Requires=docker.service\nWants=network-online.target\n") if action == "run" else ""
        units[name + ".service"] = (
            f"[Unit]\nDescription=Bybit cold {action}\n{dependencies}\n[Service]\nType=oneshot\n"
            f"User={config['user']}\nEnvironment=TZ=UTC\n"
            f"ExecStart={release}/.venv/bin/python {release}/scripts/cold_deploy.py {action} {release}\n"
            "TimeoutStartSec=infinity\nStandardOutput=journal\nStandardError=journal\n")
        units[name + ".timer"] = (
            f"[Unit]\nDescription=Bybit cold {action} UTC\n\n[Timer]\nOnCalendar=*-*-* {hour}:00 UTC\n"
            f"Persistent=true\nUnit={name}.service\n\n[Install]\nWantedBy=timers.target\n")
    return units


def docker_command(config, start: date, end: date, dry_run=False):
    """Run the cold module explicitly, bypassing the image's legacy live command."""
    config = inventory(config)
    return ["/usr/bin/docker", "run", "--rm", "--pull=never", "--env", "TZ=UTC",
            "--env", "PYTHONPATH=/app/src", "--user", f"{int(config['uid'])}:{int(config['gid'])}",
            "--mount", f"type=bind,src={config['cold_root']},dst=/data", "--entrypoint", "python",
            config["image"], "-m", "bybit_data_downloader.backfill", "--start-date", start.isoformat(),
            "--end-date", end.isoformat(), "--data-root", "/data"] + (["--dry-run"] if dry_run else [])
