#!/usr/bin/env python3
"""Regression suite for the Claude-Codex global orchestrator.

Every test runs against a disposable copy of the engine, a temporary HOME
(so ~/.local/state/claude-codex is isolated) and temporary Git projects.
Codex is replaced by a fake executable; no real Claude or Codex call is made.

Run:  python3 tests/test_orchestrator.py [--cli PATH] [--report PATH]
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = Path(os.environ.get("ORCH_TEST_ENGINE", REPO / "engine"))
CLI = Path(os.environ.get("ORCH_TEST_CLI", ENGINE / "orchestrator.py"))
RELEASE = os.environ.get("ORCH_TEST_RELEASE", "4.1.0")
LEGACY = REPO / "tests/fixtures/legacy-4.0.0"
LEGACY_CLI = [LEGACY / "orchestrator.py"] if (LEGACY / "orchestrator.py").is_file() else []

FAKE_CODEX = r'''#!/usr/bin/env python3
import json, sys, uuid
args = sys.argv[1:]
thread = None
for value in args:
    try:
        thread = str(uuid.UUID(value)); break
    except ValueError:
        pass
thread = thread or str(uuid.uuid4())
for event in (
    {"type": "thread.started", "thread_id": thread},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "FAKE-CODEX " + args[-1]}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 2}},
):
    print(json.dumps(event), flush=True)
'''


def tree_digest(root, exclude=(".git",)):
    """Digest of every path, type, mode and content under root."""
    items = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in exclude:
            continue
        if path.is_symlink():
            items.append(f"L {rel} {os.readlink(path)}")
        elif path.is_file():
            items.append(f"F {rel} {oct(stat.S_IMODE(path.stat().st_mode))} "
                         + hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            items.append(f"D {rel}")
    return hashlib.sha256("\n".join(items).encode()).hexdigest()


def project_id(root):
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


def reseal(release_dir):
    manifest = json.loads((release_dir / "checksums.json").read_text())
    for name in manifest:
        manifest[name] = hashlib.sha256((release_dir / name).read_bytes()).hexdigest()
    (release_dir / "checksums.json").write_text(json.dumps(manifest, indent=2))


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="orch-test-")).resolve()
        self.engine = self.tmp / "engine"
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        for directory in (self.engine / "registry", self.home, self.bin):
            directory.mkdir(parents=True)
        shutil.copy2(CLI, self.engine / "orchestrator.py")
        shutil.copytree(LEGACY / "releases/4.0.0", self.engine / "releases/4.0.0")
        shutil.copytree(ENGINE / "releases" / RELEASE, self.engine / "releases" / RELEASE)
        meta_path = self.engine / "releases" / RELEASE / "release.json"
        meta = json.loads(meta_path.read_text())
        meta["status"] = "VERIFIED"
        meta_path.write_text(json.dumps(meta))
        (self.engine / "current.json").write_text(json.dumps({"version": RELEASE}))
        (self.engine / "registry/projects.json").write_text('{"projects": {}}\n')
        codex = self.bin / "codex"
        codex.write_text(FAKE_CODEX)
        codex.chmod(0o700)
        self.session = str(uuid.uuid4())
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "ORCHESTRATOR_CLAUDE_SESSION_ID": self.session,
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def tearDown(self):
        for path in self.tmp.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers -------------------------------------------------------------

    def project(self, name, files=None):
        root = self.tmp / "projects" / name
        root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(root)], check=True, env=self.env)
        for rel, content in (files or {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return root

    def cli(self, *args, cwd, env=None, cli=None):
        return subprocess.run(
            [sys.executable, str(cli or self.engine / "orchestrator.py"), *args],
            cwd=cwd, env={**self.env, **(env or {})},
            capture_output=True, text=True, timeout=120
        )

    def script(self, root, name, *args, stdin=None, env=None):
        return subprocess.run(
            [sys.executable, str(root / ".claude" / name), *args],
            cwd=root, env={**self.env, "CLAUDE_PROJECT_DIR": str(root), **(env or {})},
            input=stdin, capture_output=True, text=True, timeout=120
        )

    def ok(self, result, code=0):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def install(self, root):
        return self.ok(self.cli("init", cwd=root))

    def state(self, root):
        return self.home / ".local/state/claude-codex" / project_id(root)

    def registry(self):
        return json.loads((self.engine / "registry/projects.json").read_text())["projects"]

    def make_release(self, version, marker):
        source = self.engine / "releases" / RELEASE
        target = self.engine / "releases" / version
        shutil.copytree(source, target)
        script = target / "scripts/watchdog.py"
        script.write_text(script.read_text() + f"\n# release {marker}\n")
        (target / "VERSION").write_text(version + "\n")
        reseal(target)
        meta = json.loads((target / "release.json").read_text())
        meta.update({"version": version, "status": "VERIFIED"})
        (target / "release.json").write_text(json.dumps(meta))
        return target

    def seed_runtime_state(self, root):
        """Fake session mapping and archived workflow history to prove preservation."""
        state = self.state(root)
        (state / "tasks/history" / self.session).mkdir(parents=True, exist_ok=True)
        (state / f"{self.session}.json").write_text(json.dumps(
            {"claude_session_id": self.session, "codex_session_id": str(uuid.uuid4())}))
        (state / "tasks/history" / self.session / "wf.json").write_text('{"workflow_status": "FINISHED"}')

    def runtime_digest(self, root):
        state = self.state(root)
        return {
            str(p.relative_to(state)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in state.rglob("*.json")
            if p.parts[-2] != "integrity" and p.name != "profile-approvals.json"
        }


class InstallationTests(Base):

    def test_fresh_installation(self):
        root = self.project("fresh")
        result = self.install(root)
        self.assertIn("PROJECT_INITIALIZATION_SUCCESS", result.stdout)
        for rel in (".claude/scripts/codex-session.py", ".claude/hooks/completion-gate.py",
                    ".claude/orchestration.json", ".claude/orchestration-profiles.json",
                    ".claude/settings.local.json", "CLAUDE.md"):
            self.assertTrue((root / rel).is_file(), rel)
        self.assertEqual(stat.S_IMODE((root / ".claude/scripts/task-state.py").stat().st_mode), 0o700)
        self.ok(self.cli("verify", cwd=root))
        self.assertIn(project_id(root), self.registry())
        claude = (root / "CLAUDE.md").read_text()
        self.assertIn("Default Mode is Claude-only", claude)
        self.assertIn("Use Codex", claude)
        self.assertIn("Use Claude only", claude)

    def test_no_project_specific_leakage(self):
        root = self.project("leak")
        self.install(root)
        for path in (root / ".claude").rglob("*"):
            if path.is_file():
                text = path.read_text()
                self.assertNotIn("Project Rules", text, path)
                self.assertNotIn("LEGACY_CLAUDE_SESSION_ID", text, path)
                self.assertNotIn("frontend-browser", text, path)
        self.assertNotIn("Project Rules", (root / "CLAUDE.md").read_text())

    def test_dry_run_changes_nothing(self):
        root = self.project("dry", {"CLAUDE.md": "# Mine\n"})
        before = tree_digest(root)
        result = self.ok(self.cli("init", "--dry-run", cwd=root))
        self.assertEqual(json.loads(result.stdout)["profiles_approved"], 0)
        self.assertEqual(tree_digest(root), before)
        self.assertFalse(self.state(root).exists())

    def test_multiple_project_isolation(self):
        a = self.project("alpha", {"CLAUDE.md": "# Alpha only rule\n"})
        b = self.project("beta", {"CLAUDE.md": "# Beta only rule\n"})
        self.install(a)
        self.install(b)
        self.assertNotIn("Alpha only rule", (b / "CLAUDE.md").read_text())
        self.assertNotIn("Beta only rule", (a / "CLAUDE.md").read_text())
        self.assertNotEqual(self.state(a), self.state(b))
        manifest_a = json.loads((self.state(a) / "integrity/manifest.json").read_text())
        self.assertEqual(manifest_a["project"], str(a))
        self.assertEqual(len(self.registry()), 2)
        # tampering in A does not affect B
        (a / ".claude/scripts/watchdog.py").write_text("# tampered\n")
        self.ok(self.cli("verify", cwd=a), 1)
        self.ok(self.cli("verify", cwd=b))

    def test_preserves_existing_configuration(self):
        settings = {
            "permissions": {"allow": ["Bash(ls)"], "deny": ["Bash(rm *)"], "ask": ["Bash(curl *)"]},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo user-stop"}]}]},
            "env": {"KEEP": "1"},
        }
        root = self.project("keep", {
            "CLAUDE.md": "# Original rules\n\nNever touch prod.\n",
            "AGENTS.md": "# Agents\n",
            ".claude/settings.local.json": json.dumps(settings),
            ".claude/settings.json": '{"permissions": {"deny": ["Read(.env)"]}}\n',
            ".claude/.gitignore": "custom-ignore\n",
            "src/app.py": "print('app')\n",
        })
        shared_before = (root / ".claude/settings.json").read_bytes()
        app_before = (root / "src/app.py").read_bytes()
        agents_before = (root / "AGENTS.md").read_bytes()
        self.install(root)
        merged = json.loads((root / ".claude/settings.local.json").read_text())
        self.assertEqual(merged["permissions"]["deny"], ["Bash(rm *)"])
        self.assertEqual(merged["permissions"]["ask"], ["Bash(curl *)"])
        self.assertIn("Bash(ls)", merged["permissions"]["allow"])
        self.assertIn({"hooks": [{"type": "command", "command": "echo user-stop"}]}, merged["hooks"]["Stop"])
        self.assertEqual(merged["env"], {"KEEP": "1"})
        claude = (root / "CLAUDE.md").read_text()
        self.assertTrue(claude.startswith("# Original rules\n\nNever touch prod.\n"))
        self.assertIn("@AGENTS.md", claude)
        self.assertEqual((root / ".claude/settings.json").read_bytes(), shared_before)
        self.assertEqual((root / "src/app.py").read_bytes(), app_before)
        self.assertEqual((root / "AGENTS.md").read_bytes(), agents_before)
        self.assertTrue((root / ".claude/.gitignore").read_text().startswith("custom-ignore\n"))
        # uninstall restores the originals
        self.ok(self.cli("uninstall", "--apply", "--yes", cwd=root))
        self.assertEqual((root / "CLAUDE.md").read_text(), "# Original rules\n\nNever touch prod.\n")
        self.assertEqual(json.loads((root / ".claude/settings.local.json").read_text()), settings)
        self.assertEqual((root / ".claude/.gitignore").read_text(), "custom-ignore\n")
        self.assertEqual((root / ".claude/settings.json").read_bytes(), shared_before)

    def test_duplicate_installation_protection(self):
        root = self.project("dup")
        self.install(root)
        before = tree_digest(root)
        result = self.ok(self.cli("init", cwd=root), 3)
        self.assertIn("Existing orchestration detected", result.stderr)
        self.assertEqual(tree_digest(root), before)

    def test_existing_hooks_in_shared_settings_conflict(self):
        root = self.project("shared", {
            ".claude/settings.json": json.dumps({"hooks": {"Stop": [{"hooks": [{
                "type": "command", "command": "python3 .claude/hooks/completion-gate.py"}]}]}})
        })
        before = tree_digest(root)
        self.ok(self.cli("init", cwd=root), 3)
        self.assertEqual(tree_digest(root), before)

    def test_generic_stack_profiles(self):
        root = self.project("stacks", {
            "web/package.json": json.dumps({"scripts": {"build": "next build", "lint": "eslint",
                                                        "dev": "next dev", "test:e2e": "playwright"}}),
            "web/pnpm-lock.yaml": "",
            "api/artisan": "#!/usr/bin/env php\n",
            "api/composer.json": json.dumps({"require-dev": {"laravel/pint": "^1"}}),
            "svc/go.mod": "module example.com/svc\n",
            "tool/pyproject.toml": "[project]\nname='tool'\n",
            "Makefile": "test:\n\techo ok\n",
        })
        self.install(root)
        profiles = json.loads((root / ".claude/orchestration-profiles.json").read_text())["profiles"]
        self.assertEqual(profiles["web-build"]["command"], ["pnpm", "run", "build"])
        self.assertIn("web-test-e2e", profiles)
        self.assertNotIn("web-dev", profiles)
        self.assertEqual(profiles["api-artisan-test"]["command"], ["php", "artisan", "test"])
        self.assertIn("api-pint-test", profiles)
        self.assertEqual(profiles["svc-go-test"]["command"], ["go", "test", "./..."])
        self.assertIn("tool-pytest", profiles)
        self.assertIn("root-make-test", profiles)
        listed = [json.loads(line) for line in self.ok(self.cli("profiles", cwd=root)).stdout.splitlines()]
        self.assertTrue(listed and not any(p["approved"] for p in listed))


class RuntimeTests(Base):

    def test_generic_session_environment(self):
        root = self.project("env")
        self.install(root)
        env_file = self.tmp / "claude-env"
        session = str(uuid.uuid4())
        self.ok(self.script(root, "hooks/session-init.py", stdin=json.dumps({"session_id": session}),
                            env={"CLAUDE_ENV_FILE": str(env_file)}))
        self.assertEqual(env_file.read_text().strip(), f"export ORCHESTRATOR_CLAUDE_SESSION_ID='{session}'")
        missing = self.script(root, "scripts/task-state.py", "status",
                              env={"ORCHESTRATOR_CLAUDE_SESSION_ID": ""})
        self.assertNotEqual(missing.returncode, 0)

    def test_codex_session_mapping_isolation_mocked(self):
        a, b = self.project("map-a"), self.project("map-b")
        self.install(a)
        self.install(b)
        first = self.ok(self.script(a, "scripts/codex-session.py", "--sandbox", "read-only", "one"))
        self.assertIn("Action: CREATE", first.stdout)
        self.assertIn("FAKE-CODEX one", first.stdout)
        second = self.ok(self.script(a, "scripts/codex-session.py", "--sandbox", "read-only", "two"))
        self.assertIn("Action: RESUME", second.stdout)
        id_a = json.loads((self.state(a) / f"{self.session}.json").read_text())["codex_session_id"]
        self.assertIn(id_a, second.stdout)
        self.ok(self.script(b, "scripts/codex-session.py", "--sandbox", "read-only", "three"))
        id_b = json.loads((self.state(b) / f"{self.session}.json").read_text())["codex_session_id"]
        self.assertNotEqual(id_a, id_b)
        other = str(uuid.uuid4())
        third = self.ok(self.script(a, "scripts/codex-session.py", "--sandbox", "read-only", "x",
                                    env={"ORCHESTRATOR_CLAUDE_SESSION_ID": other}))
        self.assertIn("Action: CREATE", third.stdout)

    def test_completion_gate_behavior(self):
        root = self.project("gate")
        self.install(root)
        stop = json.dumps({"session_id": self.session, "stop_hook_active": False})
        self.assertEqual(self.ok(self.script(root, "hooks/completion-gate.py", stdin=stop)).stdout.strip(), "")
        self.ok(self.script(root, "scripts/task-state.py", "start"))
        self.ok(self.script(root, "scripts/task-state.py", "add", "--id", "T001", "--title", "x"))
        blocked = self.ok(self.script(root, "hooks/completion-gate.py", stdin=stop))
        self.assertEqual(json.loads(blocked.stdout)["decision"], "block")
        self.assertIn("T001", blocked.stdout)
        self.ok(self.script(root, "scripts/task-state.py", "pause"))
        self.assertEqual(self.ok(self.script(root, "hooks/completion-gate.py", stdin=stop)).stdout.strip(), "")
        self.ok(self.script(root, "scripts/task-state.py", "resume"))
        self.ok(self.script(root, "scripts/task-state.py", "update", "--id", "T001", "--state", "VERIFIED",
                            "--note", "done"))
        self.ok(self.script(root, "scripts/task-state.py", "finish"))
        self.assertEqual(self.ok(self.script(root, "hooks/completion-gate.py", stdin=stop)).stdout.strip(), "")

    def test_managed_execution_requires_approval(self):
        root = self.project("managed", {"Makefile": "test:\n\techo managed-ok\n"})
        self.install(root)
        dry = json.loads(self.ok(self.script(root, "scripts/managed-exec.py", "root-make-test", "--dry-run")).stdout)
        self.assertFalse(dry["approved"])
        self.ok(self.script(root, "scripts/managed-exec.py", "root-make-test"), 77)
        self.ok(self.cli("profile-approve", "root-make-test", cwd=root), 4)
        self.ok(self.cli("profile-approve", "root-make-test", "--yes", cwd=root))
        run = self.ok(self.script(root, "scripts/managed-exec.py", "root-make-test"))
        self.assertIn("managed-ok", run.stdout)
        # an approval for a different command definition is not honoured
        approvals = self.state(root) / "profile-approvals.json"
        approvals.write_text(json.dumps({"root-make-test": "0" * 64}))
        self.ok(self.script(root, "scripts/managed-exec.py", "root-make-test"), 77)
        # editing the profile file breaks integrity -> refused before running
        profiles = root / ".claude/orchestration-profiles.json"
        data = json.loads(profiles.read_text())
        data["profiles"]["root-make-test"]["command"] = ["sh", "-c", "echo pwned"]
        profiles.write_text(json.dumps(data))
        result = self.script(root, "scripts/managed-exec.py", "root-make-test")
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertNotIn("pwned", result.stdout)

    def test_global_registry_and_unregister(self):
        a, b = self.project("reg-a"), self.project("reg-b")
        self.install(a)
        self.install(b)
        projects = json.loads(self.ok(self.cli("projects", cwd=a)).stdout)["projects"]
        self.assertEqual({p["path"] for p in projects.values()}, {str(a), str(b)})
        before = tree_digest(a)
        self.ok(self.cli("unregister", cwd=a))
        self.assertNotIn(project_id(a), self.registry())
        self.assertIn(project_id(b), self.registry())
        self.assertEqual(tree_digest(a), before)
        self.ok(self.cli("unregister", "--id", project_id(b), cwd=self.tmp))
        self.assertEqual(self.registry(), {})
        self.ok(self.cli("unregister", "--id", "deadbeef", cwd=self.tmp), 1)

    def test_global_monitoring(self):
        a, b = self.project("mon-a"), self.project("mon-b")
        self.install(a)
        self.install(b)
        result = self.ok(self.cli("status", "--all", cwd=self.tmp))
        self.assertIn(str(a), result.stdout)
        self.assertIn(str(b), result.stdout)
        versions = json.loads(self.ok(self.cli("versions", cwd=a)).stdout)
        self.assertEqual(versions["this_project"]["version"], RELEASE)
        self.assertEqual(len(versions["projects"]), 2)
        self.ok(self.cli("doctor", cwd=a))


class LifecycleTests(Base):

    def test_backup_creation_and_verification(self):
        root = self.project("bk", {"CLAUDE.md": "# rules\n"})
        self.install(root)
        self.assertIn("BACKUP_CREATED", self.ok(self.cli("backup", cwd=root)).stdout)
        listing = json.loads(self.ok(self.cli("backups", cwd=root)).stdout)
        self.assertEqual({b["kind"] for b in listing["backups"]}, {"pre-install", "manual"})
        self.assertTrue(all(b["checksums"] == "PASS" for b in listing["backups"]))
        manual = sorted((self.engine / "backups/projects" / project_id(root)).glob("*-manual"))[0]
        (manual / "files/CLAUDE.md").write_text("tampered")
        self.ok(self.cli("backups", cwd=root), 6)
        before = tree_digest(root)
        self.ok(self.cli("rollback", "--apply", "--yes", "--backup", manual.name, cwd=root), 6)
        self.assertEqual(tree_digest(root), before)

    def test_update_and_rollback_preserve_runtime_state(self):
        root = self.project("upd", {"CLAUDE.md": "# keep\n"})
        self.install(root)
        self.seed_runtime_state(root)
        runtime = self.runtime_digest(root)
        installed_tree = tree_digest(root)
        self.make_release("9.9.9", "nine")
        check = json.loads(self.ok(self.cli("update", "--check", "--release", "9.9.9", cwd=root)).stdout)
        self.assertEqual((check["installed"], check["target"], check["conflicts"]), (RELEASE, "9.9.9", []))
        dry = json.loads(self.ok(self.cli("update", "--dry-run", "--release", "9.9.9", cwd=root)).stdout)
        self.assertIn("replace .claude/scripts/watchdog.py", dry["operations"])
        self.assertEqual(tree_digest(root), installed_tree)
        self.ok(self.cli("update", "--apply", "--release", "9.9.9", cwd=root), 4)
        self.assertEqual(tree_digest(root), installed_tree)
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))
        self.assertIn("# release nine", (root / ".claude/scripts/watchdog.py").read_text())
        self.ok(self.cli("verify", cwd=root))
        self.assertEqual(self.registry()[project_id(root)]["version"], "9.9.9")
        self.assertEqual(self.runtime_digest(root), runtime)
        self.assertEqual(self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))
                         .stdout.split(":")[0], "UP_TO_DATE")
        self.ok(self.cli("rollback", "--check", cwd=root))
        self.ok(self.cli("rollback", "--dry-run", cwd=root))
        self.ok(self.cli("rollback", "--apply", cwd=root), 4)
        self.ok(self.cli("rollback", "--apply", "--yes", cwd=root))
        self.assertEqual(tree_digest(root), installed_tree)
        self.ok(self.cli("verify", cwd=root))
        self.assertEqual(self.registry()[project_id(root)]["version"], RELEASE)
        self.assertEqual(self.runtime_digest(root), runtime)
        self.ok(self.cli("rollback", "--check", cwd=root), 1)

    def test_rollback_refuses_after_local_edits(self):
        root = self.project("edit", {"CLAUDE.md": "# keep\n"})
        self.install(root)
        self.make_release("9.9.9", "nine")
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))
        with (root / "CLAUDE.md").open("a") as handle:
            handle.write("\nlocal edit after update\n")
        before = tree_digest(root)
        self.ok(self.cli("rollback", "--apply", "--yes", cwd=root), 3)
        self.assertEqual(tree_digest(root), before)

    def test_unverified_release_refused(self):
        root = self.project("unv")
        self.install(root)
        target = self.make_release("9.9.8", "unverified")
        meta = json.loads((target / "release.json").read_text())
        meta["status"] = "TESTING"
        (target / "release.json").write_text(json.dumps(meta))
        before = tree_digest(root)
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.8", cwd=root), 3)
        self.assertEqual(tree_digest(root), before)

    @unittest.skipUnless(LEGACY_CLI, "legacy 4.0.0 CLI backup unavailable")
    def test_legacy_400_install_update_rollback_uninstall(self):
        original_claude = "# Legacy project\n"
        original_settings = {"permissions": {"deny": ["Bash(rm *)"]}}
        root = self.project("legacy", {
            "CLAUDE.md": original_claude,
            ".claude/settings.local.json": json.dumps(original_settings),
            "package.json": json.dumps({"scripts": {"build": "tsc"}}),
        })
        shutil.copy2(LEGACY_CLI[-1], self.engine / "orchestrator_v400.py")
        self.ok(self.cli("init", cwd=root, cli=self.engine / "orchestrator_v400.py"))
        self.seed_runtime_state(root)
        runtime = self.runtime_digest(root)
        legacy_tree = tree_digest(root)
        self.ok(self.cli("update", "--check", "--release", RELEASE, cwd=root))
        self.ok(self.cli("update", "--apply", "--yes", "--release", RELEASE, cwd=root))
        claude = (root / "CLAUDE.md").read_text()
        self.assertEqual(claude.count("# Claude-Codex Orchestration V4"), 1)
        self.assertIn("<!-- BEGIN CLAUDE-CODEX ORCHESTRATION", claude)
        self.ok(self.cli("verify", cwd=root))
        profiles = json.loads((root / ".claude/orchestration-profiles.json").read_text())["profiles"]
        self.assertEqual(profiles["root-build"]["command"], ["npm", "run", "build"])
        self.assertEqual(self.runtime_digest(root), runtime)
        self.ok(self.cli("rollback", "--apply", "--yes", cwd=root))
        self.assertEqual(tree_digest(root), legacy_tree)
        self.ok(self.cli("verify", cwd=root))
        self.ok(self.cli("uninstall", "--apply", "--yes", cwd=root))
        self.assertEqual((root / "CLAUDE.md").read_text(), original_claude)
        self.assertEqual(json.loads((root / ".claude/settings.local.json").read_text()), original_settings)
        self.assertEqual(self.runtime_digest(root), runtime)

    def test_legacy_v3_project_is_never_modified(self):
        root = self.project("v3", {".claude/scripts/codex-session.py": "# v3\n", "CLAUDE.md": "# v3\n"})
        before = tree_digest(root)
        for args in (("update", "--apply", "--yes"), ("rollback", "--apply", "--yes"),
                     ("uninstall", "--apply", "--yes"), ("init",)):
            result = self.cli(*args, cwd=root)
            self.assertIn(result.returncode, (1, 3), args)
            self.assertEqual(tree_digest(root), before, args)

    def test_safe_uninstall(self):
        root = self.project("rm", {"src/main.go": "package main\n"})
        self.install(root)
        self.seed_runtime_state(root)
        runtime = self.runtime_digest(root)
        before = tree_digest(root)
        dry = json.loads(self.ok(self.cli("uninstall", "--dry-run", cwd=root)).stdout)
        self.assertIn(".claude/scripts/codex-session.py", dry["remove"])
        self.assertEqual(tree_digest(root), before)
        self.ok(self.cli("uninstall", "--apply", cwd=root), 4)
        self.assertEqual(tree_digest(root), before)
        self.ok(self.cli("uninstall", "--apply", "--yes", cwd=root))
        self.assertFalse((root / ".claude/scripts").exists())
        self.assertFalse((root / "CLAUDE.md").exists())
        self.assertFalse((root / ".claude/settings.local.json").exists())
        self.assertTrue((root / "src/main.go").is_file())
        self.assertNotIn(project_id(root), self.registry())
        self.assertEqual(self.runtime_digest(root), runtime)
        self.assertFalse((self.state(root) / "integrity/manifest.json").exists())
        self.install(root)  # reinstall works after uninstall


class SafetyTests(Base):

    def test_failed_installation_recovery(self):
        for point in ("install:after-scripts", "install:after-settings",
                      "install:after-instructions", "install:before-verify",
                      "install:before-register"):
            with self.subTest(point=point):
                root = self.project("fail-" + point.split(":")[1], {
                    "CLAUDE.md": "# Mine\n", ".claude/settings.local.json": '{"env": {"A": "1"}}'})
                before = tree_digest(root)
                result = self.cli("init", cwd=root, env={"ORCHESTRATOR_FAULT": point})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("rolled back", result.stderr)
                self.assertEqual(tree_digest(root), before)
                self.assertFalse((self.state(root) / "integrity/manifest.json").exists())
                self.assertNotIn(project_id(root), self.registry())
                self.install(root)

    def test_failed_update_and_uninstall_recovery(self):
        root = self.project("fail-upd", {"CLAUDE.md": "# Mine\n"})
        self.install(root)
        self.make_release("9.9.9", "nine")
        before = tree_digest(root)
        manifest = (self.state(root) / "integrity/manifest.json").read_bytes()
        for args, point in ((("update", "--apply", "--yes", "--release", "9.9.9"), "update:before-register"),
                            (("uninstall", "--apply", "--yes"), "uninstall:before-unregister")):
            result = self.cli(*args, cwd=root, env={"ORCHESTRATOR_FAULT": point})
            self.assertNotEqual(result.returncode, 0, point)
            self.assertEqual(tree_digest(root), before, point)
            self.assertEqual((self.state(root) / "integrity/manifest.json").read_bytes(), manifest)
            self.ok(self.cli("verify", cwd=root))

    @unittest.skipIf(os.getuid() == 0, "root ignores file permissions")
    def test_permission_errors(self):
        root = self.project("perm", {".claude/settings.local.json": "{}"})
        before = tree_digest(root)
        (root / ".claude").chmod(0o500)
        try:
            result = self.cli("init", cwd=root)
        finally:
            (root / ".claude").chmod(0o700)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(tree_digest(root), before)
        self.assertNotIn(project_id(root), self.registry())

    def test_world_writable_and_foreign_paths_rejected(self):
        root = self.project("ww", {"CLAUDE.md": "# x\n"})
        (root / "CLAUDE.md").chmod(0o666)
        before = tree_digest(root)
        self.ok(self.cli("init", cwd=root), 5)
        self.assertEqual(tree_digest(root), before)

    def test_symlink_attacks(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "victim.md").write_text("victim\n")
        cases = {
            "scripts-dir": (".claude/scripts", outside),
            "claude-md": ("CLAUDE.md", outside / "victim.md"),
            "settings": (".claude/settings.local.json", outside / "victim.md"),
            "claude-dir": (".claude", outside),
        }
        for name, (rel, target) in cases.items():
            with self.subTest(case=name):
                root = self.project("sym-" + name)
                link = root / rel
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target)
                outside_before = tree_digest(outside)
                project_before = tree_digest(root)
                result = self.cli("init", cwd=root)
                self.assertIn(result.returncode, (3, 5), result.stderr)
                self.assertEqual(tree_digest(outside), outside_before)
                self.assertEqual(tree_digest(root), project_before)
        # symlink planted inside a backup
        root = self.project("sym-backup")
        self.install(root)
        backup = next((self.engine / "backups/projects" / project_id(root)).glob("*-pre-install"))
        claude = backup / "files/.claude/settings.local.json"
        if claude.exists():
            claude.unlink()
        backup_files = backup / "files"
        backup_files.mkdir(exist_ok=True)
        record = json.loads((backup / "backup.json").read_text())
        record["files"]["CLAUDE.md"] = {"sha256": hashlib.sha256(b"victim\n").hexdigest(), "mode": 420}
        (backup / "backup.json").write_text(json.dumps(record))
        (backup_files / "CLAUDE.md").symlink_to(outside / "victim.md")
        self.ok(self.cli("backups", cwd=root), 6)

    def test_path_traversal(self):
        root = self.project("trav")
        self.install(root)
        self.ok(self.cli("init", "--release", "../../etc", cwd=self.project("trav2")), 1)
        # traversal inside a backup record
        backup = next((self.engine / "backups/projects" / project_id(root)).glob("*-pre-install"))
        record = json.loads((backup / "backup.json").read_text())
        record["files"]["../../escape.txt"] = None
        (backup / "backup.json").write_text(json.dumps(record))
        before = tree_digest(self.tmp / "projects")
        self.ok(self.cli("rollback", "--apply", "--yes", "--backup", backup.name, cwd=root), 5)
        self.assertEqual(tree_digest(self.tmp / "projects"), before)
        # traversal in an execution profile (attacker re-seals the manifest)
        profiles = root / ".claude/orchestration-profiles.json"
        profiles.write_text(json.dumps({"schema": 1, "profiles": {
            "escape": {"directory": "../..", "command": ["true"], "timeout": 5}}}))
        manifest_path = self.state(root) / "integrity/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][".claude/orchestration-profiles.json"] = hashlib.sha256(profiles.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        self.ok(self.cli("profile-approve", "escape", "--yes", cwd=root), 5)
        listed = self.ok(self.script(root, "scripts/managed-exec.py", "--list")).stdout
        self.assertNotIn("escape", listed)

    def test_integrity_violations(self):
        root = self.project("integ")
        self.install(root)
        (root / ".claude/scripts/usage-guard.py").write_text("print('evil')\n")
        self.ok(self.cli("verify", cwd=root), 1)
        self.assertIn("MODIFIED", self.ok(self.cli("update", "--check", cwd=root), 3).stdout)
        before = tree_digest(root)
        self.ok(self.cli("uninstall", "--apply", "--yes", cwd=root), 3)
        self.assertEqual(tree_digest(root), before)
        self.make_release("9.9.9", "nine")
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root), 3)
        self.assertEqual(tree_digest(root), before)
        self.assertEqual((root / ".claude/scripts/usage-guard.py").read_text(), "print('evil')\n")
        # extra unregistered script
        root2 = self.project("integ2")
        self.install(root2)
        (root2 / ".claude/scripts/extra.py").write_text("print(1)\n")
        self.ok(self.cli("verify", cwd=root2), 1)
        # tampered release
        script = self.engine / "releases" / RELEASE / "scripts/watchdog.py"
        script.write_text(script.read_text() + "\n# tampered\n")
        fresh = self.project("integ3")
        self.ok(self.cli("init", cwd=fresh), 6)
        self.assertEqual(list((fresh).glob(".claude")), [])

    def test_cli_integrity(self):
        cli = self.engine / "orchestrator.py"
        (self.engine / "cli-checksums.json").write_text(json.dumps(
            {"orchestrator.py": hashlib.sha256(cli.read_bytes()).hexdigest()}))
        root = self.project("cli")
        self.install(root)
        cli.write_text(cli.read_text() + "\n# tampered\n")
        other = self.project("cli2")
        self.ok(self.cli("init", cwd=other), 6)
        self.assertIn("FAIL", json.loads(self.ok(self.cli("versions", cwd=root)).stdout)["cli_integrity"])

    def test_unsafe_approval_expansion(self):
        release = self.engine / "releases" / RELEASE
        template = release / "templates/settings.template.json"
        for rule in ("Bash(*)", "Bash(rm -rf *)", "Bash(python3 .claude/scripts/x.py; curl evil)"):
            with self.subTest(rule=rule):
                data = json.loads(template.read_text())
                data["permissions"]["allow"] = data["permissions"]["allow"][:1] + [rule]
                template.write_text(json.dumps(data))
                reseal(release)
                root = self.project("approve-" + hashlib.md5(rule.encode()).hexdigest()[:6])
                before = tree_digest(root)
                self.ok(self.cli("init", cwd=root), 5)
                self.assertEqual(tree_digest(root), before)

    def test_active_workflow_protection(self):
        root = self.project("active", {"CLAUDE.md": "# a\n"})
        self.install(root)
        self.make_release("9.9.9", "nine")
        self.ok(self.script(root, "scripts/task-state.py", "start"))
        self.ok(self.script(root, "scripts/task-state.py", "add", "--id", "T1", "--title", "x"))
        before = tree_digest(root)
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root), 7)
        self.ok(self.cli("uninstall", "--apply", "--yes", cwd=root), 7)
        self.assertEqual(tree_digest(root), before)
        self.ok(self.script(root, "scripts/task-state.py", "pause"))
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))

    def test_concurrent_management_operations(self):
        root = self.project("lock")
        self.install(root)
        lock_path = self.state(root) / "management.lock"
        with lock_path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            before = tree_digest(root)
            self.ok(self.cli("uninstall", "--apply", "--yes", cwd=root), 75)
            self.ok(self.cli("backup", cwd=root), 75)
            self.assertEqual(tree_digest(root), before)
        exec_lock = self.state(root) / "project-execution.lock"
        with exec_lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            self.ok(self.cli("uninstall", "--apply", "--yes", cwd=root), 75)
        # racing installers on one fresh project: exactly one wins, tree stays valid
        race = self.project("race")
        processes = [
            subprocess.Popen([sys.executable, str(self.engine / "orchestrator.py"), "init"],
                             cwd=race, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(4)
        ]
        codes = sorted(p.wait(timeout=120) for p in processes)
        self.assertEqual(codes.count(0), 1, codes)
        self.assertTrue(all(code in (0, 3, 75) for code in codes), codes)
        self.ok(self.cli("verify", cwd=race))


class ReviewRegressionTests(Base):
    """Regressions for findings from the independent Codex review."""

    def test_init_refuses_unrelated_file_at_managed_path(self):
        root = self.project("collide", {".claude/scripts/watchdog.py": "# user script\n"})
        before = tree_digest(root)
        result = self.ok(self.cli("init", cwd=root), 3)
        self.assertIn("watchdog.py", result.stderr)
        self.assertEqual(tree_digest(root), before)

    def test_state_directory_symlink_refused(self):
        root = self.project("statesym")
        outside = self.tmp / "outside-state"
        outside.mkdir()
        state = self.state(root)
        state.mkdir(parents=True)
        (state / "integrity").symlink_to(outside)
        before = tree_digest(root)
        self.ok(self.cli("init", cwd=root), 5)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(tree_digest(root), before)

    def test_update_with_new_script_rolls_back_cleanly(self):
        root = self.project("newscript")
        self.install(root)
        installed = tree_digest(root)
        target = self.make_release("9.9.9", "nine")
        (target / "scripts/new-tool.py").write_text("print('new')\n")
        manifest = json.loads((target / "checksums.json").read_text())
        manifest["scripts/new-tool.py"] = ""
        (target / "checksums.json").write_text(json.dumps(manifest))
        reseal(target)
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))
        self.assertTrue((root / ".claude/scripts/new-tool.py").is_file())
        self.ok(self.cli("rollback", "--apply", "--yes", cwd=root))
        self.assertFalse((root / ".claude/scripts/new-tool.py").exists())
        self.assertEqual(tree_digest(root), installed)

    def test_update_refuses_unmanaged_file_at_new_release_path(self):
        root = self.project("newcollide")
        self.install(root)
        target = self.make_release("9.9.9", "nine")
        (target / "scripts/new-tool.py").write_text("print('release')\n")
        manifest = json.loads((target / "checksums.json").read_text())
        manifest["scripts/new-tool.py"] = ""
        (target / "checksums.json").write_text(json.dumps(manifest))
        reseal(target)
        (root / ".claude/scripts/new-tool.py").write_text("print('user owned')\n")
        (root / ".claude/scripts/new-tool.py").chmod(0o700)
        before = tree_digest(root)
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root), 3)
        self.assertEqual(tree_digest(root), before)

    def test_failed_update_backup_not_selected_for_rollback(self):
        root = self.project("failsel")
        self.install(root)
        self.make_release("9.9.9", "nine")
        self.assertNotEqual(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root,
                                     env={"ORCHESTRATOR_FAULT": "update:before-register"}).returncode, 0)
        result = self.ok(self.cli("rollback", "--check", cwd=root), 1)
        self.assertIn("No pre-update backup", result.stderr)

    def test_failed_rollback_keeps_backup_eligible(self):
        root = self.project("failrb")
        self.install(root)
        self.make_release("9.9.9", "nine")
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))
        updated = tree_digest(root)
        self.assertNotEqual(self.cli("rollback", "--apply", "--yes", cwd=root,
                                     env={"ORCHESTRATOR_FAULT": "rollback:before-register"}).returncode, 0)
        self.assertEqual(tree_digest(root), updated)
        self.ok(self.cli("rollback", "--apply", "--yes", cwd=root))

    def test_rollback_detects_deleted_user_file(self):
        root = self.project("deleted", {"CLAUDE.md": "# keep\n"})
        self.install(root)
        self.make_release("9.9.9", "nine")
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))
        (root / "CLAUDE.md").unlink()
        result = self.ok(self.cli("rollback", "--check", cwd=root), 3)
        self.assertIn("CLAUDE.md: DELETED_SINCE_UPDATE", result.stdout)
        self.ok(self.cli("rollback", "--apply", "--yes", cwd=root), 3)
        self.assertFalse((root / "CLAUDE.md").exists())

    def test_manual_backup_restore_lists_overwrites(self):
        root = self.project("manual", {"CLAUDE.md": "# keep\n"})
        self.install(root)
        self.ok(self.cli("backup", cwd=root))
        with (root / "CLAUDE.md").open("a") as handle:
            handle.write("later edit\n")
        manual = sorted((self.engine / "backups/projects" / project_id(root)).glob("*-manual"))[0]
        report = json.loads(self.ok(self.cli("rollback", "--check", "--backup", manual.name, cwd=root)).stdout)
        self.assertEqual(report["overwrites_current_files"], ["CLAUDE.md"])

    def test_identical_unmanaged_file_at_new_path_is_conflict(self):
        root = self.project("identical")
        self.install(root)
        target = self.make_release("9.9.9", "nine")
        (target / "scripts/new-tool.py").write_text("print('same')\n")
        manifest = json.loads((target / "checksums.json").read_text())
        manifest["scripts/new-tool.py"] = ""
        (target / "checksums.json").write_text(json.dumps(manifest))
        reseal(target)
        user = root / ".claude/scripts/new-tool.py"
        user.write_text("print('same')\n")
        user.chmod(0o700)
        before = tree_digest(root)
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root), 3)
        self.assertEqual(tree_digest(root), before)

    def test_manual_backup_apply_requires_overwrite_confirmation(self):
        root = self.project("manual-apply", {"CLAUDE.md": "# keep\n"})
        self.install(root)
        self.ok(self.cli("backup", cwd=root))
        with (root / "CLAUDE.md").open("a") as handle:
            handle.write("later edit\n")
        manual = sorted((self.engine / "backups/projects" / project_id(root)).glob("*-manual"))[0]
        before = tree_digest(root)
        self.ok(self.cli("rollback", "--apply", "--yes", "--backup", manual.name, cwd=root), 4)
        self.assertEqual(tree_digest(root), before)
        self.ok(self.cli("rollback", "--apply", "--yes", "--overwrite-edits", "--backup", manual.name, cwd=root))
        self.assertEqual((root / "CLAUDE.md").read_text().count("later edit"), 0)

    def test_rollback_continues_past_state_symlink(self):
        root = self.project("txn-sym")
        self.install(root)
        self.make_release("9.9.9", "nine")
        integrity = self.state(root) / "integrity"
        outside = self.tmp / "outside-integrity"
        shutil.copytree(integrity, outside)
        shutil.rmtree(integrity)
        integrity.symlink_to(outside)
        outside_before = tree_digest(outside)
        before = tree_digest(root)
        result = self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root)
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(tree_digest(root), before)
        self.assertEqual(tree_digest(outside), outside_before)

    def test_update_does_not_regrant_revoked_permissions(self):
        root = self.project("revoke")
        self.install(root)
        settings_path = root / ".claude/settings.local.json"
        settings = json.loads(settings_path.read_text())
        revoked = "Bash(python3 .claude/scripts/watchdog.py *)"
        settings["permissions"]["allow"].remove(revoked)
        settings_path.write_text(json.dumps(settings))
        self.make_release("9.9.9", "nine")
        self.ok(self.cli("update", "--apply", "--yes", "--release", "9.9.9", cwd=root))
        self.assertNotIn(revoked, json.loads(settings_path.read_text())["permissions"]["allow"])

    def test_update_from_400_drops_git_wildcards(self):
        if not LEGACY_CLI:
            self.skipTest("legacy CLI unavailable")
        root = self.project("gitwild")
        shutil.copy2(LEGACY_CLI[-1], self.engine / "orchestrator_v400.py")
        self.ok(self.cli("init", cwd=root, cli=self.engine / "orchestrator_v400.py"))
        self.ok(self.cli("update", "--apply", "--yes", "--release", RELEASE, cwd=root))
        allow = json.loads((root / ".claude/settings.local.json").read_text())["permissions"]["allow"]
        self.assertFalse([rule for rule in allow if rule.startswith("Bash(git diff")], allow)

    def test_write_capable_rules_rejected(self):
        release = self.engine / "releases" / RELEASE
        template = release / "templates/settings.template.json"
        for rule in ("Bash(git diff *)", "Bash(git log *)", "Bash(python3 .claude/scripts/evil.py *)"):
            with self.subTest(rule=rule):
                data = json.loads(template.read_text())
                data["permissions"]["allow"] = [rule]
                template.write_text(json.dumps(data))
                reseal(release)
                root = self.project("rule-" + hashlib.md5(rule.encode()).hexdigest()[:6])
                self.ok(self.cli("init", cwd=root), 5)


class ReleaseTests(Base):

    def test_release_promotion_requires_passing_report(self):
        version = "9.9.7"
        target = self.make_release(version, "promote")
        meta = json.loads((target / "release.json").read_text())
        meta["status"] = "TESTING"
        (target / "release.json").write_text(json.dumps(meta))
        cli = self.engine / "orchestrator.py"
        good = {
            "status": "PASS", "failures": 0, "errors": 0, "tests_run": 1, "release": version,
            "release_checksums_sha256": hashlib.sha256((target / "checksums.json").read_bytes()).hexdigest(),
            "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
        }
        report = self.tmp / "report.json"
        report.write_text(json.dumps({**good, "status": "FAIL", "failures": 1}))
        self.ok(self.cli("release-promote", version, "--test-report", str(report), "--yes", cwd=self.tmp), 6)
        report.write_text(json.dumps({**good, "release_checksums_sha256": "0" * 64}))
        self.ok(self.cli("release-promote", version, "--test-report", str(report), "--yes", cwd=self.tmp), 6)
        self.assertEqual(json.loads((target / "release.json").read_text())["status"], "TESTING")
        report.write_text(json.dumps(good))
        self.ok(self.cli("release-promote", version, "--test-report", str(report), "--yes", cwd=self.tmp))
        self.assertEqual(json.loads((target / "release.json").read_text())["status"], "VERIFIED")
        self.assertEqual(json.loads((self.engine / "current.json").read_text())["version"], version)
        self.assertTrue((self.engine / "cli-checksums.json").is_file())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report")
    parser.add_argument("-k", dest="pattern")
    options, rest = parser.parse_known_args()
    loader = unittest.TestLoader()
    if options.pattern:
        loader.testNamePatterns = [f"*{options.pattern}*"]
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    started = time.time()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if options.report:
        release_dir = ENGINE / "releases" / RELEASE
        report = {
            "status": "PASS" if result.wasSuccessful() and not result.skipped else "FAIL",
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": [str(test) for test, _ in result.skipped],
            "release": RELEASE,
            "release_checksums_sha256": hashlib.sha256((release_dir / "checksums.json").read_bytes()).hexdigest(),
            "cli_sha256": hashlib.sha256(CLI.read_bytes()).hexdigest(),
            "cli_path": str(CLI),
            "duration_seconds": round(time.time() - started, 2),
            "execution": "automated; Codex replaced by a fake executable; no live Claude/Codex calls",
        }
        Path(options.report).write_text(json.dumps(report, indent=2) + "\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
