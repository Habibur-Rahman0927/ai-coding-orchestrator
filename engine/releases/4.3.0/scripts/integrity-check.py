#!/usr/bin/env python3

import hashlib
import json
import os
import stat
import sys
from pathlib import Path
import ccx_platform as platform

root = Path(__file__).resolve().parents[2]

project_id = hashlib.sha256(
    str(root).encode()
).hexdigest()[:16]

manifest_path = (
    platform.state_root()
    / project_id
    / "integrity/manifest.json"
)

if not manifest_path.is_file():
    print("MANIFEST_MISSING")
    sys.exit(2)

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

if manifest.get("project") != str(root):
    sys.exit("ERROR: Manifest project mismatch")

verified = []
modified = []
missing = []
unsafe = []

for name, expected in manifest["files"].items():

    try:
        path = root / platform.validate_relative(name)
    except (ValueError, PermissionError):
        unsafe.append(name + ": UNSAFE_PATH")
        continue

    if any(platform.is_link(entry) for entry in (path,) + tuple(path.parents)) :
        unsafe.append(name + ": SYMLINK")
        continue

    if not path.is_file():
        missing.append(name)
        continue

    try:
        platform.validate_owner(path)
        platform.validate_permissions(path)
    except (OSError, ValueError) as error:
        unsafe.append(name + ": " + str(error))

    actual = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    if actual == expected:
        verified.append(name)
    else:
        modified.append(name)

registered = set(manifest["files"])

current = {
    p.relative_to(root).as_posix()
    for directory in (
        root / ".claude/scripts",
        root / ".claude/hooks"
    )
    for p in directory.glob("*.py")
}

unregistered = sorted(current - registered)

passed = not (
    modified or missing or unsafe or unregistered
)

print(json.dumps({
    "status": "PASS" if passed else "REVIEW_REQUIRED",
    "registered_files": len(registered),
    "verified_files": len(verified),
    "modified_files": modified,
    "missing_files": missing,
    "unsafe_files": unsafe,
    "unregistered_scripts": unregistered
}, indent=2))

sys.exit(0 if passed else 1)
