"""Host-native platform tests; do not pretend mocked OS values verify an OS."""
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import unittest

LIB = Path(__file__).resolve().parents[1] / 'engine/lib'
sys.path.insert(0, str(LIB))
import ccx_platform as platform


class PlatformTests(unittest.TestCase):
    def test_relative_paths(self):
        for name in ('../x', '/x', 'C:/x', 'C:x', r'\\server\share', 'a\\b',
                     'a:b', 'NUL', 'con.txt', 'aux', 'COM1.py', 'LPT9', 'a.', 'a ',
                     'a//b', './a', 'a/../b', 'a\n', 'a?b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                platform.validate_relative(name)
        self.assertEqual(platform.validate_relative('space ü/file.py'), Path('space ü/file.py'))

    def test_owner_permissions_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.write_text('x', encoding='utf-8')
            platform.secure_mode(path, 0o600)
            platform.validate_owner(path)
            platform.validate_permissions(path)
            if not platform.WINDOWS:
                path.chmod(0o666)
                with self.assertRaises(PermissionError):
                    platform.validate_permissions(path)
                link = Path(directory) / 'link'
                link.symlink_to(path)
                self.assertTrue(platform.is_link(link))
                with self.assertRaises(PermissionError):
                    platform.secure_mode(link, 0o600)

    def test_cross_process_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            code = ('import sys;sys.path.insert(0,sys.argv[1]);import ccx_platform as p;'
                    'f=open(sys.argv[2],"a");p.flock(f,p.LOCK_EX|p.LOCK_NB)')
            with path.open('a') as stream:
                platform.flock(stream, platform.LOCK_EX)
                result = subprocess.run([sys.executable, '-B', '-c', code, str(LIB), str(path)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'BlockingIOError', result.stderr)
                platform.flock(stream, platform.LOCK_UN)
                result = subprocess.run([sys.executable, '-B', '-c', code, str(LIB), str(path)], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_lock_excludes_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            code = ('import sys;sys.path.insert(0,sys.argv[1]);import ccx_platform as p;'
                    'f=open(sys.argv[2],"a");p.flock(f,int(sys.argv[3])|p.LOCK_NB)')
            with path.open('a') as stream:
                platform.flock(stream, platform.LOCK_SH)
                for operation, expected in ((platform.LOCK_SH, 0), (platform.LOCK_EX, 1)):
                    result = subprocess.run([sys.executable, '-B', '-c', code, str(LIB), str(path), str(operation)], capture_output=True)
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_secure_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'space ü' / 'nested'
            platform.secure_mkdir(path, parents=True)
            platform.validate_permissions(path)
            platform.secure_mkdir(path, exist_ok=True)
            with self.assertRaises(FileExistsError):
                platform.secure_mkdir(path)

    @unittest.skipUnless(platform.WINDOWS, 'Requires Windows ACL APIs and icacls')
    def test_windows_acl_rejects_public_write_and_restores(self):
        import ccx_windows
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'owned.txt'
            path.write_text('test', encoding='utf-8')
            platform.secure_mode(path, 0o600)
            original = platform.capture_security(path)
            executable = str(Path(ccx_windows.system_directory()) / 'icacls.exe')
            result = subprocess.run([executable, str(path), '/grant', '*S-1-1-0:(W)'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with self.assertRaises(PermissionError):
                platform.validate_permissions(path)
            platform.restore_security(path, original)
            platform.validate_permissions(path)
            self.assertEqual(platform.capture_security(path), original)

    @unittest.skipUnless(platform.WINDOWS, 'Requires native Windows junctions')
    def test_windows_junction_rejected(self):
        import ccx_windows
        with tempfile.TemporaryDirectory() as directory:
            target, junction = Path(directory) / 'target', Path(directory) / 'junction'
            platform.secure_mkdir(target)
            shell = str(Path(ccx_windows.system_directory()) / 'cmd.exe')
            command = '"' + shell + '" /d /v:off /s /c mklink /J "' + str(junction) + '" "' + str(target) + '"'
            result = subprocess.run(command, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                self.assertTrue(platform.is_link(junction))
                with self.assertRaises(PermissionError):
                    platform.validate_owner(junction)
                with self.assertRaises(PermissionError):
                    platform.secure_mkdir(junction / 'nested')
            finally:
                junction.rmdir()

    def test_process_identity(self):
        first = platform.process_info(os.getpid())
        second = platform.process_info(os.getpid())
        self.assertEqual(first['start_ticks'], second['start_ticks'])
        self.assertGreater(first['start_ticks'], 0)
        self.assertGreaterEqual(second['cpu_ticks'], first['cpu_ticks'])
        self.assertTrue(first['command'])

    @unittest.skipIf(platform.WINDOWS, 'Windows containment uses Job Objects')
    def test_owned_group_snapshot(self):
        child = subprocess.Popen([sys.executable, '-B', '-c', 'import time;time.sleep(30)'], start_new_session=True)
        try:
            snapshot = platform.group_snapshot(child.pid)
            self.assertEqual(len(snapshot), 1)
            self.assertTrue(next(iter(snapshot)).startswith(str(child.pid) + ':'))
        finally:
            child.terminate()
            child.wait(timeout=10)
        self.assertEqual(platform.group_snapshot(child.pid), {})

    def test_executable_resolution(self):
        self.assertEqual(Path(platform.resolve_executable(sys.executable)), Path(sys.executable).absolute())
        with self.assertRaises(FileNotFoundError):
            platform.resolve_executable('ccx-command-that-does-not-exist')

    def test_batch_quoting(self):
        value = platform.batch_command('C:/Program Files/tool.cmd', ['a & b', 'x|y', ''], 'C:/Windows/System32/cmd.exe')
        self.assertEqual(value, '"C:/Windows/System32/cmd.exe" /d /v:off /s /c ""C:/Program Files/tool.cmd" "a & b" "x|y" """')
        for arg in ('a"b', '%PATH%', '!name!', 'a\nb', 'a\rb', 'a\0b'):
            with self.subTest(arg=arg), self.assertRaises(ValueError):
                platform.batch_command('tool.cmd', [arg], 'cmd.exe')

    @unittest.skipUnless(platform.WINDOWS, 'Requires real Windows cmd.exe')
    def test_windows_batch_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix='ccx space ü ') as directory:
            script = Path(directory) / 'echo arguments.cmd'
            script.write_bytes(b'@echo %1\r\n')
            for argument in ('hello world', 'a & b', 'x|y', 'x<y>z', '(x)', 'x^y'):
                command = platform.command_argv([str(script), argument])
                result = subprocess.run(command, capture_output=True, text=True, shell=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '"' + argument + '"')

    def test_security_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'owned'
            path.write_text('test', encoding='utf-8')
            original = platform.capture_security(path)
            platform.secure_mode(path, 0o600)
            platform.restore_security(path, original)
            self.assertEqual(platform.capture_security(path), original)

    def test_environment(self):
        info = platform.environment_info()
        self.assertTrue(info['os'])
        self.assertTrue(info['architecture'])
        self.assertTrue(platform.state_root().is_absolute())


if __name__ == '__main__':
    unittest.main()
