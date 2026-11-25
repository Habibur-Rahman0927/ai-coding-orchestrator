# Developer experience audit

Inspected source and actual Chrome journeys, not interviews or invented feedback.
The Phase 6 baseline was 375 passes/9 native-host skips, ten dashboard groups and
three artifact-installed lifecycle groups. Its live-provider, native-client/host,
real-project, signing and production gates remain open.

| Priority / friction | Existing process | Implemented process | Measured or observable benefit |
|---|---|---|---|
| P1: mandatory setup choices | Six screens, environment review, three agent roles, budgets, project, finish | One provider, optional project; workflow defaults remain advanced | Same automated project-onboarding scenario: 8→4 clicks, 4→2 field changes |
| P1: architecture-first landing | Overview metrics then navigate to chat and name a conversation | Chat landing; task text creates a titled local Solo draft | No required conversation-name field in primary path; exact task text carried over locally |
| P1: manually construct collaboration | Objective, criteria, three role selectors and four budget fields exposed together | Explicit mode, small preset, primary agent, partner and criteria; inspect inherited budgets | Removes repeated planner/executor decisions; existing approvals remain required |
| P1: switching loses navigation | Selection only in JavaScript memory; chats from all projects listed together | Database-backed last project, per-project agent, recent/favorites, filtered chats | Actual reload and two-project browser checks; no reindex on switching |
| P1: delayed view responses | Async chat/project callbacks could render after navigation | View/project guards discard stale presentation results | CDP delays a real chat-list request while selecting another project |
| P2: foreground launch knowledge | `start --background` needed for terminal-returning startup | `open`, including installed launcher; repeat open reuses PID | One command remains one command; removes the mandatory background flag |
| P2: technical progress/results | Raw status and detailed records dominate | Existing real status plus concise verified-result/test/review summary | No invented progress percentages; detailed evidence retained |
| P2: no continuation entry | Locate workflow/session details manually | Project-scoped Continue previous work and supported continuation instruction | Opens saved work only; no automatic replay or completed-task restart |
| P2: too much navigation | Eleven equal destinations | Seven primary destinations, five advanced destinations including Overview, plus in-product Help | Primary task is first; original advanced functionality retained |
| P2: raw connection failure | Fetch error alone | Actionable disconnected-workspace message, unknown-outcome warning | Browser test stops the actual fixture HTTP server; no false success |
| P2: one appearance | Dark only | System/light/dark persisted in private SQLite settings | Actual browser persistence and screenshots; light label/brand contrast corrected |
| P3: optional dependencies look mandatory | Missing AI CLI/gh warnings without context | Clarifies optional providers and zero dependency downloads; actionable Python/Git errors | Installer behavior preserved; no untrusted installation or sudo |

## Persona assessment

These are engineering perspectives, not claims of testing with these users.

- Junior developer: fewer setup decisions; Chat, Help and clear next actions. Still
  needs a repository path and explicit sharing permission; no native folder picker.
- Experienced engineer: advanced roles, models, budgets, context and evidence stay
  accessible. Solo remains read-only, so implementation uses explicit collaboration.
- Team lead: per-user accounts/data and bounded defaults; no shared credential or
  central server introduced. Real team pilot authorization/evidence is still missing.
- Codex user: existing CLI settings/login are delegated to the installed adapter;
  provider detection is not live readiness. No native session is reset.
- Claude user: same preservation boundary, with prior availability and compatibility
  gates carried forward. No unsupported native integration is claimed.
- MiniMax user: secure credential controls and explicit model remain; live tests
  require consent. No account quota or model identifier was fabricated.
- Cross-platform developer: launcher/storage adapters preserved, current execution
  only on Ubuntu x86_64. Native Windows, WSL2 and macOS acceptance remain pending.

## Decisions and limits

No Electron wrapper, IDE extension, package manager, cloud service or second design
system was added. The standard-library runtime already has no third-party Python
dependencies; automatic downloads would add trust and maintenance decisions.
Desktop shortcuts and OS folder pickers remain unimplemented rather than fake.

Auto follows explicit presets; it does not infer task difficulty from provider names
or choose a hidden ranking. Natural-language support is deliberately small and
checked against explicit controls. A provider mention cannot authorize execution.
No model-generated planning call is used merely to populate the interface.

Initial workflow permissions and per-message chat sharing remain required. This
phase does not claim reduced real approval burden, prompt transfer or token usage.
Session rotation and live failover remain constrained by existing adapter evidence;
no session history was reset to make the experience look simpler.

Browser failure evidence is preserved: early favorite checks clicked the first
project card while registration was still refreshing the list; the stored favorite
was correct for that card. The test now waits for the new project and verifies its
state. Preference writes were also made transactional to prevent independent
concurrent changes from overwriting one another. A subsequent new-login test used
a fragment/reload race; it now opens a fresh document like a normal startup link.
