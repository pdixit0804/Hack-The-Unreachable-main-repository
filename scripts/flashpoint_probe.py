"""Connect to the Flashpoint MCP server and print its tools and argument schemas.

    python scripts/flashpoint_probe.py

Use the output to set FLASHPOINT_PANEL_TOOL and FLASHPOINT_PANEL_ARGS in .env.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tester.panel.flashpoint import MCPClient  # noqa: E402

client = MCPClient()
info = client.initialize()
print("Server:", json.dumps((info or {}).get("serverInfo", {})))
for tool in client.list_tools():
    print("\n==", tool["name"])
    print(tool.get("description", "")[:400])
    print(json.dumps(tool.get("inputSchema", {}), indent=2)[:2000])
