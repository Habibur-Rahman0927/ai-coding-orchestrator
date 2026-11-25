# Test quality and evidence limits

The initial source suite discovered 281 tests, not the 279 in the Phase 2 report.
Unittest discovery does not recurse into tests/browser because it is not an ordinary
importable test package; browser results must be reported separately. Baseline socket
skips were explicit but hid six important runtime checks in a restricted environment.
Permitted loopback runs execute those checks rather than changing their assertions.

Two runtime tests failed in checkout/archive environments with group-writable source.
Their fixture copied permissions with copytree/copy2 and never reached the intended
session assertions. Only disposable copies now lose group/world write bits. Actual
installation writes payload mode0700; immutable payload source and integrity checks
remain untouched. Reproductions and the 15-case corrected runtime run are retained.

New safety tests assert real effects: no late child write after cancellation, no FIFO
hang under controlled replacement, no credential in SQLite, no cross-project result,
no old memory revival, unchanged future-version DB bytes, and rollback after actual
SQLite page exhaustion. Test commands and subprocesses are real; provider language
outputs remain mocks. Existing six-direction routing is a single test with six
subcases, not six proven live integrations. Correction fixtures intentionally script
review rejection; they do not prove actual model judgment.

Before-fix failures substitute for useful targeted mutation evidence: tests fail on
the uncorrected implementation and pass with controls restored. No production safety
control was disabled for testing. Independent contexts reviewed corrections using the
same assistant model; no independent paid provider was launched.

Remaining limits: no multi-day soak, exhaustive fault-state enumeration, model-quality
assessment or blanket flake-free claim. Timing fixtures use bounded deadlines and
explicit markers/barriers; host scheduling can still affect runtime tests. All test
credentials/projects/browser profiles are synthetic/disposable. Existing OS-vault APIs
remain mocked; CLI discovery/help does not authenticate or call a provider.
