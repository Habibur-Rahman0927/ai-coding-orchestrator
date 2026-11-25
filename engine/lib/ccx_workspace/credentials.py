"""Application-owned secrets in OS facilities or explicitly selected process memory.

No secret is written to SQLite, arguments, diagnostic output, or a plaintext file.
Native CLI authentication is deliberately outside this module.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from .settings import provider_config, save_setting, setting

_LOCK = threading.RLock()
_SESSION = {}


class CredentialError(RuntimeError):
    pass


def validate_secret(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('Enter a bounded API credential without whitespace')
    return value


class MacKeychain:
    name = 'macOS Keychain'
    def __init__(self):
        self.api = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.api.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        self.api.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        self.api.SecKeychainAddGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.api.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        self.api.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        self.api.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        self.api.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        self.api.SecKeychainItemDelete.restype = ctypes.c_int32
        self.api.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    def _find(self, service, account):
        a, b = service.encode(), account.encode()
        size, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        status = self.api.SecKeychainFindGenericPassword(None, len(a), a, len(b), b, ctypes.byref(size), ctypes.byref(data), ctypes.byref(item))
        if status == -25300:
            return None, None
        if status != 0:
            raise CredentialError('Keychain access refused or unavailable; unlock it or select session-only storage')
        try:
            value = ctypes.string_at(data, size.value).decode('utf-8')
        finally:
            self.api.SecKeychainItemFreeContent(None, data)
        return value, item

    def get(self, service, account):
        value, item = self._find(service, account)
        if item: self.cf.CFRelease(item)
        return value

    def set(self, service, account, value):
        _, item = self._find(service, account)
        encoded = value.encode()
        try:
            if item:
                status = self.api.SecKeychainItemModifyAttributesAndData(item, None, len(encoded), encoded)
            else:
                a, b = service.encode(), account.encode()
                status = self.api.SecKeychainAddGenericPassword(None, len(a), a, len(b), b, len(encoded), encoded, None)
            if status != 0:
                raise CredentialError('Keychain refused credential storage; nothing was saved to a plaintext fallback')
        finally:
            if item: self.cf.CFRelease(item)

    def remove(self, service, account):
        _, item = self._find(service, account)
        if item:
            try:
                if self.api.SecKeychainItemDelete(item) != 0: raise CredentialError('Keychain refused credential removal')
            finally: self.cf.CFRelease(item)


class WindowsCredentialManager:
    name = 'Windows Credential Manager'
    def __init__(self):
        from ctypes import wintypes as w
        class Credential(ctypes.Structure):
            _fields_ = [('Flags', w.DWORD), ('Type', w.DWORD), ('TargetName', w.LPWSTR),
                        ('Comment', w.LPWSTR), ('LastWritten', w.FILETIME), ('CredentialBlobSize', w.DWORD),
                        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', w.DWORD),
                        ('AttributeCount', w.DWORD), ('Attributes', ctypes.c_void_p),
                        ('TargetAlias', w.LPWSTR), ('UserName', w.LPWSTR)]
        self.Credential = Credential
        self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = w.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), w.DWORD]
        self.api.CredWriteW.restype = w.BOOL
        self.api.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
        self.api.CredDeleteW.restype = w.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def get(self, service, account):
        pointer = ctypes.POINTER(self.Credential)()
        if not self.api.CredReadW(service + ':' + account, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168: return None
            raise CredentialError('Windows credential access refused')
        try:
            value = pointer.contents
            return ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode('utf-8')
        finally: self.api.CredFree(pointer)

    def set(self, service, account, value):
        encoded = value.encode()
        if len(encoded) > 2560: raise ValueError('Credential exceeds Windows storage limit')
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        record = self.Credential(Type=1, TargetName=service + ':' + account, CredentialBlobSize=len(encoded),
                                 CredentialBlob=blob, Persist=2, UserName=account)
        if not self.api.CredWriteW(ctypes.byref(record), 0): raise CredentialError('Windows credential storage refused')

    def remove(self, service, account):
        if not self.api.CredDeleteW(service + ':' + account, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialError('Windows credential removal refused')


class SecretService:
    name = 'Linux Secret Service'
    def _run(self, operation, service, account, value=None):
        argv = ['secret-tool', operation]
        if operation == 'store': argv += ['--label=Universal AI Workspace MiniMax']
        argv += ['application', service, 'provider', account]
        try:
            result = subprocess.run(argv, input=value, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            raise CredentialError('Secret Service unavailable or locked; use explicit session-only/environment mode') from None
        if result.returncode and operation == 'lookup': return None
        if result.returncode: raise CredentialError('Secret Service refused the operation; no plaintext fallback was used')
        return result.stdout.rstrip('\n') if operation == 'lookup' else None
    def get(self, service, account): return self._run('lookup', service, account)
    def set(self, service, account, value): self._run('store', service, account, value)
    def remove(self, service, account): self._run('clear', service, account)


def native_backend():
    try:
        if sys.platform == 'darwin': return MacKeychain()
        if os.name == 'nt': return WindowsCredentialManager()
        if shutil.which('secret-tool') and os.environ.get('DBUS_SESSION_BUS_ADDRESS'): return SecretService()
    except (OSError, AttributeError):
        pass
    return None


class CredentialManager:
    def __init__(self, store, backend=None):
        self.store = store
        self.service = 'ccx.workspace.' + hashlib.sha256(str(Path(store.path).resolve()).encode()).hexdigest()[:24]
        self.backend = native_backend() if backend is None else backend

    def facilities(self):
        return {'os': {'available': bool(self.backend), 'name': self.backend.name if self.backend else None,
                       'verified': False, 'note': 'Availability is not proof the credential store is unlocked.'},
                'alternatives': ['environment', 'session'], 'plaintext_fallback': False}

    def status(self, provider='minimax'):
        self._provider(provider)
        config = provider_config(self.store).get(provider, {})
        mode = config.get('credential_mode', 'environment')
        metadata = setting(self.store, 'credential_metadata', {}).get(provider, {})
        if mode == 'environment': present = bool(os.environ.get(config.get('api_key_env', ''), ''))
        elif mode == 'session': present = bool(_SESSION.get((self.service, provider)))
        else: present = bool(metadata.get('os_saved')) and bool(self.backend)
        return {'provider': provider, 'mode': mode, 'configured': present,
                'stored_in_os': bool(metadata.get('os_saved')), 'authentication': 'unknown',
                'persistent': mode == 'os', 'key_visible': False}

    def _provider(self, provider):
        if provider != 'minimax': raise ValueError('Only application-owned MiniMax credentials are managed here')

    def _save_metadata(self, provider, mode=None, os_saved=None):
        # Update the latest preferences and metadata together; a slow vault prompt
        # must not overwrite model settings saved while that prompt was open.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            def get(key):
                row = db.execute('SELECT value FROM dashboard_settings WHERE key=?', (key,)).fetchone()
                return json.loads(row[0]) if row else {}
            config, metadata = get('providers'), get('credential_metadata')
            if mode is not None: config.setdefault(provider, {})['credential_mode'] = mode
            value = metadata.setdefault(provider, {})
            if os_saved is not None: value['os_saved'] = os_saved
            value['updated_at'] = time.time()
            for key, content in (('providers', config), ('credential_metadata', metadata)):
                db.execute('INSERT OR REPLACE INTO dashboard_settings(key,value) VALUES(?,?)', (key, json.dumps(content)))

    def set(self, provider, secret, mode='os', authorized=False):
        self._provider(provider)
        if authorized is not True: raise PermissionError('Explicit credential storage authorization required')
        secret = validate_secret(secret)
        if mode not in ('os', 'session'): raise ValueError('Select OS storage or explicitly authorized session-only storage')
        with _LOCK:
            provider_config(self.store)  # Initialize non-secret settings schema.
            if mode == 'os':
                if not self.backend: raise CredentialError('OS credential facility unavailable; select session-only or environment explicitly')
                self.backend.set(self.service, provider, secret)
                _SESSION.pop((self.service, provider), None)
            else: _SESSION[(self.service, provider)] = secret
            self._save_metadata(provider, mode, True if mode == 'os' else None)
            self.store.audit('CREDENTIAL_UPDATED', details={'provider': provider, 'mode': mode})
        return self.status(provider)

    def remove(self, provider='minimax', authorized=False):
        self._provider(provider)
        if authorized is not True: raise PermissionError('Explicit credential removal authorization required')
        with _LOCK:
            metadata = setting(self.store, 'credential_metadata', {})
            if metadata.get(provider, {}).get('os_saved'):
                if not self.backend: raise CredentialError('OS credential facility unavailable; cannot confirm removal')
                self.backend.remove(self.service, provider)
            _SESSION.pop((self.service, provider), None)
            self._save_metadata(provider, os_saved=False)
            self.store.audit('CREDENTIAL_REMOVED', details={'provider': provider})
        return self.status(provider)

    def resolve(self, provider, config):
        self._provider(provider)
        mode = config.get('credential_mode', 'environment')
        if mode == 'environment': return os.environ.get(config.get('api_key_env', ''))
        if mode == 'session': return _SESSION.get((self.service, provider))
        if mode == 'os':
            if not self.backend: raise CredentialError('OS credential storage unavailable')
            return self.backend.get(self.service, provider)
        raise ValueError('Unknown credential mode')
