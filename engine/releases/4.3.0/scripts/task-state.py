#!/usr/bin/env python3

import argparse
import ccx_platform as fcntl
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import ccx_platform as platform
from ccx_runtime import atomic_write
from ccx_runtime import safe_open
from ccx_runtime import private_directory

STATUSES = [
    "PENDING",
    "IN_PROGRESS",
    "REVIEWING",
    "CORRECTION_REQUIRED",
    "VERIFIED",
    "BLOCKED"
]

parser = argparse.ArgumentParser()

parser.add_argument(
    "action",
    choices=[
        "start",
        "add",
        "update",
        "status",
        "heartbeat",
        "finish",
        "pause",
        "resume",
        "recover"
    ]
)

parser.add_argument("--id")
parser.add_argument("--title")
parser.add_argument("--state", choices=STATUSES)
parser.add_argument("--note", default="")
parser.add_argument("--retry", action="store_true")

args = parser.parse_args()

try:
    session_id = str(uuid.UUID(
        os.environ["ORCHESTRATOR_CLAUDE_SESSION_ID"]
    ))
except (KeyError, ValueError):
    sys.exit("ERROR: Claude session ID unavailable.")

root = Path(__file__).resolve().parents[2]

project_id = hashlib.sha256(
    str(root).encode()
).hexdigest()[:16]

directory = (
    platform.state_root()
    / project_id
    / "tasks"
)

private_directory(directory)

state_file = directory / f"{session_id}.json"
lock_file = directory / f"{session_id}.lock"

def now():
    return datetime.now(timezone.utc).isoformat()


def recovery_status(state):

    timestamp = state.get("updated_at")
    age = None

    if timestamp:
        try:
            age = max(0, int(
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(timestamp)
                ).total_seconds()
            ))
        except (ValueError, TypeError):
            pass

    execution_lock = directory.parent / f"{session_id}.lock"

    with safe_open(execution_lock, "a") as handle:
        try:
            fcntl.flock(
                handle,
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )
            execution_busy = False
            fcntl.flock(handle, fcntl.LOCK_UN)
        except BlockingIOError:
            execution_busy = True

    unfinished = [
        task_id
        for task_id, task in state.get("tasks", {}).items()
        if task.get("status") not in (
            "VERIFIED", "BLOCKED"
        )
    ]

    recovery_required = (
        state.get("workflow_status") == "RUNNING"
        and not execution_busy
        and age is not None
        and age >= 300
        and bool(unfinished)
    )

    return {
        "last_activity_age_seconds": age,
        "codex_execution_lock_held": execution_busy,
        "unfinished_tasks": unfinished,
        "possible_stale_workflow": recovery_required,
        "diagnosis_required": recovery_required
    }


def new_workflow():
    return {
        "schema_version": 3,
        "workflow_id": str(uuid.uuid4()),
        "claude_session_id": session_id,
        "project": str(root),
        "active": True,
        "workflow_status": "RUNNING",
        "tasks": {},
        "created_at": now(),
        "updated_at": now()
    }


def archive_workflow(state):
    archive_dir = directory / "history" / session_id
    private_directory(archive_dir)

    workflow_id = state.setdefault(
        "workflow_id", str(uuid.uuid4())
    )

    workflow_id = str(uuid.UUID(workflow_id))
    archive_file = archive_dir / f"{workflow_id}.json"

    if not archive_file.exists():
        atomic_write(archive_file, json.dumps(state, indent=2) + "\n")

    return archive_file

with safe_open(lock_file, "a") as lock:

    fcntl.flock(lock, fcntl.LOCK_EX)

    state = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else {
            "claude_session_id": session_id,
            "project": str(root),
            "active": False,
            "tasks": {},
            "created_at": now()
        }
    )

    if args.action == "start":

        status = state.get("workflow_status")

        if status == "FINISHED":
            archive_workflow(state)
            state = new_workflow()

        elif status == "PAUSED":
            sys.exit(
                "ERROR: Unfinished paused workflow exists. "
                "Use resume instead."
            )

        elif status == "RUNNING":
            state.setdefault(
                "workflow_id", str(uuid.uuid4())
            )

        else:
            state = new_workflow()

    elif state_file.exists() and args.action != "status":
        state.setdefault(
            "workflow_id", str(uuid.uuid4())
        )

    if args.action != "status":
        state["schema_version"] = 3

    tasks = state["tasks"]

    if args.action in ("add", "update", "heartbeat", "finish"):
        if not state.get("active") or (
            state.get("workflow_status") != "RUNNING"
        ):
            sys.exit("ERROR: No active workflow.")

    if args.action == "pause":
        if state.get("workflow_status") != "RUNNING":
            sys.exit("ERROR: No running workflow to pause.")

    if args.action == "start":
        state["active"] = True
        state["workflow_status"] = "RUNNING"

    elif args.action == "add":

        if not args.id or not args.title:
            sys.exit("ERROR: --id and --title required.")

        if args.id not in tasks:
            tasks[args.id] = {
                "title": args.title,
                "status": "PENDING",
                "retries": 0,
                "note": "",
                "updated_at": now()
            }

    elif args.action == "update":

        if args.id not in tasks or not args.state:
            sys.exit("ERROR: Valid task ID and state required.")

        task = tasks[args.id]

        if args.retry:
            if task["retries"] >= 3:
                sys.exit("ERROR: Maximum retries reached.")
            task["retries"] += 1

        task["status"] = args.state
        task["note"] = args.note
        task["updated_at"] = now()

    elif args.action == "recover":

        if state.get("workflow_status") not in (
            "RUNNING", "PAUSED"
        ):
            sys.exit("ERROR: No unfinished workflow to recover.")

        diagnosis = recovery_status(state)

        if diagnosis["codex_execution_lock_held"]:
            sys.exit(
                "ERROR: Codex execution is still active. "
                "Do not launch duplicate recovery."
            )

        if not args.note.strip():
            sys.exit(
                "ERROR: Recovery requires a diagnostic note."
            )

        history = state.setdefault("recovery_history", [])

        history.append({
            "timestamp": now(),
            "note": args.note,
            "previous_status": state.get("workflow_status"),
            "diagnosis": diagnosis
        })

        for task in tasks.values():

            if task["status"] in (
                "IN_PROGRESS",
                "REVIEWING",
                "CORRECTION_REQUIRED"
            ):
                task["recovery_required"] = True

        state["last_recovered_at"] = now()

    elif args.action == "heartbeat":
        state["last_heartbeat"] = now()

    elif args.action == "pause":
        state["active"] = False
        state["workflow_status"] = "PAUSED"

    elif args.action == "resume":

        if state.get("workflow_status") not in (
            "PAUSED", "RUNNING"
        ):
            sys.exit(
                "ERROR: No unfinished workflow to resume. "
                "Use start for a new workflow."
            )

        if state.get("workflow_status") == "PAUSED":

            gate = state.get("completion_gate", {})

            if gate.get("limit_reached"):

                history = state.setdefault(
                    "completion_gate_history", []
                )

                history.append({
                    **gate,
                    "resumed_at": now(),
                    "pause_reason": state.get("pause_reason")
                })

                state.pop("completion_gate", None)

            state.pop("pause_reason", None)

            state["resume_count"] = (
                state.get("resume_count", 0) + 1
            )

            state["last_resumed_at"] = now()

        state["active"] = True
        state["workflow_status"] = "RUNNING"

    elif args.action == "finish":

        remaining = [
            key for key, task in tasks.items()
            if task["status"] not in ("VERIFIED", "BLOCKED")
        ]

        if remaining or not tasks:
            sys.exit(
                f"ERROR: Workflow incomplete. Remaining: {remaining}"
            )

        state["active"] = False
        state["workflow_status"] = "FINISHED"
        state["completed_at"] = now()

    if args.action != "status":
        state["updated_at"] = now()

        atomic_write(state_file, json.dumps(state, indent=2) + "\n")

    summary = {
        status: sum(
            task["status"] == status
            for task in tasks.values()
        )
        for status in STATUSES
    }

    print(json.dumps({
        **state,
        "summary": summary,
        "total_tasks": len(tasks),
        "recovery_status": recovery_status(state)
    }, indent=2))
