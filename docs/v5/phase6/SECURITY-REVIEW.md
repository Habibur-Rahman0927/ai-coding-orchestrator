# Phase 6 independent security review

The reviewed packaging, authentication, service ownership, backup and update boundaries have no remaining confirmed critical or high-severity finding from this review. This is a scoped source and automated-test assessment, not certification of production readiness or untested platforms. No production code was edited by this reviewer during Phase 6.

## Findings and corrections

- **Packaging evidence exposure — corrected.** The shared `USER_DOCUMENTS` allowlist in `engine/lib/ccx_install.py:31` limits both source installation and archive documentation. Audit/session evidence is excluded. Release metadata explicitly identifies the V5 development workspace as local evaluation only, with `production_ready: false`.
- **Incomplete database-sidecar exclusion — independently reproduced and corrected.** The first fix still copied `workspace.sqlite3-wal`, `workspace.sqlite3-shm` and `runtime.db-journal` into source installations; `.db-journal` also entered archives. Synthetic before evidence is retained in [source payload reproduction](security-sidecar-before.json) and [archive reproduction](security-archive-sidecar-before.json). The shared case-insensitive `runtime_data_path` predicate at `ccx_install.py:40`, used by installer and builder, now rejects those names and uppercase variants. Regression checks cover both paths.
- **Active runtime versus code mutation — reviewed correction.** `ccx_install.workspace_runtime` holds the same engine-scoped lock in shared mode used exclusively by updates/uninstallation. CLI, owned service and workflow execution hold leases; custom database paths cannot change the engine lock identity. Independent workflow concurrency tests passed. The installed service loopback test was skipped in this reviewer sandbox; its separate elevated result must be assessed from the primary release evidence.
- **Backup dashboard boundary — reviewed.** `server.py:98` reaches backup creation through the existing authenticated request handler. Nonempty request bodies, including destination overrides, are rejected. Random destinations reside under the private application backup directory. `Store.backup` refuses existing files and symlink paths, creates mode 0600 files, uses SQLite backup and returns a SHA-256 digest. Tests reopened the backup and verified memory identity and digest without replacing the live database. This is database backup, not project-file or provider credential-store backup.

## Independent verification

| Suite | Result |
| --- | --- |
| Signed update and rollback | 15 passed, 21.373 seconds |
| Phase 6 packaging, backup and runtime | 7 passed, 1 loopback sandbox skip, 1.007 seconds |
| Earlier unchanged browser authentication/onboarding | 9 passed |
| Earlier server suite | 9 passed, 1 skipped |
| Earlier service suite | 3 passed, 5 skipped |

Final logs: [signed update](security-update-final.log), [Phase 6 targeted](security-targeted-final.log). [Reviewed source hashes](security-reviewed-source.json) bind the assessment to files inspected. Commands used `python3 -B -m unittest discover -s tests -p 'test_self_update.py' -v` and the corresponding `test_v5_phase6_*.py` pattern. The earlier update rerun found one stale assertion about an excluded private document; it was corrected to test sensitive content in an included document, preserving rejection coverage.

Signed tests covered tampered artifacts/checksums, unknown signer, absent signatures, unsigned dual opt-in, unsafe archive members and limits, external-input snapshots, update failure recovery, reversible rollback, lock contention and protected state. Only explicitly authorized disposable test signing keys were generated. The suite cleaned its temporary fixture directories; a subsequent check found zero `/tmp/ccx-artifacts-*` directories. No release key, candidate signature, publication, live provider call or commit was created.

## Limits

Exact Host/Origin checks, browser session proof and one-use bootstrap handling were reviewed; the service challenge verifies ownership before transmitting its control bearer to a possibly reused port. Selected loopback tests could not execute within this reviewer sandbox. Native Windows shared-lock/DACL/reparse behavior and macOS were inspected or covered only by existing evidence, not independently executed here. Actual release signer provisioning remains outside this test authorization.

Filename exclusions and recognizable-secret filtering do not guarantee detection of arbitrary secrets disguised in ordinary source files. The application remains a same-user local tool; approved native commands/providers are not an operating-system sandbox. This review does not authorize unrestricted commands, production publication, or a full-provider/platform verification claim.
