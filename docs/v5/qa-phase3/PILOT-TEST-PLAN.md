# Controlled pilot gate and procedure

**Do not start a client-project pilot yet.** No release is promoted or published.

1. Review the Phase 3 source diff and final regression evidence on the V5 branch.
2. Authorize or supply browser tooling and permitted browser process/socket execution;
   rerun both actual browser suites with fresh
   profiles and deterministic providers. Resolve any failure before proceeding.
3. Choose pilot providers/models and an explicit maximum paid usage budget. Use an
   isolated synthetic Git repo first, with narrow sharing/native-access/command grants.
4. Run backend correction, context restart, reviewer-detected defect, authorized
   provider failover, cancellation and crash reconciliation. Record actual session IDs,
   revision-bound tests/review, provider usage and every human intervention.
5. Run matched repeated token A/B workloads; include all roles and preserve acceptance
   quality. No savings claim until provider-reported evidence supports it.
6. Verify the pilot's native OS credential facility and installation lifecycle. Additional
   OS/provider combinations stay explicitly unverified rather than blocking a narrower
   approved pilot indefinitely.
7. Obtain explicit authorization for the selected real project only after high/critical
   pilot-path findings are resolved and browser/provider acceptance passes.

Rollback/recovery: stop the owned service; retain an integrity-checked workspace DB
backup and exact engine/source revision before testing. Restore into a separate private
path first and verify integrity; do not overwrite live history. For uncertain actions,
inspect filesystem effects and session/action records before approving any retry.
Use existing engine rollback/project backup procedures in docs/MIGRATION-AND-RECOVERY.md
and docs/TEAM-UPDATE.md. Keep global engine updates separate from project integrations.
Never reset native AI sessions or automatically replay unknown side effects.
