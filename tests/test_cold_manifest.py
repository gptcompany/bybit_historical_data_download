"""The deployed inventory must exist in version control and render the cold mount."""
from datetime import date
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from scripts.cold_deploy import docker_command, inventory, render_units

ROOT = Path(__file__).resolve().parents[1]


def test_real_inventory_pins_the_dell_cold_contract():
    config = inventory(json.loads((ROOT / 'deploy/cold.json').read_bytes()))
    assert (config['user'], config['uid'], config['gid']) == ('sam', 1000, 1000)
    assert config['dns'] == ['1.1.1.1', '9.9.9.9']
    assert config['cold_root'] == '/data/cold/12TB/bybit_data_downloader/data'
    units = render_units(config, '/opt/bybit-cold/' + '1' * 40)
    assert 'OnCalendar=*-*-* 03:15:00 UTC' in units['bybit-cold.timer']
    assert 'OnCalendar=*-*-* 02:45:00 UTC' in units['bybit-cold-drift.timer']
    command = docker_command(config, date(2026, 6, 29), date(2026, 11, 9), dry_run=True)
    assert command[4:8] == ['--dns', '1.1.1.1', '--dns', '9.9.9.9']
    assert command.count('--dns') == 2
    assert config['image'] in command and '--pull=never' in command
    assert 'type=bind,src=' + config['cold_root'] + ',dst=/data' in command
    assert '--dry-run' in command and 'TZ=UTC' in command


def test_inventory_requires_explicit_dns():
    config = json.loads((ROOT / 'deploy/cold.json').read_bytes())
    config.pop('dns', None)
    with pytest.raises(ValidationError, match="'dns' is a required property"):
        inventory(config)


@pytest.mark.parametrize('dns', [None, '1.1.1.1', [], ['1.1.1.1'],
    ['1.1.1.1', '1.1.1.1'], [True, '9.9.9.9'], [1, '9.9.9.9'],
    ['256.1.1.1', '9.9.9.9'], ['01.1.1.1', '9.9.9.9'],
    ['::1', '9.9.9.9'], ['resolver.example', '9.9.9.9'],
    ['1.1.1.1\n', '9.9.9.9']])
def test_inventory_rejects_invalid_dns(dns):
    config = json.loads((ROOT / 'deploy/cold.json').read_bytes())
    with pytest.raises(ValidationError):
        inventory(dict(config, dns=dns))


@pytest.mark.parametrize('dry_run', [False, True])
def test_docker_uses_each_inventory_resolver_before_the_image(dry_run):
    config = json.loads((ROOT / 'deploy/cold.json').read_bytes())
    config['dns'] = ['9.9.9.9', '1.1.1.1', '8.8.8.8']
    command = docker_command(config, date(2026, 11, 9), date(2026, 11, 9), dry_run=dry_run)
    assert command[4:10] == ['--dns', '9.9.9.9', '--dns', '1.1.1.1', '--dns', '8.8.8.8']
    assert command.count('--dns') == 3
    assert command.index(config['image']) > 9
