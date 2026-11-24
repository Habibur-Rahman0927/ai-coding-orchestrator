#!/usr/bin/env python3
"""Scan all source files, including ignored files, without exposing their contents."""
import ast
import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_KEY = re.compile(rb'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----')
HOME_PATH = re.compile(rb'/(?:home|Users)/([^/\s\x00"\'<>]+)')
UUID_JSON = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\.json')


def violations(relative, data):
    path = Path(relative)
    hits = []
    if ('__pycache__' in path.parts or path.suffix == '.pyc'
            or path.name in ('auth.json', 'config.toml') or path.name.endswith('.jsonl')
            or UUID_JSON.fullmatch(path.name)
            or any(part in ('registry', 'backups', 'engine-backups') for part in path.parts)):
        hits.append('forbidden data path')
    if PRIVATE_KEY.search(data):
        hits.append('private key marker')
    for match in HOME_PATH.finditer(data):
        allowed = (path.parts[0] in ('tests', 'docs') and match.group(1) in (b'USER', b'someone')
                   and match.group(0).startswith(b'/' + b'home/'))
        if not allowed:
            hits.append('absolute personal home path')
            break
    return hits


class RepositoryHygiene(unittest.TestCase):
    def test_source_tree(self):
        hits = []
        for directory, dirs, names in os.walk(ROOT, followlinks=False):
            dirs[:] = [name for name in dirs if name != '.git']
            for name in names:
                path = Path(directory) / name
                relative = path.relative_to(ROOT)
                if path.is_symlink():
                    hits.append(str(relative) + ': symlink (not followed)')
                    continue
                for reason in violations(relative, path.read_bytes()):
                    hits.append(str(relative) + ': ' + reason)
        self.assertEqual(hits, [], '\n'.join(hits))

    def test_candidate_imports_disable_bytecode_before_shared_modules(self):
        payload = ROOT / 'engine/releases/4.3.0'
        for path in list((payload / 'scripts').glob('*.py')) + list((payload / 'hooks').glob('*.py')):
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                imports = [node.lineno for node in ast.walk(tree)
                           if (isinstance(node, ast.Import) and any(a.name.startswith('ccx_') for a in node.names))
                           or (isinstance(node, ast.ImportFrom) and (node.module or '').startswith('ccx_'))]
                if not imports:
                    continue
                guards = [node.lineno for node in tree.body if isinstance(node, ast.Assign)
                          and isinstance(node.value, ast.Constant) and node.value.value is True
                          and any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                                  and t.value.id == 'sys' and t.attr == 'dont_write_bytecode'
                                  for t in node.targets)]
                self.assertTrue(guards, path)
                self.assertLess(min(guards), min(imports))

    def test_detection_and_scoped_placeholders(self):
        home = b'/' + b'home/'
        users = b'/' + b'Users/'
        for relative in ('README.md', 'engine/example.py'):
            self.assertTrue(violations(relative, home + b'USER/project'))
        for relative in ('tests/example.py', 'docs/example.md'):
            self.assertFalse(violations(relative, home + b'USER/project'))
            self.assertFalse(violations(relative, home + b'someone/project'))
            self.assertTrue(violations(relative, home + b'OTHER/project'))
            self.assertTrue(violations(relative, users + b'USER/project'))
        for relative in ('engine/registry/item.json', 'docs/backups/item', 'auth.json',
                         'config.toml', 'log.jsonl', '00000000-0000-0000-0000-000000000000.json'):
            self.assertTrue(violations(relative, b''))
        for label in (b'', b'OPENSSH ', b'RSA ', b'EC ', b'ENCRYPTED '):
            marker = b'-----BEGIN ' + label + b'PRIVATE KEY-----'
            self.assertTrue(violations('docs/example.txt', marker))


if __name__ == '__main__':
    unittest.main()
