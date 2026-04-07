#!/usr/bin/env python3
"""remote: Run a command on the active remote cluster.

Usage: remote <command>

Reads the active cluster from the state file written by the MCP gateway.
Uses SSH ControlMaster to reuse the existing connection — no extra auth.

Designed to be used with Bash(run_in_background=true) for background tasks
that get local harness notifications when done.
"""

import json
import os
import shlex
import subprocess
import sys

_STATE_DIR = f"/tmp/remote-claude-{os.getuid()}"
CONTROL_DIR = os.path.expanduser("~/.ssh/controlmasters")


def main():
    if len(sys.argv) < 2:
        print("Usage: remote <command>", file=sys.stderr)
        sys.exit(1)

    command = " ".join(sys.argv[1:])

    # Read active cluster state (session-scoped)
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    if not session_id:
        print("$CLAUDE_SESSION_ID not set. Is the SessionStart hook installed?", file=sys.stderr)
        sys.exit(1)
    state_file = os.path.join(_STATE_DIR, f"active-{session_id}.json")
    if not os.path.exists(state_file):
        print(f"No active cluster for session {session_id}. Use use_cluster() first.", file=sys.stderr)
        sys.exit(1)

    with open(state_file) as f:
        state = json.load(f)

    # Build SSH args
    args = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={CONTROL_DIR}/%r@%h:%p",
        "-o", "ControlPersist=600",
    ]
    if state.get("ssh_key"):
        args.extend(["-i", state["ssh_key"]])
    if state.get("jump_proxy"):
        args.extend(["-J", state["jump_proxy"]])
    if state.get("port") and state["port"] != 22:
        args.extend(["-p", str(state["port"])])

    host = f"{state['user']}@{state['host']}" if state.get("user") else state["host"]
    args.append(host)

    # Prepend cd work_dir if set
    if state.get("work_dir"):
        command = f"cd {shlex.quote(state['work_dir'])} && {command}"

    args.extend(["--", command])

    # Exec ssh — replaces this process, inherits stdin/stdout
    os.execvp("ssh", args)


if __name__ == "__main__":
    main()
