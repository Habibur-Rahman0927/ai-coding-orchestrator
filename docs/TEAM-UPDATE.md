# Team updates

## Engine updates

Configure the repository and trusted signers first (see [installation](TEAM-INSTALL.md)).
Remote operations use only your authenticated `gh`; no token configuration is
needed in the orchestrator.

```sh
orchestrator self-update --check
orchestrator self-update --dry-run
orchestrator self-update --apply --yes
```

`--check` compares the installed engine with stable `vX.Y.Z` tags among the
latest 50 non-draft, non-prerelease releases; it does not download or verify an
artifact. `--version X.Y.Z` selects a version. `--dry-run` downloads and fully
verifies the artifact, then prints planned files without changing the install.
`--apply` without `--yes` exits 4. Identical installed files at the same version
produce `UP_TO_DATE`. Downgrades require `--allow-downgrade`.

Offline updates still require distribution configuration:

```sh
orchestrator self-update --dry-run \
  --archive /path/to/claude-codex-orchestrator-X.Y.Z.tar.gz \
  --sums /path/to/SHA256SUMS --signature /path/to/SHA256SUMS.sig
orchestrator self-update --apply --yes \
  --archive /path/to/claude-codex-orchestrator-X.Y.Z.tar.gz \
  --sums /path/to/SHA256SUMS --signature /path/to/SHA256SUMS.sig
```

Verification authenticates SHA256SUMS, checks the named tarball, safely extracts
it with size/member limits, checks exact manifest coverage and version, and
verifies release checksums. Only then is the verified new installer run.
Registry, project backups, existing release directories, projects and runtime
state are preserved. The installer uses the bin directory recorded in the receipt;
older receipts without it fall back to `$HOME/.local/bin`.

Unsigned artifacts are accepted only when configuration was explicitly written
with `distribution configure --repository OWNER/REPO --no-require-signature`
**and** the update includes `--allow-unsigned`. Leave both protections enabled
for team releases. A supplied signature is still checked.

## Engine rollback

```sh
orchestrator self-rollback --check
orchestrator self-rollback --dry-run
orchestrator self-rollback --apply --yes
```

The newest engine backup is selected by directory modification time and verified
before use. Applying first backs up current code, then restores the selected
code and receipt, keeping release directories. With no intervening operations
or edits, a second rollback restores that undo backup and toggles back. This is
not a walk through older versions. No backup gives exit 1; an invalid backup
gives exit 6; a busy engine lock gives exit 75. Caught failures restore the
previous code automatically; interrupted power or process loss is not atomic
across the whole tree.

## Project payload updates are separate

Updating the engine does not update already-installed projects. In each project:

```sh
orchestrator update --check
orchestrator update --dry-run
orchestrator update --apply --yes
```

Use `--release V` to select a project payload. Resolve reported conflicts and
active workflows before applying. Project `rollback` is separate from
`self-rollback`; see [CLI reference](CLI.md).

## Pre-distribution engine

From a trusted new source checkout or verified extracted release:

```sh
./install.sh --upgrade --prefix /path/to/ENGINE --bin-dir /path/to/BIN
```

This supports installations without receipts, creates a verified engine backup,
and writes a receipt including the bin directory. It preserves registry,
project backups and existing releases. Configure distribution provenance after
upgrading. `--dry-run` prints the installer plan without applying it.
