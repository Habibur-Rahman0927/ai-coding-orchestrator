# V5 development candidate scope

This checkout is an unpublished local evaluation candidate. It is not a certified
V5 production or team distribution release. The workspace identifies as
`5.0.0-dev`; existing CLI and engine version metadata remain separate (CLI
`4.1.0`, engine `4.3.0`). Do not publish this modified development tree as another
4.3.0 release. A public release needs a deliberate version change, final artifact
review, trusted signing and explicit publication authorization.

Automated tests cover local SQLite persistence, scoped tools, approvals, mocked
provider workflows, recovery and context retrieval. Synthetic retrieval and
resource measurements are not evidence of real provider token savings. Native
Windows, Intel macOS, other platform acceptance and live Codex/Claude/MiniMax
integration are not certified by this candidate. Historical platform evidence
does not establish acceptance of the current source tree.

For exact results and exclusions use the phase-specific reports under
phase6 (source checkout: `docs/v5/phase6`; omitted from packages), phase5 (source checkout: `docs/v5/phase5`; omitted from packages) and phase4 (source checkout: `docs/v5/phase4`; omitted from packages). The independent
integration review (source checkout: `docs/v5/phase6/INTEGRATION-REVIEW.md`; omitted from packages) records command and lifecycle
limits. Passing an isolated install or mocked workflow does not close paid-call,
native-client, real-project or remote distribution gates.

The existing signed distribution mechanism remains the release mechanism. Test
keys are disposable test fixtures, not authorized release identities. No signing
private key, runtime database, credential, project registry or workflow transcript
belongs in a distributed artifact. Immutable V4 project payloads retain their
own version and integrity boundaries.

Start from the checkout using the [operations guide](OPERATIONS.md). An existing
global launcher may still select an older engine until separately upgraded.
