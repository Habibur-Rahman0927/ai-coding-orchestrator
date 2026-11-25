# Native platform and distribution evidence

This audit ran on native Ubuntu 24.04.3 x86_64 / Python 3.12.3. Existing installation,
signing, tampering, unsafe archive, launcher preservation, update/rollback, migration,
uninstall and runtime tests ran with disposable prefixes/projects. No global user
installation, release signing/publishing, remote CI or client-project change occurred.

Native Windows, macOS ARM/Intel, Ubuntu 20.04 and WSL2 are not verified by this run.
Platform mocks do not count as native results. The final report identifies native-only
skips. Docker availability alone proves no container test; no images were pulled.
Real Linux Secret Service is unavailable (`secret-tool` absent); native vault CRUD
remains untested. Python 3.8 compatibility of new code requires its own execution.

Every tracked immutable V4 payload file was compared byte-for-byte against the V5
baseline and retained unchanged. Exact hashes and file count: immutable-payloads.json.
The baseline archive permission issue was corrected in the audit copy without changing
payload bytes; this was not a production security-control bypass.
