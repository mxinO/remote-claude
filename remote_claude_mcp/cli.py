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


# ── read ──────────────────────────────────────────────────────────────

def cmd_read(argv):
    """Read a file on the remote cluster. Output in cat -n format."""
    import argparse
    parser = argparse.ArgumentParser(prog="remote-claude read")
    parser.add_argument("file_path")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args(argv)

    state, session_id = _get_state()
    file_path = _resolve_path(state, args.file_path)

    # Read file content via SSH
    # Use sed for offset/limit to avoid transferring entire large files
    if args.offset > 0:
        start = args.offset + 1  # sed is 1-based
        end = start + args.limit - 1
        cmd = f"cat -n {shlex.quote(file_path)} | sed -n '{start},{end}p'"
    else:
        cmd = f"cat -n {shlex.quote(file_path)} | head -n {args.limit}"

    # But first check if file exists and handle edge cases
    check_cmd = f"""
if [ ! -e {shlex.quote(file_path)} ]; then
    echo "ERROR:NOENT"
elif [ -d {shlex.quote(file_path)} ]; then
    echo "ERROR:ISDIR"
elif [ ! -r {shlex.quote(file_path)} ]; then
    echo "ERROR:PERM"
elif [ ! -s {shlex.quote(file_path)} ]; then
    lines=$(wc -l < {shlex.quote(file_path)} 2>/dev/null || echo 1)
    echo "ERROR:EMPTY:$lines"
else
    echo "OK"
fi
"""
    rc, out, err = _run_ssh(state, check_cmd)
    out = out.strip()

    if out == "ERROR:NOENT":
        print(f"File does not exist: {args.file_path}", file=sys.stderr)
        sys.exit(1)
    elif out == "ERROR:ISDIR":
        print(f"Path is a directory, not a file: {args.file_path}", file=sys.stderr)
        sys.exit(1)
    elif out == "ERROR:PERM":
        print(f"Permission denied: {args.file_path}", file=sys.stderr)
        sys.exit(1)
    elif out.startswith("ERROR:EMPTY:"):
        total = out.split(":")[-1]
        _mark_read(session_id, state["name"], file_path)
        print(f"Warning: the file exists but has empty contents. The file has {total} lines.")
        return
    elif out != "OK":
        print(f"Error checking file: {err.strip() or out}", file=sys.stderr)
        sys.exit(1)

    # Actually read the file
    rc, out, err = _run_ssh(state, cmd)
    if rc != 0:
        print(f"Error reading file: {err.strip()}", file=sys.stderr)
        sys.exit(1)

    # Mark as read and output
    _mark_read(session_id, state["name"], file_path)
    # cat -n output uses spaces for padding, convert to tab format like Claude
    # cat -n format: "     1\tcontent" — we want "1\tcontent"
    lines = []
    for line in out.split("\n"):
        # cat -n prefixes with spaces + number + tab
        stripped = line.lstrip()
        lines.append(stripped)
    print("\n".join(lines), end="")


# ── edit backends ─────────────────────────────────────────────────────

def _edit_python(state, file_path, args):
    """Edit via remote Python. Returns (rc, stdout, stderr). rc=-1 if python3 not found."""
    edit_script = '''
import sys, json

file_path = sys.argv[1]
data = json.loads(sys.stdin.read())
old_string = data["old"]
new_string = data["new"]
replace_all = data["replace_all"]

try:
    with open(file_path, "r") as f:
        content = f.read()
except FileNotFoundError:
    print(json.dumps({"error": f"File does not exist: {file_path}"}))
    sys.exit(0)
except PermissionError:
    print(json.dumps({"error": f"Permission denied: {file_path}"}))
    sys.exit(0)

count = content.count(old_string)
if count == 0:
    print(json.dumps({"error": "old_string not found in file."}))
    sys.exit(0)

if count > 1 and not replace_all:
    print(json.dumps({"error": f"Found {count} matches of the string to replace, but replace_all is false. To replace all occurrences, use --replace-all. To replace only one, provide more context to uniquely identify the instance."}))
    sys.exit(0)

if replace_all:
    new_content = content.replace(old_string, new_string)
else:
    new_content = content.replace(old_string, new_string, 1)

with open(file_path, "w") as f:
    f.write(new_content)

print(json.dumps({"ok": True, "file": file_path, "replacements": count if replace_all else 1}))
'''
    input_data = json.dumps({
        "old": args.old_string,
        "new": args.new_string,
        "replace_all": args.replace_all,
    }).encode()

    cmd = f"python3 -c {shlex.quote(edit_script)} {shlex.quote(file_path)}"
    rc, out, err = _run_ssh(state, cmd, input_data=input_data)

    # Detect python3 not found
    if rc != 0 and ("python3: not found" in err or "No such file" in err):
        return -1, "", ""
    return rc, out, err


def _edit_shell(state, file_path, args):
    """Edit via pure shell (awk). No Python required on remote."""
    # awk script: reads entire file, counts exact (non-regex) matches, replaces
    # Uses ENVIRON[] to read old/new strings — avoids awk -v backslash interpretation
    # Preserves trailing newline by checking with a shell test before awk
    awk_script = r'''
BEGIN {
    old = ENVIRON["_OLD"]; new = ENVIRON["_NEW"]
    ra = ENVIRON["_RA"]; outfile = ENVIRON["_OUTFILE"]
    count = 0
    content = ""
}
{
    if (NR > 1) content = content "\n"
    content = content $0
}
END {
    # Count occurrences using index()
    tmp = content
    while ((pos = index(tmp, old)) > 0) {
        count++
        tmp = substr(tmp, pos + length(old))
    }

    if (count == 0) {
        print "{\"error\":\"old_string not found in file.\"}"
        exit 0
    }

    if (count > 1 && ra != "true") {
        printf "{\"error\":\"Found %d matches of the string to replace, but replace_all is false. To replace all occurrences, use --replace-all. To replace only one, provide more context to uniquely identify the instance.\"}\n", count
        exit 0
    }

    # Replace using index() — exact string, not regex
    result = ""
    tmp = content
    limit = (ra == "true") ? 0 : 1
    done = 0
    while ((pos = index(tmp, old)) > 0) {
        if (limit > 0 && done >= limit) break
        result = result substr(tmp, 1, pos - 1) new
        tmp = substr(tmp, pos + length(old))
        done++
    }
    result = result tmp

    # Preserve trailing newline: check if original file ended with one
    if (ENVIRON["_HAS_TRAILING_NL"] == "1") {
        printf "%s\n", result > outfile
    } else {
        printf "%s", result > outfile
    }
    close(outfile)
    printf "{\"ok\":true,\"replacements\":%d}\n", done
}
'''
    replace_all_str = "true" if args.replace_all else "false"

    # Pass strings via environment variables — ENVIRON[] doesn't interpret backslashes
    # Check trailing newline before awk runs
    cmd = (
        f"export _OLD={shlex.quote(args.old_string)} "
        f"_NEW={shlex.quote(args.new_string)} "
        f"_RA={shlex.quote(replace_all_str)} "
        f"_OUTFILE={shlex.quote(file_path)} && "
        f"_HAS_TRAILING_NL=0 && "
        f"[ -n \"$(tail -c 1 {shlex.quote(file_path)})\" ] || _HAS_TRAILING_NL=1 && "
        f"export _HAS_TRAILING_NL && "
        f"awk {shlex.quote(awk_script)} {shlex.quote(file_path)}"
    )
    return _run_ssh(state, cmd)


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
        print(f"File has not been read yet. Read it first before editing.", file=sys.stderr)
        sys.exit(1)

    # Try Python first, fall back to awk (pure shell)
    rc, out, err = _edit_python(state, file_path, args)
    if rc == -1:
        # Python not available, use shell version
        rc, out, err = _edit_shell(state, file_path, args)

    if rc != 0:
        print(f"Error: {err.strip()}", file=sys.stderr)
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
