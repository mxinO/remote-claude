"""Remote Claude proxy — manages SSH connections to remote `claude mcp serve` instances."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .config import ClusterConfig

logger = logging.getLogger(__name__)

# Paths to search for claude on remote host
CLAUDE_SEARCH_PATHS = [
    "~/.local/bin/claude",
    "~/.claude/local/claude",
    "/usr/local/bin/claude",
    "~/.nix-profile/bin/claude",
]

INSTALL_HINT = (
    "Claude Code must be installed and authenticated on the remote host.\n"
    "  1. ssh <host>\n"
    "  2. curl -fsSL https://claude.ai/install.sh | sh\n"
    "  3. claude  # follow auth prompts\n"
    "  4. exit"
)


@dataclass
class RemoteConnection:
    cluster: ClusterConfig
    process: asyncio.subprocess.Process
    claude_path: str
    work_dir: str = ""
    _id_counter: int = 0
    _pending: Dict[int, asyncio.Future] = field(default_factory=dict)
    _read_task: Optional[asyncio.Task] = None

    def next_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    async def start_read_loop(self):
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        """Read JSON-RPC responses from the remote MCP server."""
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    self._pending[msg_id].set_result(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Read loop error: {e}")
            # Fail all pending requests
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(e)

    async def send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        req_id = self.next_id()
        request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        data = json.dumps(request) + "\n"

        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()
            result = await asyncio.wait_for(future, timeout=300)
            return result
        finally:
            self._pending.pop(req_id, None)

    async def send_notification(self, method: str, params: dict = None):
        """Send a JSON-RPC notification (no response expected)."""
        notif = {"jsonrpc": "2.0", "method": method}
        if params:
            notif["params"] = params
        data = json.dumps(notif) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the remote MCP server and return the text result."""
        resp = await self.send_request(
            "tools/call", {"name": tool_name, "arguments": arguments}
        )
        return self._extract_result(resp)

    async def call_tool_with_progress(
        self, tool_name: str, arguments: dict, ctx, progress_interval: int = 5
    ) -> str:
        """Call a tool, reporting progress with heartbeat while waiting."""
        req_id = self.next_id()
        request = {"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments}}
        data = json.dumps(request) + "\n"

        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()

            elapsed = 0
            while True:
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(future), timeout=progress_interval
                    )
                    return self._extract_result(result)
                except asyncio.TimeoutError:
                    elapsed += progress_interval
                    # Heartbeat: send a quick command to verify connection is alive
                    try:
                        hb = await asyncio.wait_for(
                            self._heartbeat(), timeout=10
                        )
                        if not hb:
                            return "[ERROR] Remote connection lost (heartbeat failed)"
                    except asyncio.TimeoutError:
                        return "[ERROR] Remote connection lost (heartbeat timeout)"
                    if ctx:
                        await ctx.report_progress(
                            elapsed, elapsed + 60,
                            f"Running on remote ({elapsed}s, connection alive)..."
                        )
                    if elapsed > 600:
                        return "[ERROR] Remote command timed out after 600s"
        finally:
            self._pending.pop(req_id, None)

    async def _heartbeat(self) -> bool:
        """Send a quick echo to verify the remote connection is alive."""
        try:
            resp = await self.send_request(
                "tools/call", {"name": "Bash", "arguments": {"command": "echo 1"}}
            )
            return "error" not in resp
        except Exception:
            return False

    @staticmethod
    def _extract_result(resp: dict) -> str:
        """Extract text result from a JSON-RPC response."""
        if "error" in resp:
            err = resp["error"]
            return f"[ERROR] {err.get('message', str(err))}"
        result = resp.get("result", {})
        content = result.get("content", [])
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item["text"])
            elif isinstance(item, dict):
                parts.append(json.dumps(item))
            else:
                parts.append(str(item))
        return "\n".join(parts) if parts else "(no output)"

    async def close(self):
        if self._read_task:
            self._read_task.cancel()
        if self.process.returncode is None:
            try:
                self.process.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self.process.kill()
        # Also kill remote process via PID file as a safety net
        pidfile = f"/tmp/remote-claude-mcp-{self.cluster.name}.pid"
        try:
            await _run_ssh_command(
                self.cluster,
                f"test -f {pidfile} && kill $(cat {pidfile}) 2>/dev/null; rm -f {pidfile}"
            )
        except Exception:
            pass


def _build_ssh_args(cluster: ClusterConfig) -> list[str]:
    """Build SSH command args from cluster config."""
    args = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if cluster.ssh_key:
        args.extend(["-i", cluster.ssh_key])
    if cluster.jump_proxy:
        args.extend(["-J", cluster.jump_proxy])
    if cluster.port != 22:
        args.extend(["-p", str(cluster.port)])

    host = f"{cluster.user}@{cluster.host}" if cluster.user else cluster.host
    args.append(host)
    return args


async def _run_ssh_command(cluster: ClusterConfig, command: str) -> tuple[int, str, str]:
    """Run a one-shot SSH command. Returns (returncode, stdout, stderr)."""

    args = _build_ssh_args(cluster) + ["--", command]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def find_claude_path(cluster: ClusterConfig) -> Optional[str]:
    """Find claude binary on the remote host."""
    if cluster.claude_path:
        rc, out, _ = await _run_ssh_command(cluster, f"test -x {cluster.claude_path} && echo ok")
        if rc == 0 and "ok" in out:
            return cluster.claude_path

    # Search common paths
    check_cmd = " || ".join(
        f'(test -x {p} && echo "FOUND:{p}")'
        for p in CLAUDE_SEARCH_PATHS
    )
    # Also try `which claude`
    check_cmd += ' || (which claude 2>/dev/null && echo "FOUND:$(which claude)")'

    rc, out, _ = await _run_ssh_command(cluster, check_cmd)
    for line in out.strip().splitlines():
        if line.startswith("FOUND:"):
            return line.split("FOUND:", 1)[1].strip()

    return None


async def connect(cluster: ClusterConfig, work_dir: str = "") -> RemoteConnection:
    """Connect to a cluster: find claude, start MCP serve, do handshake."""

    # Step 1: Find claude (must be pre-installed and authenticated)
    claude_path = await find_claude_path(cluster)
    if not claude_path:
        raise RuntimeError(
            f"Claude Code not found on {cluster.name} ({cluster.host}).\n{INSTALL_HINT}"
        )

    logger.info(f"Using claude at {claude_path} on {cluster.name}")

    # Step 2: Kill any orphan claude mcp serve processes from previous sessions
    pidfile = f"/tmp/remote-claude-mcp-{cluster.name}.pid"
    await _run_ssh_command(
        cluster,
        f"test -f {pidfile} && kill $(cat {pidfile}) 2>/dev/null; rm -f {pidfile}"
    )

    # Step 3: Start `claude mcp serve` over SSH, optionally in a working directory
    # Write PID file, then exec so stdin/stdout go directly to claude.
    # Orphan cleanup relies on: PID file kill on reconnect + atexit SSH kill.
    cd_cmd = f"cd {work_dir} && " if work_dir else ""
    serve_cmd = f'{cd_cmd}echo $$ > {pidfile} && exec {claude_path} mcp serve'
    ssh_args = _build_ssh_args(cluster) + ["--", serve_cmd]
    proc = await asyncio.create_subprocess_exec(
        *ssh_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    conn = RemoteConnection(cluster=cluster, process=proc, claude_path=claude_path, work_dir=work_dir)
    await conn.start_read_loop()

    # Step 3: MCP handshake
    resp = await conn.send_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "remote-claude-mcp", "version": "1.0.0"},
    })

    if "error" in resp:
        await conn.close()
        raise RuntimeError(f"MCP handshake failed on {cluster.name}: {resp['error']}")

    await conn.send_notification("notifications/initialized")

    server_info = resp.get("result", {}).get("serverInfo", {})
    logger.info(
        f"Connected to {cluster.name}: {server_info.get('name')} v{server_info.get('version')}"
    )

    return conn
