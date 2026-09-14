"""Dependency startup failures must never flush the caller's protected streams."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux-only launcher')
@pytest.mark.parametrize('dependency', ['ctypes', '_ctypes', 'os', 'pathlib', 'stat', 'sys'])
def test_dependency_import_failure_preserves_streams_and_never_executes_candidate(tmp_path, dependency):
    bootstrap = '''
import atexit, builtins, sys
launcher, dependency, seen = sys.argv[1:4]
code = compile(open(launcher, 'rb').read(), launcher, 'exec')
sys.argv = [launcher, *sys.argv[4:]]
original_import = builtins.__import__
def fail_dependency(name, *args, **kwargs):
    if name == dependency:
        with open(seen, 'w') as stream:
            stream.write(name)
        raise ImportError('TEST_DEPENDENCY_IMPORT_FAILURE')
    return original_import(name, *args, **kwargs)
atexit.register(lambda: sys.stderr.write('TEST_FINALIZER\\n'))
assert not sys.stdout.write_through and not sys.stderr.write_through
sys.stdout.write('TEST_BUFFERED_STDOUT')
sys.stderr.write('TEST_BUFFERED_STDERR')
builtins.__import__ = fail_dependency
exec(code, {'__name__': '__main__', '__file__': launcher})
'''
    stdout = tmp_path / 'protected-stdout'
    stderr = tmp_path / 'protected-stderr'
    seen = tmp_path / 'injected-dependency'
    stdout.write_bytes(b'ORIGINAL_STDOUT')
    stderr.write_bytes(b'ORIGINAL_STDERR')
    with tempfile.TemporaryDirectory(prefix='r297-postgres-work.', dir='/tmp') as directory:
        work = Path(directory)
        log = work / 'pytest.log'
        log.touch(mode=0o600)
        marker = work / 'candidate-executed'
        before = work.stat()
        candidate = f'open({str(marker)!r}, "w").write("EXECUTED"); raise SystemExit(97)'
        with stdout.open('ab') as out, stderr.open('ab') as err:
            result = subprocess.run(
                [sys.executable, '-c', bootstrap, str(ROOT / 'ops/r297_candidate_pytest.py'),
                 dependency, str(seen), directory, '-c', candidate],
                stdout=out, stderr=err, timeout=10,
                # CI images may set PYTHONUNBUFFERED; this probe needs pending buffers.
                env={key: value for key, value in os.environ.items() if key != 'PYTHONUNBUFFERED'},
            )
        assert seen.read_text() == dependency, 'fault must reach the actual import boundary'
        assert (stdout.read_bytes(), stderr.read_bytes()) == (b'ORIGINAL_STDOUT', b'ORIGINAL_STDERR')
        assert result.returncode == 2
        assert not marker.exists()
        assert log.read_bytes() == b''
        after = work.stat()
        assert (after.st_uid, after.st_gid, after.st_mode) == (before.st_uid, before.st_gid, before.st_mode)
