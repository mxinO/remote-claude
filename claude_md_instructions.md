<!-- BEGIN remote-claude-mcp -->
## Remote clusters (remote-claude-mcp)

When the user asks to work on a remote machine (e.g. "work on dev1", "let's use the prod cluster",
"edit files on my-host.example.com"), use the remote-claude MCP tools:
- First call use_cluster() with the cluster name or hostname to connect.
- If the user specifies a working directory, pass it as work_dir to use_cluster().
  This starts the remote server in that directory so relative paths work naturally.
- If the user changes the working directory later (e.g. "now work in /other/project"),
  call use_cluster() again with the same cluster name and the new work_dir.
- Then use remote_bash, remote_read, remote_edit, remote_write, remote_glob, remote_grep
  as drop-in replacements for the local Bash, Read, Edit, Write, Glob, Grep tools.
- When work_dir is set, paths work exactly like working locally — use relative paths.
  Without work_dir, use absolute paths on the remote machine.
- Cluster names are defined in ~/.config/remote-claude-mcp/clusters.yaml.
  The user may also provide a raw hostname instead of a configured name.
- Stay on the remote cluster for subsequent commands until the user says otherwise.
- Remote commands block until completion by default (max 10 minutes with heartbeat).
- run_in_background is supported for remote_bash and remote_agent, but there are no
  automatic notifications when they finish. The result includes the task ID and a
  command to check status manually. Use this for long-running tasks where blocking
  is not acceptable.
<!-- END remote-claude-mcp -->
