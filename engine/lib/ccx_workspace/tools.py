"""Small, explicitly authorized project tools; model output grants no authority."""
import hashlib
import fnmatch
import json
import os
from pathlib import Path
import re
import queue
import threading
import time
import stat
import subprocess
import sys
import tempfile

import ccx_platform as platform

OPERATIONS = frozenset(('list_directory', 'read_file', 'search', 'patch', 'run_command', 'git_diff'))
DENIED_PARTS = frozenset(('.git', '.ssh', '.aws', '.codex', '.claude', '.ccx', 'node_modules', '__pycache__'))
SECRET_NAME = re.compile(r'(?:secret|credential|token|private.?key)|^(?:\.env|id_rsa|id_ed25519)|\.(?:pem|key|p12|pfx)$', re.I)
from .security import SECRET_CONTENT, read_regular_bytes
MAX_FILE = 1024 * 1024
MAX_OUTPUT = 65536


def controller_path():
    path = Path(__file__).resolve().parents[2] / 'releases/4.3.0/scripts/recovery-controller.py'
    if not path.is_file():
        raise RuntimeError('Verified process supervisor unavailable')
    return path


def supervised_command(argv, timeout):
    return [sys.executable, str(controller_path()), '--timeout', str(max(1, int(timeout))),
            '--heartbeat', '60', '--retries', '0', '--', *argv]


def safe_name(path):
    return not any(part.casefold() in DENIED_PARTS or SECRET_NAME.search(part) for part in Path(path).parts)


class ScopedTools:
    def __init__(self, project, allowed_operations=(), approved_commands=None, exclusions=(), cancel_event=None):
        original = Path(project).absolute()
        if any(platform.is_link(p) for p in (original,) + tuple(original.parents)):
            raise PermissionError('Project link/reparse point refused')
        self.project = original.resolve(strict=True)
        if not self.project.is_dir():
            raise ValueError('Project must be a directory')
        platform.validate_permissions(self.project, mask=0o002)
        self.cancel_event = cancel_event
        self.event_callback = None
        self.allowed = frozenset(allowed_operations)
        self.approved_commands = dict(approved_commands or {})
        self.exclusions = tuple(exclusions)
        if not all(isinstance(pattern, str) for pattern in self.exclusions):
            raise ValueError('Project exclusions must be patterns')

    def _authorize(self, operation):
        if operation not in OPERATIONS or operation not in self.allowed:
            raise PermissionError('Operation requires explicit authorization: ' + operation)

    def _path(self, relative, allow_root=False):
        if relative == '.' and allow_root:
            return self.project
        rel = platform.validate_relative(relative)
        if not safe_name(rel) or any(fnmatch.fnmatch(rel.as_posix(), pattern) for pattern in self.exclusions):
            raise PermissionError('Sensitive or excluded project path')
        ignored = subprocess.run(['git', '-C', str(self.project), 'check-ignore', '--quiet', '--no-index', '--', rel.as_posix()],
                                 capture_output=True, timeout=10)
        if ignored.returncode == 0:
            raise PermissionError('Git-ignored project path')
        if ignored.returncode != 1:
            raise PermissionError('Project Git exclusion policy unavailable')
        path = self.project
        for component in rel.parts:
            path = path / component
            if platform.is_link(path):
                raise PermissionError('Link/reparse point refused')
            if path.exists():
                platform.validate_permissions(path, mask=0o002)
        if self.project not in path.resolve().parents:
            raise PermissionError('Path escapes selected project')
        return path

    def _read(self, path):
        data = read_regular_bytes(path, MAX_FILE)
        text = data.decode('utf-8')
        if SECRET_CONTENT.search(text):
            raise PermissionError('Potential secret content refused')
        return data, text

    def _files(self):
        count = 0
        for folder, directories, files in os.walk(str(self.project), followlinks=False):
            base = Path(folder)
            directories[:] = [name for name in sorted(directories)
                              if safe_name(base.relative_to(self.project) / name)
                              and not platform.is_link(base / name)]
            for name in sorted(files):
                rel = (base / name).relative_to(self.project)
                if safe_name(rel) and not platform.is_link(base / name):
                    count += 1
                    if count > 1000:
                        return
                    try:
                        yield self._path(rel)
                    except PermissionError:
                        continue

    def execute(self, name, arguments):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise InterruptedError("Workflow interrupted before tool dispatch")
        self._authorize(name)
        if not isinstance(arguments, dict):
            raise ValueError('Tool arguments must be an object')
        expected = {'list_directory': {'path'}, 'read_file': {'path'},
                    'search': {'query'}, 'patch': {'path', 'sha256', 'old', 'new'},
                    'run_command': {'name'}, 'git_diff': set()}[name]
        if set(arguments) - expected:
            raise ValueError('Unexpected tool arguments')
        if name == 'list_directory':
            directory = self._path(arguments.get('path', '.'), allow_root=True)
            entries = []
            for path in sorted(directory.iterdir()):
                if safe_name(path.relative_to(self.project)) and not platform.is_link(path):
                    try:
                        self._path(path.relative_to(self.project))
                    except PermissionError:
                        continue
                    entries.append({'name': path.name, 'directory': path.is_dir()})
                if len(entries) >= 1000:
                    break
            return {'entries': entries}
        if name == 'read_file':
            data, text = self._read(self._path(arguments['path']))
            return {'text': text[:MAX_OUTPUT], 'truncated': len(text) > MAX_OUTPUT,
                    'sha256': hashlib.sha256(data).hexdigest()}
        if name == 'search':
            query = arguments['query']
            if not isinstance(query, str) or not 1 <= len(query) <= 256:
                raise ValueError('Search requires a bounded literal query')
            hits = []
            for path in self._files():
                try:
                    _, text = self._read(path)
                except (PermissionError, UnicodeError, ValueError):
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if query.casefold() in line.casefold():
                        hits.append({'path': path.relative_to(self.project).as_posix(),
                                     'line': number, 'text': line[:300]})
                        if len(hits) >= 100:
                            return {'matches': hits, 'truncated': True}
            return {'matches': hits, 'truncated': False}
        if name == 'patch':
            path = self._path(arguments['path'])
            creating = arguments['sha256'] == 'absent'
            if creating:
                if path.exists() or platform.is_link(path) or arguments['old'] != '':
                    raise ValueError('Creation requires absent path and empty old text')
                data, text, security, mode = None, '', None, 0o600
            else:
                data, text = self._read(path)
                if hashlib.sha256(data).hexdigest() != arguments['sha256']:
                    raise ValueError('Patch rejected: file changed since review')
                security = platform.capture_security(path)
                mode = stat.S_IMODE(path.stat().st_mode)
            old, new = arguments['old'], arguments['new']
            if not isinstance(old, str) or (not old and not creating) or not isinstance(new, str) or len(new) > MAX_FILE:
                raise ValueError('Patch requires bounded old/new text')
            if not creating and text.count(old) != 1:
                raise ValueError('Patch context must match exactly once')
            updated = (new if creating else text.replace(old, new, 1)).encode('utf-8')
            if len(updated) > MAX_FILE or SECRET_CONTENT.search(updated.decode('utf-8')):
                raise PermissionError('Patch size or secret-content policy rejected')
            if creating:
                platform.secure_mkdir(path.parent, mode=0o700, parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.ccx-edit-', dir=str(path.parent))
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                platform.secure_mode(Path(temporary), mode)
                if security is not None:
                    platform.restore_security(Path(temporary), security)
                target = self._path(arguments['path'])
                if creating:
                    # Atomic no-overwrite publication: a concurrent destination,
                    # including a planted link, makes link() fail rather than replace it.
                    os.link(temporary, target)
                else:
                    if target.read_bytes() != data:
                        raise ValueError('Patch rejected: concurrent file change')
                    os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {'sha256': hashlib.sha256(updated).hexdigest(), 'changed': True, 'created': creating}
        if name == 'run_command':
            key = arguments.get('name')
            if not isinstance(key, str) or key not in self.approved_commands:
                raise PermissionError('Command has no explicit user approval')
            specification = self.approved_commands[key]
            argv = specification.get('argv') if isinstance(specification, dict) else specification
            timeout = specification.get('timeout', 60) if isinstance(specification, dict) else 60
            if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
                raise ValueError('Approved command must be an argv list')
            cwd = specification.get('cwd', '.') if isinstance(specification, dict) else '.'
            return self._run(argv, timeout, cwd)
        if name == 'git_diff':
            # Enumerate only permitted files; exclude deleted paths because their
            # old contents cannot be checked before git returns them.
            permitted = []
            for path in self._files():
                try:
                    self._read(path)
                except (PermissionError, UnicodeError, ValueError):
                    continue
                permitted.append(path.relative_to(self.project).as_posix())
            if not permitted:
                return {'output': '', 'exit_code': 0, 'scope': 'existing permitted files only'}
            result = self._run(['git', '--no-pager', 'diff', '--no-ext-diff', '--no-textconv', '--', *permitted], 30)
            if SECRET_CONTENT.search(result['output']):
                raise PermissionError('Potential historical secret content refused')
            result['scope'] = 'existing permitted files only; excludes deleted/sensitive files'
            return result

    def _run(self, argv, timeout, cwd='.'):
        if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 3600:
            raise ValueError('Invalid approved command timeout')
        directory = self._path(cwd, allow_root=True)
        if not directory.is_dir():
            raise ValueError('Approved command working directory unavailable')
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise InterruptedError('Workflow interrupted before command dispatch')
        process = subprocess.Popen(supervised_command(argv, timeout), cwd=str(directory),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        chunks, stop = queue.Queue(maxsize=16), threading.Event()
        def read():
            try:
                while not stop.is_set():
                    data = os.read(process.stdout.fileno(), 65536)
                    if not data:
                        break
                    while not stop.is_set():
                        try:
                            chunks.put(data, timeout=.1)
                            break
                        except queue.Full:
                            pass
            finally:
                while not stop.is_set():
                    try:
                        chunks.put(None, timeout=.1)
                        break
                    except queue.Full:
                        pass
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        output, total = bytearray(), 0
        last_event, emitted_bytes = 0, -1
        def flush_output():
            nonlocal last_event, emitted_bytes
            if self.event_callback and len(output) != emitted_bytes and time.monotonic()-last_event >= .2:
                text = bytes(output).decode('utf-8', errors='replace')
                if not SECRET_CONTENT.search(text):
                    self.event_callback({'type':'text','phase':'running','label':'Command output','detail':json.dumps(argv)[:1000],'text':text[-12000:]})
                last_event, emitted_bytes = time.monotonic(), len(output)
        deadline = time.monotonic() + timeout + 30
        try:
            while True:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    # The retained supervisor owns the child tree and performs
                    # identity-safe cleanup on termination; never kill by name.
                    raise InterruptedError('Workflow interrupted during approved command')
                if time.monotonic() > deadline:
                    raise RuntimeError('Approved command supervisor exceeded cleanup deadline')
                try:
                    chunk = chunks.get(timeout=.1)
                except queue.Empty:
                    flush_output()
                    continue
                if chunk is None:
                    break
                total += len(chunk)
                output.extend(chunk[:max(0, MAX_OUTPUT-len(output))])
                flush_output()
            code = process.wait(timeout=10)
        finally:
            stop.set()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('Approved command cleanup could not be confirmed')
            process.stdout.close()
            reader.join(timeout=1)
        text = bytes(output).decode('utf-8', errors='replace')
        if SECRET_CONTENT.search(text):
            raise PermissionError('Potential command-output secret refused')
        return {'exit_code': code, 'output': text, 'truncated': total > MAX_OUTPUT}


def tool_definitions(allowed_operations):
    fields = {'list_directory': {'path': {'type': 'string'}}, 'read_file': {'path': {'type': 'string'}},
              'search': {'query': {'type': 'string'}},
              'patch': {name: {'type': 'string'} for name in ('path', 'sha256', 'old', 'new')},
              'run_command': {'name': {'type': 'string'}}, 'git_diff': {}}
    if 'agent_commands' in allowed_operations:
        fields['run_command'] = {'name':{'type':'string'}, 'argv':{'type':'array','items':{'type':'string'}}, 'cwd':{'type':'string'}, 'timeout':{'type':'integer'}}
    return [{'type': 'function', 'function': {'name': name,
             'description': 'Explicitly authorized project operation: ' + name,
             'parameters': {'type': 'object', 'properties': fields[name],
                            'required': list(fields[name]), 'additionalProperties': False}}}
            for name in sorted(set(allowed_operations) & OPERATIONS)]
