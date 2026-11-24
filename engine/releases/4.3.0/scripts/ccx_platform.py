"""Platform boundary for engine and versioned project runtimes (Python 3.8+).

Security checks fail closed. Linux retains its established paths and /proc
identities; Darwin uses libproc identities with microsecond creation times.
"""

import sys
sys.dont_write_bytecode = True
import ctypes
import os
from pathlib import Path, PurePath, PureWindowsPath
import platform
import re
import shutil
import stat
import sys

WINDOWS = os.name == 'nt'
LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4, 8


def is_link(path):
    path = Path(path)
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def validate_relative(rel):
    value = rel.as_posix() if isinstance(rel, PurePath) else str(rel)
    win = PureWindowsPath(value)
    if not value or value == '.' or win.drive or win.root or value.startswith('/') or '\\' in value:
        raise ValueError('Unsafe relative path: ' + value)
    parts = value.split('/')
    reserved = re.compile(r'^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', re.I)
    for part in parts:
        if (part in ('', '.', '..') or part.endswith((' ', '.')) or reserved.match(part)
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
            raise ValueError('Unsafe relative path: ' + value)
    return Path(*parts)


def validate_owner(path):
    if is_link(path):
        raise PermissionError('Link/reparse point refused: ' + str(path))
    if WINDOWS:
        import ccx_windows
        ccx_windows.validate(path, permissions=False)
    elif Path(path).stat().st_uid != os.getuid():
        raise PermissionError('Unexpected file owner: ' + str(path))


def validate_permissions(path, mask=0o022):
    validate_owner(path)
    if WINDOWS:
        import ccx_windows
        ccx_windows.validate(path)
    elif stat.S_IMODE(Path(path).stat().st_mode) & mask:
        raise PermissionError('Unsafe file permissions: ' + str(path))


def secure_mode(path, mode):
    if is_link(path):
        raise PermissionError('Link/reparse point refused: ' + str(path))
    if WINDOWS:
        import ccx_windows
        ccx_windows.secure(path)
    else:
        os.chmod(path, mode)


def flock(handle, operation):
    fd = handle if isinstance(handle, int) else handle.fileno()
    if WINDOWS:
        import ccx_windows
        ccx_windows.flock(fd, operation)
    else:
        import fcntl
        fcntl.flock(fd, operation)


def data_root():
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'claude-codex-orchestrator'
    if sys.platform == 'darwin' and 'XDG_DATA_HOME' not in os.environ:
        return Path.home() / 'Library/Application Support/claude-codex-orchestrator'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'claude-codex-orchestrator'


def state_root():
    if WINDOWS:
        return data_root() / 'state'
    # This is also the established project-script path on Darwin. Do not silently
    # relocate mappings when switching engine versions or application directories.
    return Path.home() / '.local/state/claude-codex'


def config_root():
    if WINDOWS or (sys.platform == 'darwin' and 'XDG_CONFIG_HOME' not in os.environ):
        return data_root() / 'config'
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'claude-codex-orchestrator'


def bin_root():
    return data_root() / 'bin' if WINDOWS else Path.home() / '.local/bin'


def resolve_executable(command):
    result = shutil.which(str(command))
    if result is None:
        raise FileNotFoundError('Executable not found: ' + str(command))
    return str(Path(result).absolute())


def batch_command(executable, arguments, shell):
    """Build cmd.exe's distinct quoting grammar without CRT backslash quoting.

    A command-line string must be passed directly to CreateProcess/Popen. Percent
    expansion and delayed-expansion characters are rejected even inside quotes.
    """
    values = [str(executable)] + [str(arg) for arg in arguments]
    for value in [str(shell)] + values:
        if any(char in value for char in ('"', '%', '!', '\r', '\n', '\0')):
            raise ValueError('Batch argument cannot be represented safely')
    quoted = ' '.join('"' + value + '"' for value in values)
    return '"' + str(shell) + '" /d /v:off /s /c "' + quoted + '"'


def command_argv(command):
    """Resolve an approved command; batch files return a Windows command string."""
    if not command:
        raise ValueError('Empty command')
    result = [resolve_executable(command[0])] + [str(arg) for arg in command[1:]]
    if WINDOWS and Path(result[0]).suffix.lower() in ('.cmd', '.bat'):
        import ccx_windows
        shell = str(Path(ccx_windows.system_directory()) / 'cmd.exe')
        return batch_command(result[0], result[1:], shell)
    return result


def environment_info():
    return {'os': platform.system(), 'release': platform.release(),
            'architecture': platform.machine(), 'python': platform.python_version(),
            'data_root': str(data_root()), 'state_root': str(state_root()),
            'bin_root': str(bin_root()), 'config_root': str(config_root()),
            'tools': {name: shutil.which(name) for name in ('python3', 'git', 'claude', 'codex', 'gh', 'ssh', 'ssh-keygen')}}


class _BSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
        'rgid', 'svuid', 'svgid', 'rfu')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'pjobc', 'tdev', 'tpgid', 'nice')]
    _fields_ += [('start_sec', ctypes.c_uint64), ('start_usec', ctypes.c_uint64)]


class _TaskInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'virtual_size', 'resident_size', 'total_user', 'total_system', 'threads_user', 'threads_system')]
    _fields_ += [(name, ctypes.c_int32) for name in (
        'policy', 'faults', 'pageins', 'cow_faults', 'messages_sent', 'messages_received',
        'syscalls_mach', 'syscalls_unix', 'csw', 'threadnum', 'running', 'priority')]


def _darwin_info(pid):
    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    query = library.proc_pidinfo
    query.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    query.restype = ctypes.c_int
    info, task = _BSDInfo(), _TaskInfo()
    if query(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
        error = ctypes.get_errno()
        if error in (0, 3):
            return None
        raise OSError(error, os.strerror(error))
    task_size = query(pid, 4, 0, ctypes.byref(task), ctypes.sizeof(task))
    if task_size != ctypes.sizeof(task) and info.status != 5:
        error = ctypes.get_errno()
        if error == 3:
            return None
        raise OSError(error or 5, 'Cannot read Darwin process activity')
    return {'state': 'Z' if info.status == 5 else 'R',
            'cpu_ticks': task.total_user + task.total_system,
            'start_ticks': info.start_sec * 1000000 + info.start_usec,
            'command': (info.name or info.comm).decode('utf-8', errors='replace'),
            'uid': info.uid, 'pgid': info.pgid, 'ppid': info.ppid}


def process_info(pid):
    pid = int(pid)
    if pid <= 0:
        return None
    if WINDOWS:
        import ccx_windows
        return ccx_windows.process_info(pid)
    if sys.platform == 'darwin':
        return _darwin_info(pid)
    if sys.platform.startswith('linux'):
        try:
            entry = Path('/proc') / str(pid)
            raw = (entry / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            return {'state': fields[0], 'cpu_ticks': int(fields[11]) + int(fields[12]),
                    'start_ticks': int(fields[19]),
                    'command': (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').strip(),
                    'uid': entry.stat().st_uid, 'pgid': int(fields[2]),
                    'session': int(fields[3]), 'ppid': int(fields[1])}
        except (FileNotFoundError, ProcessLookupError):
            return None
    raise NotImplementedError('Process identity unavailable on ' + sys.platform)


def _pids(group_id):
    if sys.platform.startswith('linux'):
        return [int(entry.name) for entry in Path('/proc').iterdir() if entry.name.isdigit()]
    if sys.platform == 'darwin':
        library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        query = library.proc_listpids
        query.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        query.restype = ctypes.c_int
        count = query(2, group_id, None, 0) // ctypes.sizeof(ctypes.c_int)
        if count < 0:
            raise OSError('Cannot enumerate Darwin processes')
        if count == 0:
            return []
        buffer = (ctypes.c_int * (count * 2 + 128))()
        count = query(2, group_id, buffer, ctypes.sizeof(buffer)) // ctypes.sizeof(ctypes.c_int)
        if count < 0:
            raise OSError('Cannot enumerate Darwin processes')
        return list(buffer[:count])
    raise NotImplementedError('Windows process containment requires Job Objects')


def group_snapshot(group_id):
    if WINDOWS:
        raise NotImplementedError('Windows process containment requires Job Objects')
    members = {}
    for pid in _pids(group_id):
        try:
            if sys.platform.startswith('linux'):
                # Read only stat to filter membership before accessing cmdline.
                # hidepid mounts already omit foreign processes from enumeration.
                try:
                    raw = (Path('/proc') / str(pid) / 'stat').read_text()
                except (PermissionError, FileNotFoundError, ProcessLookupError):
                    continue
                if int(raw[raw.rfind(')') + 2:].split()[2]) != group_id:
                    continue
            info = process_info(pid)
            if not info or info['state'] == 'Z' or info['pgid'] != group_id:
                continue
            if info['uid'] != os.getuid():
                raise PermissionError('Foreign process in owned group')
            session = info.get('session')
            if session is None:
                session = os.getsid(pid)
            if session == group_id:
                members['%s:%s' % (pid, info['start_ticks'])] = info['cpu_ticks']
        except ProcessLookupError:
            continue
        except PermissionError:
            # Inaccessible unrelated processes are common; we cannot determine
            # their membership safely, so callers must see this failure.
            raise
    return members


def capture_security(path):
    if is_link(path):
        raise PermissionError('Link/reparse point refused: ' + str(path))
    if WINDOWS:
        import ccx_windows
        return ccx_windows.capture_security(path)
    return None


def restore_security(path, snapshot):
    if is_link(path):
        raise PermissionError('Link/reparse point refused: ' + str(path))
    if WINDOWS:
        import ccx_windows
        ccx_windows.restore_security(path, snapshot)
    elif snapshot is not None:
        raise ValueError('Cannot restore a Windows security snapshot on POSIX')


def secure_mkdir(path, mode=0o700, parents=False, exist_ok=False):
    path = Path(path)
    if not WINDOWS:
        path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)
        return
    import ccx_windows
    for ancestor in (path,) + tuple(path.parents):
        if is_link(ancestor):
            raise PermissionError('Link/reparse point refused: ' + str(ancestor))
    if path.exists() or is_link(path):
        if not exist_ok or not path.is_dir():
            raise FileExistsError('Directory exists: ' + str(path))
        validate_permissions(path)
        return
    if parents and not path.parent.exists():
        secure_mkdir(path.parent, mode=mode, parents=True, exist_ok=True)
    # A writable ancestor can replace a private child. Never create sensitive
    # state below a directory controlled by another account or a reparse point.
    validate_permissions(path.parent)
    try:
        ccx_windows.private_directory(path)
    except FileExistsError:
        if not exist_ok or not path.is_dir():
            raise
    validate_permissions(path)
