"""Offline deployment contract: rendering never downloads or changes host units."""
from configparser import ConfigParser
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from jsonschema import ValidationError

from scripts.cold_deploy import docker_command, render_units

RELEASE = Path('/opt/bybit-cold/' + 'a' * 40)
INVENTORY = dict(image='ghcr.io/gptcompany/bybit-downloader@sha256:' + 'b' * 64,
                 image_source_sha='c' * 40, user='sam', uid=1000, gid=1000,
                 cold_root='/data/cold/12TB/bybit_data_downloader/data')


def unit(text):
    parser = ConfigParser(interpolation=None)
    parser.read_string(text)
    return parser


def test_scheduler_render_is_explicit_and_has_no_legacy_authority():
    rendered = render_units(INVENTORY, RELEASE)
    assert set(rendered) == {'bybit-cold.service', 'bybit-cold.timer',
                             'bybit-cold-drift.service', 'bybit-cold-drift.timer'}
    service = unit(rendered['bybit-cold.service'])
    assert service['Unit']['RequiresMountsFor'] == INVENTORY['cold_root']
    assert service['Service']['User'] == 'sam'
    assert service['Service']['Environment'] == 'TZ=UTC'
    assert str(RELEASE) in service['Service']['ExecStart']
    assert ' run ' in service['Service']['ExecStart']
    assert unit(rendered['bybit-cold.timer'])['Timer']['OnCalendar'] == '*-*-* 03:15:00 UTC'
    assert unit(rendered['bybit-cold.timer'])['Timer']['Persistent'] == 'true'
    drift = unit(rendered['bybit-cold-drift.timer'])
    assert drift['Timer']['OnCalendar'] == '*-*-* 02:45:00 UTC'
    assert ' drift ' in unit(rendered['bybit-cold-drift.service'])['Service']['ExecStart']
    assert all('bybit-sync' not in text and 'dotenv' not in text for text in rendered.values())
    assert render_units(INVENTORY, RELEASE) == rendered


@pytest.mark.parametrize('change', [dict(image='ghcr.io/gptcompany/bybit-downloader:latest'),
    dict(image_source_sha='main'), dict(uid=True), dict(uid=-1), dict(user='sam\nExecStart=bad'),
    dict(cold_root='relative'), dict(cold_root='/data/../runtime'), dict(extra='unversioned')])
def test_inventory_rejects_unpinned_or_ambiguous_input(change):
    invalid = dict(deepcopy(INVENTORY), **change)
    with pytest.raises((ValidationError, ValueError)):
        render_units(invalid, RELEASE)


@pytest.mark.parametrize('uid', [1000, 1000.0])
def test_docker_command_binds_only_explicit_cold_and_overrides_live_entrypoint(uid):
    config = dict(INVENTORY, uid=uid, gid=uid)
    command = docker_command(config, date(2026, 6, 29), date(2026, 11, 9))
    assert command[:4] == ['/usr/bin/docker', 'run', '--rm', '--pull=never']
    assert command[command.index('--mount') + 1] == (
        'type=bind,src=/data/cold/12TB/bybit_data_downloader/data,dst=/data')
    assert command[command.index('--entrypoint') + 1] == 'python'
    assert INVENTORY['image'] in command
    assert command[command.index('--user') + 1] == '1000:1000'
    assert 'TZ=UTC' in command and 'PYTHONPATH=/app/src' in command
    assert command[-4:] == ['--end-date', '2026-11-09', '--data-root', '/data']
    assert '--start-date' in command and '2026-06-29' in command
    assert 'bybit_data_downloader.backfill' in command
    assert 'bash' not in command and 'compose' not in command
    assert '--dry-run' not in command
    assert docker_command(INVENTORY, date(2026, 6, 29), date(2026, 11, 9), dry_run=True)[-1] == '--dry-run'
