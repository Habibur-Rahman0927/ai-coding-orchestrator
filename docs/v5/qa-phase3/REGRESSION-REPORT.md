# Final regression

Delivery branch `v5/phase3-qa`, baseline `c933c04`; no commit/push/publication.
Final command: `PYTHONDONTWRITEBYTECODE=1 python3 -B tools/run_phase3_qa.py --output /tmp/ccx-phase3-final-complete.json --source-revision c933c04-plus-phase3-final`.
The suite ran in the actual delivered checkout with loopback permission.

**334 run, 325 passed, 9 native-platform skips, 0 failures, 0 errors; 126.695 seconds; exit 0.**
Discovered: 334; discovery errors: 0.
Added 53 tests across seven modules, plus corrected a host-dependent runtime fixture.
The nine skips require native Windows or a non-Linux host. No confirmed-defect test is skipped.

Before-fix failures are retained. Intermediate 314-test snapshot passed after archive
mode normalization; 332/334-test delivered runs exposed the same source-mode fixture
issue and failed twice. The fixture now normalizes only disposable copies, preserving
runtime permission enforcement. The final run above supersedes those intermediate runs.

Per-test outcomes/durations: final.json. Detailed log: final.log. Exact changed-file
hashes: changed-files.json. Reviewed patch: phase3-hardening.patch. Immutable V4 bytes
are unchanged (immutable-payloads.json). Extra delivery distribution checks:21 passed;
repository hygiene:3 passed. Browser checks, if any, are reported separately and are
not included in unittest discovery. All upstream provider responses here are mocked.

Independent contexts reviewed security/output, context/cancellation and storage fixes.
A real killed SQLite writer, actual page exhaustion and subprocess side effects were
observed. No machine reboot or independent paid-provider review is claimed.
