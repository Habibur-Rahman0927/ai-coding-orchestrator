# Phase 7 developer experience result

2026-11-25 · branch `v5/phase7-developer-experience` · uncommitted source based on
`c933c04063b16d6c47b430f512fadd26b9d1e0a1` with preserved Phase 3–6 work.

**Working local UX improvements and an unsigned evaluation candidate are prepared.
Full developer-experience, team-pilot and production readiness remain incomplete.**
No live provider usage, real client-project changes, native account/session reset,
dependency installation, commit, push, deployment or publication occurred.

## What changed and what passed

- Six mandatory onboarding screens became two: choose one agent and optionally
  register a project. Advanced role/model/budget settings remain accessible.
- `orchestrator open` starts or reuses a background backend and opens the existing
  secure browser bootstrap. Repeated installed `open` reused the same PID.
- Chat is the landing view. Solo creates a local draft from the instruction,
  without a required conversation title or extra plan-confirmation click.
  Sending still requires explicit sharing/usage consent.
- Collaborate and Auto produce inspectable, bounded proposals. Four presets retain
  existing tests, review and spending/permission gates. Auto follows the chosen
  preset, not invented task rankings. No proposal executes a provider.
- Recent/favorite/searchable projects, last-project restoration, per-project agent
  preferences and filtered conversations improve continuation. Async view guards
  prevent delayed chat/project responses from populating another project.
- Saved-work inspection, concise verified-result evidence, in-product Help, grouped
  advanced navigation, actionable disconnect errors and persisted appearance work.

Full regression: **395 discovered/executed, 386 passed, 9 native-host skips, zero
failures/errors/discovery errors**, 161.899 seconds. Eleven Phase 7 tests cover
proposal permissions, natural-language boundaries, unavailable providers, atomic
preferences, simultaneous updates, continuation and real HTTP authentication/
Origin/session-proof enforcement. [Results](FINAL-REGRESSION.json),
[log](FINAL-REGRESSION.log), [focused tests](EXPERIENCE-TESTS.log).

Actual sandboxed Chrome 144: **15/15 dashboard groups**, 43.271 seconds, using
offline provider fixtures but real HTTP/SQLite, local patch/command effects and
rendered controls. **3/3 lifecycle groups** passed after installing the exact
checksum/manifest-verified archive. These are not live-model or real-user results.
[Dashboard evidence](BROWSER-FINAL.json), [archive browser](ARTIFACT-BROWSER.json).

All **38 immutable V4 payload files are unchanged** against the verified 425-file
[entry checkpoint](ENTRY-STATE.json): [payload verification](IMMUTABLE-PAYLOADS.json).

## Measured interaction and performance results

| Scenario / measurement | Before | After | Interpretation |
|---|---:|---:|---|
| Onboarding screens | 6 | 2 | Optional connection controls retained |
| Onboarding button clicks | 8 | 4 | Same automated provider-choice/project-registration scenario |
| Onboarding field changes | 4 | 2 | Three role choices reduced to one preferred agent |
| Browser onboarding duration | 1.521 s | 0.955 s | One automated sample each; not human completion time or statistical speedup |
| Ordinary background launch | `start --background` | `open` | Command count stays one; one required option removed |
| Primary navigation destinations | 11 | 7 | Five secondary destinations remain under Advanced tools; Help added |
| Current archive installation | — | 0.237 s | Disposable Linux prefix |
| Empty installed backend startup | — | 0.300 s | One current-source sample |
| Idle RSS, start/end | — | 39,096,320 / 39,096,320 bytes | Five-second empty-backend sample |
| Idle CPU ticks consumed | — | 0 observed | OS accounting resolution; not a zero-CPU guarantee |
| Empty database / sidecars | — | 196,608 / 0 bytes | Point-in-time measurement |
| Health-based stop | — | 0.005 s | No running backend remained |

Raw [before browser](BROWSER-BEFORE.json), [after browser](BROWSER-FINAL.json),
[resources](RESOURCE.json). Field changes/clicks count automation helper actions,
not developer cognitive effort. No invented usability score, real human time,
approval reduction, manual prompt-transfer reduction or real token savings is
reported. Other browser groups retain exact elapsed times but do not isolate
rendering, project-switch latency or provider response time from all other work.
Phase 5 indexing/context/active-soak measurements remain historical evidence, not
a new Phase 7 sustained-resource certification.

## First-time and existing-developer acceptance

The clean browser fixture completed secure bootstrap, provider selection, disposable
session-only credential controls, repository preview/index, explicit chat consent
and streaming, collaborative preset creation, bounded approvals, actual local
tests/review/completion, reload, previous-work inspection, backup/recovered-copy
verification, two-project isolation, appearance/Help, logout/expiry and a real
backend disconnection. A delayed actual chat-list response could not contaminate
the newly selected project's view. An active workflow disabled duplicate Run.

The separate archive installation used a disposable prefix/database, repeated
`open` without duplicate processes, completed onboarding, restarted with knowledge
intact, then uninstalled while preserving database integrity and registered project
knowledge. The full regression retains signed update/rollback and failure-recovery
tests; these are separate CLI scenarios, not a new dashboard updater or one complete
live-user update journey.

Existing-user compatibility is automated/fixture evidence: native provider config
and session mechanisms were preserved, existing regressions passed, and no real
user installation/authentication was changed. Actual authenticated Codex/Claude/
MiniMax users, IDE clients, native OS credential stores and real team members were
not acceptance-tested. “Configured” and historical connection verification remain
distinct from current authentication, availability and quota.

## Security review and corrections

This phase includes implementation review and automated adversarial checks; it
does not claim a separate independent Phase 7 reviewer session. Phase 6's independent
review remains historical and does not certify new code.

- New preference/proposal routes pass the existing authenticated Handler. HTTP
  tests reject missing authentication, cookie-only requests and hostile Origins.
- Proposals reject unknown fields/providers/modes, require registered projects and
  independent collaboration roles, retain zero default spending, and never grant
  approvals, dispatch providers or create workflows by themselves.
- Supported imperative provider requests must match explicit selections. Ordinary
  references to another provider do not trigger delegation. Continuation is scoped
  to the selected project and opens saved state without execution.
- Preference updates merge inside `BEGIN IMMEDIATE`, preventing stale concurrent
  writes from dropping another control's changes. Invalid writes are atomic.
- Navigation preferences live in the private database, not browser local storage.
  Session proofs remain in their existing tab scope; no new credential storage.
- Browser view guards discard delayed results after project/view changes. The
  disconnect message explicitly warns that a request outcome can be unknown.
- Existing runtime mutation locks, signed distribution, scoped tools, command
  profiles, budgets, recovery checkpoints and approval gates remain intact.

Early browser failures are retained in BROWSER-ATTEMPT files. Favorite checks
initially acted before registration finished refreshing the list, favoriting the
first card instead of the intended one. The harness now waits for the target
project and confirms persistence. Another test raced fragment navigation/reload;
the final test uses a fresh startup document. Visual inspection found and corrected
light-theme label/brand contrast; [light](light.png) and [dark](dark.png) screenshots
are retained. These screenshots are not a full WCAG audit.

No remaining confirmed high/critical defect was identified in these changed local
paths. That is not blanket certification of native platforms, live providers,
arbitrary authorized commands or production use. Disposable signing keys were
authorized for regression tests only and their fixture directories were removed:
[cleanup evidence](KEY-CLEANUP.json). No candidate signature was produced.

## Requested deliverables and remaining scope

| Deliverables | Result / limits |
|---|---|
| 1–2 Audit and prioritized friction | [FRICTION-AUDIT.md](FRICTION-AUDIT.md); persona perspectives explicitly not user interviews |
| 3 Installation | Existing safe single installer retained; actionable dependency diagnostics; no automatic downloads, new runtime packaging or native certification |
| 4 Startup | Actual installed `open`, duplicate-instance reuse, authenticated browser and restart verified |
| 5 Onboarding | Two-step real-browser acceptance; no live authentication claim |
| 6 Provider discovery | Existing discovery/config inheritance retained, friendlier truthful labels; live status remains unverified |
| 7 Projects | Preview/register/index, recent/favorites/search/last project and isolated switching verified; no native folder picker or new build-command discovery |
| 8 Chat-first interface | Chat landing, instruction-derived draft/title, exact text transfer, streaming, resume, copy control and advanced old form; no full conversation search or file-reference viewer |
| 9 Modes | Solo read-only; Collaborate bounded implementation/review; Auto explicit-preset routing. Solo mutation and semantic complexity inference remain unimplemented |
| 10 Presets | Question, Quick fix, Feature development, Review and test; editable provider/criteria/default budgets; backend gates unchanged |
| 11 Natural-language delegation | Small checked imperative/continuation grammar, not arbitrary natural-language planning or provider-name authorization |
| 12 Context/session experience | Existing automatic context and exact sessions retained; project/view restoration improved; automatic native rotation and unverified handoff not added |
| 13 Approvals | Existing reusable bounded workflow permissions retained; primary draft path cannot grant them. No measured real approval reduction |
| 14 Progress/recovery | Existing pause/resume/cancel/retry controls retained; real progress and continuation inspection; unknown effects never auto-replayed |
| 15 Final results | Concise verified task/command summary plus detailed tests/review; no falsely verified chat reply |
| 16 Help/diagnostics | Working Help and diagnostic navigation, redacted export retained; update instructions rather than fake update availability |
| 17 Browser | 15 source groups + 3 exact-archive installed groups; comprehensive accessibility, every advanced-control path and all native browsers remain pending |
| 18 First-time acceptance | Automated offline clean-environment journey and interaction counts; no live user/provider claim |
| 19 Existing developer acceptance | Preservation regressions and isolated install/restart; real authenticated/native-user acceptance BLOCKED |
| 20–21 Interaction/performance | Table and raw evidence above; no human/team study, real token benchmark or current long soak |
| 22 Security | Implementation review, HTTP and negative tests, full regression; no independent Phase 7 session or broad release certification |
| 23 Regression | 386 pass / 9 required-host skips / zero failures |
| 24 Blockers | Live providers/budget, six directions, native clients/hosts, real project/team pilot, remaining UX scope, signer/license/release decisions |
| 25–27 Instructions/adoption/pilot | [DAILY-USE.md](../DAILY-USE.md), [Operations](../OPERATIONS.md), controlled evaluation recommendation below |

Desktop shortcuts, optional IDE integration, automatic trusted update notifications,
native folder selection, new semantic session rotation and broad natural-language
automation were not added. Existing native adapters remain available without new
verification claims. No unnecessary desktop wrapper, cloud service or design system
was introduced. These omissions remain partial requirements, not hidden successes.

## Local artifact and recommendation

`dist/v5-phase7-local-evaluation/claude-codex-orchestrator-4.3.0.tar.gz`
with adjacent `SHA256SUMS`: **233,706 bytes, 90 members**. SHA-256:
`1d0090bf247bf8b35a613abcc80f2fe84a02561117e0cbd188fbc8a479a2af37`.
Two builds matched byte-for-byte. Exact manifest/checksum verification and archive
installation/browser lifecycle passed. Audit data, credentials, runtime databases
and Phase 7 screenshots/reports are excluded. [Artifact evidence](ARTIFACT.json).

Engine metadata stays 4.3.0, workspace 5.0.0-dev, `local_evaluation_only`,
`production_ready: false`. Do not republish this as another production 4.3.0 release.
The checksum is integrity evidence, not trusted publisher authentication.

Recommend local evaluation on the tested Ubuntu 24.04 x86_64 / Python 3.12.3 /
Chrome 144 scope. Before a real team pilot, authorize project copies, provider
combinations/models and bounded usage; close applicable native-client/platform,
live recovery and trusted-signature gates. Other Windows/WSL/macOS/older Linux
hosts were not executed here. No client directory or spend budget was guessed.

The measured onboarding reduction is real within the automated scenario, but no
broad V5_DEVELOPER_EXPERIENCE_VERIFIED, V5_MINIMAL_INTERACTION_VERIFIED,
V5_TEAM_PILOT_READY, V5_TEAM_ADOPTION_READY or full product-readiness label is issued.
