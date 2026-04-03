# ssh-gateway-mcp

MCP server that proxies Claude Code tools to remote clusters via SSH.

Work on any remote cluster from a single local Claude Code session — no restart needed to add new clusters. The gateway connects on-demand and uses `claude mcp serve` on the remote side, giving you the exact same Edit, Read, Write, Bash, Glob, and Grep tools.

## How it works

```
Local Claude Code (MCP client)
    │ stdio
ssh-gateway-mcp (always-on, configured once)
    │ SSH on-demand (ControlMaster-persisted)
Remote: claude mcp serve (full Claude Code tools)
```

## Install

```bash
git clone <repo-url> && cd ssh-gateway-mcp
./install.sh
```

This will:
1. Install the Python package
2. Register the MCP server with Claude Code
3. Create a default config at `~/.config/ssh-gateway-mcp/clusters.yaml`
4. Append usage instructions to `~/.claude/CLAUDE.md` (safe if you already have one)

Restart Claude Code to load the new MCP server.

## Configure clusters

Create `~/.config/ssh-gateway-mcp/clusters.yaml`:

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

Or set `SSH_GATEWAY_MCP_CONFIG=/path/to/clusters.yaml`.

## Usage

Just talk to Claude naturally:

```
> Let's work on dev1, the project is in /home/me/myapp

> Fix the bug in server.py on prod-cluster-01.example.com

> Search for TODO comments on dev1 under /home/me/project

> Switch to prod1 and check the logs
```

Claude will automatically connect to the cluster and use the remote tools. No special syntax needed.

## Prerequisites: Remote hosts

Each remote cluster needs Claude Code **installed and authenticated** before use:

```bash
ssh user@remote-host
curl -fsSL https://claude.ai/install.sh | sh
claude   # follow the auth prompts
exit
```

The gateway auto-detects the claude binary in common paths (`~/.local/bin/claude`, `/usr/local/bin/claude`, etc.) or you can set `claude_path` in the config.

## Features

- **Auto-detect Claude Code** on remote hosts (searches common paths)
- **SSH ControlMaster** for persistent, fast connections
- **Ad-hoc hosts** — use any hostname, not just configured clusters
- **Full fidelity** — proxies to `claude mcp serve`, so you get Claude Code's exact Edit tool with string-matching, indentation preservation, etc.
- **Minimal token overhead** — thin tool descriptions, no duplication

## Requirements

- Python 3.10+
- `mcp` Python SDK
- `pyyaml`
- SSH access to remote clusters
- Claude Code CLI installed and authenticated on remote hosts
