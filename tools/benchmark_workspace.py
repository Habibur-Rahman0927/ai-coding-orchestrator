#!/usr/bin/env python3
"""Reproduce the offline V5 context benchmark without registering user projects."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace.benchmark import benchmark


def main():
    with tempfile.TemporaryDirectory(prefix='ccx-v5-benchmark-') as temporary:
        base = Path(temporary).resolve()
        project = base / 'fixture'
        project.mkdir()
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        for name in ('routing', 'storage', 'recovery'):
            (project / (name + '.py')).write_text(
                'def ' + name + '_operation():\n    """Acceptance evidence for ' + name + '."""\n    return True\n')
        for number in range(30):
            (project / ('background%d.md' % number)).write_text('Unrelated background documentation.\n' * 100)
        store = Store(base / 'state/workspace.sqlite3')
        identifier = store.register(project)['id']
        initial = store.index(identifier)
        repeated = store.index(identifier)
        result = benchmark(store, identifier, ['routing_operation', 'storage_operation', 'recovery_operation'], budget=300)
        result.update(fixture='33 generated files: three targeted symbols, thirty unrelated documents',
                      initial_index=initial, repeated_index=repeated,
                      live_providers=False, scope='Synthetic retrieval benchmark; not end-to-end task quality or billing')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
