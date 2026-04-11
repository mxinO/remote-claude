# Remote Claude

Work on any remote cluster from a single local Claude Code session. Just say "work on dev1" and Claude connects on-demand via SSH — no server or Claude Code install needed on the remote.

## How it works

```
Local Claude Code
    │
    └── remote-claude CLI
            │ SSH (ControlMaster)
            └── Remote: lightweight read/edit scripts + shell commands
```

Everything goes through the `remote-claude` CLI via SSH:
- **Read/Edit** — small Python scripts auto-deployed to `~/.cache/remote-claude/` on the remote on first use. Drop-in replacements for Claude Code's local Read and Edit tools (same args, same output format).
- **All other operations** (bash, glob, grep, write) — standard Linux commands run directly via SSH.

No MCP server, no remote daemon, no Claude Code on the remote. Just SSH + Python.

## Install

```bash
git clone git@github.com:mxinO/remote-claude.git && cd remote-claude
./install.sh
```

This will:
1. Install the Python package (`remote-claude-mcp` + `remote-claude` CLI)
2. Register the MCP server with Claude Code (for `use_cluster` connection management)
3. Generate `~/.config/remote-claude-mcp/clusters.yaml` from your `~/.ssh/config`
4. Install a `SessionStart` hook for per-session isolation (`$CLAUDE_SESSION_ID`)
5. Add usage instructions to `~/.claude/CLAUDE.md`

Restart Claude Code to load.

## Configure clusters

Edit `~/.config/remote-claude-mcp/clusters.yaml`:

```yaml
clusters:
  dev1:
    host: dev-cluster-01.example.com
    user: myuser
    # jump_proxy: bastion.example.com
    # ssh_key: ~/.ssh/id_rsa
    # port: 22

  prod1:
    host: prod-cluster-01.example.com
    user: myuser
```

SSH config (`ProxyJump`, `ControlMaster`, etc.) is respected automatically.

## Usage

Just talk to Claude naturally:

```
> Let's work on dev1, the project is in /home/me/myapp

> Fix the bug in server.py on prod-cluster-01.example.com

> Search for TODO comments on dev1 under /home/me/project

> Switch to prod1 and check the logs
```

Claude automatically connects to the cluster, sets the working directory, and uses remote tools. Relative paths work when a working directory is set. No special syntax needed.

## How Claude uses it

| Operation | Command | Notes |
|-----------|---------|-------|
| Read files | `remote-claude read <file> [--offset N] [--limit N]` | cat -n format, same as local Read |
| Edit files | `remote-claude edit <file> '<old>' '<new>' [--replace-all]` | Same as local Edit |
| Run commands | `remote-claude <cmd>` | Any shell command |
| Find files | `remote-claude find . -name '*.py'` | Standard Linux |
| Search code | `remote-claude rg 'pattern'` | Standard Linux |
| Write files | `remote-claude tee file <<< 'content'` | Standard Linux |
| Background | `Bash("remote-claude <cmd>", run_in_background=true)` | Local harness notifications |

## Prerequisites

- **Local**: Python 3.10+, Claude Code
- **Remote**: Python 3 (for read/edit scripts), SSH access

No Claude Code installation needed on remote hosts. The read/edit scripts are auto-deployed on first use via SSH.

## Features

- **Zero remote setup** — no server, no daemon, no Claude Code install on remote
- **Drop-in Read/Edit** — same arguments and output as Claude Code's local tools
- **Natural language** — just say "work on dev1" and Claude handles the rest
- **Per-session isolation** — multiple sessions work independently via `$CLAUDE_SESSION_ID`
- **Background tasks** — `run_in_background` works with local harness notifications
- **Working directory** — relative paths work; auto-detects remote `$HOME`
- **Auto-deploy** — read/edit scripts deployed to remote on first use (atomic, cached)
- **Read-before-edit** — enforces read tracking, same safety as local Edit tool
- **Ad-hoc hosts** — use any hostname, not just configured clusters
- **SSH config import** — installer reads `~/.ssh/config` to bootstrap cluster config
- **MFA support** — works with ControlMaster sessions for hosts requiring MFA

## Architecture

The MCP server (`remote-claude-mcp`) handles only connection management (`use_cluster`, `list_clusters`). All file operations go through the `remote-claude` CLI:

1. `use_cluster()` writes active cluster state to a session-scoped JSON file
2. `remote-claude` CLI reads that state and SSHes to the active cluster
3. `read`/`edit` subcommands call deployed scripts on the remote
4. All other args are passed as shell commands via SSH

For the previous MCP-based approach (proxying through `claude mcp serve`), see the `mcp-version` branch.

## Requirements

- Python 3.10+ (local)
- Python 3 (remote — for read/edit scripts only)
- `mcp` Python SDK, `pyyaml` (local)
- SSH access to remote clusters
