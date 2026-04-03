#!/bin/bash
set -e

echo "Installing ssh-gateway-mcp..."

# Install Python package
pip install -e "$(dirname "$0")" || pip install -e "$(dirname "$0")" --user

# Register MCP server with Claude Code
PYTHON_BIN=$(which python3 || which python)
claude mcp remove ssh-gateway 2>/dev/null || true
claude mcp add ssh-gateway -- "$PYTHON_BIN" -m ssh_gateway_mcp

# Create config from ~/.ssh/config if available, otherwise use example
CONFIG_DIR="$HOME/.config/ssh-gateway-mcp"
if [ ! -f "$CONFIG_DIR/clusters.yaml" ]; then
    mkdir -p "$CONFIG_DIR"
    if [ -f "$HOME/.ssh/config" ]; then
        echo "Found ~/.ssh/config — generating clusters.yaml from SSH hosts..."
        python3 - "$HOME/.ssh/config" "$CONFIG_DIR/clusters.yaml" << 'PYSCRIPT'
import sys

ssh_config = sys.argv[1]
out_path = sys.argv[2]

# Skip hosts that are git forges, not remote machines to work on
SKIP_HOSTS = {"github.com", "gitlab.com", "bitbucket.org", "ssh.dev.azure.com"}
SKIP_PREFIXES = ("gitlab", "github", "bitbucket")

hosts = []
current = {}

def should_skip(alias):
    """Skip wildcard patterns and known non-cluster hosts."""
    if "*" in alias or "?" in alias:
        return True
    lower = alias.lower()
    for skip in SKIP_HOSTS:
        if lower == skip or lower.endswith("." + skip):
            return True
    # Skip git forge subdomains (e.g. gitlab.company.com)
    first_part = lower.split(".")[0]
    if first_part in SKIP_PREFIXES:
        return True
    return False

with open(ssh_config) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition(" ")
        key = key.lower()
        val = val.strip()
        if key == "host":
            if current.get("host_alias") and not should_skip(current["host_alias"]):
                hosts.append(current)
            current = {"host_alias": val}
        elif key == "hostname":
            current["hostname"] = val
        elif key == "user":
            current["user"] = val
        elif key == "port":
            current["port"] = val
        elif key == "identityfile":
            current["ssh_key"] = val
        elif key == "proxyjump":
            current["jump_proxy"] = val

    if current.get("host_alias") and not should_skip(current["host_alias"]):
        hosts.append(current)

with open(out_path, "w") as f:
    f.write("clusters:\n")
    if not hosts:
        f.write("  # No hosts found in ~/.ssh/config. Add your clusters here.\n")
        f.write("  # example:\n")
        f.write("  #   host: dev-cluster-01.example.com\n")
        f.write("  #   user: myuser\n")
    for h in hosts:
        alias = h["host_alias"].replace(" ", "-")
        f.write(f"\n  {alias}:\n")
        f.write(f"    host: {h.get('hostname', h['host_alias'])}\n")
        if "user" in h:
            f.write(f"    user: {h['user']}\n")
        if "port" in h and h["port"] != "22":
            f.write(f"    port: {h['port']}\n")
        if "ssh_key" in h:
            f.write(f"    ssh_key: {h['ssh_key']}\n")
        if "jump_proxy" in h:
            f.write(f"    jump_proxy: {h['jump_proxy']}\n")

print(f"Generated {len(hosts)} cluster(s) from ~/.ssh/config")
PYSCRIPT
    else
        cp "$(dirname "$0")/example_clusters.yaml" "$CONFIG_DIR/clusters.yaml"
        echo "No ~/.ssh/config found. Created example config."
    fi
    echo "Config at $CONFIG_DIR/clusters.yaml — review and edit as needed."
else
    echo "Config already exists at $CONFIG_DIR/clusters.yaml"
fi

# Append CLAUDE.md instructions if not already present
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
MARKER="## Remote clusters (ssh-gateway-mcp)"
if [ -f "$CLAUDE_MD" ] && grep -qF "$MARKER" "$CLAUDE_MD"; then
    echo "CLAUDE.md already has ssh-gateway instructions."
else
    mkdir -p "$HOME/.claude"
    cat >> "$CLAUDE_MD" << 'INSTRUCTIONS'

## Remote clusters (ssh-gateway-mcp)

When the user asks to work on a remote machine (e.g. "work on dev1", "let's use the prod cluster",
"edit files on my-host.example.com"), use the ssh-gateway MCP tools:
- First call use_cluster() with the cluster name or hostname to connect.
- Then use remote_bash, remote_read, remote_edit, remote_write, remote_glob, remote_grep
  as drop-in replacements for the local Bash, Read, Edit, Write, Glob, Grep tools.
- All file paths should be absolute paths on the remote machine.
- If the user specifies a working directory, cd into it via remote_bash first or use it as
  the path argument in remote_glob/remote_grep.
- Cluster names are defined in ~/.config/ssh-gateway-mcp/clusters.yaml.
  The user may also provide a raw hostname instead of a configured name.
- Stay on the remote cluster for subsequent commands until the user says otherwise.
INSTRUCTIONS
    echo "Appended ssh-gateway instructions to $CLAUDE_MD"
fi

echo ""
echo "Done! Restart Claude Code to load the new MCP server."
echo "Edit $CONFIG_DIR/clusters.yaml to configure your clusters."
