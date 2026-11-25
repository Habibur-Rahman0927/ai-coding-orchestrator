"""Actual approved subprocess cancellation; no live providers."""
import sys
import threading
import time
import unittest
from unittest import mock
import test_v5_workflows as fixtures


class CancellationTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    tearDown = fixtures.WorkflowTests.tearDown
    create = fixtures.WorkflowTests.create
    authorize = fixtures.WorkflowTests.authorize

    def test_already_cancelled_tool_does_not_spawn(self):
        from ccx_workspace.tools import ScopedTools
        cancellation = threading.Event()
        cancellation.set()
        tools = ScopedTools(self.project, allowed_operations=['run_command'],
                            approved_commands={'test': [sys.executable, '-c', 'pass']}, cancel_event=cancellation)
        with mock.patch('ccx_workspace.tools.subprocess.Popen') as spawn:
            with self.assertRaises(InterruptedError):
                tools.execute('run_command', {'name': 'test'})
        spawn.assert_not_called()

    def _interruption(self, operation, tool_call=False):
        identifier = self.create()
        self.authorize(identifier, test=False)
        started = self.base / 'started'
        late = self.base / 'after_interrupt'
        second = self.base / 'second_command'
        code = ('from pathlib import Path; import time; '
                'Path(%r).write_text("started"); time.sleep(4); Path(%r).write_text("late")'
                % (str(started), str(late)))
        self.engine.approve(identifier, 'command', {'name': 'slow', 'argv': [sys.executable, '-c', code], 'timeout': 15})
        self.engine.approve(identifier, 'command', {'name': 'second', 'argv': [sys.executable, '-c',
            'from pathlib import Path; Path(%r).write_text("second")' % str(second)], 'timeout': 15})
        result = []
        registry = fixtures.MockRegistry()
        if tool_call:
            invoke = registry.invoke
            def invoke_tool(provider, request):
                response = invoke(provider, request)
                if request['role'] == 'executor':
                    response.update(status='tool_calls', tool_calls=[{'id': 'approved-command',
                        'name': 'run_command', 'arguments': {'name': 'slow'}}])
                return response
            registry.invoke = invoke_tool
        worker = threading.Thread(target=lambda: result.append(self.engine.run(identifier, registry)))
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(started.exists(), 'approved child never started')
            getattr(self.engine, operation)(identifier)
            worker.join(10)
            self.assertFalse(worker.is_alive(), 'worker did not finish cancellation cleanup')
            self.assertFalse(late.exists(), 'owned child continued after interruption')
            self.assertFalse(second.exists(), 'another approved command dispatched after interruption')
            self.assertEqual(result[0]['status'], 'CANCELLED' if operation == 'cancel' else 'PAUSED')
        finally:
            worker.join(20)

    def test_cancel_terminates_owned_command_and_prevents_next_dispatch(self):
        self._interruption('cancel')

    def test_pause_terminates_owned_command_and_prevents_next_dispatch(self):
        self._interruption('pause')

    def test_cancel_terminates_provider_requested_approved_command(self):
        self._interruption('cancel', tool_call=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
