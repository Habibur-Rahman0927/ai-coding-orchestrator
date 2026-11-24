"""Native Windows security, locking, and process identity (no third-party code).

Imported only on Windows. Errors deliberately propagate: unavailable security
facilities are never interpreted as successful validation.
"""
import ctypes as C
from ctypes import wintypes as W
import os

K = C.WinDLL('kernel32', use_last_error=True)
A = C.WinDLL('advapi32', use_last_error=True)
P = C.c_void_p
DWORD = W.DWORD

def bind(lib, name, args, result=W.BOOL):
    fn = getattr(lib, name)
    fn.argtypes, fn.restype = args, result
    return fn

close = bind(K, 'CloseHandle', [W.HANDLE])
free = bind(K, 'LocalFree', [P], P)
get_current = bind(K, 'GetCurrentProcess', [], W.HANDLE)
open_token = bind(A, 'OpenProcessToken', [W.HANDLE, DWORD, C.POINTER(W.HANDLE)])
get_token = bind(A, 'GetTokenInformation', [W.HANDLE, C.c_int, P, DWORD, C.POINTER(DWORD)])
equal_sid = bind(A, 'EqualSid', [P, P])
sid_string = bind(A, 'ConvertSidToStringSidW', [P, C.POINTER(W.LPWSTR)])
get_security = bind(A, 'GetNamedSecurityInfoW', [W.LPWSTR, C.c_int, DWORD, C.POINTER(P), P, C.POINTER(P), P, C.POINTER(P)], DWORD)
get_ace = bind(A, 'GetAce', [P, DWORD, C.POINTER(P)])
convert_sd = bind(A, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', [W.LPCWSTR, DWORD, C.POINTER(P), P])
get_dacl = bind(A, 'GetSecurityDescriptorDacl', [P, C.POINTER(W.BOOL), C.POINTER(P), C.POINTER(W.BOOL)])
set_security = bind(A, 'SetNamedSecurityInfoW', [W.LPWSTR, C.c_int, DWORD, P, P, P, P], DWORD)


def check(ok):
    if not ok:
        raise C.WinError(C.get_last_error())


def current_sid():
    handle = W.HANDLE()
    check(open_token(get_current(), 0x0008, C.byref(handle)))
    try:
        size = DWORD()
        get_token(handle, 1, None, 0, C.byref(size))
        buffer = C.create_string_buffer(size.value)
        check(get_token(handle, 1, buffer, size, C.byref(size)))
        sid = C.cast(buffer, C.POINTER(P))[0]
        return sid_text(sid)
    finally:
        close(handle)


def sid_text(sid):
    value = W.LPWSTR()
    check(sid_string(sid, C.byref(value)))
    try:
        return value.value
    finally:
        free(C.cast(value, P))


class ACL(C.Structure):
    _fields_ = [('revision', C.c_ubyte), ('sbz1', C.c_ubyte),
                ('size', W.WORD), ('count', W.WORD), ('sbz2', W.WORD)]


class ACE(C.Structure):
    _fields_ = [('type', C.c_ubyte), ('flags', C.c_ubyte),
                ('size', W.WORD), ('mask', DWORD), ('sid', DWORD)]


def validate(path, permissions=True):
    owner, dacl, descriptor = P(), P(), P()
    status = get_security(str(path), 1, 0x1 | 0x4, C.byref(owner), None,
                          C.byref(dacl), None, C.byref(descriptor))
    if status:
        raise C.WinError(status)
    try:
        user = current_sid()
        if not owner or sid_text(owner) != user:
            raise PermissionError('Owner differs from current Windows user: ' + str(path))
        if not permissions:
            return
        if not dacl:
            raise PermissionError('Unrestricted Windows DACL: ' + str(path))
        trusted = {user, 'S-1-5-18', 'S-1-5-32-544'}
        # File data/append/EA/attributes/delete-child, DELETE/WRITE_DAC/WRITE_OWNER,
        # and generic WRITE/ALL. Read-only grants to other users are acceptable.
        writes = 0x00000156 | 0x000D0000 | 0x50000000
        acl = C.cast(dacl, C.POINTER(ACL)).contents
        for index in range(acl.count):
            ptr = P()
            check(get_ace(dacl, index, C.byref(ptr)))
            ace = C.cast(ptr, C.POINTER(ACE)).contents
            if ace.flags & 0x08:  # INHERIT_ONLY_ACE does not grant this object access.
                continue
            if ace.type == 1:  # deny ACE only restricts access
                continue
            if ace.type != 0:
                raise PermissionError('Unsupported Windows access ACE: ' + str(path))
            trustee = sid_text(P(ptr.value + ACE.sid.offset))
            if ace.mask & writes and trustee not in trusted:
                raise PermissionError('Writable by an untrusted Windows principal: ' + str(path))
    finally:
        free(descriptor)


def secure(path):
    # Refuse to take over foreign-owned files. Protect DACL from inherited grants.
    validate(path, permissions=False)
    descriptor = P()
    text = 'D:P(A;OICI;FA;;;%s)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' % current_sid()
    check(convert_sd(text, 1, C.byref(descriptor), None))
    try:
        present, defaulted, dacl = W.BOOL(), W.BOOL(), P()
        check(get_dacl(descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)))
        status = set_security(str(path), 1, 0x80000004, None, None, dacl, None)
        if status:
            raise C.WinError(status)
    finally:
        free(descriptor)
    validate(path)


class OVERLAPPED(C.Structure):
    _fields_ = [('Internal', C.c_size_t), ('InternalHigh', C.c_size_t),
                ('Offset', DWORD), ('OffsetHigh', DWORD), ('hEvent', W.HANDLE)]

lock_file = bind(K, 'LockFileEx', [W.HANDLE, DWORD, DWORD, DWORD, DWORD, C.POINTER(OVERLAPPED)])
unlock_file = bind(K, 'UnlockFileEx', [W.HANDLE, DWORD, DWORD, DWORD, C.POINTER(OVERLAPPED)])


def flock(fd, operation):
    import msvcrt
    handle = W.HANDLE(msvcrt.get_osfhandle(fd))
    overlapped = OVERLAPPED()
    if operation & 8:
        check(unlock_file(handle, 0, 1, 0, C.byref(overlapped)))
        return
    flags = (2 if operation & 2 else 0) | (1 if operation & 4 else 0)
    if not lock_file(handle, flags, 0, 1, 0, C.byref(overlapped)):
        error = C.get_last_error()
        if error in (32, 33):
            raise BlockingIOError(11, 'Lock held by another process')
        raise C.WinError(error)


open_process = bind(K, 'OpenProcess', [DWORD, W.BOOL, DWORD], W.HANDLE)
process_times = bind(K, 'GetProcessTimes', [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4)
exit_code = bind(K, 'GetExitCodeProcess', [W.HANDLE, C.POINTER(DWORD)])
process_name = bind(K, 'QueryFullProcessImageNameW', [W.HANDLE, DWORD, W.LPWSTR, C.POINTER(DWORD)])


def ticks(value):
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def process_info(pid):
    handle = open_process(0x1000, False, pid)
    if not handle:
        error = C.get_last_error()
        if error == 87:
            return None
        raise C.WinError(error)
    try:
        code = DWORD()
        check(exit_code(handle, C.byref(code)))
        if code.value != 259:
            return None
        created, ended, kernel, user = (W.FILETIME() for _ in range(4))
        check(process_times(handle, C.byref(created), C.byref(ended), C.byref(kernel), C.byref(user)))
        if ticks(ended):
            return None
        length = DWORD(32768)
        name = C.create_unicode_buffer(length.value)
        check(process_name(handle, 0, name, C.byref(length)))
        return {'state': 'R', 'cpu_ticks': ticks(kernel) + ticks(user),
                'start_ticks': ticks(created), 'command': name.value}
    finally:
        close(handle)

sd_string = bind(A, 'ConvertSecurityDescriptorToStringSecurityDescriptorW',
                 [P, DWORD, DWORD, C.POINTER(W.LPWSTR), P])
sd_control = bind(A, 'GetSecurityDescriptorControl', [P, C.POINTER(W.WORD), C.POINTER(DWORD)])

get_sd_owner = bind(A, 'GetSecurityDescriptorOwner', [P, C.POINTER(P), C.POINTER(W.BOOL)])
get_sd_group = bind(A, 'GetSecurityDescriptorGroup', [P, C.POINTER(P), C.POINTER(W.BOOL)])


def capture_security(path):
    descriptor = P()
    status = get_security(str(path), 1, 0x7, None, None, None, None, C.byref(descriptor))
    if status:
        raise C.WinError(status)
    value = W.LPWSTR()
    try:
        owner, defaulted = P(), W.BOOL()
        check(get_sd_owner(descriptor, C.byref(owner), C.byref(defaulted)))
        if not owner or sid_text(owner) != current_sid():
            raise PermissionError('Cannot snapshot foreign-owned Windows file')
        check(sd_string(descriptor, 1, 0x7, C.byref(value), None))
        return {'windows_sddl': value.value}
    finally:
        if value:
            free(C.cast(value, P))
        free(descriptor)


def restore_security(path, snapshot):
    validate(path, permissions=False)
    if not isinstance(snapshot, dict) or set(snapshot) != {'windows_sddl'}:
        raise ValueError('Invalid Windows security snapshot')
    descriptor = P()
    check(convert_sd(snapshot['windows_sddl'], 1, C.byref(descriptor), None))
    try:
        present, defaulted = W.BOOL(), W.BOOL()
        owner, group, dacl = P(), P(), P()
        control, revision = W.WORD(), DWORD()
        check(get_sd_owner(descriptor, C.byref(owner), C.byref(defaulted)))
        check(get_sd_group(descriptor, C.byref(group), C.byref(defaulted)))
        check(get_dacl(descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)))
        check(sd_control(descriptor, C.byref(control), C.byref(revision)))
        if not owner or sid_text(owner) != current_sid() or not group or not present or not dacl:
            raise PermissionError('Unsafe Windows security snapshot')
        flags = 0x80000000 if control.value & 0x1000 else 0x20000000
        status = set_security(str(path), 1, 0x7 | flags, owner, group, dacl, None)
        if status:
            raise C.WinError(status)
    finally:
        free(descriptor)


get_system_directory = bind(K, 'GetSystemDirectoryW', [W.LPWSTR, W.UINT], W.UINT)


def system_directory():
    buffer = C.create_unicode_buffer(32768)
    size = get_system_directory(buffer, len(buffer))
    if not size or size >= len(buffer):
        raise C.WinError(C.get_last_error())
    return buffer.value


class SECURITY_ATTRIBUTES(C.Structure):
    _fields_ = [('nLength', DWORD), ('lpSecurityDescriptor', P), ('bInheritHandle', W.BOOL)]


create_directory = bind(K, 'CreateDirectoryW', [W.LPCWSTR, C.POINTER(SECURITY_ATTRIBUTES)])


def private_directory(path):
    """Create one directory with a protected DACL in the creation operation."""
    descriptor = P()
    user = current_sid()
    sddl = 'O:%sD:P(A;OICI;FA;;;%s)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' % (user, user)
    check(convert_sd(sddl, 1, C.byref(descriptor), None))
    try:
        attributes = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
        if not create_directory(str(path), C.byref(attributes)):
            error = C.get_last_error()
            if error == 183:
                raise FileExistsError(17, 'Directory exists', str(path))
            raise C.WinError(error)
    finally:
        free(descriptor)
