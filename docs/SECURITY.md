# Security model

The signature on **SHA256SUMS**, verified against independently trusted
`allowed_signers` and the configured signer identity, is the release trust
anchor. Its namespace is `claude-codex-orchestrator-release`. The authenticated
checksum binds the tarball; exact MANIFEST coverage binds its files. Extraction
rejects links, traversal, special files, multiple roots, more than 5,000 members
and more than 100 MB of member data. Version and release checks run before the
new installer is executed. A trusted signer can publish executable code: protect
signing keys and review releases.

Local checksums alone detect accidental same-user edits and corruption, not
malicious same-user tampering. A process running as you can rewrite the engine,
checksums, backups, configuration or trusted signers together. Preserve private
permissions and protect the user account.

## Data boundaries

The release allowlist contains only install/uninstall scripts, VERSION, optional
README, docs and engine source/payloads. Credentials, global `~/.claude`, global
`~/.codex`, registry, backups, session state and logs must never be packaged or
uploaded. The builder rejects registry/backups/engine-backups/test-reports,
JSONL logs, credential filenames, key filenames, environment files, UUID-named
JSON, cache directories and private absolute home paths. This is an allowlist
plus heuristic guard, not a universal secret detector: do not put sensitive
content under an innocuous source filename. Review artifacts before publishing
and upload only the tarball and its checksum/signature files.

`gh` handles GitHub authentication using the user's existing login. The
orchestrator invokes `gh release list` / `gh release download`; it does not read,
print or save tokens. Signing and verification use `ssh-keygen`; private keys
are never release assets. The container harness mounts public test artifacts
only, with neither host HOME/config nor its throwaway private key.

Engine update, rollback and uninstall do not edit projects or runtime state.
Engine uninstall keeps registry and project backups unless explicitly purged,
and purge refuses while projects remain registered. Project commands have their
own narrower data rules; see [CLI reference](CLI.md).

## Limitations

- Path checks leave residual time-of-check/time-of-use (TOCTOU) races. They are
  pathname checks, not complete protection against concurrent same-user swaps.
- Locks are cooperative: engine operations use a directory-inode `flock`;
  project operations use management/execution locks. Other programs can ignore them.
- File replacement is atomic per file, not for an entire engine upgrade. Caught
  failures restore backups; abrupt process termination or power loss can leave
  mixed files. Keep verified releases and backups for manual recovery.
- Source-checkout installs have no independent signature verification. Trust the
  checkout before executing it. Bootstrap signature verification is a manual step.
- Setting `require_signature` false alone does not allow unsigned updates;
  `--allow-unsigned` is also required. This bypass removes release authentication.
