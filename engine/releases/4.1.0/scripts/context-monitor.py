#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import uuid

from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--session")
args = parser.parse_args()

session_id = args.session or os.environ.get(
    "ORCHESTRATOR_CLAUDE_SESSION_ID"
)

if not session_id:
    raise SystemExit("ERROR: Claude session ID unavailable.")

session_id = str(uuid.UUID(session_id))

root = Path(__file__).resolve().parents[2]

project_id = hashlib.sha256(
    str(root).encode()
).hexdigest()[:16]

directory = (
    Path.home()
    / ".local/state/claude-codex"
    / project_id
)

mapping_file = directory / f"{session_id}.json"
log_file = directory / "logs" / f"{session_id}.jsonl"

if not mapping_file.exists():
    print(json.dumps({
        "status": "NO_CODEX_SESSION",
        "claude_session_id": session_id
    }, indent=2))
    raise SystemExit(0)

mapping = json.loads(mapping_file.read_text())

codex_id = mapping.get("codex_session_id")
model = mapping.get("model")

entries = []
invalid_records = 0

if log_file.exists():
    for line in log_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            invalid_records += 1

usage = [
    e for e in entries
    if e.get("event") == "TOKEN_USAGE"
    and e.get("codex_session_id") == codex_id
]

latest = usage[-1] if usage else {}

codex_home = Path(os.environ.get(
    "CODEX_HOME",
    Path.home() / ".codex"
))

metadata_file = codex_home / "models_cache.json"

metadata = {}

if metadata_file.exists():
    try:
        data = json.loads(metadata_file.read_text())
        models = (
            data.get("models", [])
            if isinstance(data, dict)
            else data
        )

        metadata = next(
            (
                m for m in models
                if isinstance(m, dict)
                and m.get("slug") == model
            ),
            {}
        )
    except (OSError, ValueError, TypeError):
        pass

context_window = metadata.get("context_window")
effective_percent = metadata.get(
    "effective_context_window_percent"
)

effective_window = None

if (
    isinstance(context_window, int)
    and context_window > 0
    and isinstance(effective_percent, (int, float))
    and 0 < effective_percent <= 100
):
    effective_window = int(
        context_window * effective_percent / 100
    )

token_fields = [
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "cache_write_input_tokens"
]

totals = {
    key: sum(e.get(key, 0) for e in usage)
    for key in token_fields
}

cache_ratio = None

if totals["input_tokens"] > 0:
    cache_ratio = round(
        totals["cached_input_tokens"]
        / totals["input_tokens"] * 100,
        2
    )

warnings = []
recommendations = []

latest_input = latest.get("input_tokens")

if (
    effective_window
    and isinstance(latest_input, int)
    and latest_input >= effective_window
):
    warnings.append(
        "Latest reported turn input is large relative "
        "to the model's default context window. "
        "This is not a context occupancy measurement."
    )

if len(usage) >= 3:

    recent = usage[-3:]

    inputs = [
        e.get("input_tokens", 0)
        for e in recent
    ]

    if inputs[0] < inputs[1] < inputs[2]:
        warnings.append(
            "Reported input token usage has increased "
            "across the last three recorded turns."
        )

        recommendations.extend([
            "Avoid repeating unchanged repository analysis.",
            "Send concise task-specific instructions.",
            "Preserve verified findings in task checkpoints.",
            "Allow Codex native context management."
        ])

result = {
    "status": "AVAILABLE" if usage else "NO_USAGE_DATA",
    "claude_session_id": session_id,
    "codex_session_id": codex_id,
    "model": model,
    "effort": mapping.get("effort"),
    "service_tier": mapping.get("service_tier"),
    "model_context_metadata": {
        "default_context_window": context_window,
        "maximum_context_window": metadata.get(
            "max_context_window"
        ),
        "effective_context_window": effective_window
    },
    "recorded_turns": len(usage),
    "latest_turn_usage": {
        key: latest.get(key)
        for key in token_fields
    },
    "total_recorded_usage": totals,
    "input_cache_ratio_percent": cache_ratio,
    "actual_context_occupancy_percent": None,
    "invalid_log_records": invalid_records,
    "warnings": warnings,
    "recommendations": recommendations,
    "automatic_session_reset": False
}

print(json.dumps(result, indent=2))
