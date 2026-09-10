"""Windows handle-bound reads; no path-based ACL check followed by a reopen.

Parent handles deny deletion; the leaf denies both writes and deletion until the
consumer finishes. Native execution is required to certify this boundary.
"""
from contextlib import contextmanager, ExitStack
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import PureWindowsPath

_ADMINS = {"S-1-5-18", "S-1-5-32-544"}
_TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
_POLICY = r"C:\ProgramData\TiantongAI\R297TrustedWindowsObserver\protected\file-policy.json"
_WRITE = 0x40000000 | 0x10000000 | 0xD0156
_READ = 0x80000000 | 0x10000000 | 1


def _validate_acl(owner, entries, *, observer=None, secret=False, output=False, ancestor=False):
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
        if kind == 1 or flags & 8:  # Deny or INHERIT_ONLY cannot grant access here.
            continue
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
            handle = kernel.CreateFileW(str(current), 0x80020000 if is_file else 0x20080,
                                        1 if is_file else 3, None, 3, 0x02200000, None)
            if handle == C.c_void_p(-1).value:
                raise OSError(C.get_last_error(), "R297_WINDOWS_PROTECTED_OPEN_FAILED")
            stack.callback(kernel.CloseHandle, handle)
            info = _FileInfo()
            if not kernel.GetFileInformationByHandle(handle, C.byref(info)):
                raise RuntimeError("R297_WINDOWS_FILE_IDENTITY_FAILED")
            if info.attributes & 0x400 or bool(info.attributes & 0x10) == is_file:
                raise RuntimeError("R297_WINDOWS_REPARSE_OR_TYPE_INVALID")
            if is_file and info.links != 1:
                raise RuntimeError("R297_WINDOWS_HARDLINK_REJECTED")
            owner, entries = _handle_acl(kernel, security, handle)
            _validate_acl(owner, entries, observer=observer, secret=secret and leaf,
                          output=output, ancestor=not leaf)
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
