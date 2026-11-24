"""Windows containment: assign the Job atomically during native process creation.

PROC_THREAD_ATTRIBUTE_JOB_LIST prevents a suspended, uncontained creation gap.
No child instruction executes before successful Job assignment. Closing the
non-inheritable Job handle terminates all contained processes, including when
the supervising Python process is forcibly terminated.
"""

import sys
sys.dont_write_bytecode = True
import ctypes
from ctypes import wintypes as w
import os
import subprocess
import time


class WindowsJob:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows Job Objects require native Windows')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                                     'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def start(self, command, **kwargs):
        """Create a child with Job membership and an exact inherited-handle list.

        Windows 10+ supports JOB_LIST. Older/unsupported hosts fail closed at
        UpdateProcThreadAttribute/CreateProcess; there is no uncontained fallback.
        """
        if set(kwargs) - {'stdout', 'stderr'} or any(kwargs.get(name) != subprocess.PIPE for name in ('stdout', 'stderr')):
            raise ValueError('Job.start requires captured stdout/stderr and inherited environment/cwd')
        k = self.k
        void = ctypes.c_void_p
        size = ctypes.c_size_t

        class Security(ctypes.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', void), ('inherit', w.BOOL)]

        class Startup(ctypes.Structure):
            _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR)]
            _fields_ += [(name, w.DWORD) for name in ('x', 'y', 'xsize', 'ysize', 'xchars', 'ychars', 'fill', 'flags')]
            _fields_ += [('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', void),
                        ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]

        class StartupEx(ctypes.Structure):
            _fields_ = [('startup', Startup), ('attributes', void)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]

        k.CreatePipe.argtypes = [ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), ctypes.POINTER(Security), w.DWORD]
        k.SetHandleInformation.argtypes = [w.HANDLE, w.DWORD, w.DWORD]
        k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(Security), w.DWORD, w.DWORD, w.HANDLE]
        k.CreateFileW.restype = w.HANDLE
        k.InitializeProcThreadAttributeList.argtypes = [void, w.DWORD, w.DWORD, ctypes.POINTER(size)]
        k.UpdateProcThreadAttribute.argtypes = [void, w.DWORD, size, void, size, void, void]
        k.DeleteProcThreadAttributeList.argtypes = [void]
        k.DeleteProcThreadAttributeList.restype = None
        k.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, void, void, w.BOOL, w.DWORD, void,
                                    w.LPCWSTR, ctypes.POINTER(StartupEx), ctypes.POINTER(ProcessInfo)]
        k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.WaitForSingleObject.restype = w.DWORD
        security = Security(ctypes.sizeof(Security), None, True)
        owned = []
        attributes = None
        initialized = False
        info = ProcessInfo()
        streams = []

        def check(result):
            if not result:
                raise ctypes.WinError(ctypes.get_last_error())

        try:
            readers, writers = [], []
            for _ in range(2):
                read, write = w.HANDLE(), w.HANDLE()
                check(k.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0))
                owned.extend((read.value, write.value))
                check(k.SetHandleInformation(read, 1, 0))  # parent read end never inherited
                readers.append(read.value)
                writers.append(write.value)
            null = k.CreateFileW('NUL', 0x80000000, 3, ctypes.byref(security), 3, 0x80, None)
            if null == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            owned.append(null)
            needed = size()
            k.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(needed))
            if not needed.value:
                raise ctypes.WinError(ctypes.get_last_error())
            attributes = ctypes.create_string_buffer(needed.value)
            check(k.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(needed)))
            initialized = True
            inherited = (w.HANDLE * 3)(null, *writers)
            jobs = (w.HANDLE * 1)(self.handle)
            check(k.UpdateProcThreadAttribute(attributes, 0, 0x20002, inherited,
                                             ctypes.sizeof(inherited), None, None))  # HANDLE_LIST
            check(k.UpdateProcThreadAttribute(attributes, 0, 0x2000D, jobs,
                                             ctypes.sizeof(jobs), None, None))  # JOB_LIST
            startup = StartupEx()
            startup.startup.cb = ctypes.sizeof(StartupEx)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = null, *writers
            startup.attributes = ctypes.cast(attributes, void)
            commandline = command if isinstance(command, str) else subprocess.list2cmdline(command)
            if isinstance(command, str):
                if not command.startswith('"') or '"' not in command[1:]:
                    raise ValueError('Windows command strings require a quoted executable path')
                application = command.split('"', 2)[1]
            else:
                application = command[0]
            buffer = ctypes.create_unicode_buffer(commandline)
            # EXTENDED_STARTUPINFO_PRESENT | CREATE_NEW_PROCESS_GROUP. Job
            # association is part of CreateProcess, before the initial thread runs.
            check(k.CreateProcessW(application, buffer, None, None, True, 0x80000 | 0x200,
                                   None, None, ctypes.byref(startup), ctypes.byref(info)))
            k.CloseHandle(info.thread)
            info.thread = None
            import msvcrt
            for handle in readers:
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                owned.remove(handle)  # CRT now owns the native handle
                try:
                    streams.append(os.fdopen(fd, 'rb', buffering=0))
                except BaseException:
                    os.close(fd)
                    raise
            process = _Process(k, info.process, info.pid, command, streams[0], streams[1])
            info.process = None  # process wrapper owns this handle
            streams = []
            return process
        except BaseException:
            if info.process:
                k.TerminateProcess(info.process, 130)
                k.WaitForSingleObject(info.process, 10000)
            raise
        finally:
            if info.thread:
                k.CloseHandle(info.thread)
            if info.process:
                k.CloseHandle(info.process)
            for stream in streams:
                stream.close()
            for handle in owned:
                k.CloseHandle(handle)
            if initialized:
                k.DeleteProcThreadAttributeList(attributes)

    def pids(self):
        capacity = 64
        while capacity <= 65536:
            class ProcessList(ctypes.Structure):
                _fields_ = [('assigned', w.DWORD), ('count', w.DWORD), ('ids', ctypes.c_size_t * capacity)]
            info = ProcessList()
            if self.k.QueryInformationJobObject(self.handle, 3, ctypes.byref(info), ctypes.sizeof(info), None):
                return list(info.ids[:info.count])
            error = ctypes.get_last_error()
            if error != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(error)
            capacity *= 2
        raise OSError('Job process list exceeds safe monitoring capacity')

    def snapshot(self, process_info):
        result = {}
        for pid in self.pids():
            info = process_info(pid)
            if info and info['state'] != 'Z':
                result['%s:%s' % (pid, info['start_ticks'])] = info['cpu_ticks']
        return result

    def terminate(self):
        if not self.k.TerminateJobObject(self.handle, 130):
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + 10
        while self.pids() and time.monotonic() < deadline:
            time.sleep(.05)
        return not self.pids()

    def close(self):
        if getattr(self, 'handle', None):
            self.k.CloseHandle(self.handle)
            self.handle = None


class _Process:
    """Minimal owned process interface used by the portable recovery controller."""
    def __init__(self, kernel, handle, pid, args, stdout, stderr):
        self.k, self.handle, self.pid, self.args = kernel, handle, pid, args
        self.stdout, self.stderr = stdout, stderr
        self.returncode = None
        self.k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        self.k.GenerateConsoleCtrlEvent.argtypes = [w.DWORD, w.DWORD]

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        status = self.k.WaitForSingleObject(self.handle, 0)
        if status == 258:  # WAIT_TIMEOUT, including an alive process whose exit code will be 259
            return None
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = w.DWORD()
        if not self.k.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is not None:
            return self.returncode
        milliseconds = 0xFFFFFFFF if timeout is None else min(0xFFFFFFFE, max(0, int(timeout * 1000)))
        status = self.k.WaitForSingleObject(self.handle, milliseconds)
        if status == 258:
            raise subprocess.TimeoutExpired(self.args, timeout)
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def kill(self):
        if self.poll() is None and not self.k.TerminateProcess(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    terminate = kill

    def send_signal(self, sig):
        import signal
        if sig == signal.CTRL_BREAK_EVENT:
            if not self.k.GenerateConsoleCtrlEvent(1, self.pid):
                raise ctypes.WinError(ctypes.get_last_error())
        elif sig == signal.SIGTERM:
            self.kill()
        else:
            raise ValueError('Unsupported Windows signal')

    def __del__(self):
        if getattr(self, 'handle', None):
            self.k.CloseHandle(self.handle)
            self.handle = None
