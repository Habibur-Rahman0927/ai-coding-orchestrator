"""Dashboard backup creates a private verified copy, never overwrites live state."""
import hashlib
import os
from pathlib import Path
import unittest
import test_v5_memory as fixtures
from ccx_workspace.server import Dashboard, DashboardError
from ccx_workspace.store import Store

class DashboardBackupTests(unittest.TestCase):
    setUp=fixtures.MemoryTests.setUp
    tearDown=fixtures.MemoryTests.tearDown
    def test_backup_restores_project_memory_without_touching_live_database(self):
        record=self.store.add_memory(self.pid,'project','Important rule','No deployments',kind='user_instruction')
        dashboard=Dashboard(self.store)
        try:result=dashboard.dispatch('POST','/api/backups',{})
        finally:dashboard.close()
        path=Path(result['backup']);self.assertEqual(path.parent,self.db.parent/'backups')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),result['sha256'])
        self.assertEqual(Store(path).memories(self.pid)[0]['id'],record['id'])
        self.assertEqual(self.store.memories(self.pid)[0]['id'],record['id'])
        if os.name!='nt':self.assertEqual(path.stat().st_mode&0o777,0o600)
    def test_backup_refuses_arbitrary_destination_and_symlink_directory(self):
        dashboard=Dashboard(self.store)
        try:
            with self.assertRaises(DashboardError):dashboard.dispatch('POST','/api/backups',{'destination':str(self.root/'overwrite')})
            self.assertFalse((self.root/'overwrite').exists())
            if os.name!='nt':
                (self.db.parent/'backups').symlink_to(self.root,target_is_directory=True)
                with self.assertRaises(PermissionError):dashboard.dispatch('POST','/api/backups',{})
        finally:dashboard.close()

if __name__=='__main__':unittest.main()
