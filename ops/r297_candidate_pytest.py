"""Linux candidate-only privilege drop; publication remains with the caller.

Run as root in an ephemeral CI job/container. No accounts or policy are changed.
This is not the process supervisor and does not claim descendant reaping.
"""
import ctypes
import os
from pathlib import Path
import stat
import sys


def main() -> None:
    try:
        if not sys.platform.startswith('linux') or os.geteuid() != 0:
            raise RuntimeError
        caller_uid = int(os.environ.get('SUDO_UID', '0'))
        caller_gid = int(os.environ.get('SUDO_GID', '0'))
        test_uid = 65534
        if caller_uid == test_uid or len(sys.argv) < 3:
            raise RuntimeError
        work = Path(sys.argv[1])
        descriptor = os.open(work, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            metadata = os.fstat(descriptor)
            if (metadata.st_uid != caller_uid or stat.S_IMODE(metadata.st_mode) != 0o700
                    or not work.name.startswith('r297-postgres-work.')
                    or set(os.listdir(descriptor)) != {'pytest.log'}):
                raise RuntimeError
            # Candidate writes only raw reports. The caller can read the directory.
            os.fchown(descriptor, test_uid, caller_gid)
            os.fchmod(descriptor, 0o750)
        finally:
            os.close(descriptor)
        for name in ('GITHUB_OUTPUT', 'GITHUB_ENV', 'GITHUB_PATH', 'GITHUB_STEP_SUMMARY'):
            os.environ.pop(name, None)
        # Inherited across fork/exec: setuid binaries cannot regain publication authority.
        if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
            raise RuntimeError
        os.setgroups([])
        os.setresgid(test_uid, test_uid, test_uid)
        os.setresuid(test_uid, test_uid, test_uid)
        os.umask(0o022)
        os.execv(sys.executable, [sys.executable, *sys.argv[2:]])
    except BaseException:
        print('POSTGRES_TEST_ISOLATION_FAILED', flush=True)
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
