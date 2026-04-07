# Remote Claude

Work on any remote cluster from a single local Claude Code session. Just say "work on dev1" and Claude connects on-demand via SSH, giving you the exact same Edit, Read, Write, Bash, Glob, and Grep tools — no restart needed.

## How it works

```
Local Claude Code
    │
    ├── MCP gateway (file tools: Read, Edit, Write, Glob, Grep)
    │       │ SSH (persistent session, keepalive)
    │       └── Remote: claude mcp serve
    │
    └── remote-claude CLI (bash commands)
            │ SSH (ControlMaster, reuses gateway connection)
            └── Remote: runs command directly
```

**File operations** (Read, Edit, Write, Glob, Grep) go through the MCP gateway which proxies to `claude mcp serve` on the remote — giving you Claude Code's exact tool implementations.

**Bash commands** use the `remote-claude` CLI via the local Bash tool. This supports `run_in_background` with local notifications, and reuses the gateway's SSH connection via ControlMaster.

## Install

```bash
git clone git@github.com:mxinO/remote-claude.git && cd remote-claude
./install.sh
```

This will:
1. Install the Python package (`remote-claude-mcp` + `remote-claude` CLI)
2. Register the MCP server with Claude Code
3. Generate `~/.config/remote-claude-mcp/clusters.yaml` from your `~/.ssh/config` (skips git forges)
4. Install a `SessionStart` hook for per-session isolation (`$CLAUDE_SESSION_ID`)
5. Add usage instructions to `~/.claude/CLAUDE.md` (updates safely on reinstall)

Restart Claude Code to load the MCP server.

## Configure clusters

Edit `~/.config/remote-claude-mcp/clusters.yaml`:

```yaml
clusters:
  dev1:
    host: dev-cluster-01.example.com
    user: myuser
    # claude_path: ~/.local/bin/claude  # auto-detected
    # jump_proxy: bastion.example.com   # ProxyJump
    # ssh_key: ~/.ssh/id_rsa            # identity file
    # port: 22

  prod1:
    host: prod-cluster-01.example.com
    user: myuser
```

SSH config (`ProxyJump`, `ControlMaster`, etc.) is respected automatically — no need to duplicate it here.

Or set `REMOTE_CLAUDE_MCP_CONFIG=/path/to/clusters.yaml`.

## Usage

Just talk to Claude naturally:

```
> Let's work on dev1, the project is in /home/me/myapp

> Fix the bug in server.py on prod-cluster-01.example.com

> Search for TODO comments on dev1 under /home/me/project

> Switch to prod1 and check the logs
```

Claude automatically connects to the cluster, sets the working directory, and uses remote tools. Relative paths work when a working directory is specified. No special syntax needed.

## How Claude uses it

| Operation | Tool | Path |
|-----------|------|------|
| Run commands | `Bash("remote-claude <cmd>")` | Local Bash → SSH → remote |
| Read files | `remote_read` | MCP → claude mcp serve |
| Edit files | `remote_edit` | MCP → claude mcp serve |
| Write files | `remote_write` | MCP → claude mcp serve |
| Find files | `remote_glob` | MCP → claude mcp serve |
| Search code | `remote_grep` | MCP → claude mcp serve |
| Background tasks | `Bash("remote-claude <cmd>", run_in_background=true)` | Local harness notifications |

## Prerequisites

Each remote host needs Claude Code **installed and authenticated**:

```bash
ssh user@remote-host
curl -fsSL https://claude.ai/install.sh | sh
claude   # follow the auth prompts
exit
```

The gateway auto-detects the claude binary in common paths (`~/.local/bin/claude`, `/usr/local/bin/claude`, etc.) or you can set `claude_path` in the config.

## Features

- **Natural language** — just say "work on dev1" and Claude handles the rest
- **Full fidelity** — proxies to `claude mcp serve`, so you get Claude Code's exact Edit, Read, Write tools
- **Per-session isolation** — multiple Claude Code sessions work independently on same/different clusters
- **Background tasks** — `run_in_background` works with local harness notifications via `remote-claude` CLI
- **Working directory** — set a work_dir and use relative paths, just like working locally; auto-detects remote `$HOME`
- **Dead server detection** — immediate error if remote server dies, no hanging; auto-reconnect on next `use_cluster`
- **SSH keepalive** — `ServerAliveInterval` prevents silent connection drops
- **Auto-detect Claude Code** on remote hosts (searches common paths)
- **Ad-hoc hosts** — use any hostname, not just configured clusters
- **Minimal token overhead** — thin tool descriptions, responses match local tool format
- **SSH config import** — install script reads `~/.ssh/config` to bootstrap cluster config
- **Orphan cleanup** — session-scoped PID files + signal handlers prevent zombie remote processes
- **Multi-cluster** — switch between clusters within a session; all cleaned up on exit
- **MFA support** — works with ControlMaster sessions for hosts requiring MFA

## Limitations

The MCP protocol does not support push notifications from server to client. This means `remote_bash` MCP tool calls cannot receive `<task-notification>` when backgrounded. Use `Bash("remote-claude <cmd>", run_in_background=true)` instead for background tasks with notifications.

See [anthropics/claude-code#18617](https://github.com/anthropics/claude-code/issues/18617) for discussion on MCP background task support.

## Requirements

- Python 3.10+
- `mcp` Python SDK
- `pyyaml`
- SSH access to remote clusters
- Claude Code installed and authenticated on remote hosts
