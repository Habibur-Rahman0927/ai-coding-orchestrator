"""Disposable real backend for the dependency-free CDP browser test.

The only control channel is the parent's private stdin/stdout pipe. Provider
adapters are patched to fail closed; no real account, key vault or project is used.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine/lib'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_workspace_browser import BrowserRegistry
from ccx_workspace.server import create_server
from ccx_workspace.store import Store
from ccx_workspace.settings import setting


class CorrectionRegistry(BrowserRegistry):
    def __init__(self):
        super().__init__()
        self.reviews = 0
        self.gate = threading.Event()
        self.gate.set()

    def invoke(self, provider, request):
        if not self.gate.wait(20):
            raise AssertionError('Browser fixture provider barrier timed out')
        result = super().invoke(provider, request)
        if request['role'] == 'reviewer' and result['status'] == 'completed':
            self.reviews += 1
            if self.reviews == 1:
                review = json.loads(result['output'])
                review['decision'] = 'changes_requested'
                review['rationale'] = 'Controlled independent reviewer requests a correction pass.'
                for criterion in review['criteria']:
                    criterion['met'] = False
                result['output'] = json.dumps(review)
        return result


def main():
    with tempfile.TemporaryDirectory(prefix='ccx-cdp-fixture-') as temporary:
        base = Path(temporary).resolve()
        project = base / 'sample project'
        subprocess.run(['git', 'init', '-q', str(project)], check=True, capture_output=True)
        (project / 'app.txt').write_text('bad')
        (project / 'check.py').write_text('from pathlib import Path\nassert Path("app.txt").read_text()=="good"\n')
        (project / 'README.md').write_text('The application is correct when app.txt contains good.\n')
        second_project = base / 'second project'
        subprocess.run(['git', 'init', '-q', str(second_project)], check=True, capture_output=True)
        (second_project / 'README.md').write_text('Second isolated project; no first-project conversation belongs here.\n')
        store = Store(base / 'private/workspace.sqlite3')
        registry = CorrectionRegistry()
        guards = [mock.patch('ccx_workspace.providers.' + adapter + '.execute',
                             side_effect=AssertionError('Live provider execution forbidden in CDP tests'))
                  for adapter in ('CLIProvider', 'MiniMaxProvider')]
        # Credential changes rebuild the production registry. Keep that factory
        # pinned to the same offline fixture throughout this combined journey.
        guards.append(mock.patch('ccx_workspace.server.registry_for', return_value=registry))
        for guard in guards:
            guard.start()
        server = create_server(store, registry=registry)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        print(json.dumps({'ready': True, 'url': 'http://127.0.0.1:' + str(server.server_address[1]),
                          'bootstrap': server.auth.issue(), 'project': str(project), 'second_project': str(second_project), 'python': sys.executable}), flush=True)
        try:
            for line in sys.stdin:
                request = json.loads(line)
                operation = request['operation']
                if operation == 'stop':
                    print(json.dumps({'id': request['id'], 'result': {'stopped': True}}), flush=True)
                    break
                if operation == 'snapshot':
                    workflows = server.application.engine.list()
                    result = {'offline_registry_preserved': server.application.registry is registry and server.application.chat.registry is registry,
                              'projects': len(store.projects()), 'setup': setting(store, 'setup', {}), 'experience': setting(store, 'experience', {}),
                              'backup_count': len(list((store.path.parent / 'backups').glob('workspace-*.sqlite3'))),
                              'file': (project / 'app.txt').read_text(), 'calls': registry.calls,
                              'executions': registry.executions, 'reviews': registry.reviews,
                              'workflows': [server.application.engine.status(w['id']) for w in workflows],
                              'approval_count': sum(len(server.application.engine.approvals(w['id'])) for w in workflows),
                              'chats': [server.application.chat.status(c['id']) for c in server.application.chat.list()]}
                elif operation == 'verify_backup':
                    # Private parent pipe only: inspect the UI-created backup,
                    # reopen a separate copy, and never restore over live state.
                    name = request['name']
                    if not isinstance(name, str) or Path(name).name != name or not name.startswith('workspace-') or not name.endswith('.sqlite3'):
                        raise ValueError('Expected a generated backup basename')
                    backup = store.path.parent / 'backups' / name
                    if backup.is_symlink() or not backup.is_file():
                        raise ValueError('Expected an ordinary application backup')
                    original_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
                    if original_hash != request['sha256']:
                        raise ValueError('Rendered backup checksum did not match actual file')
                    copy = base / 'recovery-copy.sqlite3'
                    if copy.exists():
                        raise ValueError('Recovery verification copy already exists')
                    shutil.copy2(backup, copy)
                    recovered = Store(copy)
                    with recovered.connect() as db:
                        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
                        restored_workflows = [tuple(row) for row in db.execute('SELECT id,project_id,objective,status FROM w5_workflows ORDER BY id')]
                    with store.connect() as db:
                        original_workflows = [tuple(row) for row in db.execute('SELECT id,project_id,objective,status FROM w5_workflows ORDER BY id')]
                    restored_projects = recovered.projects()
                    records = [record for item in restored_projects for record in recovered.memories(item['id'])]
                    result = {'integrity': integrity, 'copy_reopened': True,
                              'projects_match': restored_projects == store.projects(),
                              'project_count': len(restored_projects),
                              'workflow_statuses_match': restored_workflows == original_workflows,
                              'workflow_count': len(restored_workflows),
                              'memory_marker_recovered': any('cdp_memory_marker' in record['body'] for record in records),
                              'verified_workflow_memory_recovered': any(record['kind'] == 'verified' and str(record['source']).startswith('workflow:') for record in records),
                              'private_backup_mode': os.name == 'nt' or backup.stat().st_mode & 0o077 == 0,
                              'original_backup_unchanged': hashlib.sha256(backup.read_bytes()).hexdigest() == original_hash}
                elif operation == 'delay':
                    registry.delay = request.get('value', .3)
                    result = {'delay': registry.delay}
                elif operation == 'hold':
                    registry.gate.clear()
                    result = {'held': True}
                elif operation == 'release':
                    registry.gate.set()
                    result = {'held': False}
                elif operation == 'bootstrap':
                    result = {'bootstrap': server.auth.issue()}
                elif operation == 'disconnect':
                    server.shutdown()
                    server.server_close()
                    result = {'disconnected': True}
                elif operation == 'expire':
                    for item in server.auth.sessions.values():
                        item['expires'] = 0
                    result = {'expired': True}
                else:
                    raise ValueError('Unknown fixture command')
                print(json.dumps({'id': request['id'], 'result': result}), flush=True)
        finally:
            registry.gate.set()
            server.application.close()
            server.shutdown()
            server.server_close()
            worker.join(3)
            for guard in reversed(guards):
                guard.stop()


if __name__ == '__main__':
    main()
