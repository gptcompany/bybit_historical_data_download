"""Versioned cold deployment contract; rendering has no host side effects."""
import argparse
from configparser import ConfigParser, Error as ConfigError
from datetime import date, datetime, timedelta, timezone
import json
import os
import subprocess
import tempfile
from uuid import uuid4
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

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


def docker_command(config, start: date, end: date, dry_run=False, symbols=None, types=None, intervals=None):
    """Run the cold module explicitly, bypassing the image's legacy live command."""
    config = inventory(config)
    command = ["/usr/bin/docker", "run", "--rm", "--pull=never", "--env", "TZ=UTC",
            "--env", "PYTHONPATH=/app/src", "--user", f"{int(config['uid'])}:{int(config['gid'])}",
            "--mount", f"type=bind,src={config['cold_root']},dst=/data", "--entrypoint", "python",
            config["image"], "-m", "bybit_data_downloader.backfill", "--start-date", start.isoformat(),
            "--end-date", end.isoformat(), "--data-root", "/data"]
    for flag, value in (("--symbols", symbols), ("--types", types), ("--intervals", intervals)):
        if value is not None: command.extend([flag, value])
    return command + (["--dry-run"] if dry_run else [])


LEGACY = [name + suffix for name in ('bybit-sync', 'bybit-sync-docker')
          for suffix in ('.service', '.timer')]


def load_release(release, approved_sha=None):
    """The SHA-named, tracked-clean release is the only inventory authority."""
    release = Path(release).resolve()
    def git(*args):
        return subprocess.run(['git', '-C', str(release), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    sha = git('rev-parse', 'HEAD')
    if release.name != sha or (approved_sha is not None and approved_sha != sha):
        raise ValueError('Release does not match approved SHA')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked release files are dirty')
    approved = subprocess.run(['git', '-C', str(release), 'show', sha + ':deploy/cold.json'],
                              check=True, capture_output=True).stdout
    manifest = (release / 'deploy/cold.json').read_bytes()
    if manifest != approved:
        raise ValueError('Inventory bytes differ from approved commit')
    return inventory(json.loads(manifest))


def install(release, approved_sha, unit_dir):
    """Write units and legacy masks; never reload, enable, start or stop services."""
    config = load_release(release, approved_sha)
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
    config = load_release(release)
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


Count = Annotated[int, Field(ge=0)]


class ClosedRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Quarantine(ClosedRecord):
    path: str
    reason: str
    error: str


class RunSummary(ClosedRecord):
    outcome: Literal['success', 'failure']
    downloaded: Count
    skipped: Count
    records: Count
    files: Count
    quarantined: list[Quarantine]
    timezone: Literal['UTC']
    started_at: AwareDatetime
    finished_at: AwareDatetime
    days: list[date]
    phase: Literal['planning', 'execution']
    error: str | None = None
    log_error: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode='after')
    def utc_and_order(self):
        if (self.started_at.utcoffset() != timedelta(0) or self.finished_at.utcoffset() != timedelta(0)
                or self.finished_at < self.started_at):
            raise ValueError('Require ordered UTC timestamps')
        if self.downloaded + self.skipped > self.files:
            raise ValueError('Completed files exceed plan')
        return self


class PlanJob(ClosedRecord):
    day: date
    symbol: Annotated[str, Field(pattern='^[A-Z0-9]+USDT$')]
    type: Literal['trade', 'orderbook', 'klines', 'funding', 'openinterest', 'longshortratio']
    interval: Literal['1m', '5m', '15m'] | None
    timezone: Literal['UTC']
    expected_bytes: Annotated[int, Field(gt=0)] | None
    source: Literal['archive', 'api']
    url: str
    path: str


class PlanSummary(ClosedRecord):
    days: Annotated[int, Field(gt=0)]
    files: Count
    archive_bytes: Count
    api_files_unknown_bytes: Count
    data_root: str
    jobs: list[PlanJob]

    @model_validator(mode='after')
    def counts(self):
        if (self.files != len(self.jobs) or self.archive_bytes != sum(job.expected_bytes or 0 for job in self.jobs)
                or self.api_files_unknown_bytes != sum(job.source == 'api' for job in self.jobs)):
            raise ValueError('Plan counts differ from jobs')
        return self


def run_backfill(release, start, end, dry_run=False, symbols=None, types=None, intervals=None):
    """Fail closed on drift and emit one validated, enriched container record."""
    if start is None or end is None or start > end or end >= datetime.now(timezone.utc).date():
        raise ValueError('Require an ordered range of closed UTC days')
    check = drift(release, Path('/etc/systemd/system'))
    if check['outcome'] != 'success':
        return dict(check, finding='F-649', phase='preflight', downloaded=0, skipped=0, records=0)
    config = load_release(release)
    metadata = dict(finding='F-649', timezone='UTC', start_date=start.isoformat(), end_date=end.isoformat(),
                    image=config['image'], image_source_sha=config['image_source_sha'])
    completed = subprocess.run(docker_command(config, start, end, dry_run, symbols, types, intervals),
                               capture_output=True, text=True)
    metadata['returncode'] = completed.returncode
    unknown = dict(metadata, outcome='failure', phase='container', downloaded=None, skipped=None, records=None)
    if completed.returncode in (125, 126, 127):
        return dict(unknown, counts_status='not_started', error='ContainerNotStarted')
    try:
        if dry_run and completed.returncode == 0:
            plan = PlanSummary.model_validate_json(completed.stdout).model_dump(mode='json')
            return dict(plan, **metadata, outcome='success', phase='planning')
        RunSummary.model_validate_json(completed.stdout)
        summary = json.loads(completed.stdout)  # Preserve the validated child's timestamp spelling.
        if (completed.returncode == 0) != (summary['outcome'] == 'success'):
            raise ValueError('Child exit status contradicts summary')
    except ValueError:
        return dict(unknown, counts_status='unknown', error='InvalidRunSummary')
    return dict(summary, **metadata, counts_status='reported')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'drift', 'run', 'backfill'])
    parser.add_argument('release', type=Path)
    parser.add_argument('--approved-sha')
    parser.add_argument('--start-date', type=date.fromisoformat)
    parser.add_argument('--end-date', type=date.fromisoformat)
    parser.add_argument('--symbols')
    parser.add_argument('--types')
    parser.add_argument('--intervals')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'install':
            if not args.approved_sha: raise ValueError('Installation requires approved SHA')
            result = install(args.release, args.approved_sha, Path('/etc/systemd/system'))
        elif args.action == 'drift': result = drift(args.release, Path('/etc/systemd/system'))
        else:
            start, end = args.start_date, args.end_date
            if args.action == 'run':
                if start is not None or end is not None: raise ValueError('Run always selects yesterday UTC')
                start = end = datetime.now(timezone.utc).date() - timedelta(days=1)
            result = run_backfill(args.release, start, end, args.dry_run, args.symbols, args.types, args.intervals)
    except (OSError, ValueError, ValidationError, ConfigError, subprocess.CalledProcessError) as error:
        result = dict(outcome='failure', finding='F-649', error=type(error).__name__,
                      phase='preflight', timezone='UTC', downloaded=0, skipped=0, records=0)
    print(json.dumps(result), flush=True)
    return int(result['outcome'] != 'success')


if __name__ == '__main__':
    raise SystemExit(main())
