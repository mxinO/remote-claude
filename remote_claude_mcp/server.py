"""Remote Claude MCP Server — FastMCP server with tools that proxy to remote clusters."""

from __future__ import annotations

import atexit
import asyncio
import logging
from typing import Dict, Optional

from mcp.server.fastmcp import FastMCP

from .config import ClusterConfig, Config, load_config
from .proxy import RemoteConnection, connect

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

    # Already connected — switch, optionally change work_dir
    if name in _connections:
        _active_cluster = name
        if work_dir:
            await _connections[name].close()
            del _connections[name]
            # Reconnect with new work_dir below
        else:
            return f"Switched to cluster '{name}' ({_connections[name].cluster.host})"

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


@server.tool(description="Same as Bash but runs on the active remote cluster.")
async def remote_bash(
    command: str, timeout: int = 120, description: str = ""
) -> str:
    conn = _get_active()
    # Always reset to work_dir before running — the remote shell persists cd
    if conn.work_dir:
        command = f"cd {conn.work_dir} && {command}"
    args = {"command": command, "timeout": timeout}
    if description:
        args["description"] = description
    return await conn.call_tool("Bash", args)


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
    return await conn.call_tool("Read", args)


@server.tool(description="Same as Write but runs on the active remote cluster.")
async def remote_write(file_path: str, content: str) -> str:
    conn = _get_active()
    return await conn.call_tool("Write", {"file_path": file_path, "content": content})


@server.tool(description="Same as Edit but runs on the active remote cluster.")
async def remote_edit(
    file_path: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    conn = _get_active()
    return await conn.call_tool(
        "Edit",
        {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
            "replace_all": replace_all,
        },
    )


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


def _cleanup():
    """Kill all remote SSH processes on exit."""
    for name, conn in _connections.items():
        if conn.process.returncode is None:
            logger.info(f"Closing connection to {name}")
            conn.process.terminate()
            try:
                conn.process.wait()
            except Exception:
                conn.process.kill()


def run(config_path: str = None):
    global _config
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    _config = load_config(config_path)
    logger.info(f"Loaded {len(_config.clusters)} cluster(s) from config")
    atexit.register(_cleanup)
    server.run(transport="stdio")
