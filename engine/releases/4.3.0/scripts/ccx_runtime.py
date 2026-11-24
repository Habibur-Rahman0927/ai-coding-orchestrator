"""Runtime launch handoff and portable stream collection."""
import os
from pathlib import Path
import queue
import subprocess
import threading
import tempfile

import ccx_platform as platform


def serialize_session(state_dir, session_id):
    """Bridge Windows guardian handoff and protect the caller's final telemetry.

    Keep both handles alive until the caller exits. The guardian owns canonical
    session/execution locks while the Job runs; the caller's shared management
    lock also prevents uninstall during handoff and after the guardian exits.
    """
    if os.name != 'nt':
        return None
    handles = []
    try:
        management = safe_open(state_dir / 'management.lock', 'a')
        handles.append(management)
        platform.flock(management, platform.LOCK_SH | platform.LOCK_NB)
        launch = safe_open(state_dir / (session_id + '.launch.lock'), 'a')
        handles.append(launch)
        platform.flock(launch, platform.LOCK_EX | platform.LOCK_NB)
        return tuple(handles)
    except BaseException:
        for handle in reversed(handles):
            handle.close()
        raise


def guardian_popen(command, locks, shared=(), preflight=None, approval=None, **kwargs):
    if os.name != 'nt':
        return subprocess.Popen(command, pass_fds=tuple(h.fileno() for h in locks), **kwargs)
    # LockFileEx locks belong to a process and cannot be inherited like flock.
    # The session launch lock prevents a second caller reading stale mapping
    # during this handoff. The guardian checks integrity again after locking.
    argv = list(command)
    separator = argv.index('--')
    before, after = argv[:separator], argv[separator:]
    cleaned = []
    index = 0
    while index < len(before):
        if before[index] == '--lock-fd':
            index += 2
        else:
            cleaned.append(before[index])
            index += 1
    identity = platform.process_info(os.getpid())
    if not identity:
        raise OSError('Unable to verify parent process identity')
    cleaned += ['--parent-pid', str(os.getpid()), '--parent-start', str(identity['start_ticks'])]
    for handle in locks:
        cleaned += ['--shared-lock-path' if handle in shared else '--lock-path', str(handle.ccx_path)]
    if preflight:
        cleaned += ['--integrity-script', str(preflight)]
    if approval:
        cleaned += ['--approval-file', str(approval[0]), '--approval-name', approval[1], '--approval-digest', approval[2]]
    for handle in locks:
        platform.flock(handle, platform.LOCK_UN)
    return subprocess.Popen(cleaned + after, close_fds=True, **kwargs)


class Streams:
    """Reader threads work for both Windows pipe handles and Unix pipes."""
    def __init__(self, process):
        self.events = queue.Queue(maxsize=64)
        self.active = 2
        self.stop = threading.Event()
        for name, stream in (('stdout', process.stdout), ('stderr', process.stderr)):
            threading.Thread(target=self._read, args=(name, stream), daemon=True).start()

    def _put(self, event):
        while not self.stop.is_set():
            try:
                self.events.put(event, timeout=.1)
                return
            except queue.Full:
                pass

    def _read(self, name, stream):
        try:
            while not self.stop.is_set():
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    break
                self._put((name, chunk))
        except OSError as error:
            self._put((name, error))
        finally:
            self._put((name, None))

    def read(self, timeout=.5):
        try:
            name, value = self.events.get(timeout=timeout)
        except queue.Empty:
            return None
        if value is None:
            self.active -= 1
        if isinstance(value, Exception):
            raise value
        return name, value

    def close(self):
        self.stop.set()


def private_directory(directory):
    """Create state directories with private ACLs before creating state files."""
    directory = Path(directory)
    root = platform.state_root()
    if directory != root and root not in directory.parents:
        raise PermissionError('Runtime directory outside application state')
    current = root
    if platform.is_link(root):
        raise PermissionError('State root is a link/reparse point')
    platform.secure_mkdir(root, mode=0o700, parents=True, exist_ok=True)
    platform.validate_permissions(root)
    for part in directory.relative_to(root).parts:
        current = current / part
        if platform.is_link(current):
            raise PermissionError('State directory is a link/reparse point')
        platform.secure_mkdir(current, mode=0o700, exist_ok=True)
        platform.validate_permissions(current)
    return directory


def safe_open(path, mode):
    """Reject link/reparse and foreign/writable lock files before opening."""
    path = Path(path)
    if platform.is_link(path):
        raise PermissionError('Lock/log is a link/reparse point: ' + str(path))
    platform.validate_permissions(path.parent)
    if path.exists():
        platform.validate_permissions(path)
    flags = os.O_RDONLY if mode == 'r' else os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        platform.validate_permissions(path)
        # Refuse a path swapped after the open; cooperative locks must refer to
        # the current pathname's inode rather than an unlinked replacement.
        if os.fstat(fd).st_ino != path.stat().st_ino:
            raise PermissionError('Lock/log replaced while opening')
        handle = os.fdopen(fd, mode, encoding='utf-8')
        handle.ccx_path = path.resolve()
        return handle
    except BaseException:
        os.close(fd)
        raise


def atomic_write(path, data):
    """Write state through a private unique file, never a predictable .tmp name."""
    path = Path(path)
    platform.validate_permissions(path.parent)
    if platform.is_link(path):
        raise PermissionError('State destination is a link/reparse point: ' + str(path))
    if path.exists():
        platform.validate_permissions(path)
    fd, temporary = tempfile.mkstemp(prefix='.ccx-state-', dir=str(path.parent))
    temporary = Path(temporary)
    try:
        platform.secure_mode(temporary, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            fd = None
            handle.write(data.encode('utf-8') if isinstance(data, str) else data)
            handle.flush()
            os.fsync(handle.fileno())
        # Recheck immediately before publishing; do not replace unsafe state.
        platform.validate_permissions(path.parent)
        if platform.is_link(path):
            raise PermissionError('State destination became a link/reparse point')
        if path.exists():
            platform.validate_permissions(path)
        os.replace(str(temporary), str(path))
        if os.name != 'nt':
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        if temporary.exists():
            temporary.unlink()
