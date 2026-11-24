#!/usr/bin/env python3

import argparse
import json
import os
import selectors
import signal
import subprocess
import sys
import time

from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()

parser.add_argument("--timeout", type=int, default=1800)
parser.add_argument("--retries", type=int, default=0)
parser.add_argument("--retry-delay", type=int, default=5)
parser.add_argument("--heartbeat", type=int, default=60)
parser.add_argument("--idle-timeout", type=int, default=300)
parser.add_argument("--idempotent", action="store_true")
parser.add_argument("--lock-fd", type=int, action="append", default=[])
parser.add_argument("command", nargs=argparse.REMAINDER)

args = parser.parse_args()

command = args.command

if command and command[0] == "--":
    command = command[1:]

if not command:
    parser.error("A command is required.")

if not 0 <= args.retries <= 3:
    parser.error("Retries must be between 0 and 3.")

if min(args.timeout, args.heartbeat, args.idle_timeout) <= 0:
    parser.error("Intervals and timeouts must be positive.")

if args.retry_delay < 0:
    parser.error("Retry delay cannot be negative.")

if args.retries and not args.idempotent:
    parser.error("Automatic retries require --idempotent.")

original_parent = os.getppid()
cancelled = False


def on_signal(signum, frame):
    global cancelled
    cancelled = True


signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)


def emit(status, **details):
    print(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        **details
    }), flush=True)


def group_snapshot(group_id):

    members = {}

    for entry in Path("/proc").iterdir():

        if not entry.name.isdigit():
            continue

        try:
            raw = (entry / "stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()

            process_group = int(fields[2])
            session = int(fields[3])

            if process_group != group_id or session != group_id:
                continue

            if fields[0] == "Z":
                continue

            identity = f"{entry.name}:{fields[19]}"

            members[identity] = (
                int(fields[11]) + int(fields[12])
            )

        except (OSError, ValueError, IndexError):
            continue

    return members


def cleanup_group(process):

    group_id = process.pid

    if not group_snapshot(group_id):
        return True

    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        return True

    deadline = time.monotonic() + 5

    while time.monotonic() < deadline:

        process.poll()

        if not group_snapshot(group_id):
            return True

        time.sleep(0.2)

    if group_snapshot(group_id):
        try:
            os.killpg(group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 5

    while time.monotonic() < deadline:

        process.poll()

        if not group_snapshot(group_id):
            return True

        time.sleep(0.2)

    return not bool(group_snapshot(group_id))


def execute(attempt):

    emit(
        "EXECUTION_STARTED",
        attempt=attempt,
        maximum_attempts=args.retries + 1
    )

    process = subprocess.Popen(
        command,
        start_new_session=True,
        pass_fds=tuple(args.lock_fd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    selector = selectors.DefaultSelector()

    selector.register(
        process.stdout,
        selectors.EVENT_READ,
        "stdout"
    )

    selector.register(
        process.stderr,
        selectors.EVENT_READ,
        "stderr"
    )

    buffers = {
        "stdout": b"",
        "stderr": b""
    }

    destinations = {
        "stdout": sys.stdout.buffer,
        "stderr": sys.stderr.buffer
    }

    started = time.monotonic()
    last_progress = started
    last_heartbeat = started
    previous_snapshot = group_snapshot(process.pid)

    output_bytes = 0
    stall_reported = False
    exit_seen_at = None
    result = None
    cleanup_ok = True

    try:

        emit(
            "SUPERVISION_STARTED",
            pid=process.pid,
            idle_timeout=args.idle_timeout,
            execution_timeout=args.timeout
        )

        while True:

            current = time.monotonic()
            elapsed = current - started

            if cancelled or os.getppid() != original_parent:

                emit(
                    "EXECUTION_INTERRUPTED",
                    pid=process.pid
                )

                result = 130
                break

            if elapsed >= args.timeout:

                emit(
                    "EXECUTION_TIMEOUT",
                    pid=process.pid,
                    elapsed_seconds=int(elapsed)
                )

                result = 124
                break

            output_changed = False

            for key, _ in selector.select(timeout=0.5):

                stream = key.fileobj
                name = key.data

                chunk = os.read(stream.fileno(), 65536)

                if not chunk:

                    selector.unregister(stream)

                    if buffers[name]:
                        destinations[name].write(
                            buffers[name] + b"\n"
                        )
                        destinations[name].flush()
                        buffers[name] = b""

                    stream.close()
                    continue

                output_changed = True
                output_bytes += len(chunk)
                buffers[name] += chunk

                while b"\n" in buffers[name]:

                    line, buffers[name] = (
                        buffers[name].split(b"\n", 1)
                    )

                    destinations[name].write(line + b"\n")
                    destinations[name].flush()

            snapshot = group_snapshot(process.pid)

            cpu_changed = snapshot != previous_snapshot
            previous_snapshot = snapshot

            if output_changed or cpu_changed:
                last_progress = time.monotonic()
                stall_reported = False

            current = time.monotonic()
            idle = int(current - last_progress)

            details = {
                "pid": process.pid,
                "attempt": attempt,
                "elapsed_seconds": int(current - started),
                "idle_seconds": idle,
                "process_count": len(snapshot),
                "cpu_progress": cpu_changed,
                "output_progress": output_changed,
                "output_bytes": output_bytes
            }

            if idle >= args.idle_timeout and not stall_reported:

                emit(
                    "POSSIBLE_STALL_REQUIRES_DIAGNOSIS",
                    **details
                )

                stall_reported = True

            if current - last_heartbeat >= args.heartbeat:

                emit("HEARTBEAT", **details)
                last_heartbeat = current

            code = process.poll()

            if code is not None:

                if not selector.get_map():
                    result = code
                    break

                if exit_seen_at is None:
                    exit_seen_at = current

                elif current - exit_seen_at >= 3:

                    emit(
                        "OUTPUT_STREAM_STILL_OPEN",
                        pid=process.pid
                    )

                    result = code if code != 0 else 1
                    break

    except BrokenPipeError:
        result = 130

    finally:

        if group_snapshot(process.pid):

            try:
                emit(
                    "TERMINATING_OWNED_PROCESS",
                    pid=process.pid
                )
            except BrokenPipeError:
                pass

            cleanup_ok = cleanup_group(process)

            if result == 0:
                result = 1

        selector.close()

        for stream in (process.stdout, process.stderr):
            if not stream.closed:
                stream.close()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cleanup_ok = False

    if not cleanup_ok:

        emit(
            "PROCESS_CLEANUP_INCOMPLETE",
            pid=process.pid
        )

        return 125

    return result if result is not None else 1


for attempt in range(1, args.retries + 2):

    if cancelled or os.getppid() != original_parent:
        sys.exit(130)

    code = execute(attempt)

    if code == 0:

        emit(
            "EXECUTION_SUCCESS",
            attempt=attempt,
            exit_code=0
        )

        sys.exit(0)

    emit(
        "EXECUTION_FAILED",
        attempt=attempt,
        exit_code=code
    )

    if attempt <= args.retries and code not in (125, 130):

        emit(
            "RETRY_SCHEDULED",
            next_attempt=attempt + 1,
            delay_seconds=args.retry_delay
        )

        time.sleep(args.retry_delay)

    else:

        emit(
            "RECOVERY_LIMIT_REACHED",
            attempts=attempt,
            exit_code=code
        )

        sys.exit(code if code > 0 else 1)
