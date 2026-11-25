# Independent baseline — 2026-11-25

Entry checkout: clean `main`, `e408e1a5e990066105137913671eebb808c284e0`.
V5 was located in the existing local reference `origin/v5/universal-workspace`,
`c933c04`; no fetch, live provider request, or account modification was needed.
The audit extracted that reference into a disposable source directory.
Phase 1/2 reports were read as claims, not reused as current evidence.

Host: native Ubuntu 24.04.3 x86_64, Python 3.12.3, Git 2.43.0.
Command: `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v`.
Before source changes: **281 discovered/run, 264 passed, 2 failed, 15 skipped,
0 errors, 0 discovery errors; 94.773 seconds; exit 1**.

Both failures were `test_runtime_portable` mocked-session tests. The host checkout/archive
contained group-writable source files; fixture copy2 preserved
those permissions and the immutable runtime correctly refused them. Removing
archive-introduced group/world write permissions (no file-content changes) produced
**15 run, 14 passed, 1 native-Windows skip, 0 failures/errors, 11.800 seconds**.
Original failures remain in evidence; they are not hidden by skips.

Skipped baseline checks: six native Windows tests, three non-Linux tests, and six
loopback-dependent tests. Browser tests are outside normal unittest discovery and
must be run separately. The separate permitted service run executed eight tests
successfully, including a real controlled backend crash with mocked providers.

Evidence: `baseline.log`, `baseline-mode-recheck.log`, `baseline-metadata.json`.
Immutable payload file hashes are in `immutable-payloads.json`.

The delivered checkout reproduced both failures. The test fixture now normalizes
only disposable copied payload permissions, matching the installer security model.
Production runtime checks and immutable source payload modes were not weakened or changed.
Targeted delivered runtime suite: 15 run, 14 passed, one native-Windows skip, 11.759 seconds.
