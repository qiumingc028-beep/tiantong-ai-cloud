"""Real launcher boundary; run only in a dedicated, secret-free Linux PID domain."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'ops/r297_candidate_pytest.py'
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith('linux') or os.geteuid() != 0,
    reason='requires isolated Linux root-to-candidate execution',
)


@pytest.mark.parametrize('channel', ['extra', 'high_fd_low_limit', 'stdin', 'stdout', 'stderr'])
def test_inherited_privileged_descriptors_cannot_write_from_candidate_or_descendant(tmp_path, channel):
    protected = tmp_path / 'protected-output'
    protected.write_bytes(b'UNCHANGED')
    with tempfile.TemporaryDirectory(prefix='r297-postgres-work.', dir='/tmp') as directory:
        work = Path(directory)
        (work / 'pytest.log').touch(mode=0o600)
        with protected.open('r+b') as stream:
            fd = (512 if channel == 'high_fd_low_limit' else stream.fileno()) if channel in (
                'extra', 'high_fd_low_limit') else ['stdin', 'stdout', 'stderr'].index(channel)
            attack = f'import os\ntry: os.write({fd}, b"FORGED")\nexcept OSError: pass\n'
            payload = (attack + 'import subprocess, sys\n'
                       + f'subprocess.run([sys.executable, "-c", {attack!r}], close_fds=False, check=True)\n')
            options = {'pass_fds': (stream.fileno(),)} if channel in ('extra', 'high_fd_low_limit') else {channel: stream}
            command = [sys.executable, str(LAUNCHER), directory, '-c', payload]
            if channel == 'high_fd_low_limit':
                bootstrap = (f'import os, resource, sys; os.dup2({stream.fileno()}, 512); '
                             'resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64)); '
                             'os.execv(sys.executable, [sys.executable, *sys.argv[1:]])')
                command = [sys.executable, '-c', bootstrap, *command[1:]]
            result = subprocess.run(command,
                                    cwd=ROOT, timeout=15, **options)
        assert result.returncode == 0
        assert protected.read_bytes() == b'UNCHANGED'
        if channel in ('stdout', 'stderr'):
            assert (work / 'pytest.log').read_bytes() == b'FORGEDFORGED'


@pytest.mark.parametrize('initial_state', ['default', 'inheritable_ambient', 'locked_securebits'])
def test_complete_privilege_postconditions_before_candidate_and_descendant(initial_state):
    probe = '''
import ctypes, json, os
from pathlib import Path
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
fields = ('Uid', 'Gid', 'Groups', 'CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb', 'NoNewPrivs')
result = {name: status[name].strip() for name in fields}
result['securebits'] = ctypes.CDLL(None).prctl(27, 0, 0, 0, 0)
for name in ('setuid', 'setgid'):
    try: getattr(os, name)(0)
    except PermissionError: result[name] = 'DENIED'
    else: result[name] = 'REGAINED'
print(json.dumps(result), flush=True)
'''
    payload = probe + f'\nimport subprocess, sys\nsubprocess.run([sys.executable, "-c", {probe!r}], check=True)'
    with tempfile.TemporaryDirectory(prefix='r297-postgres-work.', dir='/tmp') as directory:
        work = Path(directory)
        (work / 'pytest.log').touch(mode=0o600)
        bootstrap = '''
import ctypes, os, sys
libc = ctypes.CDLL(None)
if sys.argv[1] == 'inheritable_ambient':
    header = (ctypes.c_uint32 * 2)(0x20080522, 0)
    data = (ctypes.c_uint32 * 6)()
    assert libc.capget(header, data) == 0
    data[2] |= 1  # CAP_CHOWN in the inheritable set.
    assert libc.capset(header, data) == 0
    assert libc.prctl(47, 2, 0, 0, 0) == 0  # PR_CAP_AMBIENT_RAISE
elif sys.argv[1] == 'locked_securebits':
    assert libc.prctl(28, 3, 0, 0, 0) == 0  # NOROOT | NOROOT_LOCKED
os.execv(sys.executable, [sys.executable, *sys.argv[2:]])
'''
        with (work / 'pytest.log').open('ab') as stream:
            result = subprocess.run([sys.executable, '-c', bootstrap, initial_state,
                                     str(LAUNCHER), directory, '-c', payload], timeout=15,
                                    stdout=stream, stderr=stream)
        lines = (work / 'pytest.log').read_text().splitlines()
        if initial_state == 'locked_securebits':
            assert result.returncode == 2
            assert lines == ['POSTGRES_TEST_ISOLATION_FAILED']
            return
        assert result.returncode == 0
        assert len(lines) == 2
        for line in lines:
            state = json.loads(line)
            assert state['Uid'].split() == ['65534'] * 4
            assert state['Gid'].split() == ['65534'] * 4
            assert state['Groups'] == ''
            for cap in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
                assert int(state[cap], 16) == 0, cap
            assert state['NoNewPrivs'] == '1'
            assert state['securebits'] == 0
            assert state['setuid'] == state['setgid'] == 'DENIED'


@pytest.mark.parametrize('layout', ['symlink', 'hardlink', 'writable', 'nonempty', 'fifo'])
def test_unsafe_log_rejected_without_writing_inherited_streams_or_running_candidate(tmp_path, layout):
    protected = tmp_path / 'protected-output'
    protected.write_bytes(b'UNCHANGED')
    with tempfile.TemporaryDirectory(prefix='r297-postgres-work.', dir='/tmp') as directory:
        work = Path(directory)
        log = work / 'pytest.log'
        if layout == 'symlink':
            log.symlink_to(protected)
        elif layout == 'hardlink':
            os.link(protected, log)
        elif layout == 'fifo':
            os.mkfifo(log)
        else:
            log.touch(mode=0o600)
            if layout == 'writable':
                log.chmod(0o666)
            else:
                log.write_bytes(b'OLD REPORT')
        before = work.stat()
        with protected.open('r+b') as stream:
            result = subprocess.run([sys.executable, str(LAUNCHER), directory, '-c',
                                     'raise SystemExit(97)'], stdout=stream, stderr=stream, timeout=10)
        assert result.returncode == 2
        assert protected.read_bytes() == b'UNCHANGED'
        after = work.stat()
        assert (after.st_uid, after.st_gid, after.st_mode) == (before.st_uid, before.st_gid, before.st_mode)


@pytest.mark.parametrize('fault', ['saved_uid', 'saved_gid', 'supplementary_groups'])
def test_partial_identity_drop_cannot_reach_candidate(fault):
    # Fault injection at the OS boundary: a successful-looking but partial drop.
    bootstrap = '''
import os, runpy, sys
if sys.argv[1] == 'saved_uid':
    os.setresuid = lambda real, effective, saved: os.seteuid(effective)
elif sys.argv[1] == 'saved_gid':
    os.setresgid = lambda real, effective, saved: os.setegid(effective)
else:
    os.setgroups([0])
    os.setgroups = lambda groups: None
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
    with tempfile.TemporaryDirectory(prefix='r297-postgres-work.', dir='/tmp') as directory:
        work = Path(directory)
        (work / 'pytest.log').touch(mode=0o600)
        result = subprocess.run([sys.executable, '-c', bootstrap, fault, str(LAUNCHER),
                                 directory, '-c', 'raise SystemExit(97)'], timeout=15)
        assert result.returncode == 2
        assert (work / 'pytest.log').read_text() == 'POSTGRES_TEST_ISOLATION_FAILED\n'
