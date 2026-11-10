"""Installer and drift operate on disposable Git releases and fake unit directories."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.cold_deploy import drift, install, load_release, render_units

INVENTORY = dict(image='ghcr.io/gptcompany/bybit-downloader@sha256:' + 'b' * 64,
                 image_source_sha='c' * 40, user='sam', uid=1000, gid=1000,
                 cold_root='/data/cold/12TB/bybit_data_downloader/data')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def systemd_metadata(tmp_path, monkeypatch):
    overrides = {}
    original = subprocess.run

    def offline(args, **kwargs):
        if args[0] == 'systemctl':
            assert args[1] == 'show'  # Never enable/start/reload from these fixtures.
            name = args[2]
            values = dict(FragmentPath=str(tmp_path / 'units' / name),
                          DropInPaths='', NeedDaemonReload='no')
            values.update(overrides.get(name, {}))
            return subprocess.CompletedProcess(args, 0,
                ''.join(f'{key}={value}\n' for key, value in values.items()), '')
        assert args[0] == 'git'
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', offline)
    return overrides


@pytest.fixture
def release(tmp_path, systemd_metadata):
    source = tmp_path / 'source'
    (source / 'deploy').mkdir(parents=True)
    (source / 'deploy/cold.json').write_text(json.dumps(INVENTORY))
    git(source, 'init')
    git(source, 'add', '.')
    git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-m', 'Fixture inventory')
    sha = git(source, 'rev-parse', 'HEAD')
    target = tmp_path / sha
    source.rename(target)
    return target


def test_install_is_exact_and_retires_both_legacy_schedulers(release, tmp_path):
    units = tmp_path / 'units'
    units.mkdir()
    install(release, release.name, units)
    assert load_release(release) == INVENTORY
    for name, text in render_units(INVENTORY, release).items():
        assert (units / name).read_bytes() == text.encode()
    for name in ('bybit-sync', 'bybit-sync-docker'):
        for suffix in ('.service', '.timer'):
            assert (units / (name + suffix)).is_symlink()
            assert (units / (name + suffix)).readlink() == Path('/dev/null')
    assert drift(release, units)['outcome'] == 'success'
    install(release, release.name, units)
    assert drift(release, units)['mismatches'] == []


@pytest.mark.parametrize('name', ['bybit-cold.service', 'bybit-cold.timer',
    'bybit-cold-drift.service', 'bybit-cold-drift.timer', 'bybit-sync.service',
    'bybit-sync.timer', 'bybit-sync-docker.service', 'bybit-sync-docker.timer'])
def test_drift_reports_every_modified_or_missing_managed_unit(release, tmp_path, name):
    units = tmp_path / 'units'
    units.mkdir()
    install(release, release.name, units)
    (units / name).unlink()
    if name.startswith('bybit-cold'):
        (units / name).write_text('altered')
    result = drift(release, units)
    assert result['outcome'] == 'failure'
    assert result['finding'] == 'F-649'
    assert result['mismatches'] == [name]


def test_unapproved_or_dirty_release_cannot_install_or_certify_drift(release, tmp_path):
    units = tmp_path / 'units'
    units.mkdir()
    with pytest.raises(ValueError):
        install(release, '0' * 40, units)
    assert not list(units.iterdir())
    (release / 'deploy/cold.json').write_text(json.dumps(dict(INVENTORY, uid=1001)))
    with pytest.raises(ValueError):
        install(release, release.name, units)
    with pytest.raises(ValueError):
        drift(release, units)
    assert not list(units.iterdir())


def test_owner_no_longer_versions_legacy_scheduler():
    root = Path(__file__).parents[1]
    assert not (root / 'deploy/systemd/bybit-sync-docker.service').exists()
    assert not (root / 'deploy/systemd/bybit-sync-docker.timer').exists()


@pytest.mark.parametrize('change', [dict(FragmentPath='/usr/lib/systemd/system/other.service'),
    dict(DropInPaths='/etc/systemd/system/bybit-cold.service.d/override.conf'),
    dict(NeedDaemonReload='yes')])
def test_drift_checks_loaded_fragment_dropins_and_reload(release, tmp_path, systemd_metadata, change):
    units = tmp_path / 'units'
    units.mkdir()
    install(release, release.name, units)
    systemd_metadata['bybit-cold.service'] = change
    result = drift(release, units)
    assert result['outcome'] == 'failure'
    assert result['mismatches'] == ['bybit-cold.service']
