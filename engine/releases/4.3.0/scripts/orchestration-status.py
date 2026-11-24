#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import sys
import time
import ccx_platform as fcntl

from datetime import datetime, timezone
from pathlib import Path
import ccx_platform as platform
from ccx_runtime import safe_open

parser = argparse.ArgumentParser()
parser.add_argument("--session")
parser.add_argument("--json", action="store_true")
parser.add_argument("--watch", action="store_true")
parser.add_argument("--interval", type=int, default=5)
args = parser.parse_args()

if args.interval < 1:
    parser.error("Interval must be positive.")

root = Path(__file__).resolve().parents[2]

project_id = hashlib.sha256(
    str(root).encode()
).hexdigest()[:16]

directory = (
    platform.state_root()
    / project_id
)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def execution_busy(session_id):

    path = directory / f"{session_id}.lock"

    if not path.exists():
        return False

    with safe_open(path, "r") as handle:
        try:
            fcntl.flock(
                handle,
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def age_seconds(timestamp):

    if not timestamp:
        return None

    try:
        return max(0, int(
            (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(timestamp)
            ).total_seconds()
        ))
    except (ValueError, TypeError):
        return None


def collect():

    sessions = []

    ids = {
        p.stem
        for p in directory.glob("*.json")
    }

    ids.update(
        p.stem
        for p in (directory / "tasks").glob("*.json")
    )

    for session_id in sorted(ids):

        if args.session and session_id != args.session:
            continue

        mapping = read_json(
            directory / f"{session_id}.json"
        )

        workflow = read_json(
            directory / "tasks" / f"{session_id}.json"
        )

        tasks = workflow.get("tasks", {})

        summary = {}

        for task in tasks.values():
            status = task.get("status", "UNKNOWN")
            summary[status] = summary.get(status, 0) + 1

        events = []
        invalid_records = 0

        log = directory / "logs" / f"{session_id}.jsonl"

        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    invalid_records += 1

        usage = [
            e for e in events
            if e.get("event") == "TOKEN_USAGE"
        ]

        finished = [
            e for e in events
            if e.get("event") == "EXECUTION_FINISHED"
        ]

        requested = [
            e for e in events
            if e.get("event") == "EXECUTION_REQUESTED"
        ]

        recovery = [
            e for e in events
            if e.get("event") == "RECOVERY_EVENT"
        ]

        input_tokens = sum(
            e.get("input_tokens", 0) for e in usage
        )

        cached_tokens = sum(
            e.get("cached_input_tokens", 0) for e in usage
        )

        busy = execution_busy(session_id)
        age = age_seconds(workflow.get("updated_at"))

        remaining = [
            key for key, task in tasks.items()
            if task.get("status") not in (
                "VERIFIED", "BLOCKED"
            )
        ]

        possible_stale = (
            workflow.get("workflow_status") == "RUNNING"
            and not busy
            and age is not None
            and age >= 300
            and bool(remaining)
        )

        sessions.append({
            "claude_session_id": session_id,
            "codex_session_id": mapping.get("codex_session_id"),
            "workflow_id": workflow.get("workflow_id"),
            "workflow_status": workflow.get(
                "workflow_status", "NOT_STARTED"
            ),
            "model": mapping.get("model"),
            "effort": mapping.get("effort"),
            "service_tier": mapping.get("service_tier"),
            "codex_execution_busy": busy,
            "possible_stale_workflow": possible_stale,
            "last_activity_age_seconds": age,
            "pause_reason": workflow.get("pause_reason"),
            "total_tasks": len(tasks),
            "task_summary": summary,
            "remaining_tasks": remaining,
            "execution_requests": len(requested),
            "finished_executions": len(finished),
            "successful_executions": sum(
                bool(e.get("success")) for e in finished
            ),
            "failed_executions": sum(
                not bool(e.get("success")) for e in finished
            ),
            "timeouts": sum(
                e.get("recovery_status") == "EXECUTION_TIMEOUT"
                for e in recovery
            ),
            "retry_attempts": sum(
                task.get("retries", 0)
                for task in tasks.values()
            ),
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "uncached_input_tokens": max(
                0, input_tokens - cached_tokens
            ),
            "output_tokens": sum(
                e.get("output_tokens", 0) for e in usage
            ),
            "cache_ratio_percent": round(
                cached_tokens / input_tokens * 100, 2
            ) if input_tokens else None,
            "recorded_execution_seconds": round(sum(
                e.get("duration_seconds", 0)
                for e in finished
            ), 2),
            "invalid_log_records": invalid_records
        })

    return {
        "project": str(root),
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_sessions": len(sessions),
        "running_workflows": sum(
            s["workflow_status"] == "RUNNING"
            for s in sessions
        ),
        "paused_workflows": sum(
            s["workflow_status"] == "PAUSED"
            for s in sessions
        ),
        "finished_workflows": sum(
            s["workflow_status"] == "FINISHED"
            for s in sessions
        ),
        "active_codex_executions": sum(
            s["codex_execution_busy"]
            for s in sessions
        ),
        "sessions": sessions
    }


def display(data):

    if args.json:
        print(json.dumps(data, indent=2), flush=True)
        return

    print("=" * 72)
    print("CLAUDE + CODEX ORCHESTRATION STATUS")
    print("=" * 72)
    print("Project:", data["project"])
    print("Time:", data["timestamp"])
    print("Sessions:", data["total_sessions"])
    print("Running workflows:", data["running_workflows"])
    print("Paused workflows:", data["paused_workflows"])
    print("Finished workflows:", data["finished_workflows"])
    print("Active Codex executions:", data["active_codex_executions"])

    for s in data["sessions"]:

        print("-" * 72)

        print("Claude:", s["claude_session_id"])
        print("Codex:", s["codex_session_id"])
        print("Workflow:", s["workflow_status"])
        print("Model:", s["model"])
        print("Effort:", s["effort"])
        print("Speed tier:", s["service_tier"])

        verified = s["task_summary"].get("VERIFIED", 0)

        print(
            "Verified tasks:",
            f'{verified}/{s["total_tasks"]}'
        )

        print("Task states:", s["task_summary"])
        print("Remaining:", s["remaining_tasks"])
        print("Execution active:", s["codex_execution_busy"])
        print("Possible stale:", s["possible_stale_workflow"])
        print("Executions:", s["execution_requests"])
        print("Successful:", s["successful_executions"])
        print("Failed:", s["failed_executions"])
        print("Timeouts:", s["timeouts"])
        print("Task retries:", s["retry_attempts"])
        print("Input tokens:", s["input_tokens"])
        print("Cached tokens:", s["cached_input_tokens"])
        print("Uncached tokens:", s["uncached_input_tokens"])
        print("Output tokens:", s["output_tokens"])
        print("Cache ratio:", s["cache_ratio_percent"])
        print("Execution seconds:", s["recorded_execution_seconds"])

        if s["pause_reason"]:
            print("Pause reason:", s["pause_reason"])

        if s["invalid_log_records"]:
            print(
                "WARNING: Invalid log records:",
                s["invalid_log_records"]
            )

    print("=" * 72, flush=True)


try:
    while True:

        if args.watch and not args.json:
            print("\033[2J\033[H", end="")

        display(collect())

        if not args.watch:
            break

        time.sleep(args.interval)

except KeyboardInterrupt:
    sys.exit(0)
