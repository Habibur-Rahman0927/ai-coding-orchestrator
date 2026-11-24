# Phase 2 independent-session security review

Review date: 2026-11-25. Reviewer: a separate Codex session, not an independent
provider/model. Reviewed actual `auth.py`, `service.py`, `server.py`, `chat.py`,
`onboarding.py`, credential/diagnostic adapters, source diffs and targeted tests.

| Severity | Confirmed defect and cause | Correction | Verification |
|---|---|---|---|
| High | Browser cookies are host-scoped, not port-scoped. Another loopback web service receiving the cookie could exchange it for CSRF through the former unprotected session GET. | Require an additional origin-scoped tab proof on every cookie-authenticated API, including GET/session restore; keep the proof in port-scoped session storage. | Cookie-only state/session GET rejected; valid proof, expiration, replay, logout and rotation pass in `test_v5_phase2.py`. |
| High | Standalone chats accepted a first provider session ID without checking existing chat/workflow ownership. | Claim exact UUID transactionally; reject collisions with other chats and workflow sessions. Workflow engine checks the inverse mapping before resume and save. | Cross-project chat collision test and inverse workflow/chat regression. |
| High | Lazy concurrent Chat construction could mark an active conversation interrupted, permitting a duplicate call. | Eager singleton chat controller; startup reconciliation only after acquiring the service lifetime lock. No constructor-side execution reset. | Interrupted chat is retained, not automatically replayed; singleton source inspected and chat tests pass. |
| Medium | Provider preference replacement could silently drop the selected OS/session credential mode. | Preserve credential mode when omitted by the model form; allow changes only when explicitly supplied. | Credential-mode regression plus real-browser session credential configuration checks. |
| Medium | Credential metadata and model preference updates could diverge around a slow OS prompt. | Merge the latest preferences and credential revision in one SQLite transaction after successful vault operation. | Credential replace/remove and revision invalidation tests. |
| Medium | Read-only dashboard polling could spawn native auth commands if full diagnostics were reused. | Separate cheap summary from explicit diagnostics; five-minute redacted local cache and historical verification fingerprint. | Summary test prohibits subprocess invocation and vault reads. |
| Medium | Browser-session rotation did not by itself revoke the fallback bearer. | Rotate browser credentials and local control/fallback bearer together. | Old bearer and old cookie fail after rotation. |
| Low | Port-only fallback token filenames could refer to stale state from another database. | Key fallback paths by the database's service identity; validate ordinary-file ownership/link properties. | Source inspected; available native service tests are recorded by the owner. |

Provider responses, source files, memory and command output remain untrusted data.
No provider/model tool gains access to credential CRUD or human approval grants.
Local diagnostic commands retain native login state; live diagnostics require
explicit provider/call-count/native-access authorization and use isolated projects.
Error text is classified into fixed categories instead of exposing raw native
stderr. Opaque provider reasoning/history is excluded from visible event callbacks.

Credential tests verify no raw key appears in SQLite, status, ordinary configuration,
subprocess arguments or reports. macOS uses framework calls; Windows uses credential
APIs; Linux uses Secret Service stdin. Actual OS vault CRUD was not performed during
this review, so native vault behavior is not claimed verified. No plaintext fallback
exists. Session-only credentials disappear when the backend process ends.

Remaining boundaries: this is not an OS sandbox for arbitrary approved programs or
native CLI configuration; recognizable-secret filtering cannot detect every secret.
A local user with access to private application files can already access the local
bearer credential. Browser proof guards cross-port cookie disclosure, not a hostile
browser extension or a compromised same-origin script. Bootstrap links are short
lived/single-use; frontend removes their fragment before API requests. Server logs
are disabled and Referrer-Policy is no-referrer. Native Windows/Intel-Mac browser and
vault behavior still require actual platform testing.
