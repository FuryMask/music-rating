"""Open desktop media clients without requesting foreground activation."""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


def launch_without_activation(executable: Path, arguments: list[str]) -> bool:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 4  # SW_SHOWNOACTIVATE
    try:
        subprocess.Popen(
            [str(executable), *arguments],
            cwd=executable.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startup,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError:
        return False
    return True


def lock_foreground_for_launch() -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.WinDLL("user32")
    foreground = user32.GetForegroundWindow
    foreground.restype = wintypes.HWND
    owner = user32.GetWindowThreadProcessId
    owner.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    pid = wintypes.DWORD()
    window = foreground()
    # A choice dialog can still own the foreground while its main window is reactivated.
    if not window or not owner(window, ctypes.byref(pid)) or pid.value != os.getpid():
        return False
    return bool(user32.LockSetForegroundWindow(1))  # LSFW_LOCK


def unlock_foreground_after_launch() -> None:
    if sys.platform == "win32":
        ctypes.WinDLL("user32").LockSetForegroundWindow(2)  # LSFW_UNLOCK


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.UINT), ("tick", wintypes.DWORD)]


def last_input_tick() -> int | None:
    if sys.platform != "win32":
        return None
    info = _LastInputInfo(ctypes.sizeof(_LastInputInfo))
    if ctypes.WinDLL("user32").GetLastInputInfo(ctypes.byref(info)):
        return info.tick
    return None


def keep_launch_in_background(
    window_id: int, launch_input: int | None, executables: tuple[Path, ...],
    *, package_family: str = "",
) -> bool:
    """Return focus only when a known client activated itself without new user input."""
    if sys.platform != "win32" or launch_input is None:
        return False
    user32 = ctypes.WinDLL("user32")
    foreground = user32.GetForegroundWindow
    foreground.restype = wintypes.HWND
    current = foreground()
    if not current or current == window_id:
        return True

    owner = user32.GetWindowThreadProcessId
    owner.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    pid = wintypes.DWORD()
    if not owner(current, ctypes.byref(pid)):
        return False
    if pid.value == os.getpid():
        return True
    if last_input_tick() != launch_input:
        return False

    from app.services.process_loopback import _close_handle, _open_process, _package_family, _process_path

    handle = _open_process(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        name = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(name))
        if not _process_path(handle, 0, name, ctypes.byref(length)):
            return False
        selected = os.path.normcase(name.value) in {os.path.normcase(str(path)) for path in executables}
        if not selected and package_family:
            family = ctypes.create_unicode_buffer(128)
            size = wintypes.UINT(len(family))
            selected = (not _package_family(handle, ctypes.byref(size), family)
                        and family.value.casefold() == package_family.casefold())
    finally:
        _close_handle(handle)
    if not selected or last_input_tick() != launch_input:
        return False
    activate = user32.SetForegroundWindow
    activate.argtypes = (wintypes.HWND,)
    activate(window_id)
    return True
