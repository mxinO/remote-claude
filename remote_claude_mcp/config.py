"""Load cluster configuration from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml

DEFAULT_CONFIG_PATHS = [
    Path.home() / ".config" / "remote-claude-mcp" / "clusters.yaml",
    Path.home() / ".config" / "ssh-gateway-mcp" / "clusters.yaml",  # backward compat
    Path("clusters.yaml"),
]


@dataclass
class ClusterConfig:
    name: str
    host: str
    user: Optional[str] = None
    claude_path: Optional[str] = None  # auto-detected if not set
    jump_proxy: Optional[str] = None
    ssh_key: Optional[str] = None
    port: int = 22


@dataclass
class Config:
    clusters: Dict[str, ClusterConfig] = field(default_factory=dict)


def load_config(path: Optional[str] = None) -> Config:
    """Load config from explicit path, env var, or default locations."""
    config_path = None

    if path:
        config_path = Path(path)
    elif os.environ.get("REMOTE_CLAUDE_MCP_CONFIG") or os.environ.get("SSH_GATEWAY_MCP_CONFIG"):
        config_path = Path(os.environ.get("REMOTE_CLAUDE_MCP_CONFIG") or os.environ["SSH_GATEWAY_MCP_CONFIG"])
    else:
        for p in DEFAULT_CONFIG_PATHS:
            if p.exists():
                config_path = p
                break

    if config_path is None or not config_path.exists():
        return Config()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    clusters = {}
    for name, spec in raw.get("clusters", {}).items():
        clusters[name] = ClusterConfig(
            name=name,
            host=spec.get("host", name),
            user=spec.get("user"),
            claude_path=spec.get("claude_path"),
            jump_proxy=spec.get("jump_proxy"),
            ssh_key=spec.get("ssh_key"),
            port=spec.get("port", 22),
        )

    return Config(clusters=clusters)
