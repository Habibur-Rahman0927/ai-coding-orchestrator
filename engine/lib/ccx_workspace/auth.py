"""Ephemeral loopback browser authentication. Secrets are never persisted here."""
import hashlib
import hmac
from http.cookies import SimpleCookie
import secrets
import threading
import time


class BrowserAuth:
    def __init__(self, port, clock=time.monotonic, bootstrap_ttl=60, session_ttl=8*3600):
        self.cookie_name = 'ccx_session_' + str(port)
        self.clock, self.bootstrap_ttl, self.session_ttl = clock, bootstrap_ttl, session_ttl
        self.links, self.sessions = {}, {}
        self.lock = threading.Lock()

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def _prune(self):
        now = self.clock()
        self.links = {k: v for k, v in self.links.items() if v > now}
        self.sessions = {k: v for k, v in self.sessions.items() if v['expires'] > now}

    def issue(self):
        with self.lock:
            self._prune()
            if len(self.links) >= 16:
                raise ValueError('Too many outstanding browser sign-in links')
            value = secrets.token_urlsafe(32)
            self.links[self.digest(value)] = self.clock() + self.bootstrap_ttl
            return value

    def consume(self, value):
        if not isinstance(value, str) or not 32 <= len(value) <= 128:
            raise PermissionError('Browser sign-in link is invalid or expired')
        with self.lock:
            self._prune()
            if self.links.pop(self.digest(value), None) is None:
                raise PermissionError('Browser sign-in link is invalid, expired or already used')
            if len(self.sessions) >= 32:
                raise PermissionError('Session limit reached; rotate authentication locally')
            session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[self.digest(session)] = {'csrf': csrf, 'expires': self.clock()+self.session_ttl}
            return session, csrf

    def session(self, cookie_header):
        if not cookie_header or len(cookie_header) > 8192:
            return None, None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
            item = cookie.get(self.cookie_name)
            key = self.digest(item.value) if item else None
        except Exception:
            return None, None
        with self.lock:
            self._prune()
            value = self.sessions.get(key)
            return key, dict(value) if value else None

    def authorize(self, cookie_header, csrf=None, mutation=False):
        key, session = self.session(cookie_header)
        if session is None:
            raise PermissionError('Browser session expired; reopen from the workspace command')
        # Cookies have no port isolation. A separate origin-scoped tab proof is
        # required even for GET/session restore: another loopback application
        # that receives our cookie cannot exchange it for this proof.
        if not isinstance(csrf, str) or not hmac.compare_digest(csrf, session['csrf']):
            raise PermissionError('Invalid browser request verification')
        return key, session

    def logout(self, key):
        with self.lock:
            self.sessions.pop(key, None)

    def rotate(self):
        with self.lock:
            self.links.clear()
            self.sessions.clear()

    def cookie(self, session, clear=False):
        # HTTP loopback only: Secure cookies are not portable on numeric HTTP
        # loopback. Host/Origin, HttpOnly, SameSite and CSRF are enforced together.
        return '%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d' % (
            self.cookie_name, session, 0 if clear else self.session_ttl)
