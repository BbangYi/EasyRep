"""Prevent idle sleep only while a Windows vision command is active."""
from contextlib import contextmanager
import os


@contextmanager
def keep_awake():
    if os.name != "nt":
        yield
        return
    import ctypes
    function = ctypes.windll.kernel32.SetThreadExecutionState
    function.argtypes = [ctypes.c_uint]
    function.restype = ctypes.c_uint
    previous = function(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED; display may sleep.
    if not previous:
        raise OSError("could not request a temporary Windows idle-sleep lease")
    try:
        yield
    finally:
        function(previous)
