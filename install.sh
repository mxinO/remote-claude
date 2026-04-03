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

# Update CLAUDE.md instructions (replace if exists, append if not)
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MARKER_START="## Remote clusters (ssh-gateway-mcp)"
MARKER_END="# End ssh-gateway-mcp"
INSTRUCTIONS="$(cat "$SCRIPT_DIR/claude_md_instructions.md")"

mkdir -p "$HOME/.claude"
if [ -f "$CLAUDE_MD" ] && grep -qF "$MARKER_START" "$CLAUDE_MD"; then
    # Replace existing block between markers
    python3 - "$CLAUDE_MD" "$MARKER_START" "$MARKER_END" "$INSTRUCTIONS" << 'PYSCRIPT'
import sys
path, marker_start, marker_end, new_content = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(path) as f:
    content = f.read()
# Find the block: from marker_start to marker_end (or next ## heading or EOF)
start = content.find(marker_start)
if start == -1:
    sys.exit(0)
# Look for the end: next ## heading after the marker_start line
rest = content[start + len(marker_start):]
end = -1
for i, line in enumerate(rest.split('\n')[1:], 1):
    if line.startswith('## ') or line.strip() == marker_end:
        end = start + len(marker_start) + sum(len(l)+1 for l in rest.split('\n')[:i])
        break
if end == -1:
    end = len(content)
with open(path, 'w') as f:
    f.write(content[:start] + new_content.rstrip() + '\n' + content[end:])
PYSCRIPT
    echo "Updated ssh-gateway instructions in $CLAUDE_MD"
else
    # Append new block
    printf "\n%s\n" "$INSTRUCTIONS" >> "$CLAUDE_MD"
    echo "Appended ssh-gateway instructions to $CLAUDE_MD"
fi

echo ""
echo "Done! Restart Claude Code to load the new MCP server."
echo "Edit $CONFIG_DIR/clusters.yaml to configure your clusters."
