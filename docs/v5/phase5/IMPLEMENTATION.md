# Evidence-based implementation

The Phase 4 checkpoint remains intact. Production changes are limited to the existing
knowledge store, provider usage normalization, workflow accounting/learning, API context
options and existing dashboard. No remote embedding service, parser dependency, vector
database, background watcher or new agent hierarchy was added.

## Retrieval and indexing

Baseline failures were reproduced before correction. Search previously limited FTS and
fallback candidates to the first 100 rows before useful ranking; filenames were not
searchable as paths. Retrieval now combines ranked FTS with bounded path/symbol/dependency
metadata candidates, with deterministic ties and a keyword fallback. Exact path matches
use path boundaries, so `a.py` does not masquerade as an exact match for `data.py`.

Git exclusion policy is freshly checked once per candidate batch. Contents are still
opened through the existing permission/link/secret-aware reader and compared with source
hashes; cached context never bypasses freshness or authorization. Root/user constraints
remain mandatory and overflow fails explicitly. Separated matching symbols produce
separate line-numbered windows, not an unsupported semantic summary. Exact duplicates
are removed only after their snippet fits; original evidence remains in the index.

An optional role prioritizes already relevant candidates: planner architecture/project
records, executor code, reviewer test/verification references, and correction error
observations. Required instructions precede every role. This is a deterministic preference,
not a claim that all retrieved knowledge is sufficient for arbitrary model reasoning.

A touched file with an unchanged content hash updates its filesystem signature without
reparsing or rewriting the search document. Ordinary unchanged files already skipped reads
in Phase 4; no new credit is claimed for that existing optimization. Git discovery still
enumerates the approved project, rather than relying on a lossy filesystem watcher.
Deletion/rename/branch/exclusion checks remain covered by the preserved regression suite.
FTS availability changes use a transactional dirty marker and rebuild, including the case
where an existing FTS index became stale while SQLite ran without FTS5.

## Memory lifecycle and verified solutions

Exact duplicate active memory submissions reuse their record under an immediate SQLite
transaction. Identity includes project, scope, kind, source/hash, verification time,
confidence, expiry and supersession. Distinct hypotheses/evidence are never merged;
expiry is not renewed; superseded/deleted historical content is not revived. No historical
record was deleted to obtain a storage improvement.

A completed correction now supersedes its unresolved observation with a snapshot-bound
verification receipt. It links the original observation and the engine's verification
memory; the original record remains intact. It states only that completion gates passed,
not that an earlier model diagnosis became a proven root cause. Changed source invalidates
reusability; incomplete workflows retain unverified observations. Independent interruption
checks verified that a receipt written before interrupted completion stays stale and that
explicit resume completes without extra provider calls or duplicate resolution records.

Error signatures use deterministic exact normalized text, not fuzzy auto-application.
Architecture rewriting, semantic contradiction resolution, universal error root-cause
inference and automatic skill promotion were not added. Existing scoped kinds and source
records support the tested lifecycle; they do not implement every possible taxonomy.

## Automation and visibility

Existing `standard` and `single_task` policies remain explicit user choices. The latter
skips only planning, retaining implementation, independent review and actual test gates.
No provider ranking or automatic switch was invented. Synthetic policy measurements
quantify the existing call-count difference without removing verification.

Context Inspector now shows byte/token estimates, role selection, source lines and retrieval
reasons, with exclusions and exact package details available. Activity shows reported usage
by role, prepared context bytes, correction/approval counts and explicit unknowns. No
HTML from memory is interpreted; the existing text-node renderer remains in use.

Usage/accounting changes and official provider documentation are described separately in
[PROVIDER-AND-SESSION-BOUNDARIES.md](PROVIDER-AND-SESSION-BOUNDARIES.md). Request-envelope
and benchmark-contract changes do not alter provider permissions or imply a billing cap.
