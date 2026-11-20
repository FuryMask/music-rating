"""Windows WASAPI loopback for one process tree. Import only on Windows."""

import ctypes as c
import os
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from threading import Event, Lock
from time import monotonic
from uuid import UUID

SAMPLE_RATE = 44_100
CHANNELS = 2
FRAME_BYTES = CHANNELS * 2  # signed 16-bit PCM

_HANDLE = w.HANDLE
_PTR = c.c_void_p
_HRESULT = c.c_long
_GUID = c.c_ubyte * 16
_WAIT_FAILED = 0xFFFFFFFF
_WAIT_TIMEOUT = 258
_INVALID_HANDLE = _PTR(-1).value
_SYNCHRONIZE = 0x100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 2
_COM_MTA = 0
_VT_BLOB = 65
_PROCESS_LOOPBACK = 1
_INCLUDE_PROCESS_TREE = 0
_LOOPBACK_FLAGS = 0x00020000 | 0x00040000 | 0x80000000  # loopback, event callback, PCM conversion
_SILENT_PACKET = 2
_ACTIVATION_TIMEOUT = 3.0


class _ProcessEntry(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
        ("heap_id", c.c_size_t), ("module_id", w.DWORD), ("threads", w.DWORD),
        ("parent_pid", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
        ("name", w.WCHAR * w.MAX_PATH),
    ]


class _ActivationParams(c.Structure):
    _fields_ = [("type", w.DWORD), ("pid", w.DWORD), ("mode", w.DWORD)]


class _Blob(c.Structure):
    _fields_ = [("size", w.ULONG), ("data", _PTR)]


class _PropVariant(c.Structure):
    _fields_ = [("type", w.WORD), ("reserved", w.WORD * 3), ("blob", _Blob)]


class _WaveFormat(c.Structure):
    _pack_ = 1
    _fields_ = [
        ("tag", w.WORD), ("channels", w.WORD), ("sample_rate", w.DWORD),
        ("bytes_per_second", w.DWORD), ("frame_bytes", w.WORD),
        ("bits_per_sample", w.WORD), ("extra_size", w.WORD),
    ]


def _api(dll, name, result, *arguments):
    return c.WINFUNCTYPE(result, *arguments, use_last_error=True)((name, dll))


_kernel = c.WinDLL("kernel32")
_ole = c.WinDLL("ole32")
_snapshot = _api(_kernel, "CreateToolhelp32Snapshot", _HANDLE, w.DWORD, w.DWORD)
_first_process = _api(_kernel, "Process32FirstW", w.BOOL, _HANDLE, c.POINTER(_ProcessEntry))
_next_process = _api(_kernel, "Process32NextW", w.BOOL, _HANDLE, c.POINTER(_ProcessEntry))
_open_process = _api(_kernel, "OpenProcess", _HANDLE, w.DWORD, w.BOOL, w.DWORD)
_process_path = _api(_kernel, "QueryFullProcessImageNameW", w.BOOL, _HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
_package_family = _api(_kernel, "GetPackageFamilyName", w.LONG, _HANDLE, c.POINTER(w.UINT), w.LPWSTR)
_process_session = _api(_kernel, "ProcessIdToSessionId", w.BOOL, w.DWORD, c.POINTER(w.DWORD))
_process_times = _api(_kernel, "GetProcessTimes", w.BOOL, _HANDLE, *([c.POINTER(w.FILETIME)] * 4))
_close_handle = _api(_kernel, "CloseHandle", w.BOOL, _HANDLE)
_create_event = _api(_kernel, "CreateEventW", _HANDLE, _PTR, w.BOOL, w.BOOL, w.LPCWSTR)
_wait = _api(_kernel, "WaitForMultipleObjects", w.DWORD, w.DWORD, c.POINTER(_HANDLE), w.BOOL, w.DWORD)
_co_initialize = _api(_ole, "CoInitializeEx", _HRESULT, _PTR, w.DWORD)
_co_uninitialize = _api(_ole, "CoUninitialize", None)


def _matching_processes(names):
    snapshot = _snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE:
        raise c.WinError(c.get_last_error())
    try:
        entry = _ProcessEntry(size=c.sizeof(_ProcessEntry))
        found = _first_process(snapshot, c.byref(entry))
        while found:
            if entry.name.lower() in names:
                yield entry.pid, entry.parent_pid
            found = _next_process(snapshot, c.byref(entry))
    finally:
        _close_handle(snapshot)


@contextmanager
def find_process_tree(executables, *, package_family="", package_executable=""):
    """Pin the oldest matching root in the current Windows login session."""
    paths = {os.path.normcase(os.path.abspath(path)) for path in executables}
    names = {os.path.basename(path) for path in paths}
    if package_family:
        names.add(package_executable.casefold())
    own_session = w.DWORD()
    if not _process_session(os.getpid(), c.byref(own_session)):
        raise c.WinError(c.get_last_error())
    candidates = {}
    with ExitStack() as handles:
        for pid, parent in _matching_processes(names):
            session = w.DWORD()
            if not _process_session(pid, c.byref(session)) or session.value != own_session.value:
                continue
            handle = _open_process(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                continue
            handles.callback(_close_handle, handle)
            path = c.create_unicode_buffer(32768)
            size = w.DWORD(len(path))
            if not _process_path(handle, 0, path, c.byref(size)) or os.path.normcase(path.value) not in paths:
                if not package_family:
                    continue
                family = c.create_unicode_buffer(128)
                length = w.UINT(len(family))
                if _package_family(handle, c.byref(length), family) or family.value.casefold() != package_family.casefold():
                    continue
            created_at, exited_at, kernel_time, user_time = (w.FILETIME() for _ in range(4))
            if _process_times(handle, c.byref(created_at), c.byref(exited_at),
                              c.byref(kernel_time), c.byref(user_time)):
                created = (created_at.dwHighDateTime << 32) | created_at.dwLowDateTime
                candidates[pid] = (handle, parent, created)
        roots = [
            (created, pid, handle) for pid, (handle, parent, created) in candidates.items()
            if parent not in candidates or candidates[parent][2] > created
        ]
        if roots:
            _, pid, handle = min(roots)
            yield pid, handle
        else:
            yield None


def _guid(value):
    return _GUID.from_buffer_copy(UUID(value).bytes_le)


_AUDIO_CLIENT = _guid("1cb9ad4c-dbfa-4c32-b178-c2f568a703b2")
_CAPTURE_CLIENT = _guid("c8adbd64-e71e-48a0-a4de-185c395cd317")
_COMPLETION_INTERFACES = {
    bytes(_guid(iid)) for iid in (
        "00000000-0000-0000-c000-000000000046",  # IUnknown
        "94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90",  # IAgileObject
        "41d949ab-9862-444a-80f6-c261334da5eb",  # IActivateAudioInterfaceCompletionHandler
    )
}


def _method(interface, slot, *arguments, result=_HRESULT):
    vtable = c.cast(interface, c.POINTER(c.POINTER(_PTR)))[0]
    return c.WINFUNCTYPE(result, _PTR, *arguments)(vtable[slot])


def _check(result: int, operation: str) -> None:
    if result < 0:
        raise OSError(f"{operation} failed (0x{result & 0xFFFFFFFF:08X})")


def _release(interface) -> None:
    if interface:
        _method(interface, 2, result=w.ULONG)(interface)


# Async activation can finish after the thread has cancelled its wait. Keep
# each completion handler alive until COM releases its reference.
_handlers = {}
_handlers_lock = Lock()


class _Activation:
    def __init__(self, pid):
        self.completed = Event()
        self.ref_count = 1
        self.params = _ActivationParams(_PROCESS_LOOPBACK, pid, _INCLUDE_PROCESS_TREE)
        self.variant = _PropVariant(type=_VT_BLOB, blob=_Blob(c.sizeof(self.params), c.addressof(self.params)))
        self.vtable = c.cast(_COMPLETION_VTABLE, _PTR)
        self.pointer = c.addressof(self.vtable)
        with _handlers_lock:
            _handlers[self.pointer] = self


@c.WINFUNCTYPE(w.ULONG, _PTR)
def _add_ref(this):
    with _handlers_lock:
        handler = _handlers[this]
        handler.ref_count += 1
        return handler.ref_count


@c.WINFUNCTYPE(w.ULONG, _PTR)
def _release_ref(this):
    with _handlers_lock:
        handler = _handlers[this]
        handler.ref_count -= 1
        if handler.ref_count == 0:
            del _handlers[this]
        return handler.ref_count


@c.WINFUNCTYPE(_HRESULT, _PTR, c.POINTER(_GUID), c.POINTER(_PTR))
def _query_interface(this, iid, result):
    result[0] = None
    if bytes(iid.contents) not in _COMPLETION_INTERFACES:
        return -2147467262  # E_NOINTERFACE
    _add_ref(this)
    result[0] = this
    return 0


@c.WINFUNCTYPE(_HRESULT, _PTR, _PTR)
def _activate_completed(this, operation):
    _handlers[this].completed.set()
    return 0


_COMPLETION_VTABLE = (_PTR * 4)(
    *(c.cast(method, _PTR) for method in (_query_interface, _add_ref, _release_ref, _activate_completed))
)


def _activate(pid, stop):
    activate = _api(c.WinDLL("mmdevapi"), "ActivateAudioInterfaceAsync", _HRESULT,
                    w.LPCWSTR, c.POINTER(_GUID), c.POINTER(_PropVariant), _PTR, c.POINTER(_PTR))
    operation = _PTR()
    handler = _Activation(pid)
    try:
        _check(activate(r"VAD\Process_Loopback", c.byref(_AUDIO_CLIENT), c.byref(handler.variant),
                        handler.pointer, c.byref(operation)), "ActivateAudioInterfaceAsync")
        deadline = monotonic() + _ACTIVATION_TIMEOUT
        while not stop.is_set():
            if handler.completed.wait(0.05):
                break
            if monotonic() >= deadline:
                raise TimeoutError("WASAPI process loopback activation timed out")
        else:
            return None
        status = _HRESULT()
        audio = _PTR()
        get_result = _method(operation, 3, c.POINTER(_HRESULT), c.POINTER(_PTR))
        try:
            _check(get_result(operation, c.byref(status), c.byref(audio)), "GetActivateResult")
            _check(status.value, "Process loopback activation")
        except OSError:
            _release(audio)
            raise
        return audio
    finally:
        _release(operation)
        _release_ref(handler.pointer)


def _packets(capture, ready, process, stop):
    wait_handles = (_HANDLE * 2)(process, ready)
    get_buffer = _method(capture, 3, c.POINTER(_PTR), c.POINTER(w.UINT), c.POINTER(w.DWORD), _PTR, _PTR)
    release_buffer = _method(capture, 4, w.UINT)
    while not stop.is_set():
        signalled = _wait(len(wait_handles), wait_handles, False, 50)
        if signalled == _WAIT_FAILED:
            raise c.WinError(c.get_last_error())
        if signalled == 0:
            return  # Target process exited.
        if signalled == _WAIT_TIMEOUT:
            continue
        while not stop.is_set():
            data, frames, flags = _PTR(), w.UINT(), w.DWORD()
            _check(get_buffer(capture, c.byref(data), c.byref(frames), c.byref(flags), None, None), "GetBuffer")
            if not frames.value:
                break
            try:
                size = frames.value * FRAME_BYTES
                if flags.value & _SILENT_PACKET:
                    packet = bytes(size)
                elif data:
                    packet = c.string_at(data, size)
                else:
                    raise OSError("WASAPI returned a packet without audio data")
            finally:
                _check(release_buffer(capture, frames.value), "ReleaseBuffer")
            yield packet


@contextmanager
def capture_process_tree(pid, process, stop):
    """Yield an iterator of PCM packets from the pinned process and its children."""
    with ExitStack() as resources:
        _check(_co_initialize(None, _COM_MTA), "CoInitializeEx")
        resources.callback(_co_uninitialize)
        audio = _activate(pid, stop)
        if not audio:
            yield iter(())
            return
        resources.callback(_release, audio)
        ready = _create_event(None, False, False, None)
        if not ready:
            raise c.WinError(c.get_last_error())
        resources.callback(_close_handle, ready)
        fmt = _WaveFormat(1, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * FRAME_BYTES, FRAME_BYTES, 16, 0)
        initialize = _method(audio, 3, w.DWORD, w.DWORD, c.c_longlong, c.c_longlong, c.POINTER(_WaveFormat), _PTR)
        _check(initialize(audio, 0, _LOOPBACK_FLAGS, 0, 0, c.byref(fmt), None), "IAudioClient.Initialize")
        set_event = _method(audio, 13, _HANDLE)
        _check(set_event(audio, ready), "SetEventHandle")
        get_service = _method(audio, 14, c.POINTER(_GUID), c.POINTER(_PTR))
        capture = _PTR()
        _check(get_service(audio, c.byref(_CAPTURE_CLIENT), c.byref(capture)), "GetService")
        resources.callback(_release, capture)
        _check(_method(audio, 10)(audio), "IAudioClient.Start")
        resources.callback(_method(audio, 11), audio)
        yield _packets(capture, ready, process, stop)
