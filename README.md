# Remote Claude

Work on any remote cluster from a single local Claude Code session. Just say "work on dev1" and Claude connects on-demand via SSH, giving you the exact same Edit, Read, Write, Bash, Glob, and Grep tools — no restart needed.

## How it works

```
Local Claude Code
    │ stdio
Remote Claude (MCP gateway, always-on)
    │ SSH on-demand (persistent session)
Remote host: claude mcp serve
```

The gateway proxies tool calls to `claude mcp serve` running on the remote host over a persistent SSH connection. You get full-fidelity Claude Code tools remotely with minimal token overhead.

## Install

```bash
git clone git@github.com:mxinO/remote-claude.git && cd remote-claude
./install.sh
```

This will:
1. Install the Python package
2. Register the MCP server with Claude Code
3. Generate `~/.config/remote-claude-mcp/clusters.yaml` from your `~/.ssh/config` (skips git forges)
4. Add usage instructions to `~/.claude/CLAUDE.md` (updates safely on reinstall)

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
- **Working directory** — set a work_dir and use relative paths, just like working locally
- **Auto-detect Claude Code** on remote hosts (searches common paths)
- **Ad-hoc hosts** — use any hostname, not just configured clusters
- **Minimal token overhead** — thin tool descriptions, no context bloat
- **SSH config import** — install script reads `~/.ssh/config` to bootstrap cluster config

## Limitations

**Background tasks have limited support.** `run_in_background=true` works for `remote_bash` and `remote_agent` — the command starts on the remote and the task ID + output file path are returned. However, there are **no automatic notifications** when the task finishes. You must manually check the output file with `remote_bash` or `remote_read`.

This is because the MCP protocol does not support push notifications from server to client, so there's no way to replicate Claude Code's local `<task-notification>` pattern through MCP.

See [anthropics/claude-code#18617](https://github.com/anthropics/claude-code/issues/18617) for discussion on MCP background task support.

By default, remote commands block until completion with progress heartbeats (up to 10 minutes).

## Requirements

- Python 3.10+
- `mcp` Python SDK
- `pyyaml`
- SSH access to remote clusters
- Claude Code installed and authenticated on remote hosts
