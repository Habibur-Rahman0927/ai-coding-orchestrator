#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import argparse
import ccx_platform as fcntl
import hashlib
import json
import os
import subprocess
import sys
import uuid
try:
    import tomllib
except ImportError:
    tomllib = None  # Python 3.8–3.10: Codex itself inherits its TOML defaults.
import time
from datetime import datetime, timezone
from pathlib import Path
import ccx_platform as platform
from ccx_runtime import atomic_write
from ccx_runtime import safe_open
from ccx_runtime import private_directory

parser = argparse.ArgumentParser()

parser.add_argument(
    "--sandbox",
    choices=["read-only", "workspace-write"],
    default="read-only"
)

parser.add_argument("--model")

parser.add_argument(
    "--effort",
    choices=["low", "medium", "high", "xhigh", "max", "ultra"]
)

parser.add_argument(
    "--speed",
    choices=["default", "fast"]
)

parser.add_argument(
    "--sync-defaults",
    action="store_true"
)

parser.add_argument("--status", action="store_true")
parser.add_argument("--reset", action="store_true")
parser.add_argument("prompt", nargs="?")

args = parser.parse_args()

# V3 integrity preflight
if not args.status:
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



def load_codex_defaults():

    home = Path(os.environ.get(
        "CODEX_HOME",
        Path.home() / ".codex"
    ))

    config = home / "config.toml"

    if tomllib is None or not config.exists():
        return {}

    try:
        with config.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(
            f"ERROR: Cannot read Codex config: {error}"
        )

    return {
        "model": data.get("model"),
        "effort": data.get("model_reasoning_effort"),
        "service_tier": data.get("service_tier")
    }


# Detect Claude session
try:
    claude_id = str(uuid.UUID(
        os.environ["ORCHESTRATOR_CLAUDE_SESSION_ID"]
    ))
except (KeyError, ValueError):
    sys.exit("ERROR: Claude session ID unavailable.")

# Identify project
root = Path(__file__).resolve().parents[2]

project_id = hashlib.sha256(
    str(root).encode()
).hexdigest()[:16]

# Store session state outside the Git repository
state_dir = (
    platform.state_root()
    / project_id
)

private_directory(state_dir)

state_file = state_dir / f"{claude_id}.json"
lock_file = state_dir / f"{claude_id}.lock"

from ccx_runtime import serialize_session, guardian_popen
try:
    launch_lock = serialize_session(state_dir, claude_id)
except BlockingIOError:
    sys.exit(75)

with safe_open(lock_file, "a") as lock:

    fcntl.flock(lock, fcntl.LOCK_EX)

    state = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else {}
    )

    if args.reset:
        state = {}
        state_file.unlink(missing_ok=True)
        print("Codex session mapping reset.")
        sys.exit(0)

    if args.status:
        print(json.dumps({
            "claude_session_id": claude_id,
            "project": str(root),
            **state
        }, indent=2))
        sys.exit(0)

    if not args.prompt:
        sys.exit("ERROR: Task prompt is required.")

    # V3 project-level concurrency protection.
    project_lock_file = state_dir / "project-execution.lock"

    project_lock = safe_open(project_lock_file, "a")

    lock_type = (
        fcntl.LOCK_EX
        if args.sandbox == "workspace-write"
        else fcntl.LOCK_SH
    )

    try:
        fcntl.flock(
            project_lock,
            lock_type | fcntl.LOCK_NB
        )
    except BlockingIOError:
        print(json.dumps({
            "status": "PROJECT_BUSY",
            "sandbox": args.sandbox,
            "message": (
                "Another managed execution holds the project lock. "
                "Do not start a duplicate execution. "
                "Check the active workflow before retrying."
            )
        }), file=sys.stderr, flush=True)

        project_lock.close()
        sys.exit(75)

    print(json.dumps({
        "status": "PROJECT_LOCK_ACQUIRED",
        "lock_type": (
            "EXCLUSIVE"
            if args.sandbox == "workspace-write"
            else "SHARED"
        )
    }), flush=True)

    codex_id = state.get("codex_session_id")

    defaults = load_codex_defaults()

    if args.sync_defaults:
        for key in ("model", "effort", "service_tier"):
            state.pop(key, None)

    model = (
        args.model
        or state.get("model")
        or defaults.get("model")
    )

    effort = (
        args.effort
        or state.get("effort")
        or defaults.get("effort")
    )

    service_tier = (
        state.get("service_tier")
        if "service_tier" in state
        else defaults.get("service_tier")
    )

    if args.speed == "fast":
        service_tier = "priority"

    elif args.speed == "default":
        service_tier = "default"

    # V3 persistent execution telemetry.
    execution_id = str(uuid.uuid4())
    execution_started = time.monotonic()

    log_dir = state_dir / "logs"
    private_directory(log_dir)

    execution_log = log_dir / f"{claude_id}.jsonl"

    def record_execution_event(event_name, **details):

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_id": execution_id,
            "claude_session_id": claude_id,
            "codex_session_id": state.get("codex_session_id"),
            "model": model,
            "effort": effort,
            "service_tier": service_tier,
            "sandbox": args.sandbox,
            "event": event_name,
            **details
        }

        with safe_open(execution_log, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps(entry) + "\n")
            handle.flush()

    record_execution_event(
        "EXECUTION_REQUESTED",
        action="RESUME" if codex_id else "CREATE"
    )

    command = ["codex", "exec"]

    if codex_id:
        command.append("resume")

    command.extend([
        "--json",
        "-c", f'sandbox_mode="{args.sandbox}"',
        "-c", 'approval_policy="never"'
    ])

    if model:
        command.extend(["--model", model])

    if effort:
        command.extend([
            "-c",
            f'model_reasoning_effort="{effort}"'
        ])

    if service_tier:
        command.extend([
            "-c",
            f'service_tier={json.dumps(service_tier)}'
        ])

    if codex_id:
        command.append(codex_id)

    command.extend(["--", args.prompt])

    print(f"Claude session: {claude_id}", flush=True)
    print(f"Codex session: {codex_id or 'NEW'}", flush=True)
    print(f"Action: {'RESUME' if codex_id else 'CREATE'}", flush=True)
    print(f"Model: {model or 'Configured default'}", flush=True)
    print(f"Effort: {effort or 'Configured default'}", flush=True)
    print(
        f"Service tier: {service_tier or 'Configured default'}",
        flush=True
    )

    print(f"Sandbox: {args.sandbox}", flush=True)

    recovery_controller = (
        root / ".claude/scripts/recovery-controller.py"
    )

    managed_command = [
        sys.executable,
        str(recovery_controller),
        "--timeout", "1800",
        "--heartbeat", "60",
        "--retries", "0",
        "--lock-fd", str(lock.fileno()),
        "--lock-fd", str(project_lock.fileno()),
        "--",
        *command
    ]

    process = guardian_popen(
        managed_command,
        locks=(lock, project_lock),
        shared=(project_lock,) if args.sandbox == "read-only" else (),
        preflight=integrity_script,
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    completed = False

    codex_errors = []

    usage_guard_script = (
        root / ".claude/scripts/usage-guard.py"
    )

    context_monitor_script = (
        root / ".claude/scripts/context-monitor.py"
    )

    for line in process.stdout:

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "status" in event and "type" not in event:

            record_execution_event(
                "RECOVERY_EVENT",
                recovery_status=event.get("status"),
                pid=event.get("pid"),
                attempt=event.get("attempt"),
                elapsed_seconds=event.get("elapsed_seconds"),
                idle_seconds=event.get("idle_seconds"),
                exit_code=event.get("exit_code")
            )
            print(
                "Recovery:",
                json.dumps(event),
                flush=True
            )
            continue

        event_type = event.get("type")

        if event_type == "thread.started":

            thread_id = str(uuid.UUID(event["thread_id"]))

            if codex_id and thread_id != codex_id:
                process.terminate()
                sys.exit("ERROR: Unexpected Codex session ID.")

            state["codex_session_id"] = thread_id

            if model:
                state["model"] = model

            if effort:
                state["effort"] = effort

            if service_tier:
                state["service_tier"] = service_tier

            atomic_write(state_file, json.dumps(state, indent=2))

            record_execution_event(
                "CODEX_SESSION_STARTED",
                thread_id=thread_id
            )

            print(f"Active Codex session: {thread_id}", flush=True)

        elif event_type == "item.completed":

            item = event.get("item", {})

            if item.get("type") == "agent_message":
                print(item.get("text", ""), flush=True)

        elif event_type == "turn.completed":

            completed = True

            usage = event.get("usage", {})

            def token_count(key):
                value = usage.get(key, 0)
                return value if isinstance(value, int) and value >= 0 else 0

            input_tokens = token_count("input_tokens")
            cached_tokens = token_count("cached_input_tokens")
            output_tokens = token_count("output_tokens")
            reasoning_tokens = token_count("reasoning_output_tokens")

            record_execution_event(
                "TOKEN_USAGE",
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                uncached_input_tokens=max(
                    0, input_tokens - cached_tokens
                ),
                output_tokens=output_tokens,
                reasoning_output_tokens=reasoning_tokens,
                cache_write_input_tokens=token_count(
                    "cache_write_input_tokens"
                )
            )
            print(
                "Usage:",
                json.dumps(event.get("usage", {})),
                flush=True
            )

        elif event_type in ("turn.failed", "error"):

            codex_errors.append(
                json.dumps(event)
            )

            record_execution_event(
                "CODEX_ERROR",
                error_type=event_type
            )

            print(json.dumps(event), file=sys.stderr)

    exit_code = process.wait()

    record_execution_event(
        "EXECUTION_FINISHED",
        exit_code=exit_code,
        completed=completed,
        success=exit_code == 0 and completed,
        duration_seconds=round(
            time.monotonic() - execution_started, 2
        )
    )

    # Automatically classify structured execution errors.
    if (exit_code != 0 or not completed) and codex_errors:

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(usage_guard_script),
                    "--apply"
                ],
                input="\n".join(codex_errors),
                capture_output=True,
                text=True,
                timeout=15,
                check=True
            )

            guard = json.loads(result.stdout)

            record_execution_event(
                "USAGE_GUARD",
                **guard
            )

            print(
                "Usage Guard:",
                json.dumps(guard),
                flush=True
            )

        except (
            OSError,
            ValueError,
            subprocess.SubprocessError
        ) as error:

            print(
                f"WARNING: Usage Guard failed: {error}",
                file=sys.stderr
            )

    # Report context and usage after completed turns.
    if completed:

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(context_monitor_script),
                    "--session", claude_id
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=True
            )

            context = json.loads(result.stdout)

            record_execution_event(
                "CONTEXT_MONITOR",
                recorded_turns=context.get(
                    "recorded_turns", 0
                ),
                warnings=context.get("warnings", []),
                input_cache_ratio_percent=context.get(
                    "input_cache_ratio_percent"
                )
            )

            print(
                "Context Monitor:",
                json.dumps({
                    "recorded_turns": context.get(
                        "recorded_turns"
                    ),
                    "latest_turn_usage": context.get(
                        "latest_turn_usage"
                    ),
                    "input_cache_ratio_percent": context.get(
                        "input_cache_ratio_percent"
                    ),
                    "warnings": context.get(
                        "warnings", []
                    ),
                    "recommendations": context.get(
                        "recommendations", []
                    )
                }),
                flush=True
            )

        except (
            OSError,
            ValueError,
            subprocess.SubprocessError
        ) as error:

            print(
                f"WARNING: Context Monitor failed: {error}",
                file=sys.stderr
            )

    if exit_code != 0 or not completed:
        sys.exit(exit_code or 1)
