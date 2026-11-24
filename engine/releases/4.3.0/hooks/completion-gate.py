#!/usr/bin/env python3

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ccx_platform as fcntl
import hashlib
import json
import sys
import uuid

from datetime import datetime, timezone
from pathlib import Path
import ccx_platform as platform
from ccx_runtime import atomic_write
from ccx_runtime import safe_open

MAX_NO_PROGRESS_ATTEMPTS = 3
MAX_TOTAL_CONTINUATIONS = 20


def now():
    return datetime.now(timezone.utc).isoformat()


def block(reason):
    print(json.dumps({
        "decision": "block",
        "reason": reason
    }))
    sys.exit(0)


def save_state(path, data):
    atomic_write(path, json.dumps(data, indent=2) + "\n")


try:
    event = json.load(sys.stdin)
    session_id = str(uuid.UUID(event["session_id"]))
except (ValueError, KeyError, TypeError):
    sys.exit(0)

root = Path(__file__).resolve().parents[2]

project_id = hashlib.sha256(
    str(root).encode()
).hexdigest()[:16]

directory = (
    platform.state_root()
    / project_id
    / "tasks"
)

state_file = directory / f"{session_id}.json"

if not state_file.exists():
    sys.exit(0)

lock_file = directory / f"{session_id}.lock"

with safe_open(lock_file, "a") as lock:

    try:
        fcntl.flock(
            lock,
            fcntl.LOCK_EX | fcntl.LOCK_NB
        )
    except BlockingIOError:
        sys.exit(0)

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(
            "WARNING: Unable to read workflow state.",
            file=sys.stderr
        )
        sys.exit(0)

    if not state.get("active", False):
        sys.exit(0)

    if state.get("workflow_status") != "RUNNING":
        sys.exit(0)

    workflow_id = state.get(
        "workflow_id",
        session_id
    )

    tasks = state.get("tasks", {})

    remaining = [
        {
            "id": task_id,
            "title": task.get("title", ""),
            "status": task.get("status", ""),
            "retries": task.get("retries", 0)
        }
        for task_id, task in tasks.items()
        if task.get("status") not in (
            "VERIFIED", "BLOCKED"
        )
    ]

    terminal_tasks = sorted(
        (
            task_id,
            task.get("status", "")
        )
        for task_id, task in tasks.items()
        if task.get("status") in (
            "VERIFIED", "BLOCKED"
        )
    )

    progress = {
        "task_count": len(tasks),
        "terminal_tasks": terminal_tasks
    }

    fingerprint = hashlib.sha256(
        json.dumps(
            progress,
            sort_keys=True
        ).encode()
    ).hexdigest()

    gate = state.get("completion_gate", {})

    if gate.get("workflow_id") != workflow_id:
        gate = {
            "workflow_id": workflow_id,
            "total_continuations": 0,
            "no_progress_attempts": 0,
            "last_fingerprint": None
        }

    if gate["last_fingerprint"] != fingerprint:
        gate["no_progress_attempts"] = 0

    gate["last_fingerprint"] = fingerprint

    if (
        gate["total_continuations"]
        >= MAX_TOTAL_CONTINUATIONS

        or gate["no_progress_attempts"]
        >= MAX_NO_PROGRESS_ATTEMPTS
    ):

        gate["limit_reached"] = True
        gate["last_checked_at"] = now()

        state["completion_gate"] = gate
        state["active"] = False
        state["workflow_status"] = "PAUSED"

        state["pause_reason"] = (
            "Completion Gate continuation limit reached. "
            "Unfinished tasks preserved for recovery."
        )

        save_state(state_file, state)

        print(
            "WARNING: Workflow safely paused after "
            "reaching continuation limits.",
            file=sys.stderr
        )

        sys.exit(0)

    gate["total_continuations"] += 1
    gate["no_progress_attempts"] += 1
    gate["last_checked_at"] = now()

    state["completion_gate"] = gate

    save_state(state_file, state)

    verified = sum(
        t.get("status") == "VERIFIED"
        for t in tasks.values()
    )

    blocked = sum(
        t.get("status") == "BLOCKED"
        for t in tasks.values()
    )

    summary = (
        f"Workflow: {workflow_id}\n"
        f"Verified: {verified}/{len(tasks)}\n"
        f"Blocked: {blocked}\n"
        f"Remaining: {len(remaining)}\n"
        f"Continuation attempt: "
        f"{gate['total_continuations']}/"
        f"{MAX_TOTAL_CONTINUATIONS}\n"
        f"No-progress attempts: "
        f"{gate['no_progress_attempts']}/"
        f"{MAX_NO_PROGRESS_ATTEMPTS}\n"
    )

    if not tasks:
        block(
            summary
            + "\nRegister the authorized task checklist "
            "or pause if execution cannot continue."
        )

    if remaining:

        block(
            summary
            + "\nRemaining tasks:\n"
            + json.dumps(remaining, indent=2)
            + "\n\nInspect actual process health. "
            "Continue through the persistent Codex session. "
            "Do not launch duplicate executions. "
            "Verify completed work and update task states. "
            "Respect permissions, retry limits, "
            "user cancellation and genuine blockers."
        )

    block(
        summary
        + "\nAll registered tasks are terminal. "
        "Finalize the task-state workflow and "
        "provide the consolidated report."
    )
