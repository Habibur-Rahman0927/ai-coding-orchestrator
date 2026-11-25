#!/usr/bin/env python3
"""Run offline unittest discovery with explicit machine-readable outcomes.

Browser tests are a separate suite. This command does not authorize live providers.
"""
import argparse
import json
from pathlib import Path
import platform
import sys
import time
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
    def startTest(self, test):
        self.started = time.monotonic()
        super().startTest(test)
    def record(self, test, outcome, reason=None):
        self.records.append({'id': test.id(), 'outcome': outcome,
                             'seconds': round(time.monotonic()-self.started, 6), 'reason': reason})
    def addSuccess(self, test):
        super().addSuccess(test); self.record(test, 'passed')
    def addSkip(self, test, reason):
        super().addSkip(test, reason); self.record(test, 'skipped', reason)
    def addFailure(self, test, error):
        super().addFailure(test, error); self.record(test, 'failed', error[0].__name__)
    def addError(self, test, error):
        super().addError(test, error); self.record(test, 'error', error[0].__name__)
    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            self.record(subtest, 'failed' if issubclass(error[0], test.failureException) else 'error', error[0].__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--pattern', default='test*.py')
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT/'tests'), pattern=args.pattern)
    discovered = suite.countTestCases()
    start = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    report = {'source_revision': args.source_revision, 'pattern': args.pattern,
              'platform': platform.platform(), 'python': platform.python_version(),
              'discovered': discovered, 'executed_including_skips': result.testsRun,
              'passed': sum(r['outcome']=='passed' for r in result.records),
              'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'discovery_errors': len(loader.errors),
              'duration_seconds': round(time.monotonic()-start, 6),
              'exit_code': 0 if result.wasSuccessful() else 1, 'tests': result.records,
              'scope': 'Offline contracts and local effects; not live provider verification'}
    Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
