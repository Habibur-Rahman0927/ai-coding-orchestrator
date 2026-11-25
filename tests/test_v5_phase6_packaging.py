"""Release contents, reproducibility and runtime-data exclusion; no signing keys."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine/lib'))
import ccx_install as install
spec=importlib.util.spec_from_file_location('phase6_builder',ROOT/'tools/build_release.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class CandidatePackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ccx-candidate-');self.base=Path(self.tmp.name);self.source=self.base/'source'
        shutil.copytree(ROOT/'engine',self.source/'engine')
        for name in ('install.sh','uninstall.sh','install.ps1','uninstall.ps1','VERSION','README.md'):shutil.copy2(ROOT/name,self.source/name)
        (self.source/'docs/v5/phase6').mkdir(parents=True)
        (self.source/'docs/v5/phase6/audit.log').write_text('synthetic provider session journal')
        (self.source/'docs/v5/phase6/evidence.json').write_text('{"session_id":"synthetic"}')
        (self.source/'docs/CLI.md').write_text('Approved user guide.')
    def tearDown(self):self.tmp.cleanup()
    def test_source_install_and_archive_exclude_audit_and_session_evidence(self):
        payload=install.engine_payload(self.source)
        self.assertIn('docs/CLI.md',payload)
        self.assertNotIn('docs/v5/phase6/audit.log',payload)
        builder.build(self.source,self.base/'out')
        with tarfile.open(next((self.base/'out').glob('*.tar.gz'))) as t:names=t.getnames()
        self.assertFalse(any('/phase6/' in n for n in names))
        self.assertTrue(any(n.endswith('/RELEASE-INFO.json') for n in names))
    def test_reproducible_archive_has_exact_manifest_and_development_scope(self):
        builder.build(self.source,self.base/'a');builder.build(self.source,self.base/'b')
        one=next((self.base/'a').glob('*.tar.gz'));two=next((self.base/'b').glob('*.tar.gz'))
        self.assertEqual(one.read_bytes(),two.read_bytes())
        with tarfile.open(one) as t:
            data={m.name.split('/',1)[1]:t.extractfile(m).read() for m in t if m.isfile()}
        manifest=json.loads(data['MANIFEST.json'])
        self.assertEqual(set(manifest['files']),set(data)-{'MANIFEST.json'})
        self.assertTrue(all(hashlib.sha256(data[p]).hexdigest()==h for p,h in manifest['files'].items()))
        metadata=json.loads(data['RELEASE-INFO.json']);self.assertEqual(metadata['workspace_version'],'5.0.0-dev')
        self.assertEqual(metadata['release_scope'],'local_evaluation_only');self.assertFalse(metadata['production_ready'])
    def test_runtime_databases_and_logs_are_refused(self):
        for name in ('workspace.sqlite3','runtime.db','workflow.log','workspace.sqlite3-wal','workspace.sqlite3-shm','runtime.db-journal','RUNTIME.DB-JOURNAL'):
            with self.subTest(name=name):
                p=self.source/'engine/lib'/name;p.write_bytes(b'private fixture state')
                with self.assertRaises(install.InstallError):builder.build(self.source,self.base/'out')
                with self.assertRaises(install.InstallError):install.engine_payload(self.source)
                p.unlink()

if __name__=='__main__':unittest.main()
