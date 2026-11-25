# Releasing an engine

The current V5 development snapshot is for local evaluation only. See the
[candidate guide](v5/RELEASE-CANDIDATE.md). Its engine version remains 4.3.0;
the generated `RELEASE-INFO.json` explicitly says `production_ready: false`.
Do not publish this snapshot under an existing version or interpret its checksums
as publisher authentication. Phase 6 authorizes disposable test signing keys only,
not a maintainer key, signing this candidate, pushing tags, or publication.
The procedure below is a future maintainer procedure requiring explicit approval,
a reviewed new version, resolved release gates, and independently established trust.

For the unpublished 4.3.0 cross-platform candidate, see the
[cross-platform guide](CROSS-PLATFORM.md) and verification report (source checkout: `docs/CROSS-PLATFORM-RESULTS.md`; omitted from packages).

1. Change root `VERSION` and `ENGINE_VERSION` in `engine/orchestrator.py` together.
   Engine versions and `CLI_VERSION`/project payload versions are separate.
   Do not edit immutable verified payloads to bump only the engine version.
2. From a clean source tree run:

   ```sh
   python3 tests/test_orchestrator.py
   python3 tests/test_distribution.py
   python3 tests/test_self_update.py
   ./tests/container/run.sh
   ```

   The container harness builds signed 4.2.0/4.2.1 test variants with a throwaway
   key, runs the default Linux matrix, and reports each image. Optional image
   arguments replace the defaults. Docker pulls/package installation need network;
   the subsequent scenarios use only mounted artifacts. Require all PASS results.
3. Build with a maintainer signing key kept outside the source tree:

   ```sh
   python3 tools/build_release.py --sign-key /path/to/SIGNING_KEY
   # Equivalent: ./scripts/build-release.sh --sign-key /path/to/SIGNING_KEY
   ```

   `--source DIR` selects a different source; `--output-dir DIR` overrides its
   `dist/` output. The builder uses an explicit source allowlist, rejects forbidden
   paths/private absolute paths and mismatched versions (exit 6), and writes a
   deterministic tarball, SHA256SUMS and SHA256SUMS.sig. Generated files and local
   test reports must not be added to the payload. Building without `--sign-key`
   produces no signature and removes a stale output signature.
4. Verify using the independently trusted team signers, then publish:

   ```sh
   set -eu
   VERSION=$(cat VERSION)
   ALLOWED_SIGNERS=/path/to/allowed_signers
   SIGNER_IDENTITY=SIGNER_IDENTITY
   cd dist
   ssh-keygen -Y verify -f "$ALLOWED_SIGNERS" -I "$SIGNER_IDENTITY" \
     -n claude-codex-orchestrator-release -s SHA256SUMS.sig < SHA256SUMS
   sha256sum -c SHA256SUMS
   gh auth login
   gh release create "v$VERSION" --repo OWNER/REPO --verify-tag \
     --title "Engine $VERSION" --notes-file /path/to/RELEASE_NOTES \
     "claude-codex-orchestrator-$VERSION.tar.gz" SHA256SUMS SHA256SUMS.sig
   ```

   Create and push the reviewed `vX.Y.Z` tag through your team's normal process
   before `gh release create --verify-tag`. Upload only those three explicit
   assets, not the whole working directory. Never re-tag a published version or
   replace its assets; publish a new version for corrections.

## Signer rotation

Each `allowed_signers` line associates the configured identity with a public key:

```text
SIGNER_IDENTITY ssh-ed25519 PUBLIC_KEY_BASE64
```

Add a new public key under the same identity alongside the old one, distribute
that updated file through a trusted channel, and have members rerun
`distribution configure --repository OWNER/REPO --allowed-signers FILE
--signer-identity SIGNER_IDENTITY`. The file is copied, so changing the original
does not change installed trust. Start signing with the new key only after
members have it; remove the old key through another explicit trust update when
appropriate. Keep historical verification needs in mind. Never distribute the
private signing key or add it to the checkout/artifact.
