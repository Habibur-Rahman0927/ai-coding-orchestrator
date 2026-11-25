# Automatic AI pull request descriptions

This optional GitHub Actions workflow writes a professional English description
inside a managed section of a PR body. It preserves the PR title and all text
outside that section. It does not create comments, change labels, review code,
approve PRs, merge, or modify application files.

## Architecture

1. `.github/workflows/ai-pr-description.yml` handles `opened`, `reopened`,
   `synchronize`, and `ready_for_review` using `pull_request_target`.
2. Job conditions skip drafts, bot authors/senders, and **all external forks**.
   The Python script repeats the eligibility checks against current GitHub state.
3. A small standard-library bootstrap downloads **only**
   `.github/scripts/ai_pr_description.py` at the event's trusted base `GITHUB_SHA`.
   There is no checkout, no PR executable, dependency installation, third-party
   action, cache, or artifact ingestion. Python runs with `-I -B` isolation.
4. GitHub REST calls collect current PR metadata, bounded commit messages,
   changed-file metadata and actual patches, plus base-revision README context.
   Deleted and renamed files include their status and previous path when available.
5. Filtered/redacted data is sent directly to the MiniMax Chat Completions API. Requested
   JSON output is validated locally and rendered to Markdown with fixed section headings.
6. After another current-state check, one GitHub REST PATCH updates only `body`.
   Existing developer content outside the markers is preserved verbatim.

`pull_request_target` is intentional: the automation runs from the trusted base,
not the proposed workflow or script. Never change the bootstrap to download from
`head.sha`, a PR branch, or merge ref. Never add a PR checkout, PR build, package
installation, or execution of PR-supplied commands to this privileged job.
Protect base branches and require review of changes to this workflow and script.

GitHub documents the base-context behavior and restrictions for
[`pull_request_target`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target).
API contracts used are [GitHub pull requests](https://docs.github.com/en/rest/pulls/pulls),
[MiniMax Chat Completions](https://platform.minimax.io/docs/api-reference/text-chat-openai),
and [MiniMax authentication setup](https://platform.minimax.io/docs/guides/quickstart-preparation).
Compatibility was checked against these official references on 2026-11-26;
this is not a claim of a live integration test.

## Setup and permissions

1. Review these four files: the workflow, generator script, this guide, and
   `tests/test_ai_pr_description.py`. Merge them through your normal process into
   the trusted default/base branch. The initial PR adding the automation cannot
   bootstrap a script that is not yet on the base branch.
2. In **Settings → Secrets and variables → Actions → Secrets**, add
   `MINIMAX_API_KEY`. Use an API project authorized for this repository's code and
   with billing/model access configured. Do not put the key in a repository variable.
3. Optionally add the variables below in the **Variables** tab.
4. Ensure Actions is enabled at repository and organization levels, and that policy
   allows the workflow's explicit `contents: read` and `pull-requests: write` job
   permissions. All other token permissions are disabled. Organization secrets
   must be granted access to this repository. No personal access token is needed;
   GitHub supplies `GITHUB_TOKEN` automatically.
   **You do not need to create a separate PR token or GitHub PAT.** The MiniMax
   credential is separate: GitHub-hosted runners cannot read a Mac's workspace
   login, Keychain, or environment. Copy an authorized MiniMax key into the GitHub
   Secret yourself; never paste it into code or PR text. MiniMax documents both
   pay-as-you-go API keys and M Plan Subscription Keys. Use one authorized for
   the chosen model and automation usage; plan quota/credits and API billing
   depend on your account. A dashboard login alone is not API authentication.
5. Leave the setting permitting Actions to **create and approve** PRs disabled if
   unused elsewhere: this automation only edits an existing PR body. Do not enable
   write tokens or secrets for fork workflows to make this feature work.
6. Do not select **AI PR description** as a required merge/status check. The job
   is advisory (`continue-on-error`) and API failures produce sanitized messages.
7. After setup, use a non-draft, same-repository PR authored by a human. Opening,
   reopening, pushing a new commit, or marking it ready triggers the workflow.
   Review the generated description for accuracy. A live run consumes API usage.

This implementation targets **GitHub.com** and the public MiniMax API. GitHub
Enterprise Server and alternate provider endpoints need a reviewed
adaptation; endpoints are intentionally not configured from PR data.

## Configuration

| Secret or variable | Default | Purpose |
|---|---|---|
| Secret `MINIMAX_API_KEY` | Required | MiniMax API authentication; missing secret skips generation. |
| Built-in `GITHUB_TOKEN` | Provided by Actions | Read PR/context and update the body. |
| Variable `MINIMAX_MODEL` | `MiniMax-M3.1-Flash` | MiniMax model supporting Chat Completions; output shape is validated locally. |
| Variable `AI_PR_DESCRIPTION_ENABLED` | Enabled | Set exactly `false` to skip the job. |
| Variable `AI_PR_MAX_INPUT_TOKENS` | `24000` | Conservative input ceiling; allowed 8000–64000. |
| Variable `AI_PR_MAX_OUTPUT_TOKENS` | `4000` | API output cap including reasoning tokens; allowed 1000–8000. |

The default model is listed in the
[official MiniMax API documentation](https://platform.minimax.io/docs/api-reference/text-chat-openai).
Requests use `messages`, `max_completion_tokens`, non-streaming output, low reasoning
effort, and separate reasoning output. Only final answer content is parsed;
`reasoning_content` is never published. No OpenAI SDK, account, API key, endpoint,
or fallback is used. MiniMax uses a compatible HTTP format; that does not make
OpenAI the provider. The JSON schema is included in the system prompt and enforced
locally, not passed as an undocumented server-side structured-output parameter.
Verify access for your API project before selecting another model. Unsupported
parameters/model access fail safely; there is no fallback to a costlier model.

To avoid tokenizer dependencies, the input limiter counts serialized ASCII JSON
bytes, the instruction/schema bytes, and a 2048-byte protocol reserve as a
conservative input-size estimate. MiniMax token counts are not measured locally. This deliberately
limits source volume, especially for non-ASCII code. It is not a guaranteed
provider token count or an account-level spending cap. Actual model usage
and server-side overhead should be monitored in the API dashboard.

Fixed collection limits are 300 changed-file records (three pages), 100 commit
records (one page), at most 50 commit-message excerpts, 5000 characters per patch,
2000 characters of base README and developer description, and 8 MB per API
response. The total serialized payload also has to fit the input ceiling.
GitHub may omit or truncate patches independently. A scope note reports fetched,
excluded and omitted files; do not interpret a partial description as exhaustive.
PRs containing only excluded files or unavailable patches cause no AI request.

## Managed description and example

The first successful run appends a block. Later runs replace only that block:

```markdown
Developer-written context and checklist remain here.

<!-- ai-pr-description:start -->
<!-- ai-pr-description:revision=<head-and-base-fingerprint> -->
### Summary

- Allow startup when optional settings are absent.

### Changes Implemented

- Use default settings when the configuration file does not exist.

### Affected Modules

- Settings loader and startup initialization.

### Testing Status

- Test execution was not verified by this automation. Review CI results separately.
- Test-related files changed: tests/test_settings.py (added).

Analysis scope: 2 file entries included; 0 files excluded; 0 omitted locally. Patches may be partial or locally truncated. Fetched 2/2 files and 1/1 commits.
<!-- ai-pr-description:end -->

Developer notes after the block remain here too.
```

Summary and Changes Implemented are required. Affected Modules, Technical Changes,
Deployment Notes and Breaking Changes appear when applicable. Testing Status is
rendered deterministically: test-related filenames are identified heuristically,
and no model-provided test execution claim is used. This job does not collect or
verify CI results. Do not treat claims elsewhere in generated prose as evidence.

Do not edit or duplicate the markers. Ambiguous/incomplete markers cause a safe
skip. Put manual additions outside the managed block. Edits inside it will be
replaced on the next code revision. Changing only manual prose does not trigger
generation. To explicitly regenerate unchanged code, remove the managed block
and reopen the PR (or rerun the corresponding current-head workflow).

## Reliability, concurrency and cost

- Per-PR concurrency cancels older runs. A saved head/base fingerprint skips
  already-generated revisions before contacting MiniMax.
- Current PR metadata is checked before generation and immediately before write.
  Changed head/base, title, body, update timestamp, eligibility or closed state
  causes a skip/discard. In particular, manual edits during model latency survive.
- GitHub's body-update endpoint has no documented atomic compare-and-swap for
  this operation. There remains a small last-read-to-PATCH race with a human or
  another integration. Concurrency and rechecks narrow it but cannot guarantee
  atomic preservation. Avoid editing the body during the final update; GitHub's
  edit history can help recover a conflicting edit. PATCH is never blindly retried.
- Repeated successful runs at the same head/base cause no new model request.
  Cancelled/failed runs without a published fingerprint, empty commits with new
  SHAs, or a deliberate removal of the block may incur another request. This is
  not a distributed exactly-once billing guarantee.
- Each request times out after 45 seconds (bootstrap: 30 seconds). Retryable
  429/500/502/503/504 responses get at most two retries with short backoff.
  Numeric Retry-After values over 30 seconds defer work to a later run. Ambiguous
  non-GET network failures are not retried. Job timeout is eight minutes.
- Missing credentials, unsupported models, malformed/refused/incomplete output,
  rate limits and collection failures leave the original description intact.
  There is no partial generated-body publication. An ambiguous PATCH network
  failure may mean GitHub already applied the complete update.

Estimate cost using your model's **current** input, cached-input and output rates
per million tokens from [MiniMax pricing](https://platform.minimax.io/docs/pricing/pay-as-you-go):

```text
request cost = (uncached input tokens × input rate
              + cached input tokens × cached-input rate
              + output tokens × output rate) / 1,000,000
monthly cost ≈ sum of billable requests, including retries and cancelled runs
```

Use actual API project usage to refine estimates. Output includes reasoning usage
where applicable. For a subscription key, monitor plan quota/credits rather than
assuming pay-as-you-go rates or free unlimited execution. For conservative planning use configured ceilings, ignore cache
savings, and allow for up to three attempts. Set project budgets/alerts separately;
workflow limits are not a hard monthly dollar cap. No live API cost was incurred
by the local mocked tests.

## Security and source-code privacy

Only the generation step receives the MiniMax key. Tokens are not embedded in
shell command strings; event values are read as JSON. Only fixed trusted paths
are executed. No external GitHub Actions require pinning because none are used.
Redirects are rejected to avoid forwarding authorization to another endpoint.
Raw requests, source, responses, keys and exception tracebacks are not logged.

The payload includes excerpts of proprietary source if present. Generated files,
lock files, release/build artifacts, typical binaries, credential files and
sensitive directories are filtered; renamed files are checked under both names.
Common secret formats, credential assignments, private-key blocks, credentialed
URLs, JWTs and exact workflow credentials are redacted before transmission.
Output is redacted too. This is **best-effort filtering, not complete secret or
PII detection**. Add repository-specific exclusions in the trusted script and
review organizational data-sharing policy before enabling it. Some non-sensitive
configuration changes can be over-redacted or omitted.

Repository content is explicitly untrusted model input, with no tools or code
execution available. Strict output shape, fixed headings, escaped Markdown/HTML,
removed web links and neutralized mentions prevent generated content from adding
managed markers, embedded images or notifications. These controls do not prove
semantic accuracy or eliminate all prompt-injection influence on prose. Review
generated claims; do not use the description as an automated security decision.

Source excerpts are transmitted to MiniMax, not OpenAI. No unsupported `store`
parameter is sent and no zero-retention guarantee is made. Review your MiniMax
account's data-processing terms and organizational policy before enabling the
workflow. There are no uploaded source artifacts or persistent request caches in
this workflow.

## Validation

From the repository root, using Python 3.8 or newer:

```sh
python3 -B -m unittest discover -s tests -p test_ai_pr_description.py -v
python3 -B -m unittest discover -s tests -p test_repository_hygiene.py -v
```

Mocked tests cover empty/manual descriptions, replacement and duplicate execution,
new commits, stale events and concurrent edits, small/large Unicode diffs,
renames/deletions/exclusions, drafts/forks/bots, missing credentials, API errors,
rate limits, timeouts, redaction, invalid output and adversarial source text.
They validate isolation and preservation logic, **not** a model's resistance to
all prompt injection. Existing POSIX test discovery includes these tests.

No live GitHub update, MiniMax request, model quality evaluation, or hosted Actions
run was performed as part of local validation. Complete a controlled live PR
smoke test after the maintainer configures secrets and deploys these files.

## Troubleshooting

| Symptom | Check |
|---|---|
| Workflow absent | Ensure workflow and script exist on the trusted base/default branch; use a supported event. GitHub also suppresses some SHA-like head branch names for this event. |
| Job skipped | Draft, fork, bot author/sender, or `AI_PR_DESCRIPTION_ENABLED=false`. |
| Trusted automation unavailable | Script must exist at the base SHA; check Actions policy and contents permission. No fallback to PR code is allowed. |
| Missing API credentials | Secret spelling, organization-secret repository access, and MiniMax project setup. Never print a key to debug. |
| HTTP 401/403 | API key/model access or GitHub PR-write policy. Review provider dashboards without exposing keys. |
| HTTP 429 | API quota/rate limits; wait and rerun a current-head event after quota recovery. |
| Model output incomplete/invalid | Check model compatibility and output cap; increase within limits if justified. Original body is retained. |
| No eligible code diff | Only excluded files or missing GitHub patches were available. |
| Already generated | Same head/base fingerprint exists. A repeat run intentionally avoids spending. |
| PR changed / result discarded | A new commit, body edit or state change occurred; the next event can generate again. |
| Ambiguous markers | Preserve developer text and remove/fix the duplicate or incomplete managed block. |
| Incorrect description | Correct manual context outside the block; review the actual diff. AI output is not verified evidence. |

## Disable or reuse

Set repository variable `AI_PR_DESCRIPTION_ENABLED` to `false`, disable the
workflow in the Actions UI, or remove the workflow through review. Existing PR
bodies remain unchanged. Removing `MINIMAX_API_KEY` also makes generation skip.

To reuse, copy the workflow, `.github/scripts/ai_pr_description.py`, tests and this
guide into the same paths on another repository's trusted base branch. The script
uses `GITHUB_REPOSITORY`; no repository name is hard-coded. Configure secrets,
permissions and model variables independently, review file exclusions for that
codebase, run the offline tests and then a controlled live smoke test. Keep the
trusted-base-only execution boundary intact. No application dependency changes
are required.
