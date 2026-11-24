# V5 architecture decisions

Baseline: clean main at e408e1a, archived before creating v5/universal-workspace.
V4.1 verified and V4.3 candidate payloads are immutable during V5 development.
Checked-in evidence reports Mac local tests; Linux and authenticated provider
verification claims in the request are not established by those reports.

1. Add a separate ccx_workspace package and `orchestrator workspace` command.
   Keep V4 engine version, installed project scripts and histories unchanged.
2. Use SQLite transactions, versioned schema, scoped IDs and explicit project
   registration. Durable universal workflow IDs never substitute provider IDs.
3. Index Git-approved files incrementally, with source hashes and local FTS.
   Exclude secrets, dependencies, binaries and reparse points before reading.
   Python ast supplies symbols/dependencies without a Tree-sitter dependency;
   other languages retain exact text search. Embeddings are not required.
4. Build context from critical requirements and ranked, deduplicated excerpts.
   Fail when critical requirements exceed budget. Report byte/estimated token
   metrics separately from provider-reported usage. No unsupported cost claims.
5. Providers produce normalized events. The engine owns delegation, permissions,
   budgets, approval, evidence, recovery and completion. All model text is data.
   Native CLI sandbox breadth is a separately authorized capability, not assumed
   equivalent to the core's filtered tools. No automatic billable calls.
6. Start with a standard-library loopback API and buildless dashboard instead of
   introducing FastAPI/React/npm distribution requirements. Require auth and
   origin/Host checks; no public bind, cloud hosting or mandatory services.
7. Phase modules and deterministic tests remain individually reviewable without
   commits. Live evidence and mocked evidence are recorded separately. Additional
   OS/provider checks remain pending when the environment cannot run them.
