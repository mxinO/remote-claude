"""Entry point: python -m remote_claude_mcp"""

import argparse

from .server import run


def main():
    parser = argparse.ArgumentParser(description="Remote Claude MCP Server")
    parser.add_argument("--config", help="Path to clusters.yaml config file")
    args = parser.parse_args()
    run(config_path=args.config)


if __name__ == "__main__":
    main()
