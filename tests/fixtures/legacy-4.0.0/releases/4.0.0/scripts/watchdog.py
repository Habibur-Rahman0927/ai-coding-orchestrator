#!/usr/bin/env python3

import argparse
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone

parser = argparse.ArgumentParser()

parser.add_argument("--pid", type=int, required=True)
parser.add_argument("--log")
parser.add_argument("--interval", type=int, default=60)
parser.add_argument("--idle-timeout", type=int, default=300)
parser.add_argument("--max-runtime", type=int, default=3600)
parser.add_argument("--once", action="store_true")

args = parser.parse_args()

if args.pid <= 1:
    parser.error("Invalid process ID")

if min(args.interval, args.idle_timeout, args.max_runtime) <= 0:
    parser.error("Timeouts and intervals must be positive")

def now():
    return datetime.now(timezone.utc).isoformat()

def process_info(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()

        cmdline = Path(
            f"/proc/{pid}/cmdline"
        ).read_bytes().replace(b"\0", b" ").decode(
            errors="replace"
        ).strip()

        return {
            "state": fields[0],
            "cpu_ticks": int(fields[11]) + int(fields[12]),
            "start_ticks": int(fields[19]),
            "command": cmdline
        }
    except (OSError, ValueError, IndexError):
        return None

def log_info():
    if not args.log:
        return None

    try:
        stat = Path(args.log).stat()
        return [stat.st_size, stat.st_mtime_ns]
    except OSError:
        return None

def emit(status, **details):
    print(json.dumps({
        "timestamp": now(),
        "pid": args.pid,
        "status": status,
        **details
    }), flush=True)

started = time.monotonic()
last_progress = started

initial = process_info(args.pid)

if initial is None:
    emit("PROCESS_NOT_FOUND")
    raise SystemExit(1)

identity = initial["start_ticks"]
previous_cpu = initial["cpu_ticks"]
previous_log = log_info()

emit("MONITORING", command=initial["command"])

while True:

    current = process_info(args.pid)
    current_time = time.monotonic()

    elapsed = int(current_time - started)

    if current is None:
        emit("PROCESS_EXITED", elapsed_seconds=elapsed)
        raise SystemExit(0)

    if current["start_ticks"] != identity:
        emit("PID_REUSED")
        raise SystemExit(1)

    if current["state"] == "Z":
        emit("PROCESS_ZOMBIE")
        raise SystemExit(1)

    current_log = log_info()

    cpu_changed = current["cpu_ticks"] != previous_cpu
    log_changed = current_log != previous_log

    if cpu_changed or log_changed:
        last_progress = current_time

    idle = int(current_time - last_progress)

    details = {
        "elapsed_seconds": elapsed,
        "idle_seconds": idle,
        "process_state": current["state"],
        "cpu_progress": cpu_changed,
        "log_progress": log_changed
    }

    if elapsed >= args.max_runtime:
        emit("TIMEOUT_REQUIRES_DIAGNOSIS", **details)
        raise SystemExit(3)

    if idle >= args.idle_timeout:
        emit("POSSIBLE_STALL_REQUIRES_DIAGNOSIS", **details)
        raise SystemExit(2)

    emit("PROCESS_ALIVE", **details)

    if args.once:
        break

    previous_cpu = current["cpu_ticks"]
    previous_log = current_log

    time.sleep(args.interval)
