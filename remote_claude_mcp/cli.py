#!/usr/bin/env python3
"""remote-claude: Work on remote clusters via SSH.

Subcommands:
  remote-claude read <file> [--offset N] [--limit N]
  remote-claude edit <file> <old_string> <new_string> [--replace-all]
  remote-claude <any other command>   — runs as shell command on remote

State:
  Active cluster is read from a JSON state file written by the MCP gateway.
  Read-tracking uses filesystem markers for edit safety checks.
"""

import hashlib
import json
import os
import shlex
import subprocess
import sys

_STATE_DIR = f"/tmp/remote-claude-{os.getuid()}"
CONTROL_DIR = os.path.expanduser("~/.ssh/controlmasters")
REMOTE_TOOLS_DIR = "~/.cache/remote-claude"
LOCAL_TOOLS_DIR = os.path.join(os.path.dirname(__file__), "remote_tools")


def _get_session_id():
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    if not session_id:
        print("$CLAUDE_SESSION_ID not set. Is the SessionStart hook installed?", file=sys.stderr)
        sys.exit(1)
    return session_id


def _get_state():
    session_id = _get_session_id()
    state_file = os.path.join(_STATE_DIR, f"active-{session_id}.json")
    if not os.path.exists(state_file):
        print(f"No active cluster. Use use_cluster() first.", file=sys.stderr)
        sys.exit(1)
    with open(state_file) as f:
        return json.load(f), session_id


def _build_ssh_args(state):
    args = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={CONTROL_DIR}/%r@%h:%p",
        "-o", "ControlPersist=600",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
    ]
    if state.get("ssh_key"):
        args.extend(["-i", state["ssh_key"]])
    if state.get("jump_proxy"):
        args.extend(["-J", state["jump_proxy"]])
    if state.get("port") and state["port"] != 22:
        args.extend(["-p", str(state["port"])])
    host = f"{state['user']}@{state['host']}" if state.get("user") else state["host"]
    args.append(host)
    return args


def _run_ssh(state, command, input_data=None):
    """Run SSH command and return (returncode, stdout, stderr)."""
    args = _build_ssh_args(state) + ["--", command]
    proc = subprocess.run(args, capture_output=True, input=input_data, timeout=300)
    return proc.returncode, proc.stdout.decode(errors="replace"), proc.stderr.decode(errors="replace")


def _resolve_path(state, file_path):
    """Resolve relative path against work_dir."""
    if not file_path.startswith("/"):
        work_dir = state.get("work_dir", "")
        if work_dir:
            file_path = f"{work_dir}/{file_path}"
    return file_path


def _read_marker_dir(session_id, cluster_name):
    return os.path.join(_STATE_DIR, f"read-{session_id}-{cluster_name}")


def _mark_read(session_id, cluster_name, file_path):
    marker_dir = _read_marker_dir(session_id, cluster_name)
    os.makedirs(marker_dir, exist_ok=True)
    h = hashlib.sha256(file_path.encode()).hexdigest()[:16]
    marker = os.path.join(marker_dir, h)
    with open(marker, "w") as f:
        f.write(file_path)


def _was_read(session_id, cluster_name, file_path):
    marker_dir = _read_marker_dir(session_id, cluster_name)
    h = hashlib.sha256(file_path.encode()).hexdigest()[:16]
    marker = os.path.join(marker_dir, h)
    return os.path.exists(marker)


# ── remote tool deployment ────────────────────────────────────────────

def _ensure_tools(state):
    """Deploy read/edit scripts to remote if not present."""
    # Check if tools exist
    rc, out, _ = _run_ssh(state, f"test -x {REMOTE_TOOLS_DIR}/edit && echo OK")
    if "OK" in out:
        return

    # Deploy tools
    local_dir = os.path.normpath(LOCAL_TOOLS_DIR)
    for tool in ("read", "edit"):
        local_path = os.path.join(local_dir, tool)
        if not os.path.exists(local_path):
            print(f"Local tool not found: {local_path}", file=sys.stderr)
            sys.exit(1)
        with open(local_path, "rb") as f:
            content = f.read()
        _run_ssh(state, f"mkdir -p {REMOTE_TOOLS_DIR} && cat > {REMOTE_TOOLS_DIR}/{tool} && chmod +x {REMOTE_TOOLS_DIR}/{tool}",
                 input_data=content)


def _tool_cmd(state, tool_name, tool_args):
    """Build a remote command that runs a deployed tool."""
    work_dir = state.get("work_dir", "")
    cd_prefix = f"cd {shlex.quote(work_dir)} && " if work_dir else ""
    return f"{cd_prefix}{REMOTE_TOOLS_DIR}/{tool_name} {tool_args}"


# ── read ──────────────────────────────────────────────────────────────

def cmd_read(argv):
    """Read a file on the remote cluster."""
    import argparse
    parser = argparse.ArgumentParser(prog="remote-claude read")
    parser.add_argument("file_path")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args(argv)

    state, session_id = _get_state()
    file_path = _resolve_path(state, args.file_path)
    _ensure_tools(state)

    # Build remote read command
    tool_args = shlex.quote(file_path)
    if args.offset:
        tool_args += f" --offset {args.offset}"
    if args.limit != 2000:
        tool_args += f" --limit {args.limit}"

    cmd = _tool_cmd(state, "read", tool_args)
    rc, out, err = _run_ssh(state, cmd)

    if rc != 0:
        print(err.strip() or out.strip(), file=sys.stderr)
        sys.exit(1)

    # Mark as read
    _mark_read(session_id, state["name"], file_path)
    print(out, end="")


# ── edit ──────────────────────────────────────────────────────────────

def cmd_edit(argv):
    """Edit a file on the remote cluster with exact string replacement."""
    import argparse
    parser = argparse.ArgumentParser(prog="remote-claude edit")
    parser.add_argument("file_path")
    parser.add_argument("old_string")
    parser.add_argument("new_string")
    parser.add_argument("--replace-all", action="store_true")
    args = parser.parse_args(argv)

    if args.old_string == args.new_string:
        print("old_string and new_string must be different.", file=sys.stderr)
        sys.exit(1)

    state, session_id = _get_state()
    file_path = _resolve_path(state, args.file_path)

    # Check if file was read first
    if not _was_read(session_id, state["name"], file_path):
        print("File has not been read yet. Read it first before editing.", file=sys.stderr)
        sys.exit(1)

    _ensure_tools(state)

    # Send edit command — JSON data via stdin
    input_data = json.dumps({
        "old": args.old_string,
        "new": args.new_string,
        "replace_all": args.replace_all,
    }).encode()

    cmd = _tool_cmd(state, "edit", shlex.quote(file_path))
    rc, out, err = _run_ssh(state, cmd, input_data=input_data)

    if rc != 0:
        print(err.strip() or out.strip(), file=sys.stderr)
        sys.exit(1)

    try:
        result = json.loads(out.strip())
    except (json.JSONDecodeError, ValueError):
        print(f"Unexpected output: {out.strip()}", file=sys.stderr)
        sys.exit(1)

    if "error" in result:
        print(result["error"], file=sys.stderr)
        sys.exit(1)

    print(f"The file {args.file_path} has been updated successfully.")


# ── main ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  remote-claude read <file> [--offset N] [--limit N]", file=sys.stderr)
        print("  remote-claude edit <file> <old> <new> [--replace-all]", file=sys.stderr)
        print("  remote-claude <command>  — run shell command on remote", file=sys.stderr)
        sys.exit(1)

    subcmd = sys.argv[1]

    if subcmd == "read":
        cmd_read(sys.argv[2:])
    elif subcmd == "edit":
        cmd_edit(sys.argv[2:])
    else:
        # Default: run as shell command (existing behavior)
        state, _ = _get_state()
        command = " ".join(sys.argv[1:])
        if state.get("work_dir"):
            command = f"cd {shlex.quote(state['work_dir'])} && {command}"
        args = _build_ssh_args(state) + ["--", command]
        os.execvp("ssh", args)


if __name__ == "__main__":
    main()
