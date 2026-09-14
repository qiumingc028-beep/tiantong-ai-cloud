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
    safe_output = False
    try:
        if not sys.platform.startswith('linux') or os.geteuid() != 0:
            raise RuntimeError
        caller_uid = int(os.environ.get('SUDO_UID', '0'))
        caller_gid = int(os.environ.get('SUDO_GID', '0'))
        test_uid = 65534
        if caller_uid == test_uid or len(sys.argv) < 3:
            raise RuntimeError
        # Require an ordinary caller layout before allocating replacement streams.
        for fd in (0, 1, 2):
            os.fstat(fd)
        work = Path(sys.argv[1])
        descriptor = os.open(work, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            metadata = os.fstat(descriptor)
            if (metadata.st_uid != caller_uid or stat.S_IMODE(metadata.st_mode) != 0o700
                    or not work.name.startswith('r297-postgres-work.')
                    or set(os.listdir(descriptor)) != {'pytest.log'}):
                raise RuntimeError
            log_fd = os.open('pytest.log', os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=descriptor)
            try:
                log = os.fstat(log_fd)
                if (not stat.S_ISREG(log.st_mode) or log.st_uid != caller_uid
                        or log.st_nlink != 1 or log.st_size != 0 or log.st_mode & 0o022):
                    raise RuntimeError
                with open('/dev/null', 'rb') as null:
                    os.dup2(null.fileno(), 0)
                os.dup2(log_fd, 1)
                os.dup2(log_fd, 2)
                safe_output = True
            finally:
                os.close(log_fd)
            # Candidate writes only raw reports. The caller can read the directory.
            os.fchown(descriptor, test_uid, caller_gid)
            os.fchmod(descriptor, 0o750)
        finally:
            os.close(descriptor)
        # Kernel closes the entire range, including descriptors above a lowered rlimit.
        # Unsupported kernels/libc fail closed; never fall back to a partial fd snapshot.
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int, *([ctypes.c_ulong] * 4)]
        if libc.close_range(ctypes.c_uint(3), ctypes.c_uint(0xffffffff), ctypes.c_uint(0)) != 0:
            raise RuntimeError
        for name in ('GITHUB_OUTPUT', 'GITHUB_ENV', 'GITHUB_PATH', 'GITHUB_STEP_SUMMARY'):
            os.environ.pop(name, None)
        # Inherited across fork/exec: setuid binaries cannot regain publication authority.
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise RuntimeError
        # Normalize securebits and remove ambient/bounding authority while still root.
        # Locked or unsupported state is not an acceptable partial privilege drop.
        if libc.prctl(28, 0, 0, 0, 0) != 0 or libc.prctl(47, 4, 0, 0, 0) != 0:
            raise RuntimeError
        last_cap = int(Path('/proc/sys/kernel/cap_last_cap').read_text())
        if not 0 <= last_cap < 64:
            raise RuntimeError
        for capability in range(last_cap + 1):
            if libc.prctl(24, capability, 0, 0, 0) != 0:  # PR_CAPBSET_DROP
                raise RuntimeError
        os.setgroups([])
        os.setresgid(test_uid, test_uid, test_uid)
        os.setresuid(test_uid, test_uid, test_uid)
        # Linux capability ABI v3: header(version,pid), two data words(E,P,I).
        header = (ctypes.c_uint32 * 2)(0x20080522, 0)
        capabilities = (ctypes.c_uint32 * 6)()
        if libc.capset(header, capabilities) != 0:
            raise RuntimeError
        status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
        if (any(status[name].split() != [str(test_uid)] * 4 for name in ('Uid', 'Gid'))
                or status['Groups'].split() or status['NoNewPrivs'].strip() != '1'
                or any(int(status[name], 16) != 0
                       for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))
                or libc.prctl(27, 0, 0, 0, 0) != 0):  # PR_GET_SECUREBITS
            raise RuntimeError
        os.umask(0o022)
        os.execv(sys.executable, [sys.executable, *sys.argv[2:]])
    except BaseException:
        try:
            if safe_output:
                os.write(2, b'POSTGRES_TEST_ISOLATION_FAILED\n')
        finally:
            # No interpreter finalizers may flush into untrusted inherited streams.
            os._exit(2)


if __name__ == '__main__':
    main()
