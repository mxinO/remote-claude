#!/bin/bash
set -e

echo "Installing ssh-gateway-mcp..."

# Install Python package
pip install -e "$(dirname "$0")" || pip install -e "$(dirname "$0")" --user

# Register MCP server with Claude Code
PYTHON_BIN=$(which python3 || which python)
claude mcp remove ssh-gateway 2>/dev/null || true
claude mcp add ssh-gateway -- "$PYTHON_BIN" -m ssh_gateway_mcp

# Create example config if none exists
CONFIG_DIR="$HOME/.config/ssh-gateway-mcp"
if [ ! -f "$CONFIG_DIR/clusters.yaml" ]; then
    mkdir -p "$CONFIG_DIR"
    cp "$(dirname "$0")/example_clusters.yaml" "$CONFIG_DIR/clusters.yaml"
    echo "Created config at $CONFIG_DIR/clusters.yaml — edit it to add your clusters."
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
