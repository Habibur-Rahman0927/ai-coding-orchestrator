# Measured local performance

Single native Linux sample, real local service/SQLite and mocked providers:
startup to bound backend 52.370 ms; one-second idle process CPU 0.016%; whole-process
peak RSS 31,907,840 bytes; initial 101-file index 48.075 ms; repeated index 20.783 ms
with zero source bytes read; median context 7.745 ms; median static HTTP 0.787 ms.
A mock workflow with one correction completed in 1106.683 ms; database growth 20,480 bytes.
These are observations, not before/after improvement or live-provider latency claims.

Independent 10/100/1000-file fixture: initial index approximately 10.9/42.7/454.2 ms.
Repeat reads zero source bytes; one-file edit reads 35 bytes and updates one document.
Metadata traversal still scales with project size. Exact raw values: `scale.json`.

No long-duration leak/soak claim, cold/warm distribution, 50k-file project benchmark,
large workflow history throughput or browser responsiveness measurement. The inherited
measurement script's generic browser note does not mean browser tests ran in Phase 3.

Reproduce with tools/measure_workspace.py and the supplied measure-scale.py. Loopback
permission is required for the service measurement. No actual client repo is used.

Bounded repeated-workflow stress: 12 workflows, four corrections, 32 mocked calls,
48 durable actions and 520,192 bytes database growth in 2.889 seconds. A quiet real
command completed in 1.580 seconds. This is not a long-duration leak test. See stress.json.
