"""入口分发：
    python -m tiandao_cli                                              → MCP 模式（stdio）
    python -m tiandao_cli --transport streamable-http --port 8000      → HTTP 模式
    python -m tiandao_cli cli ...                                      → CLI 模式
"""

import argparse
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from tiandao_cli.cli import cli
        cli()
    else:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--transport", default="stdio")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8000)
        args, _ = parser.parse_known_args()

        from tiandao_cli.server import mcp
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            mcp.run(transport=args.transport, host=args.host, port=args.port)


main()
