#!/usr/bin/env python3
"""Own execution lifetime, workflow locks, output draining and process cleanup."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

import ccx_platform as platform
from ccx_runtime import Streams, safe_open

parser = argparse.ArgumentParser()
parser.add_argument('--timeout', type=int, default=1800)
parser.add_argument('--retries', type=int, default=0)
parser.add_argument('--retry-delay', type=int, default=5)
parser.add_argument('--heartbeat', type=int, default=60)
parser.add_argument('--idle-timeout', type=int, default=300)
parser.add_argument('--idempotent', action='store_true')
parser.add_argument('--lock-fd', type=int, action='append', default=[])
parser.add_argument('--lock-path', action='append', default=[])
parser.add_argument('--shared-lock-path', action='append', default=[])
parser.add_argument('--parent-pid', type=int)
parser.add_argument('--parent-start')
parser.add_argument('--integrity-script', type=Path)
parser.add_argument('--approval-file', type=Path)
parser.add_argument('--approval-name')
parser.add_argument('--approval-digest')
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
command = args.command[1:] if args.command[:1] == ['--'] else args.command
if not command:
    parser.error('A command is required.')
if not 0 <= args.retries <= 3:
    parser.error('Retries must be between 0 and 3.')
if min(args.timeout, args.heartbeat, args.idle_timeout) <= 0 or args.retry_delay < 0:
    parser.error('Intervals and timeouts must be positive; retry delay cannot be negative.')
if args.retries and not args.idempotent:
    parser.error('Automatic retries require --idempotent.')
if os.name == 'nt' and args.lock_fd:
    parser.error('Windows requires guardian-owned lock paths, not inherited descriptors.')

original_parent = args.parent_pid or os.getppid()
parent_info = platform.process_info(original_parent)
if not parent_info:
    sys.exit('Parent identity unavailable; refusing unsupervised execution')
parent_identity = args.parent_start or str(parent_info['start_ticks'])
cancelled = False

def parent_alive():
    info = platform.process_info(original_parent)
    return info is not None and info['state'] != 'Z' and str(info['start_ticks']) == parent_identity

def on_signal(signum, frame):
    global cancelled
    cancelled = True

signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)
if os.name != 'nt':
    # Ensure children remain waitable even if the invoking environment ignored SIGCHLD.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)

def emit(status, **details):
    print(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'status': status, **details}), flush=True)

# Windows guardian owns canonical locks through Job teardown. A separate caller
# launch lock serializes handoff, while these locks protect management/updates.
locks = []
try:
    for names, mode in ((args.lock_path, platform.LOCK_EX), (args.shared_lock_path, platform.LOCK_SH)):
        for name in names:
            path = Path(name)
            if not path.is_absolute() or any(platform.is_link(p) for p in (path,) + tuple(path.parents)):
                raise PermissionError('Unsafe guardian lock path: ' + name)
            platform.validate_owner(path.parent)
            handle = safe_open(path, 'a')
            locks.append(handle)
            platform.flock(handle, mode | platform.LOCK_NB)
    if args.integrity_script:
        result = subprocess.run([sys.executable, str(args.integrity_script)], capture_output=True, timeout=15)
        if result.returncode:
            sys.exit('Integrity changed before guardian lock acquisition')
    if args.approval_file:
        approved = json.loads(args.approval_file.read_text(encoding="utf-8"))
        if approved.get(args.approval_name) != args.approval_digest:
            sys.exit('Profile approval changed before guardian lock acquisition')
except BlockingIOError:
    emit('PROJECT_BUSY')
    sys.exit(75)


def quiet_emit(status, **details):
    try:
        emit(status, **details)
    except BrokenPipeError:
        pass


def cleanup_owned(process, snapshot, job):
    """Retain workflow locks until the owned tree is confirmed empty.

    POSIX deliberately leaves the group leader unreaped throughout supervision.
    Its PID cannot be recycled, so group termination remains safe even when
    activity monitoring fails. Windows uses the retained Job handle identity.
    """
    monitor_failed = False
    try:
        live = bool(snapshot())
    except (OSError, ValueError, NotImplementedError) as error:
        live = True
        monitor_failed = True
        quiet_emit('MONITOR_UNAVAILABLE_DURING_CLEANUP', error=str(error))
    if not live:
        return False, monitor_failed
    quiet_emit('TERMINATING_OWNED_PROCESS', pid=process.pid)
    if job:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except OSError:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return True, monitor_failed
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            if not snapshot():
                return True, monitor_failed
        except (OSError, ValueError, NotImplementedError):
            monitor_failed = True
            break
        time.sleep(.05)
    # A failed monitor is not evidence of successful cleanup. Keep the guardian
    # and its locks alive, retrying termination/confirmation until authoritative
    # native state confirms that execution ended.
    last_report = 0
    while True:
        try:
            if job:
                if job.terminate():
                    return True, monitor_failed
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    return True, monitor_failed
                if not snapshot():
                    return True, monitor_failed
        except (OSError, ValueError, NotImplementedError) as error:
            monitor_failed = True
            if time.monotonic() - last_report >= 5:
                quiet_emit('CLEANUP_UNCONFIRMED_LOCKS_RETAINED', pid=process.pid, error=str(error))
                last_report = time.monotonic()
        if time.monotonic() - last_report >= 5:
            quiet_emit('CLEANUP_UNCONFIRMED_LOCKS_RETAINED', pid=process.pid)
            last_report = time.monotonic()
        time.sleep(.1)


def execute(attempt):
    emit('EXECUTION_STARTED', attempt=attempt, maximum_attempts=args.retries + 1)
    resolved_command = platform.command_argv(command)
    job = None
    process = None
    streams = None
    result = None
    # The cleanup guard begins before spawn: stream-reader construction, native
    # identity lookup and the very first snapshot are all covered.
    try:
        if os.name == 'nt':
            from ccx_job import WindowsJob
            job = WindowsJob()
            process = job.start(resolved_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            snapshot = lambda: job.snapshot(platform.process_info)
        else:
            process = subprocess.Popen(resolved_command, start_new_session=True, pass_fds=tuple(args.lock_fd),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            snapshot = lambda: platform.group_snapshot(process.pid)
        streams = Streams(process)
        destinations = {'stdout': sys.stdout.buffer, 'stderr': sys.stderr.buffer}
        buffers = {'stdout': b'', 'stderr': b''}
        started = last_progress = last_heartbeat = time.monotonic()
        previous = snapshot()
        total_bytes = 0
        stall_reported = False
        exited_at = None
        emit('SUPERVISION_STARTED', pid=process.pid, idle_timeout=args.idle_timeout, execution_timeout=args.timeout)
        while True:
            current = time.monotonic()
            if cancelled or not parent_alive():
                emit('EXECUTION_INTERRUPTED', pid=process.pid)
                result = 130
                break
            if current - started >= args.timeout:
                emit('EXECUTION_TIMEOUT', pid=process.pid, elapsed_seconds=int(current-started))
                result = 124
                break
            event = streams.read(.2)
            output_changed = bool(event and event[1])
            if output_changed:
                name, chunk = event
                total_bytes += len(chunk)
                buffers[name] += chunk
                while b'\n' in buffers[name]:
                    line, buffers[name] = buffers[name].split(b'\n', 1)
                    destinations[name].write(line + b'\n')
                    destinations[name].flush()
            elif event and event[1] is None:
                name = event[0]
                if buffers[name]:
                    destinations[name].write(buffers[name] + b'\n')
                    destinations[name].flush()
                    buffers[name] = b''
            current_snapshot = snapshot()
            cpu_changed = current_snapshot != previous
            previous = current_snapshot
            if output_changed or cpu_changed:
                last_progress = time.monotonic()
                stall_reported = False
            current = time.monotonic()
            idle = int(current - last_progress)
            details = dict(pid=process.pid, attempt=attempt, elapsed_seconds=int(current-started),
                           idle_seconds=idle, process_count=len(current_snapshot), cpu_progress=cpu_changed,
                           output_progress=output_changed, output_bytes=total_bytes)
            if idle >= args.idle_timeout and not stall_reported:
                emit('POSSIBLE_STALL_REQUIRES_DIAGNOSIS', **details)
                stall_reported = True
            if current-last_heartbeat >= args.heartbeat:
                emit('HEARTBEAT', **details)
                last_heartbeat = current
            if job:
                exited = process.poll() is not None
            else:
                # Do not call poll()/wait() here. An unreaped leader reserves the
                # process-group identity until all descendants are confirmed gone.
                info = platform.process_info(process.pid)
                # Darwin libproc can stop exposing an exited process before
                # waitpid reaps it. SIGCHLD is default and no other code reaps
                # children, so the Popen child remains our PID reservation.
                exited = info is None or info['state'] == 'Z'
            if exited:
                if not streams.active:
                    break
                if exited_at is None:
                    exited_at = current
                elif current-exited_at >= 3:
                    emit('OUTPUT_STREAM_STILL_OPEN', pid=process.pid)
                    result = 1
                    break
    except BrokenPipeError:
        result = 130
    except (OSError, ValueError, NotImplementedError) as error:
        quiet_emit('SUPERVISION_FAILED', error=str(error))
        result = 125
    finally:
        try:
            if process is not None:
                had_live_tree, monitor_failed = cleanup_owned(process, snapshot, job)
                if monitor_failed:
                    result = 125
                elif had_live_tree and result is None:
                    result = 1
                # The native tree is empty before reaping/releasing any locks.
                code = process.wait()
                if result is None:
                    result = code
        finally:
            if job:
                job.close()
            if streams:
                streams.close()
            if process is not None:
                process.stdout.close()
                process.stderr.close()
    return result if result is not None else 1

for attempt in range(1, args.retries + 2):
    if cancelled or not parent_alive():
        sys.exit(130)
    code = execute(attempt)
    if code == 0:
        emit('EXECUTION_SUCCESS', attempt=attempt, exit_code=0)
        sys.exit(0)
    emit('EXECUTION_FAILED', attempt=attempt, exit_code=code)
    if attempt <= args.retries and code not in (125, 130):
        emit('RETRY_SCHEDULED', next_attempt=attempt+1, delay_seconds=args.retry_delay)
        deadline = time.monotonic() + args.retry_delay
        while time.monotonic() < deadline and not cancelled and parent_alive():
            time.sleep(.1)
    else:
        emit('RECOVERY_LIMIT_REACHED', attempts=attempt, exit_code=code)
        sys.exit(code if code > 0 else 1)
