"""Deterministic filesystem races at the actual workflow publication seam."""
import json
from pathlib import Path
import sys
import textwrap

import pytest

from ops import ci_pytest_gate as gate

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Ubuntu workflow publication uses Linux directory FDs')


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/r297-candidate-validation.yml'


def publish_from_workflow(work, publish, monkeypatch):
    block = WORKFLOW.read_text().split('      - name: Run complete selected', 1)[1].split('      - name:', 1)[0]
    script = textwrap.dedent(block.split('        run: |\n', 1)[1])
    code = script.split("<<'PY'\n", 1)[1].split('\nPY', 1)[0]
    monkeypatch.setattr(sys, 'argv', ['-', str(work), str(publish)])
    with pytest.raises(SystemExit) as done:
        exec(compile(code, '<postgres-publication>', 'exec'), {'__name__': '__main__'})
    return done.value.code


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv('CI_PYTEST_IDENTITY_KEY', 'test-only-p2-identity-' + 'x' * 64)
    monkeypatch.setenv('R297_REDACT_EXACT_ENV_NAMES', 'CI_PYTEST_IDENTITY_KEY')
    work, publish = tmp_path / 'work', tmp_path / 'publish'
    work.mkdir()
    publish.mkdir()
    (work / 'junit.xml').write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="real" /></testsuite></testsuites>')
    (work / 'collected-nodeids.json').write_text(json.dumps(['a' * 64]))
    (work / 'collected-nodeids.display.json').write_text('[]')
    (work / 'pytest.log').write_text('safe original log')
    return work, publish


def test_path_replaced_after_stable_read_cannot_be_followed_or_modified(reports, tmp_path, monkeypatch):
    work, publish = reports
    victim = tmp_path / 'outside'
    original = 'password=TEST_ONLY_DO_NOT_TOUCH'
    victim.write_text(original)
    read = gate._stable_file_bytes
    replaced = False

    def race(path):
        nonlocal replaced
        payload = read(path)
        if Path(path).name == 'pytest.log' and not replaced:
            replaced = True
            (work / 'pytest.log').unlink()
            (work / 'pytest.log').symlink_to(victim)
        return payload

    monkeypatch.setattr(gate, '_stable_file_bytes', race)
    result = publish_from_workflow(work, publish, monkeypatch)
    assert replaced
    assert victim.read_text() == original
    if result in (0, 10):
        assert (publish / 'pytest.log').read_text() == 'safe original log'


@pytest.mark.parametrize('name,replacement', [
    ('pytest.log', 'password=TEST_ONLY_LATE_SECRET'),
    ('junit.xml', '<testsuites><testsuite tests="999" failures="0" errors="0" skipped="0"/></testsuites>'),
])
def test_raw_replacement_after_validation_cannot_change_published_bytes(reports, monkeypatch, name, replacement):
    work, publish = reports
    original = (work / name).read_bytes()
    validate = gate.validate_report

    def race(*args, **kwargs):
        value = validate(*args, **kwargs)
        (work / name).write_text(replacement)
        return value

    monkeypatch.setattr(gate, 'validate_report', race)
    result = publish_from_workflow(work, publish, monkeypatch)
    assert result in (0, 10)
    if name == 'pytest.log':
        assert (publish / name).read_bytes() == original
    else:
        import xml.etree.ElementTree as ET
        assert ET.parse(publish / name).getroot().find('testsuite').get('tests') == '1'


def test_initial_symlink_is_rejected_without_touching_target(reports, tmp_path, monkeypatch):
    work, publish = reports
    victim = tmp_path / 'outside'
    victim.write_text('unchanged')
    (work / 'pytest.log').unlink()
    (work / 'pytest.log').symlink_to(victim)
    assert publish_from_workflow(work, publish, monkeypatch) == 2
    assert victim.read_text() == 'unchanged'
    assert not list(publish.iterdir())


@pytest.mark.parametrize('change', ['bytes', 'inode', 'directory'])
def test_publication_replacement_is_rejected_before_handoff(reports, monkeypatch, change):
    work, publish = reports
    read = gate._stable_file_bytes
    replaced = False

    def race(path):
        nonlocal replaced
        payload = read(path)
        if Path(path).parent.resolve() == publish and Path(path).name == 'pytest.log' and not replaced:
            replaced = True
            if change == 'directory':
                publish.rename(publish.with_name('original'))
                publish.mkdir()
            elif change == 'inode':
                (publish / 'pytest.log').unlink()
                (publish / 'pytest.log').write_bytes(payload)
            else:
                (publish / 'pytest.log').write_text('password=TEST_ONLY_CHANGED')
        return payload

    monkeypatch.setattr(gate, '_stable_file_bytes', race)
    assert publish_from_workflow(work, publish, monkeypatch) == 2
    assert replaced


def test_close_failure_cannot_claim_safe_publication(reports, monkeypatch):
    work, publish = reports
    close = gate._close_owned_directory

    def failure(owned):
        close(owned)
        raise OSError('TEST_ONLY_CLOSE_FAILURE')

    monkeypatch.setattr(gate, '_close_owned_directory', failure)
    assert publish_from_workflow(work, publish, monkeypatch) == 2
