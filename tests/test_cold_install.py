"""Installer and drift operate on disposable Git releases and fake unit directories."""
import json
import runpy
import shlex
import sys
import stat
import zipfile
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
            values = (dict(FragmentPath=str(tmp_path / 'units' / name),
                           DropInPaths='', NeedDaemonReload='no') if name.startswith('bybit-cold')
                      else dict(ActiveState='inactive', UnitFileState='masked'))
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
    (source / 'scripts').mkdir()
    (source / 'scripts/cold_deploy.py').write_bytes((Path(__file__).parents[1] / 'scripts/cold_deploy.py').read_bytes())
    (source / 'other.txt').write_text('approved')
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


@pytest.mark.parametrize('name', ['bybit-sync.timer', 'bybit-sync-docker.service'])
def test_drift_fails_if_a_masked_legacy_scheduler_is_still_active(release, tmp_path, systemd_metadata, name):
    units = tmp_path / 'units'
    units.mkdir()
    install(release, release.name, units)
    systemd_metadata[name] = dict(ActiveState='active')
    assert drift(release, units)['mismatches'] == [name]


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
@pytest.mark.parametrize('action', ['install', 'drift'])
def test_hidden_manifest_edit_cannot_install_or_certify(release, tmp_path, flag, action):
    units = tmp_path / 'units'
    units.mkdir()
    install(release, release.name, units)
    expected = {name: (units / name).read_bytes() for name in render_units(INVENTORY, release)}
    git(release, 'update-index', flag, 'deploy/cold.json')
    (release / 'deploy/cold.json').write_text(json.dumps(dict(INVENTORY,
        image='ghcr.io/gptcompany/bybit-downloader@sha256:' + 'd' * 64,
        cold_root='/data/unapproved-cold')))
    assert git(release, 'status', '--porcelain', '--untracked-files=no') == ''
    # The approved snapshot ignores hidden edits; it must still render approved bytes.
    deployed = runpy.run_path(str(release / 'scripts/cold_deploy.py'))
    if action == 'install':
        assert deployed['install'](release, release.name, units)['outcome'] == 'success'
    else:
        assert deployed['drift'](release, units)['outcome'] == 'success'
    assert {name: (units / name).read_bytes() for name in expected} == expected


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
@pytest.mark.parametrize('action', ['install', 'drift'])
@pytest.mark.parametrize('filename', ['scripts/cold_deploy.py', 'other.txt'])
def test_any_hidden_tracked_edit_cannot_influence_deployment(release, tmp_path, flag, action, filename):
    units = tmp_path / 'units'
    units.mkdir()
    install(release, release.name, units)
    expected = {name: (units / name).read_bytes() for name in render_units(INVENTORY, release)}
    git(release, 'update-index', flag, filename)
    target = release / filename
    original = target.read_text()
    target.write_text(original.replace('03:15', '04:15') if filename.endswith('.py') else 'unapproved')
    assert target.read_text() != original
    assert git(release, 'status', '--porcelain', '--untracked-files=no') == ''
    # The approved snapshot ignores hidden edits; it must still render approved bytes.
    deployed = runpy.run_path(str(release / 'scripts/cold_deploy.py'))
    if action == 'install':
        assert deployed['install'](release, release.name, units)['outcome'] == 'success'
    else:
        assert deployed['drift'](release, units)['outcome'] == 'success'
    assert {name: (units / name).read_bytes() for name in expected} == expected


def test_snapshot_is_private_excludes_untracked_files_and_is_removed(release):
    from scripts.cold_deploy import approved_snapshot
    (release / 'untracked.py').write_text('raise RuntimeError("unapproved")')
    with approved_snapshot(release, release.name) as (approved, config):
        snapshot = Path(approved['__file__']).parents[1]
        assert stat.S_IMODE(snapshot.stat().st_mode) == 0o700
        assert not (snapshot / 'untracked.py').exists()
        assert config == INVENTORY
    assert not snapshot.exists()


def test_failed_extraction_is_closed_and_cleans_snapshot(release, tmp_path, monkeypatch):
    seen = []
    def failed(archive, path):
        seen.append(Path(path))
        raise OSError('Fixture extraction failed')
    monkeypatch.setattr(zipfile.ZipFile, 'extractall', failed)
    units = tmp_path / 'units'
    units.mkdir()
    with pytest.raises(OSError): install(release, release.name, units)
    with pytest.raises(OSError): drift(release, units)
    assert not list(units.iterdir())
    assert len(seen) == 2 and all(not path.exists() for path in seen)


@pytest.fixture
def replaced_release(release):
    """Keep the approved checkout, but redirect its commit to different code/config."""
    script = release / 'scripts/cold_deploy.py'
    script.write_text("raise RuntimeError('Replacement script executed')\n")
    (release / 'deploy/cold.json').write_text(json.dumps(dict(INVENTORY, uid=1001)))
    git(release, 'add', '.')
    git(release, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-m', 'Unapproved replacement')
    replacement = git(release, 'rev-parse', 'HEAD')
    git(release, 'checkout', '--detach', release.name)
    git(release, 'replace', release.name, replacement)
    # Counterexample: an ordinary show really returns the substituted script.
    assert 'Replacement script executed' in git(release, 'show', release.name + ':scripts/cold_deploy.py')
    return release


@pytest.mark.parametrize('action', ['install', 'drift'])
def test_replace_ref_cannot_substitute_approved_install_or_drift(replaced_release, tmp_path, action):
    release = replaced_release
    units = tmp_path / 'units'
    units.mkdir()
    expected = render_units(INVENTORY, release)
    # Supply approved units so drift independently checks the original contract.
    for name, text in expected.items():
        (units / name).write_text(text)
    from scripts.cold_deploy import LEGACY
    for name in LEGACY:
        (units / name).symlink_to('/dev/null')
    result = (install(release, release.name, units) if action == 'install'
              else drift(release, units))
    assert result['outcome'] == 'success'
    assert load_release(release) == INVENTORY
    assert {name: (units / name).read_text() for name in expected} == expected
    if action == 'drift':
        (units / 'bybit-cold.timer').write_text('unapproved')
        assert drift(release, units)['mismatches'] == ['bybit-cold.timer']


@pytest.mark.parametrize('name', ['bybit-cold.service', 'bybit-cold-drift.service'])
def test_rendered_bootstrap_reads_original_script_with_replace_ref(replaced_release, name):
    from configparser import ConfigParser
    parser = ConfigParser(interpolation=None)
    parser.read_string(render_units(INVENTORY, replaced_release)[name])
    command = shlex.split(parser['Service']['ExecStart'])
    bootstrap = command[command.index('-c') + 1]
    # --help executes only argparse, with no host installation or service action.
    output = subprocess.check_output([sys.executable, '-I', '-c', bootstrap, '--help'], text=True)
    assert 'usage:' in output and 'Replacement script executed' not in output
