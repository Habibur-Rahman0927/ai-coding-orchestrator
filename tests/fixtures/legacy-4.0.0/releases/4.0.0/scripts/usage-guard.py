#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import uuid

from datetime import datetime, timezone
from pathlib import Path


def classify_error(message):

    patterns = {
        "USAGE_LIMIT": [
            r"usage[_ ]limit[_ ]reached",
            r"you(?:'ve| have) reached your usage limit",
            r"you(?:'ve| have) hit your usage limit",
            r"usage limit has been reached"
        ],
        "QUOTA_EXHAUSTED": [
            r"insufficient_quota",
            r"quota_exceeded",
            r"exceeded your current quota"
        ],
        "RATE_LIMIT": [
            r"rate_limit_exceeded",
            r"rate limit exceeded",
            r"too many requests",
            r"http\s*429"
        ],
        "CONTEXT_LIMIT": [
            r"context_length_exceeded",
            r"maximum context length",
            r"context window exceeded"
        ],
        "AUTHENTICATION_REQUIRED": [
            r"authentication required",
            r"invalid_api_key",
            r"token_expired"
        ]
    }

    for category, expressions in patterns.items():
        if any(
            re.search(pattern, message, re.IGNORECASE)
            for pattern in expressions
        ):
            return category

    return "UNKNOWN_ERROR"


def pause_workflow(category):

    session_id = str(uuid.UUID(
        os.environ["LEGACY_CLAUDE_SESSION_ID"]
    ))

    root = Path(__file__).resolve().parents[2]

    project_id = hashlib.sha256(
        str(root).encode()
    ).hexdigest()[:16]

    directory = (
        Path.home()
        / ".local/state/claude-codex"
        / project_id
        / "tasks"
    )

    state_file = directory / f"{session_id}.json"
    lock_file = directory / f"{session_id}.lock"

    if not state_file.exists():
        return False

    with lock_file.open("a") as lock:

        fcntl.flock(lock, fcntl.LOCK_EX)

        state = json.loads(state_file.read_text())

        if state.get("workflow_status") != "RUNNING":
            return False

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        state["active"] = False
        state["workflow_status"] = "PAUSED"

        state["pause_reason"] = category
        state["updated_at"] = timestamp

        history = state.setdefault(
            "usage_guard_history", []
        )

        history.append({
            "timestamp": timestamp,
            "category": category,
            "action": "SAFE_PAUSE"
        })

        temp = state_file.with_suffix(".tmp")

        temp.write_text(
            json.dumps(state, indent=2) + "\n"
        )

        temp.chmod(0o600)
        temp.replace(state_file)

        return True


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true"
    )

    args = parser.parse_args()

    message = sys.stdin.read()
    category = classify_error(message)

    pause_categories = {
        "USAGE_LIMIT",
        "QUOTA_EXHAUSTED",
        "AUTHENTICATION_REQUIRED"
    }

    requires_pause = category in pause_categories

    paused = False

    if args.apply and requires_pause:
        paused = pause_workflow(category)

    result = {
        "category": category,
        "requires_pause": requires_pause,
        "workflow_paused": paused,
        "automatic_session_reset": False,
        "automatic_model_fallback": False,
        "automatic_retry": False
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
