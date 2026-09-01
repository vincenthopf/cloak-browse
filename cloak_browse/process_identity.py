from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


def process_start_token(
    pid: int,
    platform_name: str | None = None,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> str | None:
    if type(pid) is not int or pid <= 0 or pid >= 1 << 31:
        return None
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name.startswith("linux"):
        return _linux_start_token(pid)
    if platform_name == "darwin":
        return _darwin_start_token(pid, run)
    if platform_name == "win32":
        return _windows_start_token(pid)
    return None


def same_process(pid: int, expected_token: str | None) -> bool:
    if not expected_token:
        return False
    return process_start_token(pid) == expected_token


def _linux_start_token(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_bytes().decode("ascii", errors="replace")
        tail = raw[raw.rindex(")") + 2 :].split()
        return f"linux:{tail[19]}"
    except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
        return None


def _darwin_start_token(
    pid: int,
    run: Callable[..., subprocess.CompletedProcess[bytes]],
) -> str | None:
    try:
        result = run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.decode("ascii", errors="replace").strip()
    return f"darwin:{value}" if value else None


def _windows_start_token(pid: int) -> str | None:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None
    try:
        load_library = getattr(ctypes, "WinDLL", None)
        if load_library is None:
            return None
        kernel32 = load_library("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
    except (OSError, AttributeError):
        return None
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return f"windows:{value}"
    finally:
        kernel32.CloseHandle(handle)
