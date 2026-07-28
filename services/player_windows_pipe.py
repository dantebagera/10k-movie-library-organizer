import ctypes
import os
import time
from ctypes import wintypes

from services.player_protocol import (
    JsonLineBuffer,
    MAX_MESSAGE_BYTES,
    PlayerProtocolError,
    encode_message,
)


class PlayerPipeError(RuntimeError):
    pass


class WindowsNamedPipeServer:
    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_BYTE = 0x00000000
    PIPE_READMODE_BYTE = 0x00000000
    PIPE_NOWAIT = 0x00000001
    PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
    PIPE_UNLIMITED_INSTANCES = 255
    ERROR_PIPE_CONNECTED = 535
    ERROR_NO_DATA = 232
    ERROR_PIPE_LISTENING = 536
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    def __init__(self, pipe_name):
        if os.name != "nt":
            raise PlayerPipeError("Cinema Paradiso Player named pipes require Windows")
        self.pipe_name = str(pipe_name)
        if not self.pipe_name or len(self.pipe_name) > 128:
            raise PlayerPipeError("Player pipe name is invalid")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()
        full_name = rf"\\.\pipe\{self.pipe_name}"
        self._handle = self._kernel32.CreateNamedPipeW(
            full_name,
            self.PIPE_ACCESS_DUPLEX,
            self.PIPE_TYPE_BYTE
            | self.PIPE_READMODE_BYTE
            | self.PIPE_NOWAIT
            | self.PIPE_REJECT_REMOTE_CLIENTS,
            1,
            64 * 1024,
            64 * 1024,
            0,
            None,
        )
        if self._handle == self.INVALID_HANDLE_VALUE:
            raise PlayerPipeError("Could not create the private player pipe")
        self._buffer = JsonLineBuffer()
        self._pending = []

    def _configure_signatures(self):
        kernel32 = self._kernel32
        kernel32.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
        kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        kernel32.ConnectNamedPipe.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def accept(self, timeout):
        deadline = time.monotonic() + max(float(timeout), 0.1)
        while time.monotonic() < deadline:
            connected = self._kernel32.ConnectNamedPipe(self._handle, None)
            if connected:
                return
            error = ctypes.get_last_error()
            if error == self.ERROR_PIPE_CONNECTED:
                return
            if error not in {self.ERROR_PIPE_LISTENING, self.ERROR_NO_DATA}:
                raise PlayerPipeError("The native player could not connect to its private pipe")
            time.sleep(0.01)
        raise TimeoutError("The native player did not connect before the startup timeout")

    def send(self, message):
        payload = encode_message(message)
        written = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(payload)
        if not self._kernel32.WriteFile(
            self._handle,
            buffer,
            len(payload),
            ctypes.byref(written),
            None,
        ) or written.value != len(payload):
            raise PlayerPipeError("The native player pipe write failed")
        self._kernel32.FlushFileBuffers(self._handle)

    def receive(self, timeout):
        if self._pending:
            return self._pending.pop(0)
        deadline = time.monotonic() + max(float(timeout), 0.1)
        chunk = ctypes.create_string_buffer(64 * 1024)
        while time.monotonic() < deadline:
            read = wintypes.DWORD()
            success = self._kernel32.ReadFile(
                self._handle,
                chunk,
                len(chunk),
                ctypes.byref(read),
                None,
            )
            if success and read.value:
                messages = self._buffer.feed(chunk.raw[:read.value])
                if messages:
                    self._pending.extend(messages[1:])
                    return messages[0]
            else:
                error = ctypes.get_last_error()
                if error not in {self.ERROR_NO_DATA, self.ERROR_PIPE_LISTENING}:
                    raise PlayerPipeError("The native player pipe was closed")
            time.sleep(0.01)
        raise TimeoutError("The native player did not respond before the protocol timeout")

    def close(self):
        handle = getattr(self, "_handle", None)
        if handle and handle != self.INVALID_HANDLE_VALUE:
            self._kernel32.DisconnectNamedPipe(handle)
            self._kernel32.CloseHandle(handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
