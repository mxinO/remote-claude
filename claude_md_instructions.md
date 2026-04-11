<!-- BEGIN remote-claude-mcp -->
## Remote clusters (remote-claude)

When the user asks to work on a remote machine (e.g. "work on dev1", "edit files on my-host"),
use the `remote-claude` CLI via the local Bash tool. Everything runs over SSH — no server needed.

- **Connect**: `use_cluster()` MCP tool sets the active cluster and work_dir.
  Always pass session_id=$CLAUDE_SESSION_ID (read it via Bash: `echo $CLAUDE_SESSION_ID`).
  This ensures multiple sessions don't interfere with each other.
- If the user specifies a working directory, pass it as work_dir to use_cluster().
  This starts the remote server in that directory so relative paths work naturally.
- If the user changes the working directory later (e.g. "now work in /other/project"),
  call use_cluster() again with the same cluster name and the new work_dir.
- `remote-claude read` and `remote-claude edit` are drop-in replacements for the
  local Read and Edit tools — same arguments, same output format, same behavior.
  Use them exactly as you would the local tools, just via Bash:
  - `Bash("remote-claude read <file> [--offset N] [--limit N]")`
  - `Bash("remote-claude edit <file> '<old_string>' '<new_string>' [--replace-all]")`
- **Run commands**: `Bash("remote-claude <any command>")`
  Runs shell commands on the remote. Supports run_in_background.
- **Glob/Grep/Write**: Use standard Linux commands via remote-claude:
  `remote-claude find . -name '*.py'`, `remote-claude rg 'pattern'`,
  `remote-claude tee file.txt <<< 'content'`
- Relative paths work when work_dir is set.
- Cluster names are defined in ~/.config/remote-claude-mcp/clusters.yaml.
- Stay on the remote cluster until the user says otherwise.
- When spawning sub-agents for remote work, tell them we are working on a remote machine
  and to use `remote-claude` for all remote operations.
<!-- END remote-claude-mcp -->
