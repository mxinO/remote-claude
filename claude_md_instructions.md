## Remote clusters (ssh-gateway-mcp)

When the user asks to work on a remote machine (e.g. "work on dev1", "let's use the prod cluster",
"edit files on my-host.example.com"), use the ssh-gateway MCP tools:
- First call use_cluster() with the cluster name or hostname to connect.
- If the user specifies a working directory, pass it as work_dir to use_cluster().
  This starts the remote server in that directory so relative paths work naturally.
- Then use remote_bash, remote_read, remote_edit, remote_write, remote_glob, remote_grep
  as drop-in replacements for the local Bash, Read, Edit, Write, Glob, Grep tools.
- All file paths should be absolute paths on the remote machine.
  If a work_dir was set, relative paths resolve from there.
- Cluster names are defined in ~/.config/ssh-gateway-mcp/clusters.yaml.
  The user may also provide a raw hostname instead of a configured name.
- Stay on the remote cluster for subsequent commands until the user says otherwise.
