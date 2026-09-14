#!/usr/bin/env python3
"""Run pytest in a Windows Job Object and reap every descendant before return."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


class BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


def _api():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _write_result(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="ascii")
    os.replace(temporary, path)


def _try_write_result(path: Path, payload: dict[str, object]) -> bool:
    try:
        _write_result(path, payload)
        return True
    except Exception:
        return False


def _child(gate: Path, log: Path, command: list[str]) -> int:
    deadline = time.monotonic() + 60
    while not gate.is_file():
        if time.monotonic() >= deadline:
            return 125
        time.sleep(0.05)
    with log.open("wb") as output:
        completed = subprocess.run(
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return completed.returncode


def _active_processes(kernel32, job) -> int:
    accounting = BasicAccountingInformation()
    if not kernel32.QueryInformationJobObject(
        job,
        JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        None,
    ):
        raise OSError(ctypes.get_last_error())
    return accounting.ActiveProcesses


def _supervise(args: argparse.Namespace) -> int:
    payload: dict[str, object] = {
        "process_exit_code": None,
        "supervisor_error": None,
        "cleanup_error": None,
    }
    try:
        kernel32 = _api()
        job = kernel32.CreateJobObjectW(None, None)
    except Exception:
        payload["supervisor_error"] = "R297_NATIVE_PROCESS_OWNERSHIP_FAILED"
        _try_write_result(args.result, payload)
        return 1
    if not job:
        payload["supervisor_error"] = "R297_NATIVE_PROCESS_OWNERSHIP_FAILED"
        _try_write_result(args.result, payload)
        return 1

    child = None
    assigned = False
    try:
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            raise OSError(ctypes.get_last_error())
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                "--gate",
                str(args.gate),
                "--log",
                str(args.log),
                "--",
                *args.command,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process = kernel32.OpenProcess(PROCESS_TERMINATE | PROCESS_SET_QUOTA, False, child.pid)
        if not process:
            raise OSError(ctypes.get_last_error())
        try:
            if not kernel32.AssignProcessToJobObject(job, process):
                raise OSError(ctypes.get_last_error())
            assigned = True
        finally:
            try:
                if not kernel32.CloseHandle(process):
                    payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
            except Exception:
                payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
        args.gate.write_text("go\n", encoding="ascii")
        try:
            payload["process_exit_code"] = child.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            payload["supervisor_error"] = "R297_NATIVE_PROCESS_TIMEOUT"
    except Exception:
        payload["supervisor_error"] = "R297_NATIVE_PROCESS_OWNERSHIP_FAILED"
    finally:
        try:
            if child is not None and not assigned and child.poll() is None:
                child.terminate()
        except Exception:
            payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
        try:
            terminated = bool(kernel32.TerminateJobObject(job, 1))
        except Exception:
            terminated = False
        if not terminated:
            payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
        else:
            try:
                deadline = time.monotonic() + 10
                while _active_processes(kernel32, job):
                    if time.monotonic() >= deadline:
                        payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
                        break
                    time.sleep(0.05)
            except Exception:
                payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
        try:
            if not kernel32.CloseHandle(job):
                payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
        except Exception:
            payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
        try:
            if child is not None and child.poll() is None:
                child.wait(timeout=2)
        except Exception:
            payload["cleanup_error"] = "R297_NATIVE_PROCESS_REAP_FAILED"
        wrote_result = _try_write_result(args.result, payload)
    return 0 if wrote_result and not payload["supervisor_error"] and not payload["cleanup_error"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if args.child:
        return _child(args.gate, args.log, args.command)
    if os.name != "nt" or args.result is None or args.timeout_seconds <= 0 or not args.command:
        return 2
    return _supervise(args)


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception:
        exit_code = 1
    raise SystemExit(exit_code)
