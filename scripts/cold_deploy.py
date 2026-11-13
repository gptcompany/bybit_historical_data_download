"""Versioned cold deployment contract; rendering has no host side effects."""
import argparse
from contextlib import contextmanager
from io import BytesIO
from configparser import ConfigParser, Error as ConfigError
from datetime import date, datetime, timedelta, timezone
import json
import os
import re
import runpy
import sys
import zipfile
import subprocess
import tempfile
from uuid import uuid4
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["image", "image_source_sha", "user", "uid", "gid", "cold_root", "dns"],
    "properties": {
        "dns": {"type": "array", "minItems": 2, "uniqueItems": True,
                "items": {"type": "string", "format": "ipv4"}},
        "image": {"type": "string", "pattern": "^ghcr[.]io/gptcompany/bybit-downloader@sha256:[0-9a-f]{64}$"},
        "image_source_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "user": {"type": "string", "pattern": "^[a-z_][a-z0-9_-]*$"},
        "uid": {"type": "integer", "minimum": 0}, "gid": {"type": "integer", "minimum": 0},
        "cold_root": {"type": "string", "pattern": "^/[A-Za-z0-9_./-]+$"},
    },
}


def inventory(config):
    """Reject unknown fields, mobile versions and ambiguous unit substitutions."""
    Draft202012Validator(SCHEMA, format_checker=FormatChecker(formats=["ipv4"])).validate(config)
    for key in ("image", "image_source_sha", "user", "cold_root"):
        if any(character.isspace() for character in config[key]):
            raise ValueError(f"Whitespace forbidden in {key}")
    path = config["cold_root"]
    if str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts:
        raise ValueError("Cold path must be normalized and absolute")
    return config


def approved_git_command(release, *args):
    """Read the approved object identity without repository-local replacement refs."""
    return ['git', '--no-replace-objects', '-C', str(release), *args]


BACKFILL = "bybit-cold-backfill@.service"


def render_units(config, release):
    """Render one downloader timer, an independent drift check and the manual backfill template."""
    config = inventory(config)
    release = str(release)
    if (not Path(release).is_absolute() or any(c not in "/._-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in release)
            or ".." in Path(release).parts):
        raise ValueError("Require a safe absolute release directory")
    source = Path(release).name + ':scripts/cold_deploy.py'
    command = approved_git_command(release, 'show', source)
    bootstrap = f"import subprocess;exec(subprocess.check_output({command!r}))"
    python = f'{release}/.venv/bin/python -I -c "{bootstrap}"'
    docker = (f"RequiresMountsFor={config['cold_root']}\nAfter=docker.service network-online.target\n"
              "Requires=docker.service\nWants=network-online.target\n")
    units = {}
    for name, action, hour in (("bybit-cold", "run", "03:15"), ("bybit-cold-drift", "drift", "02:45")):
        container = action == "run"
        units[name + ".service"] = (
            f"[Unit]\nDescription=Bybit cold {action}\n{docker if container else ''}\n[Service]\nType=oneshot\n"
            f"User={config['user']}\nEnvironment=TZ=UTC\n"
            f'ExecStart={python} {action} {release}\n'
            + (f"ExecStopPost={python} reap {release}\n" if container else "") +
            "TimeoutStartSec=infinity\nStandardOutput=journal\nStandardError=journal\n")
        units[name + ".timer"] = (
            f"[Unit]\nDescription=Bybit cold {action} UTC\n\n[Timer]\nOnCalendar=*-*-* {hour}:00 UTC\n"
            f"Persistent=true\nUnit={name}.service\n\n[Install]\nWantedBy=timers.target\n")
    # The instance carries the backfill arguments (systemd-escape); "$VAR" splits them at whitespace.
    units[BACKFILL] = (
        f"[Unit]\nDescription=Bybit cold backfill %I\n{docker}\n[Service]\nType=oneshot\n"
        f'User={config["user"]}\nEnvironment=TZ=UTC "BYBIT_BACKFILL_ARGS=%I"\n'
        f"ExecStart={python} backfill {release} $BYBIT_BACKFILL_ARGS\n"
        f"ExecStopPost={python} reap {release}\n"
        "TimeoutStartSec=infinity\nStandardOutput=journal\nStandardError=journal\n")
    return units


def docker_command(config, start: date | None, end: date, dry_run=False, symbols=None, types=None, intervals=None,
                   name=None):
    """Run the cold module explicitly, bypassing the image's legacy live command; no start resumes."""
    config = inventory(config)
    command = ["/usr/bin/docker", "run", "--rm", "--pull=never"]
    if name is not None:
        command.extend(["--name", name])
    for address in config["dns"]:
        command.extend(["--dns", address])
    command += ["--env", "TZ=UTC",
            "--env", "PYTHONPATH=/app/src", "--user", f"{int(config['uid'])}:{int(config['gid'])}",
            "--mount", f"type=bind,src={config['cold_root']},dst=/data", "--entrypoint", "python",
            config["image"], "-m", "bybit_data_downloader.backfill",
            *(["--from-last-complete"] if start is None else ["--start-date", start.isoformat()]),
            "--end-date", end.isoformat(), "--data-root", "/data"]
    for flag, value in (("--symbols", symbols), ("--types", types), ("--intervals", intervals)):
        if value is not None: command.extend([flag, value])
    return command + (["--dry-run"] if dry_run else [])


LEGACY = [name + suffix for name in ('bybit-sync', 'bybit-sync-docker')
          for suffix in ('.service', '.timer')]


@contextmanager
def approved_snapshot(release, approved_sha=None):
    """Execute deployment code and inventory only from the approved Git object tree."""
    release = Path(release).resolve()
    def git(*args):
        return subprocess.run(approved_git_command(release, *args), check=True,
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
    return dict(outcome='success', installed=len(render_units(config, Path(release).resolve())), masked=len(LEGACY))


def manager_matches(name, expected):
    """Check only manager metadata, never environment or credential-bearing unit text."""
    output = subprocess.run(['systemctl', 'show', name, '--property=' + ','.join(expected)],
                            check=True, capture_output=True, text=True).stdout
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string('[Unit]\n' + output)
    return dict(parser['Unit']) == expected  # Closed property schema, all values exact.


def loaded_instances(fragment):
    """Every loaded backfill instance: its own drop-ins never reach the synthetic @drift probe."""
    expected = dict(FragmentPath=str(fragment), DropInPaths='', NeedDaemonReload='no')
    output = subprocess.run(['systemctl', 'show', BACKFILL.replace('@.', '@*.'),
                             '--property=Id,InvocationID,' + ','.join(expected)],
                            check=True, capture_output=True, text=True).stdout
    instances = []
    for block in output.split('\n\n'):  # systemctl separates units by a blank line.
        if block.strip():
            parser = ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read_string('[Unit]\n' + block)
            unit = dict(parser['Unit'])
            instances.append(dict(unit=unit.get('Id'), invocation=unit.get('InvocationID'),
                                  matches={key: unit.get(key) for key in expected} == expected))
    return instances


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
        # systemctl show rejects template names; an instance reports the template's metadata.
        probe = name.replace('@.', '@drift.')
        if not equal or not manager_matches(probe, dict(FragmentPath=str(target), DropInPaths='', NeedDaemonReload='no')):
            mismatches.append(name)
    instances = loaded_instances(unit_dir / BACKFILL)
    mismatches += [instance['unit'] for instance in instances if not instance['matches']]
    # An instance-specific unit or drop-in directory overrides the template for that instance alone.
    mismatches += sorted(path.name for path in unit_dir.glob(BACKFILL.replace('@.', '@?*.') + '*'))
    for name in LEGACY:
        target = unit_dir / name
        if (not target.is_symlink() or target.readlink() != Path('/dev/null')
                or not manager_matches(name, dict(ActiveState='inactive', UnitFileState='masked'))):
            mismatches.append(name)
    return dict(outcome='failure' if mismatches else 'success', finding='F-649',
                timezone='UTC', checked_at=datetime.now(timezone.utc).isoformat(), mismatches=mismatches,
                instances=[dict(unit=i['unit'], invocation=i['invocation']) for i in instances])


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
    discarded_orderbook_tail: Count = 0
    retries: Count = 0
    events_not_written: Count = 0
    error: str | None = None
    error_message: str | None = None
    error_type: Literal['trade', 'orderbook', 'klines', 'funding', 'openinterest', 'longshortratio'] | None = None
    error_day: date | None = None
    error_symbol: Annotated[str, Field(pattern='^[A-Z0-9]+USDT$')] | None = None
    error_target: str | None = None
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
    outcome: Literal['success', 'failure'] = 'success'
    log_error: str | None = None
    retries: Count = 0
    events_not_written: Count = 0
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


class RetryEvent(ClosedRecord):
    event: Literal['retry']
    target: Annotated[str, Field(pattern=r'^(historical|market_metrics)/[A-Za-z0-9_./-]+$')]
    attempt: Annotated[int, Field(gt=0)]
    exception: Literal['TimeoutException', 'ConnectTimeout', 'ReadTimeout', 'WriteTimeout', 'PoolTimeout',
                       'ConnectError', 'RemoteProtocolError', 'ReadError', 'HTTPStatusError']
    wait_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]


def emit(payload, state, *, stream=None, log=None, event=False):
    """Best effort per sink; retain the first I/O error without changing work counters."""
    delivered = False
    state.setdefault('events_not_written', 0)
    for sink in ('file', 'stream'):
        if (sink == 'file' and log is None) or (sink == 'stream' and stream is None):
            continue
        try:
            if sink == 'file':
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open('a') as output:
                    output.write(json.dumps(payload) + '\n')
                    output.flush()
                    os.fsync(output.fileno())
            else:
                print(json.dumps(payload), file=stream, flush=True)
            delivered = True
        except OSError as error:  # Includes BrokenPipeError; always attempt the other sink.
            state['log_error'] = state.get('log_error') or type(error).__name__
            if state.get('outcome') == 'success' and 'phase' in state:
                state.update(error=type(error).__name__, error_target=None,
                             error_message=os.strerror(error.errno) if error.errno else 'Log emission failed')
            state['outcome'] = 'failure'
    if event and not delivered:
        state['events_not_written'] += 1


def forward_retries(stderr, config, dry_run):
    state = dict(events_not_written=0)
    for line in stderr.splitlines():
        try:
            event = RetryEvent.model_validate_json(line).model_dump(mode='json')
        except ValueError:
            continue
        emit(event, state, stream=sys.stderr, event=True,
             log=None if dry_run else Path(config['cold_root']) / 'logs/backfill.jsonl')
    return state


def container_name():
    """Name the container after this systemd invocation, which ExecStopPost shares."""
    invocation = os.environ.get('INVOCATION_ID', '')
    if not re.fullmatch('[0-9a-f]{32}', invocation):
        raise ValueError('Run only inside a systemd unit')
    return 'bybit-cold-' + invocation


def reap():
    """ExecStopPost: stop this invocation's container even when the runner was killed."""
    name = container_name()
    listed = subprocess.run(['/usr/bin/docker', 'ps', '--all', '--quiet', '--filter', 'name=' + name],
                            check=True, capture_output=True, text=True).stdout.split()
    if listed:  # Docker's own stop timeout; SIGTERM makes the backfill remove its staging.
        subprocess.run(['/usr/bin/docker', 'stop', name], check=True, capture_output=True)
    return dict(outcome='success', finding='F-649', timezone='UTC', container=name, stopped=len(listed))


def run_backfill(release, start, end, dry_run=False, symbols=None, types=None, intervals=None, resume=False,
                 instance=False):
    """Fail closed on drift and emit one validated, enriched container record."""
    if (end is None or (start is None) != resume or (start is not None and start > end)
            or end >= datetime.now(timezone.utc).date()):
        raise ValueError('Require an ordered range of closed UTC days')
    name = container_name()
    check = drift(release, Path('/etc/systemd/system'))
    if check['outcome'] != 'success':
        return dict(check, finding='F-649', phase='preflight', downloaded=0, skipped=0, records=0)
    # A backfill instance must have been among the checked ones, or its own overrides went unseen.
    if instance and name.removeprefix('bybit-cold-') not in [i['invocation'] for i in check.get('instances', [])]:
        return dict(check, outcome='failure', error='InstanceNotChecked', finding='F-649', phase='preflight',
                    downloaded=0, skipped=0, records=0)
    config = load_release(release)
    metadata = dict(finding='F-649', timezone='UTC', end_date=end.isoformat(),
                    image=config['image'], image_source_sha=config['image_source_sha'])
    if start is not None:  # Resumed runs report the start chosen by the child.
        metadata['start_date'] = start.isoformat()
    unknown = dict(metadata, outcome='failure', phase='container', downloaded=None, skipped=None, records=None)
    try:
        completed = subprocess.run(docker_command(config, start, end, dry_run, symbols, types, intervals, name),
                                   capture_output=True)
    except OSError:
        return dict(unknown, returncode=None, counts_status='not_started', error='ContainerNotStarted')
    metadata['returncode'] = completed.returncode
    unknown['returncode'] = completed.returncode
    if completed.returncode in (125, 126, 127):
        return dict(unknown, counts_status='not_started', error='ContainerNotStarted')
    emission = forward_retries(getattr(completed, 'stderr', b''), config, dry_run)
    log_failure = dict(outcome='failure', log_error=emission['log_error']) if emission.get('log_error') else {}
    try:
        if dry_run:
            try:
                PlanSummary.model_validate_json(completed.stdout)
            except ValueError:
                RunSummary.model_validate_json(completed.stdout)
        else:
            RunSummary.model_validate_json(completed.stdout)
        summary = json.loads(completed.stdout)  # Preserve the validated child's timestamp spelling.
        summary.setdefault('outcome', 'success')
        summary.setdefault('phase', 'planning')
        if (completed.returncode == 0) != (summary['outcome'] == 'success'):
            raise ValueError('Child exit status contradicts summary')
    except ValueError:
        return dict(unknown, counts_status='unknown', error='InvalidRunSummary', **emission) | log_failure
    summary['events_not_written'] = summary.get('events_not_written', 0) + emission['events_not_written']
    if log_failure and summary.get('log_error'):
        log_failure['log_error'] = summary['log_error']
    return dict(summary, **metadata, counts_status='reported') | log_failure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'drift', 'run', 'backfill', 'reap'])
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
        elif args.action == 'reap': result = reap()
        else:
            start, end = args.start_date, args.end_date
            if args.action == 'run':
                # Resume each series from its verified manifests in the cold, up to yesterday UTC.
                if start is not None or end is not None: raise ValueError('Run always ends yesterday UTC')
                end = datetime.now(timezone.utc).date() - timedelta(days=1)
            result = run_backfill(args.release, start, end, args.dry_run, args.symbols, args.types, args.intervals,
                                  args.action == 'run', args.action == 'backfill')
    except (OSError, ValueError, ValidationError, ConfigError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        result = dict(outcome='failure', finding='F-649', error=type(error).__name__,
                      phase='preflight', timezone='UTC', downloaded=0, skipped=0, records=0)
    emit(result, result, stream=sys.stdout)
    return int(result['outcome'] != 'success')


if __name__ == '__main__':
    raise SystemExit(main())
