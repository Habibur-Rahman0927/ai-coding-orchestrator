#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid

from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROFILES = {
    "frontend-build": ("frontend", ["npm", "run", "build"], 1200),
    "frontend-lint": ("frontend", ["npm", "run", "lint"], 600),
    "frontend-typecheck": ("frontend", ["npm", "run", "typecheck"], 600),
    "frontend-routing": ("frontend", ["npm", "run", "test:routing"], 600),
    "frontend-browser": ("frontend", ["npm", "run", "test:routing:browser"], 1800),
    "frontend-login": ("frontend", ["npm", "run", "test:login:browser"], 1200),
    "frontend-assets": ("frontend", ["npm", "run", "check:assets"], 600),
    "frontend-loaders": ("frontend", ["npm", "run", "test:loaders"], 600),
    "frontend-media": ("frontend", ["npm", "run", "test:media"], 600),
    "frontend-performance": ("frontend", ["npm", "run", "test:performance-tools"], 900),
    "frontend-analyzer": ("frontend", ["npm", "run", "analyze:webpack"], 1200),
    "admin-build": ("admin", ["npm", "run", "build"], 900),
    "admin-lint": ("admin", ["npm", "run", "lint"], 600),
    "admin-test": ("admin", ["npm", "run", "test"], 900),
    "backend-build": ("backend", ["npm", "run", "build"], 900),
}

parser = argparse.ArgumentParser()
parser.add_argument("profile", nargs="?", choices=sorted(PROFILES))
parser.add_argument("--list", action="store_true")
parser.add_argument("--dry-run", action="store_true")

args = parser.parse_args()

# V3 integrity preflight
if not args.list and not args.dry_run:
    integrity_script = (
        Path(__file__).resolve().parent
        / "integrity-check.py"
    )

    try:
        integrity_result = subprocess.run(
            [sys.executable, str(integrity_script)],
            capture_output=True,
            text=True,
            timeout=15
        )
    except (OSError, subprocess.SubprocessError) as error:
        sys.exit(f"Integrity preflight failed: {error}")

    if integrity_result.returncode != 0:
        print(
            integrity_result.stdout,
            file=sys.stderr
        )
        sys.exit(78)


if args.list:
    for name, (cwd, command, timeout) in PROFILES.items():
        print(json.dumps({
            "profile": name,
            "directory": cwd,
            "command": command,
            "timeout_seconds": timeout
        }))
    sys.exit(0)

if not args.profile:
    parser.error("Select an execution profile.")

cwd, command, timeout = PROFILES[args.profile]

workdir = ROOT / cwd

if not workdir.is_dir():
    sys.exit("ERROR: Profile directory unavailable.")

package_file = workdir / "package.json"

if not package_file.exists():
    sys.exit("ERROR: package.json unavailable.")

package = json.loads(package_file.read_text())

script_name = command[2]

if script_name not in package.get("scripts", {}):
    sys.exit("ERROR: Package script unavailable.")

if args.dry_run:
    print(json.dumps({
        "profile": args.profile,
        "directory": str(workdir),
        "command": command,
        "package_script": package["scripts"][script_name],
        "timeout_seconds": timeout,
        "heartbeat_seconds": 60,
        "idle_warning_seconds": 300,
        "automatic_retries": 0
    }, indent=2))
    sys.exit(0)

try:
    session_id = str(uuid.UUID(
        os.environ["LEGACY_CLAUDE_SESSION_ID"]
    ))
except (KeyError, ValueError):
    sys.exit("ERROR: Claude session ID unavailable.")

project_id = hashlib.sha256(
    str(ROOT).encode()
).hexdigest()[:16]

state_dir = (
    Path.home()
    / ".local/state/claude-codex"
    / project_id
)

log_dir = state_dir / "managed-executions"

log_dir.mkdir(
    parents=True,
    exist_ok=True,
    mode=0o700
)

execution_id = str(uuid.uuid4())
log_path = log_dir / f"{execution_id}.log"
metadata_path = log_dir / f"{execution_id}.json"

session_lock_path = state_dir / f"{session_id}.lock"
project_lock_path = state_dir / "project-execution.lock"

metadata = {
    "execution_id": execution_id,
    "claude_session_id": session_id,
    "profile": args.profile,
    "status": "STARTING",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "log_path": str(log_path)
}


def save_metadata():
    temp = metadata_path.with_suffix(".tmp")
    temp.write_text(json.dumps(metadata, indent=2) + "\n")
    temp.chmod(0o600)
    temp.replace(metadata_path)


with session_lock_path.open("a") as session_lock:
    with project_lock_path.open("a") as project_lock:

        try:
            fcntl.flock(
                session_lock,
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )

            fcntl.flock(
                project_lock,
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )

        except BlockingIOError:
            sys.exit(75)

        controller = ROOT / ".claude/scripts/recovery-controller.py"

        managed_command = [
            sys.executable,
            str(controller),
            "--timeout", str(timeout),
            "--heartbeat", "60",
            "--idle-timeout", "300",
            "--retries", "0",
            "--lock-fd", str(session_lock.fileno()),
            "--lock-fd", str(project_lock.fileno()),
            "--",
            *command
        ]

        print("Managed profile:", args.profile, flush=True)
        print("Execution ID:", execution_id, flush=True)
        print("Execution log:", log_path, flush=True)

        started = time.monotonic()

        fd = os.open(
            log_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600
        )

        with os.fdopen(fd, "w") as log:

            process = subprocess.Popen(
                managed_command,
                cwd=workdir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                pass_fds=(
                    session_lock.fileno(),
                    project_lock.fileno()
                ),
                text=True,
                errors="replace",
                bufsize=1
            )

            metadata["status"] = "RUNNING"
            metadata["controller_pid"] = process.pid
            save_metadata()

            def cancel(signum, frame):
                raise KeyboardInterrupt

            signal.signal(signal.SIGTERM, cancel)

            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    print(line, end="", flush=True)

                exit_code = process.wait()

            except (KeyboardInterrupt, BrokenPipeError):
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    metadata["cleanup_unconfirmed"] = True
                exit_code = 130

            finally:
                if process.stdout:
                    process.stdout.close()

        metadata.update({
            "status": (
                "SUCCESS" if exit_code == 0
                else "INTERRUPTED" if exit_code == 130
                else "FAILED"
            ),
            "exit_code": exit_code,
            "duration_seconds": round(
                time.monotonic() - started, 2
            ),
            "finished_at": datetime.now(timezone.utc).isoformat()
        })

        save_metadata()

        print(json.dumps(metadata, indent=2), flush=True)

        sys.exit(exit_code if exit_code >= 0 else 1)
