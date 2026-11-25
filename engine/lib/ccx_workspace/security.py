"""Shared conservative secret detection and bounded ordinary-file reads.

Detection is a defense against recognizable credentials, not a guarantee that
arbitrary secrets can be identified. Project permissions remain mandatory.
"""
import os
from pathlib import Path
import re
import stat

SECRET_CONTENT = re.compile(
    r'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----'
    r'|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}'
    r'|\bAKIA[A-Z0-9]{16}'
    r'|(?:api[_-]?key|password|access[_-]?token|client[_-]?secret|secret)'
    r'[\"\x27]?\s*[=:]\s*[\"\x27]?[^\s\"\x27]{8,}', re.I)


def sensitive_content(value):
    """Inspect JSON-compatible data, including nested keys and transcript values."""
    if isinstance(value, str):
        return bool(SECRET_CONTENT.search(value))
    if isinstance(value, dict):
        return any(sensitive_content(key) or sensitive_content(item)
                   or (isinstance(key, str) and isinstance(item, str)
                       and bool(SECRET_CONTENT.search(key + '=' + item)))
                   for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(sensitive_content(item) for item in value)
    return False


def read_regular_bytes(path, limit):
    """Refuse links, devices and pipes without blocking on an unsafe open.

    O_NONBLOCK prevents a FIFO replacement between lstat and open from hanging.
    Descriptor and pathname identity are checked before the bounded read.
    """
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise PermissionError('Only bounded ordinary single-link files may be read')
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
             | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
    fd = os.open(str(path), flags)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        after = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
                or not stat.S_ISREG(after.st_mode)
                or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
                or (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino)):
            raise PermissionError('Unsafe source or file replaced while opening')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('File exceeds size limit')
    return data
