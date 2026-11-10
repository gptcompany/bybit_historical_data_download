"""Versioned cold deployment contract; rendering has no host side effects."""
import argparse
from contextlib import contextmanager
from io import BytesIO
from configparser import ConfigParser, Error as ConfigError
from datetime import date, datetime, timezone
import json
import os
import runpy
import sys
import zipfile
import subprocess
import tempfile
from uuid import uuid4
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, ValidationError


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
    source = Path(release).name + ':scripts/cold_deploy.py'
    bootstrap = f"import subprocess;exec(subprocess.check_output(['git','-C','{release}','show','{source}']))"
    units = {}
    for name, action, hour in (("bybit-cold", "run", "03:15"), ("bybit-cold-drift", "drift", "02:45")):
        dependencies = (f"RequiresMountsFor={config['cold_root']}\nAfter=docker.service network-online.target\n"
                        "Requires=docker.service\nWants=network-online.target\n") if action == "run" else ""
        units[name + ".service"] = (
            f"[Unit]\nDescription=Bybit cold {action}\n{dependencies}\n[Service]\nType=oneshot\n"
            f"User={config['user']}\nEnvironment=TZ=UTC\n"
            f'ExecStart={release}/.venv/bin/python -I -c "{bootstrap}" {action} {release}\n'
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


LEGACY = [name + suffix for name in ('bybit-sync', 'bybit-sync-docker')
          for suffix in ('.service', '.timer')]


@contextmanager
def approved_snapshot(release, approved_sha=None):
    """Execute deployment code and inventory only from the approved Git object tree."""
    release = Path(release).resolve()
    def git(*args):
        return subprocess.run(['git', '-C', str(release), *args], check=True,
                              capture_output=True).stdout
    sha = git('rev-parse', 'HEAD').decode().strip()
    if release.name != sha or (approved_sha is not None and approved_sha != sha):
        raise ValueError('Release does not match approved SHA')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked release files are dirty')
    with tempfile.TemporaryDirectory(prefix='bybit-approved-') as directory:
        snapshot = Path(directory)  # TemporaryDirectory creates mode 0700.
        with zipfile.ZipFile(BytesIO(git('archive', '--format=zip', sha))) as archive:
            archive.extractall(snapshot)
        old_path = sys.path[:]
        try:
            sys.path[:0] = [str(snapshot), str(snapshot / 'scripts')]
            approved = runpy.run_path(str(snapshot / 'scripts/cold_deploy.py'))
            config = approved['inventory'](json.loads((snapshot / 'deploy/cold.json').read_bytes()))
            yield approved, config
        finally:
            sys.path[:] = old_path


def load_release(release, approved_sha=None):
    with approved_snapshot(release, approved_sha) as (_, config):
        return config


def install(release, approved_sha, unit_dir):
    """Write units and legacy masks; never reload, enable, start or stop services."""
    with approved_snapshot(release, approved_sha) as (approved, config):
        return approved['_install'](config, release, unit_dir)


def _install(config, release, unit_dir):
    unit_dir = Path(unit_dir)
    for name, text in render_units(config, Path(release).resolve()).items():
        with tempfile.NamedTemporaryFile(mode='w', dir=unit_dir, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(text); stream.flush(); os.fsync(stream.fileno())
                temporary.chmod(0o644)
                temporary.replace(unit_dir / name)
            finally: temporary.unlink(missing_ok=True)
    for name in LEGACY:
        temporary = unit_dir / ('.' + name + '.' + uuid4().hex)
        try:
            temporary.symlink_to('/dev/null')
            temporary.replace(unit_dir / name)
        finally: temporary.unlink(missing_ok=True)
    return dict(outcome='success', installed=4, masked=len(LEGACY))


def manager_matches(name, expected):
    """Check only manager metadata, never environment or credential-bearing unit text."""
    output = subprocess.run(['systemctl', 'show', name, '--property=' + ','.join(expected)],
                            check=True, capture_output=True, text=True).stdout
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string('[Unit]\n' + output)
    return dict(parser['Unit']) == expected  # Closed property schema, all values exact.


def drift(release, unit_dir):
    with approved_snapshot(release) as (approved, config):
        return approved['_drift'](config, release, unit_dir)


def _drift(config, release, unit_dir):
    release, unit_dir = Path(release).resolve(), Path(unit_dir)
    mismatches = []
    for name, text in render_units(config, release).items():
        target = unit_dir / name
        try:
            equal = not target.is_symlink() and target.read_bytes() == text.encode()
        except OSError:
            equal = False
        if not equal or not manager_matches(name, dict(FragmentPath=str(target), DropInPaths='', NeedDaemonReload='no')):
            mismatches.append(name)
    for name in LEGACY:
        target = unit_dir / name
        if (not target.is_symlink() or target.readlink() != Path('/dev/null')
                or not manager_matches(name, dict(ActiveState='inactive', UnitFileState='masked'))):
            mismatches.append(name)
    return dict(outcome='failure' if mismatches else 'success', finding='F-649',
                timezone='UTC', checked_at=datetime.now(timezone.utc).isoformat(), mismatches=mismatches)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'drift'])
    parser.add_argument('release', type=Path)
    parser.add_argument('--approved-sha')
    args = parser.parse_args(argv)
    try:
        if args.action == 'install':
            if not args.approved_sha: raise ValueError('Installation requires approved SHA')
            result = install(args.release, args.approved_sha, Path('/etc/systemd/system'))
        else: result = drift(args.release, Path('/etc/systemd/system'))
    except (OSError, ValueError, ValidationError, ConfigError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        result = dict(outcome='failure', finding='F-649', error=type(error).__name__)
    print(json.dumps(result), flush=True)
    return int(result['outcome'] != 'success')


if __name__ == '__main__':
    raise SystemExit(main())
