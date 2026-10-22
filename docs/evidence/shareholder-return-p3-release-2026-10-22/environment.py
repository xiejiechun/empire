"""Read-only process QoS/environment evidence. No process or OS settings changed."""
import ctypes
import json
import os
import platform
import sys
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path

class Throttling(ctypes.Structure):
    _fields_ = [('Version',wintypes.ULONG),('ControlMask',wintypes.ULONG),('StateMask',wintypes.ULONG)]
kernel = ctypes.WinDLL('kernel32',use_last_error=True)
kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
kernel.OpenProcess.restype=wintypes.HANDLE
kernel.GetProcessInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
result = dict(at=datetime.now(UTC).isoformat(),platform=platform.platform(),python=sys.version,processes=[])
for pid in [os.getpid(),os.getppid(),*map(int,sys.argv[1:])]:
    handle=kernel.OpenProcess(0x1000,False,pid)
    row=dict(pid=pid)
    if handle:
        try:
            state=Throttling(1,0,0)
            ok=kernel.GetProcessInformation(handle,4,ctypes.byref(state),ctypes.sizeof(state))
            row.update(ok=bool(ok),control_mask=state.ControlMask,state_mask=state.StateMask,error=0 if ok else ctypes.get_last_error())
        finally:kernel.CloseHandle(handle)
    else:row['open_error']=ctypes.get_last_error()
    result['processes'].append(row)
target=Path(__file__).parent/'qos-environment.json'
with target.open('x',encoding='utf8') as f:json.dump(result,f,indent=2)
print(result)
