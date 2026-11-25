#!/usr/bin/env python3
"""Claude-Codex Global Orchestrator: project installation and management CLI.

Every command that replaces or removes project files requires --yes.
State (session mappings, workflows, logs) lives under
~/.local/state/claude-codex/<project-id>/ and is never removed by this CLI.
"""

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import ccx_platform as platform_api
import ccx_platform as fcntl

os.umask(0o077)

CLI_VERSION = "4.1.0"
ENGINE_VERSION = "4.3.0"

GLOBAL = Path(__file__).resolve().parent
RELEASES = GLOBAL / "releases"
REGISTRY = GLOBAL / "registry/projects.json"
CURRENT_FILE = GLOBAL / "current.json"
CLI_CHECKSUMS = GLOBAL / "cli-checksums.json"
PROJECT_BACKUPS = GLOBAL / "backups/projects"
STATE_ROOT = platform_api.state_root().resolve()

BLOCK_BEGIN = "<!-- BEGIN CLAUDE-CODEX ORCHESTRATION (managed by orchestrator; edits inside are replaced on update) -->"
BLOCK_END = "<!-- END CLAUDE-CODEX ORCHESTRATION -->"
IGNORE_BEGIN = "# BEGIN claude-codex-orchestration"
IGNORE_END = "# END claude-codex-orchestration"
LEGACY_400_HEADING = "# Claude-Codex Orchestration V4"

MANAGED_CONFIG = (
    ".claude/orchestration.json",
    ".claude/orchestration-profiles.json",
    ".claude/settings.template.json",
)
USER_FILES = (
    "CLAUDE.md",
    ".claude/settings.local.json",
    ".claude/.gitignore",
)
STATE_FILES = (
    "integrity/manifest.json",
    "profile-approvals.json",
)

EXIT_CONFLICT = 3
EXIT_CONFIRM = 4
EXIT_UNSAFE = 5
EXIT_INTEGRITY = 6
EXIT_ACTIVE = 7
EXIT_BUSY = 75

SAFE_ALLOW_RULE = re.compile(
    r"^Bash\((?:"
    r"git status|git branch --show-current"
    r"|python3? (?:-B )?\.claude/scripts/(?P<script>[a-z][a-z-]*\.py)(?: --?[a-z][a-z-]*)*(?: \*)?"
    r")\)$"
)
SAFE_HOOK_COMMAND = re.compile(
    r'^python3? (?:-B )?"\$CLAUDE_PROJECT_DIR/\.claude/hooks/[a-z][a-z-]*\.py"$'
)


class OrchestratorError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    return sha256_bytes(path.read_bytes())


def fault(point):
    """Test hook: raise at a named point when ORCHESTRATOR_FAULT matches."""
    if os.environ.get("ORCHESTRATOR_FAULT") == point:
        raise RuntimeError(f"Injected fault at {point}")


# ---------------------------------------------------------------- filesystem

def fsync_dir(directory):
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def assert_canonical_parent(path):
    """Reject a path whose directory chain contains a symlink (checked immediately before use)."""
    parent = os.path.abspath(path.parent)
    if os.path.normcase(os.path.realpath(parent)) != os.path.normcase(parent):
        raise OrchestratorError(f"Symlink in directory chain: {path}", EXIT_UNSAFE)
    if platform_api.is_link(path):
        raise OrchestratorError(f"Refusing to use symlink: {path}", EXIT_UNSAFE)


def atomic_write(path, data, mode=0o600):
    if isinstance(data, str):
        data = data.encode()
    assert_canonical_parent(path)
    security = platform_api.capture_security(path) if path.exists() else None
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".orchestrator-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        platform_api.secure_mode(Path(temp), mode)
        if security is not None:
            platform_api.restore_security(Path(temp), security)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    fsync_dir(path.parent)


def write_json(path, data, mode=0o600):
    platform_api.secure_mkdir(path.parent, parents=True, exist_ok=True, mode=0o700)
    atomic_write(path, json.dumps(data, indent=2) + "\n", mode)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def relative_parts(rel):
    try:
        return platform_api.validate_relative(rel)
    except (ValueError, OSError) as error:
        raise OrchestratorError(f"Unsafe relative path: {rel}: {error}", EXIT_UNSAFE)


def safe_target(base, rel):
    """Return base/rel after rejecting traversal, symlinks and foreign owners."""
    rel_path = relative_parts(rel)
    current = base
    if platform_api.is_link(base):
        raise OrchestratorError(f"Unsafe symlink: {base}", EXIT_UNSAFE)
    for part in rel_path.parts:
        current = current / part
        if platform_api.is_link(current):
            raise OrchestratorError(f"Unsafe symlink: {current}", EXIT_UNSAFE)
        if current.exists():
            platform_api.validate_owner(current)
            platform_api.validate_permissions(current, mask=0o002)
    resolved_base = base.resolve()
    if current.exists() and resolved_base not in current.resolve().parents:
        raise OrchestratorError(f"Path escapes {base}: {rel}", EXIT_UNSAFE)
    return current


class Transaction:
    """Records original bytes of every touched path and restores them on failure."""

    def __init__(self):
        self.originals = {}
        self.created_dirs = []

    def remember(self, path):
        if path in self.originals:
            return
        if platform_api.is_link(path):
            raise OrchestratorError(f"Unsafe symlink: {path}", EXIT_UNSAFE)
        if path.exists():
            self.originals[path] = (
                path.read_bytes(), stat.S_IMODE(path.stat().st_mode),
                platform_api.capture_security(path)
            )
        else:
            self.originals[path] = None

    def ensure_dir(self, directory):
        missing = []
        probe = directory
        while not probe.exists() and not platform_api.is_link(probe):
            missing.append(probe)
            probe = probe.parent
        if os.path.normcase(os.path.realpath(probe)) != os.path.normcase(os.path.abspath(probe)):
            raise OrchestratorError(f"Symlink in directory chain: {probe}", EXIT_UNSAFE)
        for entry in reversed(missing):
            platform_api.secure_mkdir(entry, mode=0o700)
            self.created_dirs.append(entry)

    def write(self, path, data, mode=0o600):
        self.ensure_dir(path.parent)
        assert_canonical_parent(path)
        self.remember(path)
        atomic_write(path, data, mode)

    def remove(self, path):
        assert_canonical_parent(path)
        self.remember(path)
        if path.exists():
            path.unlink()

    def rollback(self):
        errors = []
        for path, original in reversed(list(self.originals.items())):
            try:
                if original is None:
                    assert_canonical_parent(path)
                    path.unlink(missing_ok=True)
                else:
                    platform_api.secure_mkdir(path.parent, parents=True, exist_ok=True, mode=0o700)
                    atomic_write(path, original[0], original[1])
                    platform_api.restore_security(path, original[2])
            except Exception as error:  # keep restoring the remaining paths
                errors.append(f"{path}: {error}")
        for directory in reversed(self.created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        return errors


# ---------------------------------------------------------------- projects

def git_toplevel(start):
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise OrchestratorError("Run inside a Git project (or pass --project).")
    return Path(result.stdout.strip()).resolve()


def resolve_project(args):
    start = Path(getattr(args, "project", None) or os.getcwd())
    if not start.is_dir():
        raise OrchestratorError(f"Project directory unavailable: {start}")
    root = git_toplevel(start)
    platform_api.validate_owner(root)
    if os.name == "nt":
        platform_api.validate_permissions(root)
    return root


def project_id(root):
    return hashlib.sha256(str(root).encode()).hexdigest()[:16]


def state_dir(root):
    return STATE_ROOT / project_id(root)


class ProjectLocks:
    """Exclusive management lock plus a non-blocking probe of the execution lock."""

    def __init__(self, root, hold_execution=True, cleanup_created=False):
        self.directory = state_dir(root)
        self.hold_execution = hold_execution
        self.handles = []
        self.cleanup_created = cleanup_created and os.name != "nt"  # Windows lock names remain stable.
        self.created_locks = []

    def __enter__(self):
        platform_api.secure_mkdir(self.directory, parents=True, exist_ok=True, mode=0o700)
        names = ["management.lock"]
        if self.hold_execution:
            names.append("project-execution.lock")
        try:
            for name in names:
                path = self.directory / name
                if platform_api.is_link(path):
                    raise OrchestratorError(f"Unsafe lock file: {path}", EXIT_UNSAFE)
                existed = path.exists()
                handle = path.open("a")
                if os.name == "nt":
                    platform_api.validate_permissions(path)
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    self.__exit__(None, None, None)
                    raise OrchestratorError(
                        f"PROJECT_BUSY: {name} is held by another operation.",
                        EXIT_BUSY
                    )
                if not existed and self.cleanup_created:
                    self.created_locks.append((path, os.fstat(handle.fileno()).st_ino))
                self.handles.append(handle)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        for path, inode in self.created_locks:
            if not platform_api.is_link(path) and path.exists() and path.stat().st_ino == inode:
                path.unlink()
        self.created_locks = []
        for handle in self.handles:
            handle.close()
        self.handles = []


def active_workflows(root):
    active = []
    for path in sorted((state_dir(root) / "tasks").glob("*.json")):
        data = read_json(path, {}) or {}
        if data.get("active") and data.get("workflow_status") == "RUNNING":
            active.append(data.get("workflow_id") or path.stem)
    return active


def require_no_active_workflow(root):
    active = active_workflows(root)
    if active:
        raise OrchestratorError(
            "ACTIVE_WORKFLOW: finish or pause workflows first: " + ", ".join(active),
            EXIT_ACTIVE
        )


def project_config(root):
    path = root / ".claude/orchestration.json"
    if platform_api.is_link(path):
        raise OrchestratorError(f"Unsafe symlink: {path}", EXIT_UNSAFE)
    return read_json(path)


def installed_version(root):
    config = project_config(root)
    if config:
        return config.get("version")
    if (root / ".claude/scripts/codex-session.py").exists():
        return "3"
    return None


def require_managed_install(root):
    config = project_config(root)
    if not config:
        if installed_version(root) == "3":
            raise OrchestratorError(
                "LEGACY_V3_PROJECT: use migrate-v3; no files changed.",
                EXIT_CONFLICT
            )
        raise OrchestratorError("Orchestration is not installed in this project.")
    if config.get("project") != str(root):
        raise OrchestratorError("Project path does not match installation record.", EXIT_CONFLICT)
    return config


# ---------------------------------------------------------------- releases

def release_dir(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
        raise OrchestratorError(f"Invalid release version: {version}")
    return RELEASES / version


def release_metadata(version):
    return read_json(release_dir(version) / "release.json", {}) or {}


def all_releases():
    found = []
    for path in RELEASES.iterdir() if RELEASES.is_dir() else []:
        if path.is_dir() and not platform_api.is_link(path) and re.fullmatch(r"\d+\.\d+\.\d+", path.name):
            found.append(path.name)
    return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")))


def current_release():
    data = read_json(CURRENT_FILE)
    if data and data.get("version"):
        return data["version"]
    verified = [v for v in all_releases() if release_metadata(v).get("status") == "VERIFIED"]
    return verified[-1] if verified else "4.1.0"


def runtime_supported(version):
    """Legacy payloads require Linux even when their integrity is verified."""
    return sys.platform.startswith("linux") or version not in ("4.0.0", "4.1.0")


def require_runtime_supported(version):
    if not runtime_supported(version):
        raise OrchestratorError(
            f"Release {version} payload requires Linux. "
            "Evaluate 4.3.0 explicitly with --release 4.3.0 --allow-unverified. "
            "No files changed.", EXIT_CONFLICT
        )


def verify_release(version):
    directory = release_dir(version)
    if not directory.is_dir() or platform_api.is_link(directory):
        raise OrchestratorError(f"Release unavailable: {version}", EXIT_INTEGRITY)
    manifest = read_json(directory / "checksums.json")
    if not manifest:
        raise OrchestratorError(f"Release checksums missing: {version}", EXIT_INTEGRITY)
    for name, expected in manifest.items():
        path = directory / relative_parts(name)
        if platform_api.is_link(path) or not path.is_file() or digest(path) != expected:
            raise OrchestratorError(f"Release integrity mismatch: {version}/{name}", EXIT_INTEGRITY)
    for folder in ("scripts", "hooks"):
        for path in (directory / folder).glob("*"):
            if path.is_file() and f"{folder}/{path.name}" not in manifest:
                raise OrchestratorError(f"Unregistered release file: {version}/{folder}/{path.name}", EXIT_INTEGRITY)
    return manifest


def release_payload(version):
    directory = release_dir(version)
    return {
        f".claude/{folder}/{path.name}": path
        for folder in ("scripts", "hooks")
        for path in sorted((directory / folder).glob("*.py"))
    }


def verify_cli():
    expected = read_json(CLI_CHECKSUMS)
    if not expected:
        return "UNSEALED"
    actual = digest(Path(__file__).resolve())
    if expected.get("orchestrator.py") != actual:
        raise OrchestratorError("CLI integrity mismatch: orchestrator.py", EXIT_INTEGRITY)
    return "PASS"


def preflight(version):
    verify_cli()
    verify_release(version)


def validate_template_settings(template, scripts=None):
    permissions = template.get("permissions", {})
    if set(permissions) - {"allow"}:
        raise OrchestratorError("Template may only add allow rules.", EXIT_UNSAFE)
    for rule in permissions.get("allow", []):
        match = SAFE_ALLOW_RULE.match(rule)
        if not match or (scripts is not None and match.group("script")
                         and match.group("script") not in scripts):
            raise OrchestratorError(f"Unsafe approval rule in release template: {rule}", EXIT_UNSAFE)
    for event, definitions in template.get("hooks", {}).items():
        if event not in ("SessionStart", "Stop"):
            raise OrchestratorError(f"Unexpected hook event in template: {event}", EXIT_UNSAFE)
        for definition in definitions:
            for hook in definition.get("hooks", []):
                if not SAFE_HOOK_COMMAND.match(hook.get("command", "")):
                    raise OrchestratorError(f"Unsafe hook command in template: {hook}", EXIT_UNSAFE)
    return template


def template_settings(version):
    template = json.loads((release_dir(version) / "templates/settings.template.json").read_text(encoding="utf-8"))
    # Native Windows installations commonly expose python.exe, not python3.
    # Keep the explicit Bash hook environment contract while resolving Python.
    if os.name == "nt" and version == "4.3.0" and shutil.which("python"):
        template["permissions"]["allow"] = [rule.replace("Bash(python3 ", "Bash(python ")
                                                 for rule in template["permissions"].get("allow", [])]
        for definitions in template.get("hooks", {}).values():
            for definition in definitions:
                for hook in definition.get("hooks", []):
                    hook["command"] = hook["command"].replace("python3 ", "python ", 1)
    return validate_template_settings(template,
        scripts={path.name for path in (release_dir(version) / "scripts").glob("*.py")})


def instruction_block(version, root, existing_text=None):
    body = (release_dir(version) / "templates/CLAUDE.md").read_text(encoding="utf-8").strip()
    if os.name == "nt" and version == "4.3.0" and shutil.which("python"):
        body = body.replace("python3 -B .claude/", "python -B .claude/").replace("python3 .claude/", "python .claude/")
    lines = [BLOCK_BEGIN]
    agents = root / "AGENTS.md"
    claude = root / "CLAUDE.md"
    existing = existing_text if existing_text is not None else (
        claude.read_text(encoding="utf-8") if claude.is_file() and not platform_api.is_link(claude) else "")
    existing, _ = strip_block(existing, BLOCK_BEGIN, BLOCK_END)
    legacy = legacy_400_block()
    if legacy:
        existing = existing.replace(legacy, "")
    if agents.is_file() and "@AGENTS.md" not in existing:
        lines.append("@AGENTS.md")
        lines.append("")
    lines.append(body)
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def ignore_block(version):
    body = (release_dir(version) / "templates/.gitignore").read_text(encoding="utf-8").strip()
    return f"{IGNORE_BEGIN}\n{body}\n{IGNORE_END}\n"


def legacy_400_block():
    """Rendered 4.0.0 instruction section, or None when release 4.0.0 is not installed."""
    path = RELEASES / "4.0.0/templates/CLAUDE.md"
    if not path.is_file():
        return None
    template = path.read_text(encoding="utf-8")
    template = re.split(r"^## 15\. [^\n]*Project Rules$", template, maxsplit=1, flags=re.M)[0]
    template = template.replace("@AGENTS.md", "", 1).strip()
    return template.replace("Orchestration V3", "Orchestration V4")


# ---------------------------------------------------------------- instructions / settings edits

def strip_block(text, begin, end):
    start = text.find(begin)
    if start < 0:
        return text, False
    stop = text.find(end, start)
    if stop < 0:
        raise OrchestratorError("Unterminated orchestration block.", EXIT_CONFLICT)
    stop += len(end)
    before = text[:start].rstrip("\n")
    after = text[stop:].lstrip("\n")
    joined = before + ("\n\n" if before and after else "\n" if before else "") + after
    return joined, True


def strip_legacy_400_instructions(text):
    """Remove the unmarked block appended by the 4.0.0 installer."""
    index = text.find(LEGACY_400_HEADING)
    if index < 0:
        return text, False
    block = text[index:].strip()
    if block != legacy_400_block():  # also a conflict when release 4.0.0 is unavailable
        raise OrchestratorError(
            "CLAUDE.md orchestration section was edited; resolve manually.",
            EXIT_CONFLICT
        )
    return text[:index].rstrip() + ("\n" if text[:index].strip() else ""), True


def apply_instruction_block(text, block):
    text, _ = strip_block(text, BLOCK_BEGIN, BLOCK_END)
    text, _ = strip_legacy_400_instructions(text)
    text = text.rstrip()
    return (text + "\n\n" if text else "") + block


def apply_ignore_block(text, block, legacy_template=None):
    text, _ = strip_block(text, IGNORE_BEGIN, IGNORE_END)
    if legacy_template and text.rstrip().endswith(legacy_template.rstrip()):
        text = text.rstrip()[: -len(legacy_template.rstrip())]
    text = text.rstrip()
    return (text + "\n" if text else "") + block


def load_settings(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise OrchestratorError(f"Invalid JSON, no files changed: {path}", EXIT_CONFLICT)
    if not isinstance(data, dict):
        raise OrchestratorError(f"Unexpected settings structure: {path}", EXIT_CONFLICT)
    return data


def merge_settings(settings, template):
    added = {"allow": [], "hooks": {}}
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    for rule in template.get("permissions", {}).get("allow", []):
        if rule not in allow:
            allow.append(rule)
            added["allow"].append(rule)
    hooks = settings.setdefault("hooks", {})
    for event, definitions in template.get("hooks", {}).items():
        current = hooks.setdefault(event, [])
        for definition in definitions:
            if definition not in current:
                current.append(definition)
                added["hooks"].setdefault(event, []).append(definition)
    return added


def reconcile_settings(settings, old_template, new_template, previous_added):
    """Update without re-granting entries the user removed.

    Adds only entries introduced by the new template, removes installer-owned
    entries the new template dropped, and leaves everything else untouched.
    """
    old_allow = old_template.get("permissions", {}).get("allow", [])
    new_allow = new_template.get("permissions", {}).get("allow", [])
    dropped = {"allow": [r for r in previous_added.get("allow", []) if r not in new_allow], "hooks": {}}
    for event, definitions in previous_added.get("hooks", {}).items():
        keep = new_template.get("hooks", {}).get(event, [])
        dropped["hooks"][event] = [d for d in definitions if d not in keep]
    unmerge_settings(settings, dropped)
    introduced = {
        "permissions": {"allow": [r for r in new_allow if r not in old_allow]},
        "hooks": {
            event: [d for d in definitions if d not in old_template.get("hooks", {}).get(event, [])]
            for event, definitions in new_template.get("hooks", {}).items()
        },
    }
    newly = merge_settings(settings, introduced)
    owned = {"allow": [r for r in previous_added.get("allow", []) if r in new_allow], "hooks": {}}
    for event, definitions in previous_added.get("hooks", {}).items():
        kept = [d for d in definitions if d in new_template.get("hooks", {}).get(event, [])]
        if kept:
            owned["hooks"][event] = kept
    owned["allow"] += [r for r in newly["allow"] if r not in owned["allow"]]
    for event, definitions in newly["hooks"].items():
        owned["hooks"].setdefault(event, [])
        owned["hooks"][event] += [d for d in definitions if d not in owned["hooks"][event]]
    return owned


def previous_template(config):
    """Template the project was installed with: its integrity-protected snapshot first."""
    root = Path(config["project"])
    snapshot = root / ".claude/settings.template.json"
    if snapshot.is_file() and not platform_api.is_link(snapshot):
        return json.loads(snapshot.read_text(encoding="utf-8"))
    version = str(config.get("version"))
    path = RELEASES / version / "templates/settings.template.json"
    if re.fullmatch(r"\d+\.\d+\.\d+", version) and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    raise OrchestratorError("Installed settings template unavailable; cannot reconcile safely.",
                            EXIT_CONFLICT)


def unmerge_settings(settings, added):
    allow = settings.get("permissions", {}).get("allow", [])
    for rule in added.get("allow", []):
        if rule in allow:
            allow.remove(rule)
    if "permissions" in settings and not settings["permissions"].get("allow"):
        settings["permissions"].pop("allow", None)
        if not settings["permissions"]:
            settings.pop("permissions")
    hooks = settings.get("hooks", {})
    for event, definitions in added.get("hooks", {}).items():
        current = hooks.get(event, [])
        for definition in definitions:
            if definition in current:
                current.remove(definition)
        if event in hooks and not hooks[event]:
            hooks.pop(event)
    if "hooks" in settings and not settings["hooks"]:
        settings.pop("hooks")
    return settings


def existing_orchestration(root):
    markers = []
    for rel in (".claude/scripts/codex-session.py", ".claude/hooks/completion-gate.py",
                ".claude/orchestration.json"):
        if (root / rel).exists() or platform_api.is_link(root / rel):
            markers.append(rel)
    claude = root / "CLAUDE.md"
    if claude.is_file() and not platform_api.is_link(claude):
        text = claude.read_text(encoding="utf-8")
        if BLOCK_BEGIN in text or "# Claude-Codex Orchestration" in text:
            markers.append("CLAUDE.md orchestration section")
    for name in ("settings.json", "settings.local.json"):
        path = root / ".claude" / name
        if path.is_file() and not platform_api.is_link(path):
            text = path.read_text(encoding="utf-8")
            if "completion-gate.py" in text or "codex-session.py" in text:
                markers.append(f".claude/{name} orchestration hooks")
    if (state_dir(root) / "integrity/manifest.json").exists():
        markers.append("integrity manifest")
    return markers


# ---------------------------------------------------------------- profiles

NODE_SCRIPTS = {"build": 1200, "lint": 600, "typecheck": 600, "test": 1200}


def profile_prefix(directory):
    return "root" if directory == "." else re.sub(r"[^a-z0-9]+", "-", directory.lower()).strip("-")


def detect_profiles(root):
    candidates = ["."]
    for entry in sorted(root.iterdir()):
        if (entry.is_dir() and not platform_api.is_link(entry) and not entry.name.startswith(".")
                and entry.name not in ("node_modules", "vendor", "dist", "build", "venv")):
            candidates.append(entry.name)
    profiles = {}

    def add(directory, name, command, timeout):
        profiles[f"{profile_prefix(directory)}-{name}"] = {
            "directory": directory, "command": command, "timeout": timeout
        }

    for directory in candidates:
        base = root / directory

        def has(name):
            path = base / name
            return path.is_file() and not platform_api.is_link(path)

        if has("package.json"):
            try:
                scripts = json.loads((base / "package.json").read_text(encoding="utf-8")).get("scripts", {})
            except ValueError:
                scripts = {}
            runner = (["pnpm", "run"] if has("pnpm-lock.yaml")
                      else ["yarn", "run"] if has("yarn.lock")
                      else ["npm", "run"])
            for name in sorted(scripts):
                if name in NODE_SCRIPTS or name.startswith("test:"):
                    add(directory, name.replace(":", "-"), runner + [name],
                        NODE_SCRIPTS.get(name, 1200))
        if has("composer.json"):
            try:
                scripts = json.loads((base / "composer.json").read_text(encoding="utf-8")).get("scripts", {})
            except ValueError:
                scripts = {}
            for name in sorted(scripts):
                if name in NODE_SCRIPTS or name.startswith("test:"):
                    add(directory, "composer-" + name.replace(":", "-"),
                        ["composer", "run-script", name], NODE_SCRIPTS.get(name, 1200))
        if has("compose.yaml") or has("compose.yml") or has("docker-compose.yml"):
            add(directory, "docker-config", ["docker", "compose", "config", "--quiet"], 120)
        for name in ("build", "test"):
            if has(name + ".ps1"):
                add(directory, "powershell-" + name,
                    ["pwsh", "-NoProfile", "-File", "./" + name + ".ps1"], 1200)
        if has("artisan") and has("composer.json"):
            add(directory, "artisan-test", ["php", "artisan", "test"], 1200)
            if has("vendor/bin/pint") or "laravel/pint" in (base / "composer.json").read_text(encoding="utf-8"):
                add(directory, "pint-test", (["php", "vendor/bin/pint", "--test"] if os.name == "nt" else ["vendor/bin/pint", "--test"]), 600)
        if has("pyproject.toml") or has("pytest.ini") or has("setup.py"):
            add(directory, "pytest", ["python" if os.name == "nt" else "python3", "-m", "pytest"], 1200)
        if has("go.mod"):
            add(directory, "go-build", ["go", "build", "./..."], 900)
            add(directory, "go-test", ["go", "test", "./..."], 1200)
            add(directory, "go-vet", ["go", "vet", "./..."], 600)
        if has("Cargo.toml"):
            add(directory, "cargo-test", ["cargo", "test"], 1800)
        if has("Makefile") and re.search(r"^test:", (base / "Makefile").read_text(encoding="utf-8"), re.M):
            add(directory, "make-test", ["make", "test"], 1200)
    return profiles


def profile_digest(spec):
    canonical = json.dumps(
        {key: spec.get(key) for key in ("directory", "command", "timeout")},
        sort_keys=True
    )
    return sha256_bytes(canonical.encode())


def load_profiles(root):
    path = root / ".claude/orchestration-profiles.json"
    data = read_json(path, {}) or {}
    if "profiles" in data:
        return data["profiles"]
    # 4.0.0 format: {name: [directory, command, timeout]}
    return {
        name: {"directory": value[0], "command": value[1], "timeout": value[2]}
        for name, value in data.items()
        if isinstance(value, list) and len(value) == 3
    }


# ---------------------------------------------------------------- integrity manifest

def managed_paths(root, config, version):
    """Project files owned by the installation (never user-edited files)."""
    paths = set(release_payload(version))
    if config:
        paths.update(config.get("managed_files", {}))
    manifest = read_json(state_dir(root) / "integrity/manifest.json", {}) or {}
    for name in manifest.get("files", {}):
        if name.startswith(".claude/scripts/") or name.startswith(".claude/hooks/"):
            paths.add(name)
    paths.update(MANAGED_CONFIG)
    return sorted(paths)


def build_manifest(root, files):
    return {
        "project": str(root),
        "algorithm": "sha256",
        "created_at": now(),
        "files": {rel: digest(root / rel) for rel in sorted(files)},
    }


def manifest_conflicts(root):
    manifest = read_json(state_dir(root) / "integrity/manifest.json", {}) or {}
    conflicts = []
    for rel, expected in manifest.get("files", {}).items():
        if rel in USER_FILES:
            continue
        path = root / rel
        if platform_api.is_link(path):
            conflicts.append(f"{rel}: SYMLINK")
        elif not path.is_file():
            conflicts.append(f"{rel}: MISSING")
        elif digest(path) != expected:
            conflicts.append(f"{rel}: MODIFIED")
    if not manifest:
        conflicts.append("integrity manifest: MISSING")
    return conflicts


def run_project_integrity(root):
    checker = root / ".claude/scripts/integrity-check.py"
    if not checker.is_file():
        return 2, "integrity-check.py missing"
    result = subprocess.run(
        [sys.executable, str(checker)], cwd=root, capture_output=True, text=True, timeout=60
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------- backups

def backup_scope(root, config, version):
    files = set(USER_FILES) | set(managed_paths(root, config, version))
    return sorted(files)


def create_backup(root, kind, version_before, extra_files=(), scope_version=None):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory = PROJECT_BACKUPS / project_id(root) / f"{stamp}-{kind}"
    platform_api.secure_mkdir(directory, parents=True, mode=0o700)
    config = project_config(root)
    record = {
        "schema": 1,
        "project": str(root),
        "project_id": project_id(root),
        "kind": kind,
        "version_before": version_before,
        "created_at": now(),
        "files": {},
        "state": {},
    }
    for rel in sorted(set(backup_scope(root, config, scope_version or version_before or current_release())) | set(extra_files)):
        source = safe_target(root, rel)
        if source.is_file():
            target = directory / "files" / rel
            platform_api.secure_mkdir(target.parent, parents=True, exist_ok=True, mode=0o700)
            data = source.read_bytes()
            atomic_write(target, data, 0o600)
            record["files"][rel] = {
                "sha256": sha256_bytes(data),
                "mode": stat.S_IMODE(source.stat().st_mode),
                "security": platform_api.capture_security(source),
            }
        else:
            record["files"][rel] = None
    for rel in STATE_FILES:
        source = state_dir(root) / rel
        if source.is_file() and not platform_api.is_link(source):
            target = directory / "state" / rel
            platform_api.secure_mkdir(target.parent, parents=True, exist_ok=True, mode=0o700)
            data = source.read_bytes()
            atomic_write(target, data, 0o600)
            record["state"][rel] = {"sha256": sha256_bytes(data), "mode": 0o600,
                                    "security": platform_api.capture_security(source)}
        else:
            record["state"][rel] = None
    write_json(directory / "backup.json", record)
    verify_backup(directory)
    return directory, record


def verify_backup(directory):
    if platform_api.is_link(directory) or not directory.is_dir():
        raise OrchestratorError(f"Unsafe or missing backup: {directory}", EXIT_UNSAFE)
    record = read_json(directory / "backup.json")
    if not record:
        raise OrchestratorError(f"Backup record missing: {directory}", EXIT_INTEGRITY)
    for section, folder in (("files", "files"), ("state", "state")):
        for rel, meta in record.get(section, {}).items():
            relative_parts(rel)
            if meta is None:
                continue
            path = directory / folder / rel
            for parent in [path, *path.parents]:
                if parent == directory:
                    break
                if platform_api.is_link(parent):
                    raise OrchestratorError(f"Symlink inside backup: {parent}", EXIT_UNSAFE)
            if not path.is_file() or digest(path) != meta["sha256"]:
                raise OrchestratorError(f"Backup checksum mismatch: {rel}", EXIT_INTEGRITY)
    return record


def list_backups(root):
    base = PROJECT_BACKUPS / project_id(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and not platform_api.is_link(p))


def restore_backup(root, directory, transaction):
    record = verify_backup(directory)
    if record.get("project") != str(root):
        raise OrchestratorError("Backup belongs to a different project.", EXIT_CONFLICT)
    for rel, meta in record["files"].items():
        target = safe_target(root, rel)
        if meta is None:
            transaction.remove(target)
        else:
            transaction.write(target, (directory / "files" / rel).read_bytes(), meta["mode"])
            platform_api.restore_security(target, meta.get("security"))
    for rel, meta in record["state"].items():
        target = safe_target(state_dir(root), rel)
        if meta is None:
            transaction.remove(target)
        else:
            transaction.write(target, (directory / "state" / rel).read_bytes(), 0o600)
            platform_api.restore_security(target, meta.get("security"))
    return record


# ---------------------------------------------------------------- registry

def registry_data():
    data = read_json(REGISTRY)
    return data if data and "projects" in data else {"projects": {}}


def registry_update(mutator):
    platform_api.secure_mkdir(REGISTRY.parent, parents=True, exist_ok=True, mode=0o700)
    with REGISTRY.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = registry_data()
        mutator(data["projects"])
        write_json(REGISTRY, data)


def register(root, version):
    def mutate(projects):
        entry = projects.get(project_id(root), {})
        entry.update({"name": root.name, "path": str(root), "version": version,
                      "registered_at": entry.get("registered_at", now()), "updated_at": now()})
        projects[project_id(root)] = entry
    registry_update(mutate)


# ---------------------------------------------------------------- install / update core

def install_files(root, version, transaction, config_before=None, keep_profiles=None):
    """Write all managed project files for `version`. Returns the new config."""
    payload = release_payload(version)
    template = template_settings(version)

    # scripts and hooks
    for rel, source in payload.items():
        transaction.write(safe_target(root, rel), source.read_bytes(), 0o700)
    fault("install:after-scripts")

    # profiles: keep existing project profiles, convert legacy format
    profiles = keep_profiles if keep_profiles is not None else detect_profiles(root)
    for spec in profiles.values():
        if spec.get("directory", ".") != ".":
            relative_parts(spec["directory"])
    transaction.write(
        safe_target(root, ".claude/orchestration-profiles.json"),
        json.dumps({"schema": 1, "profiles": profiles}, indent=2) + "\n", 0o600
    )

    # settings
    settings_path = safe_target(root, ".claude/settings.local.json")
    settings = load_settings(settings_path)
    if config_before:
        added = reconcile_settings(settings, previous_template(config_before), template,
                                   previous_added_settings(config_before))
    else:
        added = merge_settings(settings, template)
    transaction.write(settings_path, json.dumps(settings, indent=2) + "\n", 0o600)
    transaction.write(
        safe_target(root, ".claude/settings.template.json"),
        json.dumps(template, indent=2) + "\n", 0o600
    )
    fault("install:after-settings")

    # instructions
    claude = safe_target(root, "CLAUDE.md")
    text = claude.read_text(encoding="utf-8") if claude.exists() else ""
    block = instruction_block(version, root)
    mode = stat.S_IMODE(claude.stat().st_mode) if claude.exists() else 0o644
    transaction.write(claude, apply_instruction_block(text, block), mode)

    ignore = safe_target(root, ".claude/.gitignore")
    ignore_text = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    legacy_ignore = (RELEASES / "4.0.0/templates/.gitignore").read_text(encoding="utf-8") \
        if (RELEASES / "4.0.0/templates/.gitignore").is_file() else None
    transaction.write(ignore, apply_ignore_block(ignore_text, ignore_block(version), legacy_ignore), 0o644)
    fault("install:after-instructions")

    # stale scripts from the previous version
    managed = set(payload)
    for rel in (config_before or {}).get("managed_files", {}):
        if rel not in managed and rel.startswith((".claude/scripts/", ".claude/hooks/")):
            transaction.remove(safe_target(root, rel))

    config = {
        "schema": 2,
        "version": version,
        "project_id": project_id(root),
        "project": str(root),
        "installed_at": (config_before or {}).get("installed_at", now()),
        "updated_at": now(),
        "install_backup": (config_before or {}).get("install_backup")
        or (config_before or {}).get("backup"),
        "managed_files": {rel: sha256_bytes(src.read_bytes()) for rel, src in payload.items()},
        "added_settings": added,
        "instruction_block_sha256": sha256_bytes(block.encode()),
    }
    transaction.write(
        safe_target(root, ".claude/orchestration.json"),
        json.dumps(config, indent=2) + "\n", 0o600
    )

    manifest = build_manifest(root, list(payload) + list(MANAGED_CONFIG))
    manifest_path = state_dir(root) / "integrity/manifest.json"
    transaction.write(manifest_path, json.dumps(manifest, indent=2) + "\n", 0o600)
    fault("install:before-verify")

    code, output = run_project_integrity(root)
    if code != 0:
        raise OrchestratorError("Project integrity verification failed:\n" + output, EXIT_INTEGRITY)
    return config


def run_transaction(action):
    transaction = Transaction()
    try:
        return action(transaction)
    except BaseException as error:
        errors = transaction.rollback()
        if errors:
            raise OrchestratorError(
                f"{error}\nRESTORE_INCOMPLETE: {errors}; use the recorded backup.", EXIT_INTEGRITY
            )
        if isinstance(error, OrchestratorError):
            error.args = (f"{error}\nAll changes were rolled back.",)
            raise
        if isinstance(error, PermissionError):
            raise OrchestratorError(f"Permission denied: {error}\nAll changes were rolled back.", EXIT_UNSAFE)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise OrchestratorError(f"{error}\nAll changes were rolled back.")


# ---------------------------------------------------------------- commands

def cmd_init(args):
    root = resolve_project(args)
    version = args.release or current_release()
    require_runtime_supported(version)
    preflight(version)
    if release_metadata(version).get("status") != "VERIFIED" and not args.allow_unverified:
        raise OrchestratorError(f"Release {version} is not VERIFIED.", EXIT_CONFLICT)
    markers = existing_orchestration(root)
    if markers:
        raise OrchestratorError(
            "Existing orchestration detected (" + ", ".join(markers)
            + "). Use 'orchestrator adopt' or 'update'. No files changed.", EXIT_CONFLICT
        )
    for rel in USER_FILES + tuple(release_payload(version)) + MANAGED_CONFIG:
        safe_target(root, rel)
    collisions = [rel for rel in tuple(release_payload(version)) + MANAGED_CONFIG
                  if (root / rel).exists() or platform_api.is_link(root / rel)]
    if collisions:
        raise OrchestratorError(
            "File conflict, no files changed: " + ", ".join(collisions), EXIT_CONFLICT
        )
    load_settings(root / ".claude/settings.local.json")
    if args.dry_run:
        print(json.dumps({
            "action": "init", "project": str(root), "release": version,
            "create": sorted(list(release_payload(version)) + list(MANAGED_CONFIG)),
            "merge": list(USER_FILES), "profiles_detected": sorted(detect_profiles(root)),
            "profiles_approved": 0,
        }, indent=2))
        return 0
    with ProjectLocks(root):
        if existing_orchestration(root):
            raise OrchestratorError("Existing orchestration detected. No files changed.", EXIT_CONFLICT)
        backup, _ = create_backup(root, "pre-install", None)

        def action(transaction):
            config = install_files(root, version, transaction)
            config["install_backup"] = str(backup)
            transaction.write(root / ".claude/orchestration.json",
                              json.dumps(config, indent=2) + "\n", 0o600)
            manifest = build_manifest(root, list(release_payload(version)) + list(MANAGED_CONFIG))
            transaction.write(state_dir(root) / "integrity/manifest.json",
                              json.dumps(manifest, indent=2) + "\n", 0o600)
            fault("install:before-register")
            register(root, version)
            return config

        config = run_transaction(action)
    print("PROJECT_INITIALIZATION_SUCCESS")
    print("Project:", root)
    print("Version:", version)
    print("Managed profiles (unapproved):", len(load_profiles(root)))
    print("Backup:", backup)
    print("Default mode: Claude only. Say 'Use Codex' to activate orchestration.")
    print("Open a new Claude Code session.")
    return 0


def cmd_adopt(args):
    root = resolve_project(args)
    version = installed_version(root) or "3"
    require_runtime_supported(version)
    code, output = run_project_integrity(root)
    if code != 0:
        raise OrchestratorError("Existing integrity verification failed:\n" + output, EXIT_INTEGRITY)
    register(root, version)
    print("EXISTING_PROJECT_REGISTERED")
    print("Project version:", version)
    print("Project files unchanged.")
    print("Existing session mappings preserved.")
    return 0


def update_plan(root, config, target):
    current = config.get("version")
    payload = release_payload(target)
    old_managed = set(config.get("managed_files", {})) or {
        rel for rel in (read_json(state_dir(root) / "integrity/manifest.json", {}) or {}).get("files", {})
        if rel.startswith((".claude/scripts/", ".claude/hooks/"))
    }
    operations = []
    for rel, source in payload.items():
        path = root / rel
        if not path.exists():
            operations.append(("add", rel))
        elif digest(path) != digest(source):
            operations.append(("replace", rel))
    for rel in sorted(old_managed - set(payload)):
        operations.append(("remove", rel))
    operations += [("rewrite", rel) for rel in MANAGED_CONFIG]
    operations += [("merge", rel) for rel in USER_FILES]
    return {"from": current, "to": target, "operations": operations}


def cmd_update(args):
    root = resolve_project(args)
    config = require_managed_install(root)
    target = args.release or current_release()
    require_runtime_supported(target)
    preflight(target)
    meta = release_metadata(target)
    conflicts = manifest_conflicts(root)
    active = active_workflows(root)
    plan = update_plan(root, config, target)
    known = set(managed_paths(root, config, config.get("version") or target)) - set(release_payload(target))
    known |= set(config.get("managed_files", {})) | set(
        (read_json(state_dir(root) / "integrity/manifest.json", {}) or {}).get("files", {}))
    conflicts += [f"{rel}: UNMANAGED_FILE_AT_NEW_PATH" for rel in release_payload(target)
                  if rel not in known and ((root / rel).exists() or platform_api.is_link(root / rel))]
    up_to_date = config.get("version") == target and not [
        op for op in plan["operations"] if op[0] in ("add", "replace", "remove")
    ]
    report = {
        "project": str(root), "installed": config.get("version"), "target": target,
        "target_status": meta.get("status"), "up_to_date": up_to_date,
        "conflicts": conflicts, "active_workflows": active,
    }
    if args.check:
        print(json.dumps(report, indent=2))
        return 0 if not conflicts else EXIT_CONFLICT
    if args.dry_run:
        report["operations"] = [f"{op} {rel}" for op, rel in plan["operations"]]
        print(json.dumps(report, indent=2))
        return 0 if not conflicts else EXIT_CONFLICT
    if up_to_date:
        print(f"UP_TO_DATE: {root} already at {target}. No files changed.")
        return 0
    if meta.get("status") != "VERIFIED" and not args.allow_unverified:
        raise OrchestratorError(f"Release {target} is not VERIFIED ({meta.get('status')}).", EXIT_CONFLICT)
    if not args.yes:
        print(json.dumps(report, indent=2))
        raise OrchestratorError("CONFIRMATION_REQUIRED: re-run with --apply --yes.", EXIT_CONFIRM)
    if conflicts:
        raise OrchestratorError("CONFLICTS: " + "; ".join(conflicts) + "\nNo files changed.", EXIT_CONFLICT)
    with ProjectLocks(root):
        require_no_active_workflow(root)
        backup, record = create_backup(root, "pre-update", config.get("version"),
                                       extra_files=release_payload(target))
        profiles = load_profiles(root)

        def action(transaction):
            new_config = install_files(root, target, transaction, config_before=config,
                                       keep_profiles=profiles)
            record["to_version"] = target
            record["completed_at"] = now()
            record["post_files"] = {
                rel: (digest(root / rel) if (root / rel).is_file() else None)
                for rel in record["files"]
            }
            transaction.write(backup / "backup.json", json.dumps(record, indent=2) + "\n", 0o600)
            fault("update:before-register")
            register(root, target)
            return new_config

        run_transaction(action)
    print("PROJECT_UPDATE_SUCCESS")
    print(f"Version: {config.get('version')} -> {target}")
    print("Backup:", backup)
    print("Session mappings and workflow history unchanged.")
    return 0


def select_rollback_backup(root, name):
    backups = list_backups(root)
    if name:
        matches = [b for b in backups if b.name == name]
        if not matches:
            raise OrchestratorError(f"Backup not found: {name}")
        return matches[0]
    for backup in reversed(backups):
        record = read_json(backup / "backup.json", {}) or {}
        if (record.get("kind") in ("pre-update", "pre-migrate-v3") and record.get("completed_at")
                and not record.get("rolled_back_at")):
            return backup
    raise OrchestratorError("No pre-update backup available for rollback.")


def cmd_rollback(args):
    root = resolve_project(args)
    require_managed_install(root)
    backup = select_rollback_backup(root, args.backup)
    record = verify_backup(backup)
    conflicts = []
    overwrites = []
    post = record.get("post_files")
    for rel in record["files"]:
        path = root / rel
        if platform_api.is_link(path):
            conflicts.append(f"{rel}: SYMLINK")
            continue
        current = digest(path) if path.is_file() else None
        if post is not None:
            if current != post.get(rel):
                conflicts.append(f"{rel}: {'DELETED' if current is None else 'CHANGED'}_SINCE_UPDATE")
        else:
            meta = record["files"][rel]
            if current != (meta["sha256"] if meta else None):
                overwrites.append(rel)
    target = record.get("version_before")
    report = {
        "project": str(root), "backup": backup.name, "backup_checksums": "PASS",
        "current": installed_version(root), "rollback_to": target,
        "conflicts": conflicts, "overwrites_current_files": overwrites,
        "active_workflows": active_workflows(root),
    }
    if target and target != "3":
        verify_release(target)
    if args.check:
        print(json.dumps(report, indent=2))
        return 0 if not conflicts else EXIT_CONFLICT
    if args.dry_run:
        report["operations"] = [
            f"{'remove' if meta is None else 'restore'} {rel}"
            for rel, meta in record["files"].items()
        ] + [f"{'remove' if meta is None else 'restore'} state/{rel}"
             for rel, meta in record["state"].items()]
        print(json.dumps(report, indent=2))
        return 0 if not conflicts else EXIT_CONFLICT
    if not args.yes:
        print(json.dumps(report, indent=2))
        raise OrchestratorError("CONFIRMATION_REQUIRED: re-run with --apply --yes.", EXIT_CONFIRM)
    if conflicts:
        raise OrchestratorError("CONFLICTS: " + "; ".join(conflicts) + "\nNo files changed.", EXIT_CONFLICT)
    if overwrites and not args.overwrite_edits:
        raise OrchestratorError(
            "Restoring this backup overwrites current files: " + ", ".join(overwrites)
            + "\nRe-run with --overwrite-edits to confirm. No files changed.", EXIT_CONFIRM)
    with ProjectLocks(root, cleanup_created=record.get("kind") == "pre-migrate-v3"):
        require_no_active_workflow(root)
        safety, _ = create_backup(root, "pre-rollback", installed_version(root), extra_files=record["files"])

        def action(transaction):
            restore_backup(root, backup, transaction)
            fault("rollback:after-restore")
            code, output = run_project_integrity(root)
            if code != 0:
                raise OrchestratorError("Integrity failed after rollback:\n" + output, EXIT_INTEGRITY)
            record["rolled_back_at"] = now()
            transaction.write(backup / "backup.json", json.dumps(record, indent=2) + "\n", 0o600)
            fault("rollback:before-register")
            register(root, target)

        run_transaction(action)
    print("PROJECT_ROLLBACK_SUCCESS")
    print("Restored version:", target)
    print("Safety backup:", safety)
    print("Session mappings and workflow history unchanged.")
    return 0


def original_settings_from_install_backup(config):
    location = config.get("install_backup") or config.get("backup")
    if not location:
        return None
    path = Path(location)
    record = read_json(path / "backup.json")
    if record:
        verify_backup(path)
        meta = record["files"].get(".claude/settings.local.json")
        return {} if meta is None else json.loads((path / "files/.claude/settings.local.json").read_text(encoding="utf-8"))
    legacy = path / "settings.local.json"
    return json.loads(legacy.read_text(encoding="utf-8")) if legacy.is_file() else {}


def previous_added_settings(config):
    """Settings entries owned by the installation (derived for 4.0.0 installs)."""
    if config.get("added_settings") is not None:
        return config["added_settings"]
    before = original_settings_from_install_backup(config) or {}
    legacy_template = RELEASES / "4.0.0/templates/settings.template.json"
    if not legacy_template.is_file():
        raise OrchestratorError("Release 4.0.0 unavailable; cannot derive installer-owned settings.",
                                EXIT_CONFLICT)
    template = json.loads(legacy_template.read_text(encoding="utf-8"))
    return {
        "allow": [r for r in template.get("permissions", {}).get("allow", [])
                  if r not in before.get("permissions", {}).get("allow", [])],
        "hooks": {e: [d for d in defs if d not in before.get("hooks", {}).get(e, [])]
                  for e, defs in template.get("hooks", {}).items()},
    }


def install_backup_record(config):
    location = config.get("install_backup")
    if not location:
        return None
    return read_json(Path(location) / "backup.json")


def payload_bytecode(root, config):
    """Only remove owned cache directories containing recognizable payload pyc files.

    Mixed, foreign, linked or unrecognized caches remain user data. Never load
    bytecode to inspect it; the source record, filename and magic suffice here.
    """
    result = []
    for folder in ("scripts", "hooks"):
        prefix = f".claude/{folder}/"
        modules = {Path(rel).stem for rel in config.get("managed_files", {})
                   if rel.startswith(prefix) and Path(rel).parent.as_posix() == prefix[:-1]
                   and rel.endswith(".py")}
        try:
            cache = safe_target(root, prefix + "__pycache__")
            if not cache.is_dir():
                continue
            entries = list(cache.iterdir())
            for entry in entries:
                safe_target(root, entry.relative_to(root).as_posix())
                match = re.fullmatch(r"(.+)\.cpython-\d+(?:\.opt-[012])?\.pyc", entry.name)
                if (not entry.is_file() or not match or match[1] not in modules
                        or entry.read_bytes()[:4] != importlib.util.MAGIC_NUMBER
                        or entry.stat().st_size < 16):
                    break
            else:
                result.extend(entry.relative_to(root).as_posix() for entry in entries)
        except (OSError, OrchestratorError):
            continue
    return result


def cmd_uninstall(args):
    root = resolve_project(args)
    config = require_managed_install(root)
    conflicts = manifest_conflicts(root)
    files = sorted(set(config.get("managed_files", {})) | {
        rel for rel in (read_json(state_dir(root) / "integrity/manifest.json", {}) or {}).get("files", {})
        if rel.startswith((".claude/scripts/", ".claude/hooks/"))
    } | set(MANAGED_CONFIG))
    bytecode = payload_bytecode(root, config)
    files = sorted(set(files) | set(bytecode))
    report = {
        "project": str(root), "installed": config.get("version"),
        "remove": files, "edit": list(USER_FILES),
        "preserved": ["session mappings", "workflow history", "logs", "unrelated project files"],
        "conflicts": conflicts, "active_workflows": active_workflows(root),
    }
    if args.dry_run or not args.apply:
        print(json.dumps(report, indent=2))
        return 0 if not conflicts else EXIT_CONFLICT
    if not args.yes:
        print(json.dumps(report, indent=2))
        raise OrchestratorError("CONFIRMATION_REQUIRED: re-run with --apply --yes.", EXIT_CONFIRM)
    if conflicts:
        raise OrchestratorError("CONFLICTS: " + "; ".join(conflicts) + "\nNo files changed.", EXIT_CONFLICT)
    with ProjectLocks(root):
        require_no_active_workflow(root)
        backup, _ = create_backup(root, "pre-uninstall", config.get("version"), extra_files=bytecode)
        original = install_backup_record(config)

        def originally_absent(rel):
            return bool(original) and original["files"].get(rel, "x") is None

        def action(transaction):
            for rel in files:
                path = safe_target(root, rel)
                if path.exists():
                    transaction.remove(path)
            settings_path = safe_target(root, ".claude/settings.local.json")
            if settings_path.exists():
                settings = load_settings(settings_path)
                added = previous_added_settings(config)
                settings = unmerge_settings(settings, added)
                if not settings and originally_absent(".claude/settings.local.json"):
                    transaction.remove(settings_path)
                else:
                    transaction.write(settings_path, json.dumps(settings, indent=2) + "\n", 0o600)
            claude = safe_target(root, "CLAUDE.md")
            if claude.exists():
                text, _ = strip_block(claude.read_text(encoding="utf-8"), BLOCK_BEGIN, BLOCK_END)
                text, _ = strip_legacy_400_instructions(text)
                if not text.strip() and originally_absent("CLAUDE.md"):
                    transaction.remove(claude)
                else:
                    transaction.write(claude, text, stat.S_IMODE(claude.stat().st_mode))
            ignore = safe_target(root, ".claude/.gitignore")
            if ignore.exists():
                text, _ = strip_block(ignore.read_text(encoding="utf-8"), IGNORE_BEGIN, IGNORE_END)
                if not text.strip() and originally_absent(".claude/.gitignore"):
                    transaction.remove(ignore)
                else:
                    transaction.write(ignore, text, stat.S_IMODE(ignore.stat().st_mode))
            for rel in STATE_FILES:
                path = state_dir(root) / rel
                if path.exists():
                    transaction.remove(path)
            fault("uninstall:before-unregister")
            registry_update(lambda projects: projects.pop(project_id(root), None))

        run_transaction(action)
        for folder in ("scripts", "hooks"):
            try:
                cache = safe_target(root, f".claude/{folder}/__pycache__")
                cache.rmdir()
            except (OSError, OrchestratorError):
                pass
            try:
                (root / ".claude" / folder).rmdir()
            except OSError:
                pass
    print("PROJECT_UNINSTALL_SUCCESS")
    print("Backup:", backup)
    print("Session mappings, workflow history and logs preserved in", state_dir(root))
    return 0


def cmd_unregister(args):
    if args.id:
        key = args.id
    else:
        key = project_id(resolve_project(args))
    found = {}

    def mutate(projects):
        found["entry"] = projects.pop(key, None)

    registry_update(mutate)
    if not found["entry"]:
        raise OrchestratorError(f"Project not registered: {key}")
    print("PROJECT_UNREGISTERED:", found["entry"]["path"])
    print("Project files, sessions and workflow history unchanged.")
    return 0


def cmd_backup(args):
    root = resolve_project(args)
    with ProjectLocks(root, hold_execution=False):
        directory, record = create_backup(root, "manual", installed_version(root))
    print("BACKUP_CREATED:", directory)
    print("Files captured:", sum(1 for m in record["files"].values() if m))
    print("Checksums: PASS")
    return 0


def cmd_backups(args):
    root = resolve_project(args)
    rows = []
    for directory in list_backups(root):
        try:
            record = verify_backup(directory)
            status = "PASS"
        except OrchestratorError as error:
            record = read_json(directory / "backup.json", {}) or {}
            status = f"FAIL: {error}"
        rows.append({
            "name": directory.name, "kind": record.get("kind"),
            "version_before": record.get("version_before"),
            "to_version": record.get("to_version"),
            "rolled_back_at": record.get("rolled_back_at"),
            "checksums": status,
        })
    print(json.dumps({"project": str(root), "backups": rows}, indent=2))
    return 0 if all(r["checksums"] == "PASS" for r in rows) else EXIT_INTEGRITY


def cmd_versions(args):
    releases = []
    for version in all_releases():
        try:
            verify_release(version)
            integrity = "PASS"
        except OrchestratorError as error:
            integrity = f"FAIL: {error}"
        meta = release_metadata(version)
        releases.append({"version": version, "status": meta.get("status"), "integrity": integrity})
    try:
        cli = verify_cli()
    except OrchestratorError as error:
        cli = f"FAIL: {error}"
    output = {
        "cli_version": CLI_VERSION, "engine_version": ENGINE_VERSION, "cli_integrity": cli,
        "current_release": current_release(), "releases": releases,
        "projects": {k: {"path": v["path"], "version": v.get("version")}
                     for k, v in registry_data()["projects"].items()},
    }
    try:
        root = resolve_project(args)
        output["this_project"] = {"path": str(root), "version": installed_version(root)}
    except OrchestratorError:
        pass
    print(json.dumps(output, indent=2))
    return 0


def cmd_profiles(args):
    root = resolve_project(args)
    approvals = read_json(state_dir(root) / "profile-approvals.json", {}) or {}
    for name, spec in load_profiles(root).items():
        print(json.dumps({"profile": name, **spec,
                          "approved": approvals.get(name) == profile_digest(spec)}))
    return 0


def cmd_profile_approve(args):
    root = resolve_project(args)
    require_managed_install(root)
    code, output = run_project_integrity(root)
    if code != 0:
        raise OrchestratorError("Integrity verification failed:\n" + output, EXIT_INTEGRITY)
    profiles = load_profiles(root)
    if args.name not in profiles:
        raise OrchestratorError(f"Unknown profile: {args.name}")
    spec = profiles[args.name]
    directory = spec.get("directory", ".")
    if directory != ".":
        relative_parts(directory)
    target = (root / directory).resolve()
    if target != root and root not in target.parents:
        raise OrchestratorError("Profile directory escapes the project.", EXIT_UNSAFE)
    print(json.dumps({"profile": args.name, **spec}, indent=2))
    if not args.yes:
        raise OrchestratorError("CONFIRMATION_REQUIRED: review the command above, then add --yes.", EXIT_CONFIRM)
    with ProjectLocks(root, hold_execution=False):
        path = state_dir(root) / "profile-approvals.json"
        approvals = read_json(path, {}) or {}
        approvals[args.name] = profile_digest(spec)
        write_json(path, approvals)
    print("PROFILE_APPROVED:", args.name)
    return 0


def cmd_doctor(args):
    print("Orchestrator version:", CLI_VERSION)
    print("Engine version:", ENGINE_VERSION)
    print("Platform:", json.dumps(platform_api.environment_info(), sort_keys=True))
    print("CLI integrity:", verify_cli())
    version = current_release()
    verify_release(version)
    print(f"Release integrity ({version}): PASS")
    if not runtime_supported(version):
        print("Runtime compatibility: legacy payload requires Linux; evaluate 4.3.0 explicitly with --release 4.3.0 --allow-unverified")
    if os.name == "nt":
        print("Claude hooks: Git Bash required; native Windows lifecycle NOT VERIFIED")
    for command in ("python3", "git", "claude", "codex", "gh", "ssh-keygen"):
        print(command + ":", shutil.which(command) or "NOT FOUND")
    print("Registered projects:", len(registry_data()["projects"]))
    return 0


def cmd_verify(args):
    root = resolve_project(args)
    code, output = run_project_integrity(root)
    try:
        report = json.loads(output)
    except ValueError:
        report = None
    if isinstance(report, dict):
        report["runtime_compatible"] = runtime_supported(installed_version(root))
        output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    return code


def show_status(root, watch=False):
    script = root / ".claude/scripts/orchestration-status.py"
    if not script.is_file():
        print("Orchestration not installed:", root)
        return 1
    command = [sys.executable, str(script)] + (["--watch"] if watch else [])
    return subprocess.call(command, cwd=root)


def cmd_status(args):
    if args.all:
        code = 0
        for entry in registry_data()["projects"].values():
            root = Path(entry["path"])
            if root.is_dir():
                code |= show_status(root)
            else:
                print("Unavailable:", root)
        return code
    return show_status(resolve_project(args))


def cmd_release_promote(args):
    """Mark a release VERIFIED only with a passing test report for its exact checksums."""
    version = args.version
    manifest = verify_release(version)
    report = json.loads(Path(args.test_report).read_text(encoding="utf-8"))
    checksum_digest = sha256_bytes((release_dir(version) / "checksums.json").read_bytes())
    if report.get("status") != "PASS" or report.get("failures") or report.get("errors"):
        raise OrchestratorError("Test report is not PASS; metadata unchanged.", EXIT_INTEGRITY)
    if report.get("release") != version or report.get("release_checksums_sha256") != checksum_digest:
        raise OrchestratorError("Test report does not match this release build.", EXIT_INTEGRITY)
    if report.get("cli_sha256") != digest(Path(__file__).resolve()):
        raise OrchestratorError("Test report does not match this CLI build.", EXIT_INTEGRITY)
    if not args.yes:
        raise OrchestratorError("CONFIRMATION_REQUIRED: add --yes.", EXIT_CONFIRM)
    meta = release_metadata(version)
    meta.update({
        "status": "VERIFIED", "verified_at": now(), "files": len(manifest),
        "test_report_sha256": digest(Path(args.test_report)),
        "tests_run": report.get("tests_run"),
    })
    write_json(release_dir(version) / "release.json", meta, 0o600)
    write_json(CURRENT_FILE, {"version": version, "updated_at": now()})
    write_json(CLI_CHECKSUMS, {"orchestrator.py": digest(Path(__file__).resolve()),
                               "cli_version": CLI_VERSION, "sealed_at": now()})
    print(f"RELEASE_VERIFIED: {version}; current release updated; CLI sealed.")
    return 0


def cmd_legacy_command(args):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(GLOBAL / 'lib'))
    import ccx_migration
    try:
        if args.action == 'migrate-v3':
            return ccx_migration.migrate(sys.modules[__name__], args)
        return ccx_migration.archive(sys.modules[__name__], args)
    except (OSError, ValueError, TypeError, SyntaxError, subprocess.SubprocessError) as error:
        raise OrchestratorError('Legacy operation failed: ' + str(error))


def cmd_distribution_command(args):
    # -I omits the script directory. Load only our resolved, installed library.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(GLOBAL / 'lib'))
    import ccx_install
    import ccx_distribution
    try:
        if args.action == 'distribution':
            return ccx_distribution.distribution(args)
        if args.action == 'self-update':
            return ccx_distribution.self_update(args, GLOBAL)
        return ccx_install.rollback_engine(GLOBAL, apply=args.apply, yes=args.yes)
    except ccx_install.InstallError as error:
        raise OrchestratorError(str(error), error.code)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise OrchestratorError('Distribution operation failed: ' + str(error), 1)


def cmd_workspace(args):
    from ccx_workspace.cli import main as workspace_main
    arguments = (["--database", args.database] if args.database else []) + args.workspace_args
    return workspace_main(arguments)


def cmd_workspace_service(args):
    from ccx_workspace.cli import main as workspace_main
    arguments = (["--database", args.database] if args.database else []) + [args.action]
    if args.action != "stop":
        arguments += ["--port", str(args.port)]
        if args.no_browser: arguments.append("--no-browser")
        if args.background: arguments.append("--background")
    return workspace_main(arguments)


def build_parser():
    parser = argparse.ArgumentParser(description="Claude-Codex Global Orchestrator")
    parser.add_argument("--version", action="version", version=CLI_VERSION)
    sub = parser.add_subparsers(dest="action", required=True)
    workspace = sub.add_parser("workspace", help="V5 persistent intelligence and universal workflows")
    workspace.add_argument("--database")
    workspace.add_argument("workspace_args", nargs=argparse.REMAINDER)
    for name in ("start", "stop", "restart", "dashboard"):
        service = sub.add_parser(name, help="V5 local workspace " + name)
        service.add_argument("--database")
        if name != "stop":
            service.add_argument("--port", type=int, default=8765)
            service.add_argument("--no-browser", action="store_true")
            service.add_argument("--background", action="store_true")

    def project_cmd(name, help_text):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--project", help="Project path (default: current Git project)")
        return command

    init = project_cmd("init", "Install orchestration into the current project")
    init.add_argument("--release")
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--allow-unverified", action="store_true")
    project_cmd("adopt", "Register an existing (legacy) installation without changes")
    sub.add_parser("doctor", help="Check CLI, release and tool availability")
    project_cmd("verify", "Run the project integrity check")
    sub.add_parser("projects", help="Show the global registry")
    project_cmd("watch", "Watch project status")
    status = project_cmd("status", "Show project status")
    status.add_argument("--all", action="store_true")
    project_cmd("versions", "Show CLI, releases and project versions")
    project_cmd("backup", "Create a verified backup of project orchestration files")
    project_cmd("backups", "List and verify project backups")

    for name in ("update", "rollback"):
        command = project_cmd(name, f"{name.title()} project orchestration")
        mode = command.add_mutually_exclusive_group(required=True)
        mode.add_argument("--check", action="store_true")
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        command.add_argument("--yes", action="store_true", help="Confirm file replacement")
        if name == "update":
            command.add_argument("--release")
            command.add_argument("--allow-unverified", action="store_true")
        else:
            command.add_argument("--backup", help="Backup name (default: latest pre-update)")
            command.add_argument("--overwrite-edits", action="store_true",
                                 help="Confirm overwriting files changed since a manual backup")

    uninstall = project_cmd("uninstall", "Remove orchestration from the project")
    mode = uninstall.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    uninstall.add_argument("--yes", action="store_true")

    unregister = project_cmd("unregister", "Remove a project from the registry only")
    unregister.add_argument("--id")

    project_cmd("profiles", "List managed execution profiles")
    approve = project_cmd("profile-approve", "Approve one managed execution profile")
    approve.add_argument("name")
    approve.add_argument("--yes", action="store_true")

    migrate = project_cmd('migrate-v3', 'Migrate a verified V3 project to a managed release')
    modes = migrate.add_mutually_exclusive_group(required=True)
    for option in ('check', 'dry-run', 'apply'):
        modes.add_argument('--' + option, action='store_true')
    migrate.add_argument('--yes', action='store_true')
    migrate.add_argument('--release')
    migrate.add_argument('--allow-unverified', action='store_true')
    migrate.add_argument('--project-rules')
    migrate.add_argument('--report')
    archive = project_cmd('archive-legacy', 'Archive explicitly enumerated legacy development artifacts')
    modes = archive.add_mutually_exclusive_group(required=True)
    modes.add_argument('--dry-run', action='store_true')
    modes.add_argument('--apply', action='store_true')
    archive.add_argument('--yes', action='store_true')
    archive.add_argument('--to', required=True)

    distribution = sub.add_parser('distribution', help='Configure engine distribution provenance')
    actions = distribution.add_subparsers(dest='distribution_action', required=True)
    actions.add_parser('show')
    configure = actions.add_parser('configure')
    configure.add_argument('--repository', required=True)
    configure.add_argument('--allowed-signers')
    configure.add_argument('--signer-identity')
    configure.add_argument('--no-require-signature', action='store_true')
    for name in ('self-update', 'self-rollback'):
        command = sub.add_parser(name)
        modes = command.add_mutually_exclusive_group(required=True)
        for option in ('check', 'dry-run', 'apply'):
            modes.add_argument('--' + option, action='store_true')
        command.add_argument('--yes', action='store_true')
        if name == 'self-update':
            for option in ('version', 'archive', 'sums', 'signature'):
                command.add_argument('--' + option)
            command.add_argument('--allow-downgrade', action='store_true')
            command.add_argument('--allow-unsigned', action='store_true')

    promote = sub.add_parser("release-promote", help="Maintainer: mark a tested release VERIFIED")
    promote.add_argument("version")
    promote.add_argument("--test-report", required=True)
    promote.add_argument("--yes", action="store_true")
    return parser


COMMANDS = {
    "workspace": cmd_workspace,
    "start": cmd_workspace_service, "stop": cmd_workspace_service,
    "restart": cmd_workspace_service, "dashboard": cmd_workspace_service,
    "migrate-v3": cmd_legacy_command, "archive-legacy": cmd_legacy_command,
    "distribution": cmd_distribution_command, "self-update": cmd_distribution_command,
    "self-rollback": cmd_distribution_command,
    "init": cmd_init, "adopt": cmd_adopt, "doctor": cmd_doctor, "verify": cmd_verify,
    "projects": lambda a: print(json.dumps(registry_data(), indent=2)) or 0,
    "status": cmd_status, "watch": lambda a: show_status(resolve_project(a), watch=True),
    "versions": cmd_versions, "backup": cmd_backup, "backups": cmd_backups,
    "update": cmd_update, "rollback": cmd_rollback, "uninstall": cmd_uninstall,
    "unregister": cmd_unregister, "profiles": cmd_profiles,
    "profile-approve": cmd_profile_approve, "release-promote": cmd_release_promote,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.action](args) or 0
    except OrchestratorError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return error.code
    except PermissionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_UNSAFE


if __name__ == "__main__":
    sys.exit(main())
