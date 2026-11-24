#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import json
import os
import sys
import uuid

data = json.load(sys.stdin)

session_id = str(uuid.UUID(data["session_id"]))
env_file = os.environ.get("CLAUDE_ENV_FILE")

if not env_file:
    sys.exit("CLAUDE_ENV_FILE is unavailable")

with open(env_file, "a") as f:
    f.write(f"export ORCHESTRATOR_CLAUDE_SESSION_ID='{session_id}'\n")
