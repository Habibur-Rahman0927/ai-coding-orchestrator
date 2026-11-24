#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from datetime import datetime, timezone
from pathlib import Path

os.umask(0o077)

GLOBAL = Path(__file__).resolve().parent
RELEASE = GLOBAL / "releases/4.0.0"
REGISTRY = GLOBAL / "registry/projects.json"

VERSION = "4.0.0"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".orchestrator-"
    )

    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")

    Path(name).replace(path)


def project_root():
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise SystemExit("ERROR: Run inside a Git project.")

    return Path(result.stdout.strip()).resolve()


def project_id(root):
    return hashlib.sha256(
        str(root).encode()
    ).hexdigest()[:16]


def state_directory(root):
    return (
        Path.home()
        / ".local/state/claude-codex"
        / project_id(root)
    )


def verify_release():
    manifest = json.loads(
        (RELEASE / "checksums.json").read_text()
    )

    for name, expected in manifest.items():
        path = RELEASE / name

        if (
            not path.is_file()
            or path.is_symlink()
            or digest(path) != expected
        ):
            raise SystemExit(
                f"ERROR: Release integrity mismatch: {name}"
            )


def registry_data():
    return json.loads(REGISTRY.read_text())


def register(root, version=VERSION):
    lock_path = REGISTRY.with_suffix(".lock")

    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        data = registry_data()

        data["projects"][project_id(root)] = {
            "name": root.name,
            "path": str(root),
            "version": version,
            "registered_at": now()
        }

        write_json(REGISTRY, data)


def doctor():
    print("Orchestrator version:", VERSION)

    verify_release()
    print("Release integrity: PASS")

    for command in ("python3", "git", "claude", "codex"):
        print(
            command + ":",
            shutil.which(command) or "NOT FOUND"
        )

    print(
        "Registered projects:",
        len(registry_data()["projects"])
    )


def verify(root):
    checker = root / ".claude/scripts/integrity-check.py"

    if not checker.is_file():
        raise SystemExit(
            "Project orchestration not installed."
        )

    return subprocess.call(
        [sys.executable, str(checker)],
        cwd=root
    )


def show_status(root, watch=False):
    script = (
        root / ".claude/scripts/orchestration-status.py"
    )

    if not script.is_file():
        print("Orchestration not installed:", root)
        return 1

    command = [sys.executable, str(script)]

    if watch:
        command.append("--watch")

    return subprocess.call(command, cwd=root)


def init(root):

    verify_release()

    target = root / ".claude"

    if (
        (target / "scripts/codex-session.py").exists()
        or (target / "hooks/completion-gate.py").exists()
    ):
        raise SystemExit(
            "Existing orchestration detected. "
            "Use orchestrator adopt. No files changed."
        )

    if target.is_symlink():
        raise SystemExit("ERROR: .claude is a symlink.")

    existing_settings = target / "settings.local.json"
    existing_instructions = root / "CLAUDE.md"

    settings = (
        json.loads(existing_settings.read_text())
        if existing_settings.exists()
        else {}
    )

    template_settings = json.loads(
        (
            RELEASE
            / "templates/settings.template.json"
        ).read_text()
    )

    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])

    for rule in template_settings.get(
        "permissions", {}
    ).get("allow", []):

        if rule not in allow:
            allow.append(rule)

    hooks = settings.setdefault("hooks", {})

    for event, definitions in template_settings.get(
        "hooks", {}
    ).items():

        current = hooks.setdefault(event, [])

        for definition in definitions:
            if definition not in current:
                current.append(definition)

    instructions = (
        existing_instructions.read_text()
        if existing_instructions.exists()
        else ""
    )

    if "# Claude-Codex Orchestration" in instructions:
        raise SystemExit(
            "Existing orchestration instructions detected."
        )

    template = (
        RELEASE / "templates/CLAUDE.md"
    ).read_text()

    template = template.split(
        "## 15. Example Project Rules", 1
    )[0]

    template = template.replace(
        "@AGENTS.md", "", 1
    ).strip()

    template = template.replace(
        "Orchestration V3",
        "Orchestration V4"
    )

    if (root / "AGENTS.md").exists():
        if "@AGENTS.md" not in instructions:
            instructions = "@AGENTS.md\n\n" + instructions

    instructions = (
        instructions.rstrip()
        + "\n\n"
        + template
        + "\n"
    )

    sources = [
        (source, target / folder / source.name)
        for folder in ("scripts", "hooks")
        for source in (RELEASE / folder).glob("*.py")
    ]

    profile_file = target / "orchestration-profiles.json"
    config = target / "orchestration.json"

    for destination in [
        *(d for _, d in sources),
        profile_file,
        config
    ]:
        if destination.exists() or destination.is_symlink():
            raise SystemExit(
                f"File conflict: {destination}"
            )

    state = state_directory(root)
    manifest = state / "integrity/manifest.json"

    if manifest.exists():
        raise SystemExit(
            "Existing integrity state detected."
        )

    backup = (
        GLOBAL / "backups"
        / project_id(root)
        / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )

    backup.mkdir(parents=True)

    existing_files = [
        existing_settings,
        existing_instructions,
        target / ".gitignore",
        target / "settings.template.json"
    ]

    for path in existing_files:
        if path.is_symlink():
            raise SystemExit(
                f"Unexpected symlink: {path}"
            )

        if path.exists():
            shutil.copy2(path, backup / path.name)

    target.mkdir(exist_ok=True)
    created = []

    try:

        for source, destination in sources:

            destination.parent.mkdir(
                parents=True, exist_ok=True
            )

            if destination.parent.is_symlink():
                raise RuntimeError(
                    f"Unsafe directory: {destination.parent}"
                )

            shutil.copy2(source, destination)
            destination.chmod(0o700)
            created.append(destination)

        profiles = {}

        allowed_scripts = {
            "build": 1200,
            "lint": 600,
            "typecheck": 600,
            "test": 1200,
            "test:routing": 600,
            "test:routing:browser": 1800,
            "test:login:browser": 1200
        }

        for directory in (
            ".", "frontend", "admin", "backend"
        ):

            package_file = (
                root / directory / "package.json"
            )

            if not package_file.is_file():
                continue

            package = json.loads(
                package_file.read_text()
            )

            for name, timeout in allowed_scripts.items():

                if name not in package.get("scripts", {}):
                    continue

                prefix = (
                    "root" if directory == "."
                    else directory
                )

                profile = prefix + "-" + name.replace(
                    ":", "-"
                )

                profiles[profile] = [
                    directory,
                    ["npm", "run", name],
                    timeout
                ]

        write_json(profile_file, profiles)
        created.append(profile_file)

        managed = target / "scripts/managed-exec.py"

        content = managed.read_text()

        start = content.index("PROFILES = {")
        end = content.index(
            "\nparser = argparse.ArgumentParser()",
            start
        )

        replacement = (
            'PROFILE_FILE = ROOT / '
            '".claude/orchestration-profiles.json"\n\n'
            'PROFILES = json.loads(PROFILE_FILE.read_text())\n'
        )

        content = (
            content[:start]
            + replacement
            + content[end:]
        )

        compile(content, str(managed), "exec")
        managed.write_text(content)

        for _, path in sources:

            content = path.read_text().replace(
                "LEGACY_CLAUDE_SESSION_ID",
                "ORCHESTRATOR_CLAUDE_SESSION_ID"
            )

            compile(content, str(path), "exec")
            path.write_text(content)

        write_json(existing_settings, settings)

        write_json(
            target / "settings.template.json",
            template_settings
        )

        existing_instructions.write_text(instructions)

        ignore = target / ".gitignore"

        old_ignore = (
            ignore.read_text()
            if ignore.exists() else ""
        )

        new_ignore = (
            RELEASE / "templates/.gitignore"
        ).read_text()

        ignore.write_text(
            old_ignore.rstrip()
            + "\n"
            + new_ignore
        )

        write_json(config, {
            "version": VERSION,
            "project_id": project_id(root),
            "project": str(root),
            "installed_at": now(),
            "backup": str(backup)
        })

        created.append(config)

        protected = created + existing_files

        # V4 installed file permission hardening
        for path in protected:

            if path.is_symlink() or not path.is_file():
                raise RuntimeError(
                    f"Unsafe installed file: {path}"
                )

            if path.stat().st_uid != os.getuid():
                raise RuntimeError(
                    f"Unexpected file owner: {path}"
                )

            if path.suffix == ".py":
                path.chmod(0o700)

            elif path.name in (
                "settings.local.json",
                "settings.template.json",
                "orchestration.json",
                "orchestration-profiles.json"
            ):
                path.chmod(0o600)

            else:
                path.chmod(0o644)

        write_json(manifest, {
            "project": str(root),
            "algorithm": "sha256",
            "created_at": now(),
            "files": {
                str(path.relative_to(root)): digest(path)
                for path in protected
            }
        })

        if verify(root) != 0:
            raise RuntimeError(
                "Project integrity verification failed"
            )

        register(root)

    except BaseException:

        for path in created:
            path.unlink(missing_ok=True)

        manifest.unlink(missing_ok=True)

        for path in existing_files:

            original = backup / path.name

            if original.exists():
                shutil.copy2(original, path)
            else:
                path.unlink(missing_ok=True)

        raise

    print("PROJECT_INITIALIZATION_SUCCESS")
    print("Project:", root)
    print("Version:", VERSION)
    print("Managed profiles:", len(profiles))
    print("Backup:", backup)
    print("Open a new Claude Code session.")


def adopt(root):

    if verify(root) != 0:
        raise SystemExit(
            "Existing integrity verification failed."
        )

    config = root / ".claude/orchestration.json"

    version = (
        json.loads(config.read_text()).get("version", VERSION)
        if config.exists()
        else "3"
    )

    register(root, version)

    print("EXISTING_PROJECT_REGISTERED")
    print("Project version:", version)
    print("Project files unchanged.")
    print("Existing session mappings preserved.")


parser = argparse.ArgumentParser(
    description="Claude-Codex Global Orchestrator"
)

parser.add_argument(
    "--version",
    action="version",
    version=VERSION
)

sub = parser.add_subparsers(
    dest="action", required=True
)

for command in (
    "init",
    "adopt",
    "doctor",
    "verify",
    "projects",
    "watch"
):
    sub.add_parser(command)

status = sub.add_parser("status")
status.add_argument("--all", action="store_true")

args = parser.parse_args()

if args.action == "doctor":
    doctor()

elif args.action == "projects":
    print(json.dumps(registry_data(), indent=2))

elif args.action == "status" and args.all:

    for project in registry_data()["projects"].values():

        root = Path(project["path"])

        if root.is_dir():
            show_status(root)
        else:
            print("Unavailable:", root)

else:

    root = project_root()

    if args.action == "init":
        init(root)

    elif args.action == "adopt":
        adopt(root)

    elif args.action == "verify":
        sys.exit(verify(root))

    elif args.action == "status":
        sys.exit(show_status(root))

    elif args.action == "watch":
        sys.exit(show_status(root, watch=True))
