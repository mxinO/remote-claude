<!-- BEGIN ssh-gateway-mcp -->
## Remote clusters (ssh-gateway-mcp)

When the user asks to work on a remote machine (e.g. "work on dev1", "let's use the prod cluster",
"edit files on my-host.example.com"), use the ssh-gateway MCP tools:
- First call use_cluster() with the cluster name or hostname to connect.
- If the user specifies a working directory, pass it as work_dir to use_cluster().
  This starts the remote server in that directory so relative paths work naturally.
- If the user changes the working directory later (e.g. "now work in /other/project"),
  call use_cluster() again with the same cluster name and the new work_dir.
- Then use remote_bash, remote_read, remote_edit, remote_write, remote_glob, remote_grep
  as drop-in replacements for the local Bash, Read, Edit, Write, Glob, Grep tools.
- When work_dir is set, paths work exactly like working locally — use relative paths.
  Without work_dir, use absolute paths on the remote machine.
- Cluster names are defined in ~/.config/ssh-gateway-mcp/clusters.yaml.
  The user may also provide a raw hostname instead of a configured name.
- Stay on the remote cluster for subsequent commands until the user says otherwise.
<!-- END ssh-gateway-mcp -->
