"""Windows handle-bound reads; no path-based ACL check followed by a reopen.

Parent handles deny deletion; the leaf denies both writes and deletion until the
consumer finishes. Native execution is required to certify this boundary.
"""
from contextlib import contextmanager, ExitStack
import ctypes as C
from ctypes import wintypes as W
import json
import hashlib
import os
import re
from pathlib import Path, PureWindowsPath

_ADMINS = {"S-1-5-18", "S-1-5-32-544"}
_TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
_POLICY = r"C:\ProgramData\TiantongAI\R297TrustedWindowsObserver\protected\file-policy.json"
_WRITE = 0x40000000 | 0x10000000 | 0xD0156
_READ = 0x80000000 | 0x10000000 | 1


def _validate_acl(owner, entries, *, observer=None, secret=False, output=False, ancestor=False, children=False):
    owners = _ADMINS | ({observer} if output and observer else set())
    if ancestor:
        owners = owners | {_TRUSTED_INSTALLER}
    if owner not in owners:
        raise RuntimeError("R297_WINDOWS_UNTRUSTED_OWNER")
    writers = owners
    # Ancestors may allow creation of siblings, never replacement of this path.
    write_mask = (_WRITE & ~6) if ancestor else _WRITE
    for kind, flags, mask, sid in entries:
        if kind not in {0, 1}:  # No unevaluated object/callback/conditional ACEs.
            raise RuntimeError("R297_WINDOWS_UNSUPPORTED_ACE")
        if kind == 1:
            continue
        if flags & 8 and not (children and flags & 3):
            continue
        # CREATOR OWNER resolves to the trusted publisher on new child files.
        if children and flags & 3 and sid == "S-1-3-0":
            sid = observer
        if mask & write_mask and sid not in writers:
            raise RuntimeError("R297_WINDOWS_UNAUTHORIZED_WRITE_ACE")
        if secret and mask & _READ and sid not in _ADMINS | {observer}:
            raise RuntimeError("R297_WINDOWS_UNAUTHORIZED_KEY_READER")


def _native():
    if os.name != "nt":
        raise RuntimeError("R297_WINDOWS_NATIVE_SECURITY_REQUIRED")
    kernel = C.WinDLL("kernel32", use_last_error=True)
    security = C.WinDLL("advapi32", use_last_error=True)
    signatures = (
        (kernel.CreateFileW, [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE),
        (kernel.CloseHandle, [W.HANDLE], W.BOOL),
        (kernel.LocalFree, [C.c_void_p], C.c_void_p),
        (kernel.GetFileInformationByHandle, [W.HANDLE, C.c_void_p], W.BOOL),
        (security.GetSecurityInfo, [W.HANDLE, W.DWORD, W.DWORD] + [C.c_void_p] * 5, W.DWORD),
        (security.GetAce, [C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
        (security.ConvertSidToStringSidW, [C.c_void_p, C.c_void_p], W.BOOL),
    )
    for function, args, result in signatures:
        function.argtypes, function.restype = args, result
    return kernel, security


def _handle_acl(kernel, security, handle):
    owner, dacl, descriptor = C.c_void_p(), C.c_void_p(), C.c_void_p()
    result = security.GetSecurityInfo(handle, 1, 5, C.byref(owner), None, C.byref(dacl), None, C.byref(descriptor))
    if result:
        raise RuntimeError("R297_WINDOWS_SECURITY_QUERY_FAILED")
    def sid_string(pointer):
        value = W.LPWSTR()
        if not security.ConvertSidToStringSidW(pointer, C.byref(value)):
            raise RuntimeError("R297_WINDOWS_SID_INVALID")
        try:
            return value.value
        finally:
            kernel.LocalFree(C.cast(value, C.c_void_p))
    try:
        if not owner.value or not dacl.value:
            raise RuntimeError("R297_WINDOWS_NULL_SECURITY_DESCRIPTOR")
        count = C.c_uint16.from_address(dacl.value + 4).value
        entries = []
        for index in range(count):
            ace = C.c_void_p()
            if not security.GetAce(dacl, index, C.byref(ace)):
                raise RuntimeError("R297_WINDOWS_ACE_QUERY_FAILED")
            kind = C.c_ubyte.from_address(ace.value).value
            flags = C.c_ubyte.from_address(ace.value + 1).value
            if kind not in {0, 1}:
                raise RuntimeError("R297_WINDOWS_UNSUPPORTED_ACE")
            entries.append((kind, flags, C.c_uint32.from_address(ace.value + 4).value,
                            sid_string(ace.value + 8)))
        return sid_string(owner), entries
    finally:
        kernel.LocalFree(descriptor)


class _FileInfo(C.Structure):
    _fields_ = [("attributes", W.DWORD), ("created", W.FILETIME), ("accessed", W.FILETIME),
                ("written", W.FILETIME), ("volume", W.DWORD), ("size_high", W.DWORD),
                ("size_low", W.DWORD), ("links", W.DWORD), ("index_high", W.DWORD), ("index_low", W.DWORD)]


@contextmanager
def protected_open(path, *, secret=False, output=False, directory=False):
    """Yield a CRT descriptor whose ACL and bytes belong to the same locked object."""
    with _protected_open(path, secret=secret, output=output, directory=directory) as descriptor:
        yield descriptor


@contextmanager
def _protected_open(path, *, secret=False, output=False, directory=False, recovery=False, delete=False, flush=False):
    kernel, security = _native()
    import msvcrt
    path = PureWindowsPath(path)
    if (not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":"
            or any(part in {".", ".."} or ":" in part or part.endswith((".", " "))
                   for part in path.parts[1:])):
        raise RuntimeError("R297_WINDOWS_PATH_INVALID")
    observer = None
    if secret or output:
        with protected_open(_POLICY) as descriptor:
            policy = json.loads(os.read(descriptor, os.fstat(descriptor).st_size))
        if (not isinstance(policy, dict) or set(policy) != {"schema_version", "observer_sid", "candidate_sid"}
                or type(policy["schema_version"]) is not int or policy["schema_version"] != 1
                or any(type(policy[field]) is not str or not policy[field].startswith("S-1-5-21-")
                       for field in ("observer_sid", "candidate_sid"))
                or policy["observer_sid"] == policy["candidate_sid"]):
            raise RuntimeError("R297_WINDOWS_IDENTITY_POLICY_INVALID")
        observer = policy["observer_sid"]
    with ExitStack() as stack:
        for current in [*reversed(path.parents), path]:
            leaf = current == path
            is_file = leaf and not directory
            access = 0x80020000 if is_file else 0x20080
            share = 1 if is_file else 3
            if leaf and recovery:
                access |= 0x10000 if delete else 0x40000000
                share = 7 if delete else 5
            if leaf and flush:
                access |= 0x40000000
            handle = kernel.CreateFileW(str(current), access, share, None, 3, 0x02200000, None)
            if handle == C.c_void_p(-1).value:
                raise OSError(C.get_last_error(), "R297_WINDOWS_PROTECTED_OPEN_FAILED")
            stack.callback(kernel.CloseHandle, handle)
            info = _FileInfo()
            if not kernel.GetFileInformationByHandle(handle, C.byref(info)):
                raise RuntimeError("R297_WINDOWS_FILE_IDENTITY_FAILED")
            if info.attributes & 0x400 or bool(info.attributes & 0x10) == is_file:
                raise RuntimeError("R297_WINDOWS_REPARSE_OR_TYPE_INVALID")
            if is_file and info.links not in ({1, 2} if recovery else {1}):
                raise RuntimeError("R297_WINDOWS_HARDLINK_REJECTED")
            owner, entries = _handle_acl(kernel, security, handle)
            _validate_acl(owner, entries, observer=observer, secret=secret and leaf,
                          output=output, ancestor=not leaf, children=directory and leaf)
        # Duplicate before transferring ownership to the CRT; original stays locked.
        kernel.GetCurrentProcess.restype = W.HANDLE
        kernel.DuplicateHandle.argtypes = [W.HANDLE, W.HANDLE, W.HANDLE, C.c_void_p, W.DWORD, W.BOOL, W.DWORD]
        kernel.DuplicateHandle.restype = W.BOOL
        duplicate = W.HANDLE()
        process = kernel.GetCurrentProcess()
        if not kernel.DuplicateHandle(process, handle, process, C.byref(duplicate), 0, False, 2):
            raise RuntimeError("R297_WINDOWS_HANDLE_DUPLICATION_FAILED")
        try:
            descriptor = msvcrt.open_osfhandle(duplicate.value, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(duplicate)
            raise
        stack.callback(os.close, descriptor)
        yield descriptor


def read_protected(path, *, output=False):
    with protected_open(path, output=output) as descriptor:
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            return stream.read()


class _RecoveryIO:
    """Native filesystem adapter. Portable tests do not certify its Win32 calls."""
    @contextmanager
    def lock(self, parent):
        with _protected_open(parent, output=True, directory=True, flush=True) as directory:
            kernel, security = _native()
            # ponytail: one lock per output directory; per-run directories bound contention.
            handle = kernel.CreateFileW(str(parent / ".r297-publication.lock"), 0x80020000,
                                        0, None, 4, 0x02200000, None)
            if handle == C.c_void_p(-1).value:
                raise RuntimeError("R297_WINDOWS_PUBLICATION_BUSY_OR_UNSAFE")
            try:
                info = _FileInfo()
                if (not kernel.GetFileInformationByHandle(handle, C.byref(info))
                        or info.attributes & (0x400 | 0x10) or info.links != 1):
                    raise RuntimeError("R297_WINDOWS_PUBLICATION_LOCK_INVALID")
                # Read policy through the public single-link boundary.
                policy = json.loads(read_protected(_POLICY))
                owner, entries = _handle_acl(kernel, security, handle)
                _validate_acl(owner, entries, observer=policy["observer_sid"], output=True)
                yield directory
            finally:
                kernel.CloseHandle(handle)

    def open(self, path, *, delete=False):
        return _protected_open(path, output=True, recovery=True, delete=delete)

    def identity(self, descriptor):
        import msvcrt
        kernel, _ = _native()
        info = _FileInfo()
        if not kernel.GetFileInformationByHandle(msvcrt.get_osfhandle(descriptor), C.byref(info)):
            raise RuntimeError("R297_WINDOWS_FILE_IDENTITY_FAILED")
        return info.volume, info.index_high, info.index_low, info.links

    def read(self, descriptor):
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            content = stream.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise RuntimeError("R297_WINDOWS_RECOVERY_SIZE_LIMIT")
        return content

    def remove(self, descriptor, path):
        import msvcrt
        kernel, _ = _native()
        handle = msvcrt.get_osfhandle(descriptor)
        kernel.GetFinalPathNameByHandleW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD]
        kernel.GetFinalPathNameByHandleW.restype = W.DWORD
        buffer = C.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer) or PureWindowsPath(buffer.value.removeprefix("\\\\?\\")) != PureWindowsPath(path):
            raise RuntimeError("R297_WINDOWS_RECOVERY_LINK_MOVED")
        kernel.SetFileInformationByHandle.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
        kernel.SetFileInformationByHandle.restype = W.BOOL
        flags = W.DWORD(3)  # FileDispositionInfoEx: DELETE | POSIX_SEMANTICS.
        if not kernel.SetFileInformationByHandle(handle, 21, C.byref(flags), C.sizeof(flags)):
            raise RuntimeError("R297_WINDOWS_RECOVERY_DELETE_UNSUPPORTED_OR_FAILED")

    def flush(self, descriptor):
        import msvcrt
        kernel, _ = _native()
        kernel.FlushFileBuffers.argtypes = [W.HANDLE]
        kernel.FlushFileBuffers.restype = W.BOOL
        if not kernel.FlushFileBuffers(msvcrt.get_osfhandle(descriptor)):
            raise RuntimeError("R297_WINDOWS_RECOVERY_FILE_FLUSH_FAILED")

    def flush_directory(self, descriptor):
        import msvcrt
        class IOStatus(C.Structure):
            _fields_ = [("status_or_pointer", C.c_void_p), ("information", C.c_size_t)]
        native = C.WinDLL("ntdll", use_last_error=True)
        flush = native.NtFlushBuffersFileEx
        flush.argtypes = [W.HANDLE, C.c_uint32, C.c_void_p, C.c_uint32, C.POINTER(IOStatus)]
        flush.restype = C.c_int32
        status = IOStatus()
        # Flags 0 includes metadata and device synchronization; never DATA_ONLY/NO_SYNC.
        if flush(msvcrt.get_osfhandle(descriptor), 0, None, 0, C.byref(status)) != 0:
            raise RuntimeError("R297_WINDOWS_RECOVERY_DIRECTORY_FLUSH_FAILED")


def _recovery_entry(io, stack, path):
    descriptor = stack.enter_context(io.open(path))
    identity = io.identity(descriptor)
    content = io.read(descriptor)
    if identity[3] not in {1, 2}:
        raise RuntimeError("R297_WINDOWS_RECOVERY_LINK_COUNT_INVALID")
    temporary = None
    if identity[3] == 2:
        pattern = re.compile(rf"\.{re.escape(path.name)}\.[0-9a-f]{{16}}")
        names = [item for item in path.parent.iterdir() if pattern.fullmatch(item.name)]
        if len(names) != 1:
            raise RuntimeError("R297_WINDOWS_RECOVERY_TEMPORARY_AMBIGUOUS")
        handles = stack.enter_context(ExitStack())
        peer = handles.enter_context(io.open(names[0], delete=True))
        if io.identity(peer) != identity or io.read(peer) != content:
            raise RuntimeError("R297_WINDOWS_RECOVERY_LINK_IDENTITY_MISMATCH")
        temporary = (peer, names[0], handles)
    return descriptor, identity, content, temporary


def recover_bound_file(path, *, validate):
    """Recover only a verified original, never widen ordinary protected reads.

    validate must verify the original signature, scope and protected receipt before
    this function mutates any link. No new evidence body is produced here.
    """
    path = Path(path)
    io = _RecoveryIO()
    with io.lock(path.parent) as directory, ExitStack() as stack:
        body = _recovery_entry(io, stack, path)
        content = body[2]
        sidecar = Path(str(path) + ".sha256")
        expected_marker = f"{hashlib.sha256(content).hexdigest()}  {path.name}\n".encode("ascii")
        entries = [body]
        if sidecar.exists():
            marker = _recovery_entry(io, stack, sidecar)
            if marker[2] != expected_marker:
                raise RuntimeError("R297_WINDOWS_RECOVERY_SIDECAR_MISMATCH")
            entries.append(marker)
        validate(content)
        # Verify flush support before deletion. Retrying after an interrupted flush
        # executes these barriers again even if the temporary link is already gone.
        for descriptor, identity, expected, temporary in entries:
            io.flush(descriptor)
        io.flush_directory(directory)
        for descriptor, identity, expected, temporary in entries:
            if io.identity(descriptor) != identity or io.read(descriptor) != expected:
                raise RuntimeError("R297_WINDOWS_RECOVERY_OBJECT_CHANGED")
            if temporary is not None:
                peer, name, handles = temporary
                if io.identity(peer) != identity or io.read(peer) != expected:
                    raise RuntimeError("R297_WINDOWS_RECOVERY_OBJECT_CHANGED")
                io.remove(peer, name)
                handles.close()
                if io.identity(descriptor) != (*identity[:3], 1):
                    raise RuntimeError("R297_WINDOWS_RECOVERY_CLEANUP_INCOMPLETE")
                io.flush(descriptor)
                io.flush_directory(directory)
        if not sidecar.exists():
            # Complete publication under the same lock; never race a second
            # recovery between cleanup and the exclusive sidecar write.
            from ops.r297_evidence_events import _replace_file
            _replace_file(sidecar, expected_marker)
            marker = _recovery_entry(io, stack, sidecar)
            if marker[1][3] != 1 or marker[2] != expected_marker:
                raise RuntimeError("R297_WINDOWS_RECOVERY_SIDECAR_MISMATCH")
            io.flush(marker[0])
        io.flush_directory(directory)
        return content
