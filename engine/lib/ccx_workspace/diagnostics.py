"""Redacted local checks and explicitly authorized isolated provider smoke tests."""
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .credentials import CredentialManager
from .settings import provider_config, registry_for, save_setting, setting

PROVIDERS = ('codex', 'claude', 'minimax')


def _command(argv):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=8, text=True)
        return result.returncode, result.stdout[:65536], result.stderr[:65536]
    except (OSError, subprocess.TimeoutExpired):
        return None, '', ''


class Diagnostics:
    def __init__(self, store, registry=None, credentials=None):
        self.store = store
        self.registry = registry or registry_for(store)
        self.credentials = credentials or CredentialManager(store)

    def _provider(self, provider):
        if provider not in PROVIDERS: raise ValueError('Unknown provider')

    def _fingerprint(self, provider):
        data = {'config': provider_config(self.store).get(provider, {}),
                'credential_revision': setting(self.store, 'credential_metadata', {}).get(provider, {}).get('updated_at')}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def local(self, provider, inspect_auth=True):
        self._provider(provider)
        result = dict(self.registry.get(provider).status())
        result.update(live_connection_tested=False, authentication='unknown', models=None,
                      supported_roles=['planner', 'executor', 'reviewer'],
                      default_source='native_provider' if provider != 'minimax' else 'application',
                      remaining_quota=None, last_verified_at=None)
        if provider in ('codex', 'claude'):
            if not shutil.which(provider):
                result.update(connection_status='not_installed', remediation='Install the provider CLI, then reopen the workspace from a terminal that can find it.')
                return self._record_local(provider, result)
            code, out, err = _command([provider, '--version'])
            version = re.search(r'\b\d+\.\d+\.\d+(?:[-.a-zA-Z0-9]*)', out)
            result['version'] = version.group(0) if version else None
            result['cli_responding'] = code == 0
            result['connection_status'] = 'authentication_unknown'
            if code != 0:
                result.update(connection_status='unavailable', remediation='Run the provider version command in your terminal and repair its installation.')
                return self._record_local(provider, result)
            if provider == 'claude' and version:
                numbers = tuple(int(v) for v in re.match(r'(\d+)\.(\d+)\.(\d+)', version.group(0)).groups())
                result['compatible'] = numbers >= (2, 1, 259)
                if not result['compatible']:
                    result.update(connection_status='unavailable', remediation='This adapter requires Claude Code 2.1.259 or later for restricted mode and denied unattended permission prompts.')
                    return self._record_local(provider, result)
            if inspect_auth:
                command = [provider, 'login', 'status'] if provider == 'codex' else [provider, 'auth', 'status']
                code, out, err = _command(command)
                if code == 0:
                    result['authentication'] = 'authenticated_locally'
                    result['connection_status'] = 'configured'
                elif code == 1:
                    result['authentication'] = 'not_authenticated'
                    result['connection_status'] = 'not_configured'
                    result['remediation'] = 'Sign in using the native provider CLI; workspace does not copy or change its authentication.'
                else:
                    result['authentication'] = 'unknown'
            result['authentication_method'] = 'native_cli'
        else:
            result['credentials'] = self.credentials.status(provider)
            result['authentication_method'] = result['credentials']['mode']
            if not result.get('available'):
                result['remediation'] = 'Choose an explicit model and configure a credential through OS storage, session-only storage, or a named environment variable.'
        return self._verification(provider, self._record_local(provider, result))

    def _verification(self, provider, result):
        record = setting(self.store, 'provider_verification', {}).get(provider)
        if record and record.get('configuration_fingerprint') == self._fingerprint(provider):
            result['last_test_at'] = record.get('tested_at')
            result['last_test_status'] = record.get('status')
            result['last_test_error_kind'] = record.get('error_kind')
            if record.get('status') == 'verified' and record.get('live'):
                result['last_verified_at'] = record['tested_at']
                if result.get('available') and result.get('authentication') != 'not_authenticated':
                    result['connection_status'] = 'connection_verified'
                result['verification_note'] = 'Historical successful test, not a guarantee of current service availability or remaining quota.'
            elif record.get('error_kind') == 'usage_limit' and record.get('live'):
                result['connection_status'] = 'usage_restricted'
            elif record.get('error_kind') == 'authentication' and record.get('live'):
                result['connection_status'] = 'not_configured'
                result['authentication'] = 'not_authenticated'
        return result

    def _record_local(self, provider, result):
        fingerprint = self._fingerprint(provider)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM dashboard_settings WHERE key='provider_local_diagnostics'").fetchone()
            records = json.loads(row[0]) if row else {}
            records[provider] = {'checked_at': time.time(), 'fingerprint': fingerprint, 'result': result}
            db.execute('INSERT OR REPLACE INTO dashboard_settings(key,value) VALUES(?,?)', ('provider_local_diagnostics', json.dumps(records)))
        return result

    def summary(self, provider):
        """Cheap dashboard polling: no subprocess, network call or OS-secret read."""
        result = next((dict(item) for item in self.registry.status() if item.get('id') == provider), None)
        if result is None: raise ValueError('Unknown provider')
        result.update(authentication='unknown', last_verified_at=None, last_local_check_at=None)
        cached = setting(self.store, 'provider_local_diagnostics', {}).get(provider)
        if cached and cached.get('fingerprint') == self._fingerprint(provider):
            result['last_local_check_at'] = cached.get('checked_at')
            if time.time() - cached.get('checked_at', 0) <= 300 and result.get('available'):
                previous = cached.get('result', {})
                for key in ('authentication', 'authentication_method', 'version', 'cli_responding', 'compatible', 'remediation', 'connection_status'):
                    if key in previous: result[key] = previous[key]
        return self._verification(provider, result)

    def plan(self, provider, resume=False):
        self._provider(provider)
        return {'provider': provider, 'provider_calls': 2 if resume else 1,
                'prompt': 'Reply with WORKSPACE_OK only. Do not use tools, inspect files, or change anything.',
                'project_data_shared': False, 'location': 'new isolated temporary Git repository',
                'native_agent_access_required': provider in ('codex', 'claude'),
                'spending': 'May consume subscription usage or API credits; no fixed cost guarantee.',
                'checks': ['session_creation', 'structured_events', 'reported_usage'] + (['exact_session_resume'] if resume else []),
                'not_checked': ['real_code_implementation', 'bidirectional_workflows', 'cancellation', 'timeout_recovery'],
                'max_output_tokens': 64, 'timeout': 30}

    def live(self, provider, authorization=None, resume=False):
        """Only call from a trusted human UI/CLI; do not expose as an MCP model tool."""
        plan = self.plan(provider, resume)
        authorization = authorization or {}
        if authorization.get('confirmed') is not True or authorization.get('provider') != provider:
            raise PermissionError('Explicit provider-specific live-test spending authorization required')
        if authorization.get('max_calls') != plan['provider_calls']:
            raise PermissionError('Approve the exact displayed number of provider calls')
        if plan['native_agent_access_required'] and authorization.get('native_agent_access') is not True:
            raise PermissionError('Native CLI access must be explicitly authorized for this isolated test')
        result = {'provider': provider, 'tested_at': time.time(), 'status': 'failed', 'live': not getattr(self.registry, 'offline', False),
                  'configuration_fingerprint': self._fingerprint(provider), 'calls': [], 'error_kind': None,
                  'checks_not_run': plan['not_checked'], 'project_data_shared': False}
        with tempfile.TemporaryDirectory(prefix='ccx-connection-check-') as temporary:
            project = Path(temporary).resolve()
            subprocess.run(['git', 'init', '-q', str(project)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            request = {'project': str(project), 'prompt': plan['prompt'], 'role': 'connection_test',
                       'timeout': plan['timeout'], 'max_output_tokens': plan['max_output_tokens'],
                       'allowed_operations': ['native_agent_access'] if plan['native_agent_access_required'] else []}
            first_id = None
            for index in range(plan['provider_calls']):
                reply = self.registry.invoke(provider, request)
                session = reply.get('session_id')
                result['calls'].append({'status': reply.get('status'), 'session_id': session,
                    'usage': reply.get('usage') or {}, 'event_types': sorted({e.get('type') for e in reply.get('events', []) if isinstance(e.get('type'), str)})})
                if reply.get('status') != 'completed' or not session or (index and session != first_id):
                    result['error_kind'] = reply.get('error_kind') or 'protocol'
                    break
                if not first_id: first_id = session
                request.update(session_id=session, history=reply.get('history') or [], prompt='Reply with WORKSPACE_RESUMED only. Do not use tools or read files.')
            else:
                result['status'] = 'verified'
        with self.store.connect() as connection:
            # Serialize record updates so tests for different providers cannot lose one another.
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT value FROM dashboard_settings WHERE key='provider_verification'").fetchone()
            records = json.loads(row[0]) if row else {}
            records[provider] = result
            connection.execute('INSERT OR REPLACE INTO dashboard_settings(key,value) VALUES(?,?)', ('provider_verification', json.dumps(records)))
        self.store.audit('PROVIDER_CONNECTION_TEST', details={'provider': provider, 'status': result['status'], 'calls': len(result['calls'])})
        return result

    def doctor(self):
        with self.store.connect() as db:
            integrity = db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            interrupted = db.execute("SELECT COUNT(*) FROM w5_actions WHERE state IN ('RUNNING','UNCERTAIN')").fetchone()[0] if 'w5_actions' in tables else 0
            projects = db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
            documents = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
        from . import __version__
        return {'version': __version__, 'database_integrity': 'ok' if integrity else 'failed',
                'storage_permissions': 'validated_by_store', 'credential_facilities': self.credentials.facilities(),
                'providers': [self.local(provider) for provider in PROVIDERS],
                'projects_registered': projects, 'indexed_documents': documents, 'actions_requiring_reconciliation': interrupted,
                'remediation': 'Inspect unfinished workflow checkpoints before retrying actions.' if interrupted else None,
                'updates': 'not_configured', 'redacted': True}
