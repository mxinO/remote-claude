<!-- BEGIN remote-claude-mcp -->
## Remote clusters (remote-claude-mcp)

When the user asks to work on a remote machine (e.g. "work on dev1", "let's use the prod cluster",
"edit files on my-host.example.com"), use the remote-claude MCP tools:
- First call use_cluster() with the cluster name or hostname to connect.
- If the user specifies a working directory, pass it as work_dir to use_cluster().
  This starts the remote server in that directory so relative paths work naturally.
- If the user changes the working directory later (e.g. "now work in /other/project"),
  call use_cluster() again with the same cluster name and the new work_dir.
- Then use remote_read, remote_edit, remote_write, remote_glob, remote_grep
  as drop-in replacements for the local Read, Edit, Write, Glob, Grep tools.
- When work_dir is set, paths work exactly like working locally — use relative paths.
  Without work_dir, use absolute paths on the remote machine.
- Cluster names are defined in ~/.config/remote-claude-mcp/clusters.yaml.
  The user may also provide a raw hostname instead of a configured name.
- Stay on the remote cluster for subsequent commands until the user says otherwise.
- IMPORTANT: Do NOT use remote_bash for running commands. Instead, use the local Bash
  tool with the `remote-claude` CLI prefix: Bash(command="remote-claude <cmd>").
  This is faster (~160ms vs ~8s), supports run_in_background with local harness
  notifications (<task-notification>), and behaves exactly like local Bash.
  The `remote-claude` CLI uses SSH ControlMaster to reuse the existing connection.
- When spawning sub-agents for remote work, tell them we are working on a remote machine.
- If you are a sub-agent, do NOT call use_cluster() — the connection is already active.
<!-- END remote-claude-mcp -->
