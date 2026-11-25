"""Install/start/restart/uninstall only in a disposable prefix for real browser QA."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(os.environ.get('CCX_INSTALL_SOURCE', Path(__file__).resolve().parents[2])).resolve()


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError('Isolated installation lifecycle command failed: ' + str(result.returncode))
    return result.returncode


def main():
    with tempfile.TemporaryDirectory(prefix='ccx-installed-cdp-') as temporary:
        base = Path(temporary).resolve()
        prefix, bin_path, database = base / 'engine', base / 'bin', base / 'private/workspace.sqlite3'
        project = base / 'approved project'
        run(['git', 'init', '-q', str(project)])
        (project / 'README.md').write_text('An isolated installed-browser project. Never deploy this fixture.\n')
        installed = run(['/bin/sh', str(ROOT / 'install.sh'), '--prefix', str(prefix), '--bin-dir', str(bin_path)])
        # Control/inspection imports deliberately resolve from the installed copy.
        sys.path.insert(0, str(prefix / 'lib'))
        from ccx_workspace.store import Store
        from ccx_workspace.settings import setting
        from ccx_workspace import service
        store = Store(database)
        start = [str(bin_path / 'orchestrator'), 'open', '--database', str(database),
                 '--port', '0', '--no-browser']
        try:
            started = run(start)
            original_pid = service.private_read(service.paths(store)[0])['pid']
            run(start)
            duplicate_reused = service.private_read(service.paths(store)[0])['pid'] == original_pid
            link = service.request(store, '/api/service/browser', {})['url']
            print(json.dumps({'ready': True, 'url': link, 'project': str(project),
                              'install_exit': installed, 'start_exit': started, 'duplicate_open_reused': duplicate_reused}), flush=True)
            for line in sys.stdin:
                request = json.loads(line)
                operation = request['operation']
                if operation == 'snapshot':
                    with store.connect() as db:
                        actions = db.execute('SELECT COUNT(*) FROM w5_actions').fetchone()[0]
                    result = {'projects': len(store.projects()), 'setup_completed': setting(store, 'setup', {}).get('completed'),
                              'provider_actions': actions, 'installed_import': str(service.__file__).startswith(str(prefix))}
                elif operation == 'restart':
                    service.stop(store)
                    result = {'restart_exit': run(start), 'url': service.request(store, '/api/service/browser', {})['url']}
                elif operation == 'uninstall':
                    service.stop(store)
                    result = {'uninstall_exit': run(['/bin/sh', str(prefix / 'uninstall.sh'), '--prefix', str(prefix),
                                                     '--bin-dir', str(bin_path), '--yes']),
                              'launcher_removed': not (bin_path / 'orchestrator').exists(), 'database_preserved': database.exists()}
                    with sqlite3.connect(database) as db:
                        result['projects_preserved'] = db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
                        result['database_integrity'] = db.execute('PRAGMA integrity_check').fetchone()[0]
                    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
                    break
                elif operation == 'stop':
                    print(json.dumps({'id': request['id'], 'result': {'stopped': True}}), flush=True)
                    break
                else:
                    raise ValueError('Unknown installed fixture command')
                print(json.dumps({'id': request['id'], 'result': result}), flush=True)
        finally:
            service.stop(store)


if __name__ == '__main__':
    main()
