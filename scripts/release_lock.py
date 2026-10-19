"""One OS-owned lock, inherited by release children until they have exited."""
import os
import subprocess
from pathlib import Path


class ReleaseLock:
    def __init__(self, root):
        self.path = Path(root) / '.build.lock'
        self.handle = None

    def __enter__(self):
        if self.path.is_symlink() or self.path.is_junction():
            raise RuntimeError('Release lock cannot be a link')
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.HANDLE]
            kernel.CreateFileW.restype = wintypes.HANDLE
            handle = kernel.CreateFileW(str(self.path), 0xC0000000, 0, None, 4, 0x80, None)
            if handle == wintypes.HANDLE(-1).value:
                raise RuntimeError('Another release/build owns the workspace, or its lock is unavailable')
            self.handle = handle
            os.set_handle_inheritable(handle, True)
        else:
            import fcntl
            self.handle = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(self.handle)
                self.handle = None
                raise RuntimeError('Another release/build owns the workspace') from None
        return self

    def child_options(self):
        if self.handle is None:
            raise RuntimeError('Release ownership is not held')
        if os.name == 'nt':
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {'handle_list': [self.handle]}
            return dict(startupinfo=startup, close_fds=True,
                        creationflags=subprocess.CREATE_NO_WINDOW)
        return {'pass_fds': (self.handle,)}

    def __exit__(self, *args):
        if self.handle is not None:
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                close = ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle
                close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
                close(self.handle)
            else:
                os.close(self.handle)
            self.handle = None
        # Never unlink: deleting a lock path can create a second owner.
