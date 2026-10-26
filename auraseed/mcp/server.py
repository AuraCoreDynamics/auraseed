import sys
import json
import traceback
from typing import Dict, Any, Optional

from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest


class AuraSeedMcpServer:
    """
    Model Context Protocol (MCP) Server for AuraSeed.
    Exposes managed virtual environment capabilities and Python runtime discovery
    as tools to AuraRouter, AuraCode, and LLM coding agents.
    """

    TOOLS = [
        {
            "name": "mvenv_list",
            "description": "List all managed virtual environments (mvenvs) cataloged on this host/node.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "mvenv_info",
            "description": "Get detailed metadata, package list, and executable paths for a named mvenv.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the managed environment."}
                },
                "required": ["name"]
            }
        },
        {
            "name": "mvenv_create",
            "description": "Create and catalog a new sovereign managed virtual environment (mvenv).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Identifier for the new mvenv."},
                    "packages": {"type": "array", "items": {"type": "string"}, "description": "List of pip packages to install."},
                    "sovereign": {"type": "boolean", "description": "Whether to apply host isolation (default: true)."},
                    "base_python": {"type": "string", "description": "Optional path to base Python interpreter."}
                },
                "required": ["name"]
            }
        },
        {
            "name": "mvenv_install",
            "description": "Install additional pip packages into an existing managed virtual environment.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The target mvenv name."},
                    "packages": {"type": "array", "items": {"type": "string"}, "description": "List of packages to install."}
                },
                "required": ["name", "packages"]
            }
        },
        {
            "name": "mvenv_verify",
            "description": "Verify that an mvenv's Python executable and dependencies are functional.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The mvenv to verify."}
                },
                "required": ["name"]
            }
        },
        {
            "name": "mvenv_delete",
            "description": "Delete a managed virtual environment from disk and unregister it.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The mvenv to delete."}
                },
                "required": ["name"]
            }
        },
        {
            "name": "python_discover",
            "description": "Scan and discover all host Python runtimes (Registry, PATH, ArcGIS Pro, QGIS).",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    ]

    def __init__(self, manager: Optional[MvenvManager] = None):
        self.manager = manager or MvenvManager()

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "auraseed-mcp", "version": "0.2.0"}
                }
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self.TOOLS}
            }

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            try:
                res_content = self._execute_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(res_content, indent=2)}]
                    }
                }
            except Exception as ex:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error executing {tool_name}: {ex}"}],
                        "isError": True
                    }
                }

        if method == "notifications/initialized":
            return None

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Any:
        if name == "mvenv_list":
            records = self.manager.list_venvs()
            return [r.to_dict() for r in records]

        if name == "mvenv_info":
            rec = self.manager.get_venv(args["name"])
            if not rec:
                raise KeyError(f"Mvenv '{args['name']}' not found.")
            return rec.to_dict()

        if name == "mvenv_create":
            req = MvenvCreateRequest(
                name=args["name"],
                packages=args.get("packages"),
                sovereign=args.get("sovereign", True),
                base_python=args.get("base_python")
            )
            rec = self.manager.create_venv(req)
            return rec.to_dict()

        if name == "mvenv_install":
            rec = self.manager.install_packages(args["name"], args.get("packages", []))
            return rec.to_dict()

        if name == "mvenv_verify":
            return self.manager.verify_venv(args["name"])

        if name == "mvenv_delete":
            deleted = self.manager.delete_venv(args["name"])
            return {"success": deleted, "name": args["name"]}

        if name == "python_discover":
            best = self.manager._discover_best_interpreter()
            return {
                "selected_best": {
                    "id": best.id,
                    "name": best.name,
                    "executable": str(best.executable),
                    "version": best.version,
                    "source_type": best.source_type
                }
            }

        raise ValueError(f"Unknown tool: {name}")

    def run_stdio(self):
        """
        Runs the MCP server over standard input/output.
        """
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.handle_request(req)
                if resp:
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"}
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
