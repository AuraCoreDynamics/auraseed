"""
AuraSeed Model Context Protocol (MCP) Server.
Bridges MCP JSON-RPC 2.0 tool calls to the AuraSeed CLI (--json),
which orchestrates the AuraSeed Python API (MCP -> CLI -> Python).
Zero external runtime dependencies (Python standard library only).
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from auraseed import __version__
from auraseed.mvenv.manager import MvenvManager


SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)


class AuraSeedMcpServer:
    """
    Zero-dependency MCP server exposing AuraSeed discovery and mvenv management tools.
    Every tool delegates through the AuraSeed CLI (`--json`), ensuring single-source
    consistency with CLI automation and AI agent skills (MCP -> CLI -> Python).
    """

    def __init__(
        self,
        manager: Optional[MvenvManager] = None,
        python_executable: Optional[str] = None
    ) -> None:
        self.manager = manager
        self.default_root: Optional[str] = str(manager.root_path) if manager else None
        self.python_executable = python_executable or sys.executable
        self.repo_root = str(Path(__file__).resolve().parent.parent.parent)
        self._tools = self._build_tool_definitions()

    @staticmethod
    def _build_tool_definitions() -> List[Dict[str, Any]]:
        return [
            {
                "name": "discover_environments",
                "description": (
                    "Discover host base Python interpreters (system, registry, ArcGIS Pro, QGIS adapters) "
                    "and existing AuraSeed managed virtual environments (mvenvs) using the AuraSeed CLI."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "adapter": {
                            "type": "string",
                            "description": "Discovery adapter filter: all, windows_registry, linux_system, macos_system, arcpro, qgis.",
                            "default": "all"
                        },
                        "interpreters_only": {
                            "type": "boolean",
                            "description": "If true, only scan host base interpreters.",
                            "default": False
                        },
                        "mvenvs_only": {
                            "type": "boolean",
                            "description": "If true, only scan managed virtual environments.",
                            "default": False
                        },
                        "include_registry": {
                            "type": "boolean",
                            "description": "Whether to scan global AuraSeed OS registry manifests and default folders.",
                            "default": True
                        },
                        "root": {
                            "type": "string",
                            "description": "Optional custom mvenv catalog root directory."
                        }
                    }
                }
            },
            {
                "name": "list_mvenvs",
                "description": "List all cataloged managed virtual environments (mvenvs) in the active catalog root.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "root": {
                            "type": "string",
                            "description": "Optional custom mvenv catalog root directory."
                        }
                    }
                }
            },
            {
                "name": "get_mvenv_info",
                "description": "Get detailed metadata, interpreter path, disk size, and installed packages for an mvenv.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the mvenv."},
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "get_mvenv_activation",
                "description": "Get activation script paths, direct python/pip binaries, and shell activation commands for an mvenv.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name or path of the mvenv."},
                        "shell": {
                            "type": "string",
                            "enum": ["powershell", "cmd", "bash", "all"],
                            "default": "all",
                            "description": "Target shell hint."
                        },
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "create_mvenv",
                "description": (
                    "Create, sovereignly isolate, and catalog a new managed virtual environment (mvenv), "
                    "supporting base interpreter discovery by version spec or adapter and package installation."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name for the new mvenv."},
                        "base_python": {"type": "string", "description": "Explicit path to a base Python executable."},
                        "python_spec": {"type": "string", "description": "Version constraint for interpreter discovery (e.g. '>=3.11', '==3.12.*')."},
                        "adapter": {"type": "string", "default": "all", "description": "Discovery adapter to use when base_python is omitted."},
                        "packages": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Pip packages to install into the new mvenv."
                        },
                        "requirements_file": {"type": "string", "description": "Path to a requirements.txt file."},
                        "sovereign": {"type": "boolean", "default": True, "description": "Enable operational sovereignty host isolation."},
                        "force": {"type": "boolean", "default": False, "description": "Overwrite existing directory if present."},
                        "target_dir": {"type": "string", "description": "Explicit destination directory outside the default root."},
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "run_in_mvenv",
                "description": (
                    "Execute Python arguments (python_args) or an arbitrary command (command) inside a managed "
                    "virtual environment with VIRTUAL_ENV and PATH isolated to that environment."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name or path of the mvenv."},
                        "python_args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Arguments passed directly to the mvenv's Python executable (e.g. ['-c', 'print(1)'])."
                        },
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Full command argv list to run inside the mvenv (e.g. ['pytest', '-q'])."
                        },
                        "cwd": {"type": "string", "description": "Working directory for execution."},
                        "timeout": {"type": "integer", "default": 300, "description": "Execution timeout in seconds."},
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "install_mvenv_packages",
                "description": "Install additional pip packages or a requirements file into an existing mvenv.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the mvenv."},
                        "packages": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Package names or specifiers to install."
                        },
                        "requirements_file": {"type": "string", "description": "Path to requirements.txt."},
                        "upgrade": {"type": "boolean", "default": False, "description": "Pass --upgrade to pip."},
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "verify_mvenv",
                "description": "Verify the Python executable, version, and health of a managed virtual environment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name or path of the mvenv."},
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "merge_mvenvs",
                "description": "Merge multiple source mvenvs into a single target mvenv to consolidate dependencies and save disk space.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of source mvenv names to merge."
                        },
                        "target": {"type": "string", "description": "Target merged mvenv name."},
                        "delete_sources": {"type": "boolean", "default": False, "description": "Delete source mvenvs to reclaim disk space."},
                        "repoint_apps": {"type": "boolean", "default": True, "description": "Repoint installed apps bound to sources onto target."},
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["sources", "target"]
                }
            },
            {
                "name": "delete_mvenv",
                "description": "Delete a managed virtual environment from disk and remove it from the catalog.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the mvenv."},
                        "root": {"type": "string", "description": "Optional custom mvenv catalog root directory."}
                    },
                    "required": ["name"]
                }
            }
        ]

    def list_tools(self) -> List[Dict[str, Any]]:
        return list(self._tools)

    def _run_cli(self, cli_args: List[str], timeout: int = 300) -> Dict[str, Any]:
        cmd = [self.python_executable, "-m", "auraseed"] + cli_args
        env = os.environ.copy()
        existing_py = env.get("PYTHONPATH", "")
        if existing_py:
            parts = existing_py.split(os.pathsep)
            if self.repo_root not in parts:
                env["PYTHONPATH"] = self.repo_root + os.pathsep + existing_py
        else:
            env["PYTHONPATH"] = self.repo_root

        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        parsed_json: Optional[Any] = None
        stdout_stripped = (proc.stdout or "").strip()
        if stdout_stripped.startswith("{") or stdout_stripped.startswith("["):
            try:
                parsed_json = json.loads(stdout_stripped)
            except Exception:
                parsed_json = None

        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "json": parsed_json,
            "cli_command": cmd
        }

    def _effective_root(self, args: Dict[str, Any]) -> Optional[str]:
        return args.get("root") or self.default_root

    def _build_cli_args_for_tool(self, tool_name: str, args: Dict[str, Any]) -> tuple[List[str], int]:
        root = self._effective_root(args)
        timeout = int(args.get("timeout") or 300)

        if tool_name == "discover_environments":
            cli = ["discover", "--adapter", str(args.get("adapter") or "all")]
            if args.get("interpreters_only"):
                cli.append("--interpreters-only")
            if args.get("mvenvs_only"):
                cli.append("--mvenvs-only")
            if args.get("include_registry") is False:
                cli.append("--no-registry")
            if root:
                cli.extend(["--root", str(root)])
            cli.append("--json")
            return cli, timeout

        if tool_name == "list_mvenvs":
            cli = ["mvenv", "list", "--json"]
            if root:
                cli.extend(["--root", str(root)])
            return cli, timeout

        if tool_name == "get_mvenv_info":
            name = args.get("name")
            if not name:
                raise ValueError("Missing required argument 'name'.")
            cli = ["mvenv", "info", str(name), "--json"]
            if root:
                cli.extend(["--root", str(root)])
            return cli, timeout

        if tool_name == "get_mvenv_activation":
            name = args.get("name")
            if not name:
                raise ValueError("Missing required argument 'name'.")
            cli = ["mvenv", "activate", str(name), "--shell", str(args.get("shell") or "all"), "--json"]
            if root:
                cli.extend(["--root", str(root)])
            return cli, timeout

        if tool_name == "create_mvenv":
            name = args.get("name")
            if not name:
                raise ValueError("Missing required argument 'name'.")
            cli = ["mvenv", "create", str(name), "--json"]
            if args.get("base_python"):
                cli.extend(["--base", str(args["base_python"])])
            if args.get("python_spec"):
                cli.extend(["--spec", str(args["python_spec"])])
            if args.get("adapter"):
                cli.extend(["--adapter", str(args["adapter"])])
            packages = args.get("packages") or []
            if packages:
                cli.append("--packages")
                cli.extend([str(p) for p in packages])
            if args.get("requirements_file"):
                cli.extend(["-r", str(args["requirements_file"])])
            if args.get("sovereign") is False:
                cli.append("--no-sovereign")
            if args.get("force"):
                cli.append("--force")
            if args.get("target_dir"):
                cli.extend(["--dest", str(args["target_dir"])])
            if root:
                cli.extend(["--root", str(root)])
            return cli, timeout

        if tool_name == "run_in_mvenv":
            name = args.get("name")
            if not name:
                raise ValueError("Missing required argument 'name'.")
            python_args = args.get("python_args")
            command = args.get("command")
            if python_args is not None and command is not None:
                raise ValueError("Provide either 'python_args' or 'command', not both.")
            if python_args is None and command is None:
                raise ValueError("Provide either 'python_args' or 'command'.")

            subcmd = "python" if python_args is not None else "run"
            exec_list = python_args if python_args is not None else command
            if not exec_list:
                raise ValueError("Command argument list must not be empty.")

            cli = ["mvenv", subcmd, str(name), "--json"]
            if args.get("cwd"):
                cli.extend(["--cwd", str(args["cwd"])])
            if args.get("timeout"):
                cli.extend(["--timeout", str(int(args["timeout"]))])
            if root:
                cli.extend(["--root", str(root)])
            cli.append("--")
            cli.extend([str(x) for x in exec_list])
            return cli, max(timeout + 15, 30)

        if tool_name == "install_mvenv_packages":
            name = args.get("name")
            if not name:
                raise ValueError("Missing required argument 'name'.")
            cli = ["mvenv", "install", str(name)]
            packages = args.get("packages") or []
            cli.extend([str(p) for p in packages])
            if args.get("requirements_file"):
                cli.extend(["-r", str(args["requirements_file"])])
            if args.get("upgrade"):
                cli.append("--upgrade")
            if root:
                cli.extend(["--root", str(root)])
            cli.append("--json")
            return cli, timeout

        if tool_name == "verify_mvenv":
            name = args.get("name")
            if not name:
                raise ValueError("Missing required argument 'name'.")
            cli = ["mvenv", "verify", str(name), "--json"]
            if root:
                cli.extend(["--root", str(root)])
            return cli, timeout

        if tool_name == "merge_mvenvs":
            sources = args.get("sources") or []
            target = args.get("target")
            if not sources or not target:
                raise ValueError("Both 'sources' and 'target' are required.")
            cli = ["mvenv", "merge"] + [str(s) for s in sources] + ["--target", str(target), "--json"]
            if args.get("delete_sources"):
                cli.append("--delete-sources")
            if args.get("repoint_apps") is False:
                cli.append("--no-repoint")
            if root:
                cli.extend(["--root", str(root)])
            return cli, timeout

        if tool_name == "delete_mvenv":
            name = args.get("name")
            if not name:
                raise ValueError("Missing required argument 'name'.")
            cli = ["mvenv", "delete", str(name), "--json"]
            if root:
                cli.extend(["--root", str(root)])
            return cli, timeout

        raise KeyError(f"Unknown MCP tool: {tool_name}")

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        args = dict(arguments or {})
        try:
            cli_args, timeout = self._build_cli_args_for_tool(tool_name, args)
        except KeyError as e:
            return {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True
            }
        except ValueError as e:
            return {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True
            }

        try:
            res = self._run_cli(cli_args, timeout=timeout)
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"CLI execution error: {e}"}],
                "isError": True
            }

        if res["json"] is not None:
            text_out = json.dumps(res["json"], indent=2)
        else:
            text_out = (res["stderr"] or res["stdout"] or f"Command exited with code {res['returncode']}").strip()

        return {
            "content": [{"type": "text", "text": text_out}],
            "isError": res["returncode"] != 0
        }

    def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Dispatches a single MCP JSON-RPC 2.0 request or notification.
        Returns None for notifications (messages without an 'id').
        """
        if not isinstance(message, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request: expected JSON object"}
            }

        has_id = "id" in message and message["id"] is not None
        req_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if not isinstance(method, str) or not method:
            if not has_id:
                return None
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: missing method"}
            }

        # Notifications (no id) produce no JSON-RPC response
        if method.startswith("notifications/") or not has_id:
            return None

        if method == "initialize":
            client_version = params.get("protocolVersion") if isinstance(params, dict) else None
            negotiated = client_version if client_version in SUPPORTED_PROTOCOL_VERSIONS else "2024-11-05"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": negotiated,
                    "capabilities": {
                        "tools": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": "auraseed",
                        "version": __version__
                    }
                }
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.list_tools()}
            }

        if method == "tools/call":
            if not isinstance(params, dict) or not params.get("name"):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: 'name' is required"}
                }
            result = self.call_tool(str(params["name"]), params.get("arguments"))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }

    def run_stdio(
        self,
        stdin: Optional[TextIO] = None,
        stdout: Optional[TextIO] = None
    ) -> None:
        """
        Runs the MCP stdio transport loop (newline-delimited JSON-RPC 2.0).
        All protocol frames go to stdout; stdout is never polluted with non-JSON logs.
        """
        in_stream = stdin or sys.stdin
        out_stream = stdout or sys.stdout

        while True:
            raw_line = in_stream.readline()
            if not raw_line:
                break
            line = raw_line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"}
                }
                out_stream.write(json.dumps(err_resp) + "\n")
                out_stream.flush()
                continue

            if isinstance(msg, list):
                responses = []
                for item in msg:
                    r = self.handle_message(item)
                    if r is not None:
                        responses.append(r)
                if responses:
                    out_stream.write(json.dumps(responses) + "\n")
                    out_stream.flush()
            else:
                resp = self.handle_message(msg)
                if resp is not None:
                    out_stream.write(json.dumps(resp) + "\n")
                    out_stream.flush()
