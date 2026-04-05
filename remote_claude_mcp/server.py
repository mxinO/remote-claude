"""Remote Claude MCP Server — FastMCP server with tools that proxy to remote clusters."""

from __future__ import annotations

import atexit
import asyncio
import json
import logging
import signal
from typing import Dict, Optional

from mcp.server.fastmcp import Context, FastMCP

from .config import ClusterConfig, Config, load_config
from .proxy import RemoteConnection, connect, _build_ssh_args

ACTIVE_STATE_FILE = "/tmp/remote-claude-active.json"

logger = logging.getLogger(__name__)

server = FastMCP(
    name="remote-claude",
    instructions=(
        "Remote Claude for remote clusters. Call use_cluster(name) first to connect, "
        "then use remote_* tools which work exactly like their local counterparts "
        "(Bash, Read, Edit, Write, Glob, Grep) but execute on the remote cluster."
    ),
)

# State
_config: Config = Config()
_connections: Dict[str, RemoteConnection] = {}
_active_cluster: Optional[str] = None


def _write_active_state(cluster: ClusterConfig, work_dir: str = ""):
    """Write active cluster state so the `remote` CLI can read it."""
    state = {
        "name": cluster.name,
        "host": cluster.host,
        "user": cluster.user,
        "work_dir": work_dir,
        "ssh_key": cluster.ssh_key,
        "jump_proxy": cluster.jump_proxy,
        "port": cluster.port,
    }
    with open(ACTIVE_STATE_FILE, "w") as f:
        json.dump(state, f)


def _get_active() -> RemoteConnection:
    if _active_cluster is None:
        raise RuntimeError("No active cluster. Call use_cluster(name) first.")
    conn = _connections.get(_active_cluster)
    if conn is None:
        raise RuntimeError(f"Cluster '{_active_cluster}' not connected.")
    return conn


@server.tool(
    description=(
        "Connect to a remote cluster and set it as active. "
        "Use a name from clusters.yaml config, or pass a raw hostname. "
        "Optionally set a working directory — all relative paths will resolve from there."
    )
)
async def use_cluster(name: str, work_dir: str = "") -> str:
    global _active_cluster

    # Already connected — check if still alive, switch or reconnect
    if name in _connections:
        conn = _connections[name]
        alive = conn.process.returncode is None and await conn._heartbeat()
        if alive and (not work_dir or work_dir == conn.work_dir):
            _active_cluster = name
            _write_active_state(conn.cluster, conn.work_dir)
            return f"Switched to cluster '{name}' ({conn.cluster.host})"
        # Dead or work_dir changed — reconnect
        logger.info(f"Reconnecting to '{name}' (alive={alive})")
        await conn.close()
        del _connections[name]

    # Resolve config
    if name in _config.clusters:
        cluster = _config.clusters[name]
    else:
        # Treat as raw hostname
        cluster = ClusterConfig(name=name, host=name)

    try:
        conn = await connect(cluster, work_dir=work_dir)
    except Exception as e:
        return f"[ERROR] Failed to connect to '{name}': {e}"

    _connections[name] = conn
    _active_cluster = name
    _write_active_state(cluster, work_dir)
    wd = f", work_dir={work_dir}" if work_dir else ""
    return (
        f"Connected to '{name}' ({cluster.host}{wd}) — "
        f"claude at {conn.claude_path}. Ready for remote_* commands."
    )


@server.tool(description="List available clusters from config and their connection status.")
async def list_clusters() -> str:
    lines = []
    for name, cluster in _config.clusters.items():
        status = "connected" if name in _connections else "not connected"
        active = " (active)" if name == _active_cluster else ""
        lines.append(f"  {name}: {cluster.host} [{status}]{active}")

    # Also show ad-hoc connections not in config
    for name in _connections:
        if name not in _config.clusters:
            active = " (active)" if name == _active_cluster else ""
            lines.append(f"  {name}: {_connections[name].cluster.host} [connected, ad-hoc]{active}")

    if not lines:
        return "No clusters configured. Add clusters to ~/.config/remote-claude-mcp/clusters.yaml"
    return "Clusters:\n" + "\n".join(lines)


# remote_bash is disabled — use Bash("remote-claude <cmd>") instead, which is
# faster (~160ms vs ~8s), supports run_in_background with local harness
# notifications, and behaves exactly like local Bash. Re-enable if MCP adds
# background task notification support (see anthropics/claude-code#18617).
#
# @server.tool(description="Same as Bash but runs on the active remote cluster.")
# async def remote_bash(
#     command: str, description: str = "",
#     run_in_background: bool = False, ctx: Context = None,
# ) -> str:
#     conn = _get_active()
#     if conn.work_dir:
#         command = f"cd {conn.work_dir} && {command}"
#     args = {"command": command}
#     if description:
#         args["description"] = description
#     if run_in_background:
#         args["run_in_background"] = True
#         result = await conn.call_tool("Bash", args)
#         return await _format_background_result(result, conn)
#     return await conn.call_tool_with_progress("Bash", args, ctx)


@server.tool(description="Same as Read but runs on the active remote cluster.")
async def remote_read(
    file_path: str, offset: int = 0, limit: int = 2000
) -> str:
    conn = _get_active()
    args = {"file_path": file_path}
    if offset:
        args["offset"] = offset
    if limit != 2000:
        args["limit"] = limit
    result = await conn.call_tool("Read", args)
    # Match local Read format — plain text with line numbers (cat -n style),
    # not the JSON wrapper that claude mcp serve returns.
    try:
        parsed = json.loads(result)
        content = parsed.get("file", {}).get("content", "")
        start_line = parsed.get("file", {}).get("startLine", 1)
        if content:
            lines = content.split("\n")
            # Remove trailing empty line from split
            if lines and lines[-1] == "":
                lines = lines[:-1]
            numbered = "\n".join(
                f"{start_line + i}\t{line}" for i, line in enumerate(lines)
            )
            return numbered
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    return result


@server.tool(description="Same as Write but runs on the active remote cluster.")
async def remote_write(file_path: str, content: str) -> str:
    conn = _get_active()
    result = await conn.call_tool("Write", {"file_path": file_path, "content": content})
    if result.startswith("[ERROR]"):
        return result
    return f"File created successfully at: {file_path}"


@server.tool(description="Same as Edit but runs on the active remote cluster.")
async def remote_edit(
    file_path: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    conn = _get_active()
    result = await conn.call_tool(
        "Edit",
        {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
            "replace_all": replace_all,
        },
    )
    # Match local Edit behavior — return minimal confirmation, not the
    # full file content + patch that claude mcp serve returns.
    if result.startswith("[ERROR]"):
        return result
    try:
        parsed = json.loads(result)
        return f"The file {parsed.get('filePath', file_path)} has been updated successfully."
    except (json.JSONDecodeError, TypeError):
        return result


@server.tool(description="Same as Glob but runs on the active remote cluster.")
async def remote_glob(pattern: str, path: str = "") -> str:
    conn = _get_active()
    args = {"pattern": pattern}
    if path:
        args["path"] = path
    return await conn.call_tool("Glob", args)


@server.tool(description="Same as Grep but runs on the active remote cluster.")
async def remote_grep(
    pattern: str,
    path: str = "",
    glob: str = "",
    output_mode: str = "files_with_matches",
    type: str = "",
    context: int = 0,
) -> str:
    conn = _get_active()
    args = {"pattern": pattern}
    if path:
        args["path"] = path
    if glob:
        args["glob"] = glob
    if output_mode != "files_with_matches":
        args["output_mode"] = output_mode
    if type:
        args["type"] = type
    if context:
        args["-C"] = context
    return await conn.call_tool("Grep", args)




_TASK_OUTPUT_PATTERN = "/tmp/claude-$(id -u)/*/tasks/{task_id}.output"


async def _format_background_result(result: str, conn: RemoteConnection) -> str:
    """Format a background task result with task ID and resolved output file path."""
    try:
        parsed = json.loads(result)
        task_id = parsed.get("backgroundTaskId", "")
        if task_id:
            # Resolve the actual output file path
            find_result = await conn.call_tool("Bash", {
                "command": f"find /tmp/claude-$(id -u) -name '{task_id}.output' 2>/dev/null | head -1"
            })
            output_file = ""
            try:
                output_file = json.loads(find_result).get("stdout", "").strip()
            except (json.JSONDecodeError, TypeError):
                pass
            if output_file:
                return (
                    f"Background task started on remote: {task_id}\n"
                    f"Output file: {output_file}\n"
                    f"Check with: remote_read(file_path=\"{output_file}\")"
                )
            return f"Background task started on remote: {task_id}"
    except (json.JSONDecodeError, TypeError):
        pass
    return result


def _cleanup():
    """Kill all remote SSH/claude processes on exit."""
    import subprocess
    for name, conn in _connections.items():
        logger.info(f"Closing connection to {name}")
        # Kill local SSH process
        if conn.process.returncode is None:
            conn.process.terminate()
            try:
                conn.process.wait()
            except Exception:
                conn.process.kill()
        # Kill remote claude mcp serve via PID file
        pidfile = f"/tmp/remote-claude-mcp-{conn.cluster.name}.pid"
        host = f"{conn.cluster.user}@{conn.cluster.host}" if conn.cluster.user else conn.cluster.host
        try:
            subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                 host, "--",
                 f"test -f {pidfile} && kill $(cat {pidfile}) 2>/dev/null; rm -f {pidfile}"],
                timeout=10, capture_output=True
            )
        except Exception:
            pass


def _signal_handler(sig, frame):
    _cleanup()
    raise SystemExit(0)


def run(config_path: str = None):
    global _config
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    _config = load_config(config_path)
    logger.info(f"Loaded {len(_config.clusters)} cluster(s) from config")
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    server.run(transport="stdio")
