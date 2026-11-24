# Baseline audit — 2026-11-25

The worktree was clean on `main` at `e408e1a` before implementation. The existing
HEAD was archived outside the repository, then branch `v5/universal-workspace`
was created. No prior changes were discarded. No commits were made by this task.

| Existing component | V5 treatment |
|---|---|
| `engine/orchestrator.py` project registry and management CLI | Add one `workspace` command; preserve existing command behavior |
| `engine/releases/4.1.0` verified project payload | Immutable; unchanged |
| `engine/releases/4.3.0` cross-platform candidate payload | Immutable during V5; reuse its owned-process supervisor |
| Task state, recovery, watchdog, context/usage/completion guards in project scripts | Retained for V4; V5 uses a separate durable workflow database |
| `ccx_platform.py`, `ccx_windows.py` | Reuse path, ownership, permission and native-platform primitives |
| `ccx_install.py`, `ccx_distribution.py` | Reuse installation, artifact validation, update/backup and signature machinery |
| `ccx_migration.py` | Retain existing V4 migration; V5 knowledge import is separate and read-only |
| Existing authentication and saved provider settings | Not modified; native CLIs remain externally configured |

Before modifications, the actual macOS ARM64 baseline command was:

```sh
ORCH_TEST_RELEASE=4.3.0 python3 -B -m unittest discover -s tests -v
```

It ran **152 tests: 145 passed, 7 skipped**, in 139.720 seconds, with exit code 0.
The historical checked-in cross-platform report covers a different earlier run;
it does not establish the latest Linux/live-provider success stated in the request.
Those assertions were not copied into new verification claims.

V4.3 stabilization and V5 implementation remain separate. A single V5 development
branch contains modular source/tests/docs rather than mutations of installed
project payloads. Client projects, EWU, provider authentication, runtime history,
and saved provider defaults were outside the modification scope.
