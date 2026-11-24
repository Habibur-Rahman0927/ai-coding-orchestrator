"""Native Windows Job containment checks; skipped on other operating systems."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'engine/releases/4.3.0/scripts'


@unittest.skipUnless(os.name == 'nt', 'Requires native Windows Job Objects')
class WindowsJobTests(unittest.TestCase):
    def test_force_killed_guardian_terminates_child_and_grandchild(self):
        with tempfile.TemporaryDirectory(prefix='ccx job ü ') as directory:
            root = Path(directory)
            ready, escaped = root / 'ready', root / 'escaped'
            grandchild = ('from pathlib import Path;import time;Path(' + repr(str(ready)) +
                          ').touch();time.sleep(3);Path(' + repr(str(escaped)) + ').touch();time.sleep(30)')
            child = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",' + repr(grandchild) + ']);time.sleep(30)'
            supervisor = ('import sys,time,subprocess;sys.path.insert(0,' + repr(str(SCRIPTS)) +
                          ');from ccx_job import WindowsJob;job=WindowsJob();'
                          'child=job.start([sys.executable,"-c",' + repr(child) +
                          '],stdout=subprocess.PIPE,stderr=subprocess.PIPE);time.sleep(30)')
            guardian = subprocess.Popen([sys.executable, '-c', supervisor], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and guardian.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                if not ready.exists():
                    guardian.kill()
                    out, err = guardian.communicate(timeout=5)
                    self.fail('Contained child never started: ' + repr((out, err)))
                guardian.kill()  # TerminateProcess: no Python finally block can run.
                guardian.communicate(timeout=5)
                time.sleep(3.5)
                self.assertFalse(escaped.exists(), 'Descendant survived forced guardian termination')
            finally:
                if guardian.poll() is None:
                    guardian.kill()
                    guardian.communicate(timeout=5)

    def test_native_start_preserves_unicode_argv_and_streams(self):
        sys.path.insert(0, str(SCRIPTS))
        from ccx_job import WindowsJob
        job = WindowsJob()
        child = None
        try:
            child = job.start([sys.executable, '-X', 'utf8', '-c', 'import sys;print(sys.argv[1]);print("error",file=sys.stderr)',
                               'space ü & literal'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(child.stdout.read().decode().strip(), 'space ü & literal')
            self.assertEqual(child.stderr.read().decode().strip(), 'error')
            self.assertEqual(child.wait(timeout=5), 0)
        finally:
            job.close()
            if child:
                child.stdout.close()
                child.stderr.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
