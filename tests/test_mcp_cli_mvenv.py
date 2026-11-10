"""
Tests for AuraSeed Python API, CLI, MCP Server (MCP -> CLI -> Python),
Streamable HTTP /mcp endpoint, and workspace skill artifacts.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from auraseed.api.mcp import AuraSeedMcpServer
from auraseed.api.server import create_api_server
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestMvenvPythonCliMcp(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="auraseed_mcp_cli_test_"))
        self.mvenv_root = self.temp_dir / "mvenvs"
        self.mvenv_root.mkdir(parents=True, exist_ok=True)
        self.manager = MvenvManager(self.mvenv_root)
        self.sub_env = os.environ.copy()
        self.sub_env["PYTHONPATH"] = str(REPO_ROOT)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_cli(self, *args: str, timeout: int = 90):
        cmd = [sys.executable, "-m", "auraseed", *args]
        return subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=self.sub_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # 1. Python API tests
    # ------------------------------------------------------------------
    def test_python_api_discover_create_spec_custom_dest_and_run(self):
        interpreters = self.manager.discover_interpreters(adapter="all")
        self.assertTrue(len(interpreters) >= 1)
        self.assertTrue(any(Path(e.executable).exists() for e in interpreters))

        # Impossible version spec raises ValueError
        with self.assertRaises(ValueError):
            self.manager.create_venv(
                MvenvCreateRequest(
                    name="impossible-spec",
                    python_spec="==99.99.*",
                    sovereign=False,
                )
            )

        # Custom target_dir outside root_path should be indexed in catalog
        custom_dest = self.temp_dir / "custom_dest_env"
        req = MvenvCreateRequest(
            name="custom-env",
            base_python=sys.executable,
            sovereign=False,
            force=True,
            target_dir=str(custom_dest),
        )
        rec = self.manager.create_venv(req)
        self.assertEqual(Path(rec.path).resolve(), custom_dest.resolve())

        fetched = self.manager.get_venv("custom-env")
        self.assertIsNotNone(fetched)
        self.assertEqual(Path(fetched.path).resolve(), custom_dest.resolve())
        self.assertIn("custom-env", [v.name for v in self.manager.list_venvs()])

        # Activation info and execution isolation
        act = self.manager.get_activation_info("custom-env")
        self.assertEqual(act["name"], "custom-env")
        self.assertTrue(Path(act["python_path"]).exists())
        self.assertIsNotNone(act["launcher"])
        self.assertTrue(Path(act["launcher"]).exists())

        res_py = self.manager.run_in_venv(
            "custom-env",
            python_args=["-c", "import os, sys; print(os.environ.get('VIRTUAL_ENV', '')); print(sys.prefix)"],
        )
        self.assertEqual(res_py["returncode"], 0, res_py["stderr"])
        lines = [ln.strip() for ln in res_py["stdout"].splitlines() if ln.strip()]
        self.assertEqual(Path(lines[0]).resolve(), custom_dest.resolve())
        self.assertEqual(Path(lines[1]).resolve(), custom_dest.resolve())

        res_cmd = self.manager.run_in_venv(
            "custom-env",
            command=["python", "-c", "print('CMD_OK')"],
        )
        self.assertEqual(res_cmd["returncode"], 0)
        self.assertEqual(res_cmd["stdout"].strip(), "CMD_OK")

        # Delete custom-dest env cleanly removes disk dir and catalog entry
        self.assertTrue(self.manager.delete_venv("custom-env"))
        self.assertFalse(custom_dest.exists())
        self.assertIsNone(self.manager.get_venv("custom-env"))

    # ------------------------------------------------------------------
    # 2. CLI layer tests
    # ------------------------------------------------------------------
    def test_cli_discover_create_activate_run_delete_json(self):
        # Discover CLI (global and mvenv subcommand)
        proc_disc = self._run_cli("discover", "--no-registry", "--root", str(self.mvenv_root), "--json")
        self.assertEqual(proc_disc.returncode, 0, proc_disc.stderr)
        disc_data = json.loads(proc_disc.stdout)
        self.assertIn("interpreters", disc_data)
        self.assertIn("mvenvs", disc_data)
        self.assertGreaterEqual(len(disc_data["interpreters"]), 1)

        proc_m_disc = self._run_cli("mvenv", "discover", "--no-registry", "--root", str(self.mvenv_root), "--json")
        self.assertEqual(proc_m_disc.returncode, 0, proc_m_disc.stderr)
        m_disc_data = json.loads(proc_m_disc.stdout)
        self.assertEqual(Path(m_disc_data["root_path"]).resolve(), self.mvenv_root.resolve())

        # Create using --spec without explicit --base
        major_minor = f">={sys.version_info.major}.{sys.version_info.minor}"
        proc_create = self._run_cli(
            "mvenv", "create", "cli-env",
            "--spec", major_minor,
            "--no-sovereign",
            "--root", str(self.mvenv_root),
            "--json",
        )
        self.assertEqual(proc_create.returncode, 0, proc_create.stderr)
        created = json.loads(proc_create.stdout)
        self.assertEqual(created["name"], "cli-env")
        self.assertTrue(Path(created["python_path"]).exists())

        # Activate info
        proc_act = self._run_cli("mvenv", "activate", "cli-env", "--root", str(self.mvenv_root), "--json")
        self.assertEqual(proc_act.returncode, 0, proc_act.stderr)
        act = json.loads(proc_act.stdout)
        self.assertIn("commands", act)
        self.assertIn("direct_python", act["commands"])

        # Run python via `mvenv python` (both after -- and natural flag ordering)
        proc_py = self._run_cli(
            "mvenv", "python", "cli-env",
            "--root", str(self.mvenv_root),
            "--json",
            "--", "-c", "import os; print(os.environ.get('VIRTUAL_ENV', ''))",
        )
        self.assertEqual(proc_py.returncode, 0, proc_py.stderr)
        py_res = json.loads(proc_py.stdout)
        self.assertEqual(py_res["returncode"], 0)
        self.assertEqual(Path(py_res["stdout"].strip()).resolve(), Path(created["path"]).resolve())

        # Run command via `mvenv run`
        proc_run = self._run_cli(
            "mvenv", "run", "cli-env",
            "--root", str(self.mvenv_root),
            "--json",
            "--", "python", "-c", "print('RUN_OK')",
        )
        self.assertEqual(proc_run.returncode, 0, proc_run.stderr)
        run_res = json.loads(proc_run.stdout)
        self.assertEqual(run_res["stdout"].strip(), "RUN_OK")

        # Delete with --json
        proc_del = self._run_cli("mvenv", "delete", "cli-env", "--root", str(self.mvenv_root), "--json")
        self.assertEqual(proc_del.returncode, 0, proc_del.stderr)
        del_res = json.loads(proc_del.stdout)
        self.assertTrue(del_res["success"])

    # ------------------------------------------------------------------
    # 3. MCP -> CLI -> Python tests (unit stdio, live subprocess, HTTP)
    # ------------------------------------------------------------------
    def test_mcp_stdio_unit_and_cli_delegation(self):
        srv = AuraSeedMcpServer(self.manager)

        # Verify notifications emit NO response and requests adhere to JSON-RPC 2.0
        stdin_buf = io.StringIO(
            "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}),
                json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                    "name": "discover_environments",
                    "arguments": {"include_registry": False}
                }}),
            ]) + "\n"
        )
        stdout_buf = io.StringIO()

        # Spy on _run_cli to verify MCP explicitly delegates through CLI
        original_run_cli = srv._run_cli
        called_clis = []

        def spy_run_cli(cli_args, timeout=300):
            called_clis.append(list(cli_args))
            return original_run_cli(cli_args, timeout=timeout)

        with mock.patch.object(srv, "_run_cli", side_effect=spy_run_cli):
            srv.run_stdio(stdin=stdin_buf, stdout=stdout_buf)

        responses = [json.loads(line) for line in stdout_buf.getvalue().splitlines() if line.strip()]
        # Notification produced no output -> 4 responses for ids 1, 2, 3, 4
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4])
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2024-11-05")
        tool_names = {t["name"] for t in responses[2]["result"]["tools"]}
        self.assertIn("discover_environments", tool_names)
        self.assertIn("create_mvenv", tool_names)
        self.assertIn("run_in_mvenv", tool_names)
        self.assertIn("get_mvenv_activation", tool_names)
        self.assertEqual(called_clis[0][0], "discover")
        self.assertFalse(responses[3]["result"]["isError"])
        disc_payload = json.loads(responses[3]["result"]["content"][0]["text"])
        self.assertGreaterEqual(len(disc_payload["interpreters"]), 1)

    def test_mcp_live_serve_subprocess_lifecycle(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "create_mvenv",
                "arguments": {
                    "name": "mcp-live-env",
                    "base_python": sys.executable,
                    "sovereign": False
                }
            }},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "verify_mvenv",
                "arguments": {"name": "mcp-live-env"}
            }},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "run_in_mvenv",
                "arguments": {
                    "name": "mcp-live-env",
                    "python_args": ["-c", "import os; print('MCP_OK:' + os.environ.get('VIRTUAL_ENV', ''))"]
                }
            }},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                "name": "delete_mvenv",
                "arguments": {"name": "mcp-live-env"}
            }},
        ]
        stdin_payload = "\n".join(json.dumps(r) for r in requests) + "\n"

        proc = subprocess.run(
            [sys.executable, "-m", "auraseed", "serve", "--mcp", "--root", str(self.mvenv_root)],
            cwd=str(REPO_ROOT),
            env=self.sub_env,
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, f"serve --mcp failed: {proc.stderr}")

        out_lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(out_lines), 5, f"Unexpected stdout lines: {proc.stdout}")
        frames = [json.loads(line) for line in out_lines]

        # id=1 initialize
        self.assertEqual(frames[0]["result"]["protocolVersion"], "2025-03-26")

        # id=2 create_mvenv
        self.assertFalse(frames[1]["result"]["isError"], frames[1])
        created = json.loads(frames[1]["result"]["content"][0]["text"])
        self.assertEqual(created["name"], "mcp-live-env")

        # id=3 verify_mvenv
        self.assertFalse(frames[2]["result"]["isError"], frames[2])
        verified = json.loads(frames[2]["result"]["content"][0]["text"])
        self.assertTrue(verified["valid"])

        # id=4 run_in_mvenv
        self.assertFalse(frames[3]["result"]["isError"], frames[3])
        run_res = json.loads(frames[3]["result"]["content"][0]["text"])
        self.assertEqual(run_res["returncode"], 0)
        self.assertIn("MCP_OK:", run_res["stdout"])

        # id=5 delete_mvenv
        self.assertFalse(frames[4]["result"]["isError"], frames[4])
        del_res = json.loads(frames[4]["result"]["content"][0]["text"])
        self.assertTrue(del_res["success"])

    def test_http_streamable_mcp_endpoint_and_openapi(self):
        server = create_api_server(host="127.0.0.1", port=0, manager=self.manager)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            def post_mcp(payload):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/mcp",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8")
                    return resp.status, (json.loads(body) if body.strip() else None)

            st_init, init_resp = post_mcp({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            })
            self.assertEqual(st_init, 200)
            self.assertEqual(init_resp["result"]["serverInfo"]["name"], "auraseed")

            st_notif, notif_resp = post_mcp({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            })
            self.assertEqual(st_notif, 202)
            self.assertIsNone(notif_resp)

            st_list, list_resp = post_mcp({
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "list_mvenvs", "arguments": {}},
            })
            self.assertEqual(st_list, 200)
            self.assertFalse(list_resp["result"]["isError"])
            self.assertEqual(json.loads(list_resp["result"]["content"][0]["text"]), [])

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/openapi.json", timeout=10) as spec_resp:
                spec = json.loads(spec_resp.read().decode("utf-8"))
                self.assertIn("/mcp", spec.get("paths", {}))
        finally:
            server.shutdown()
            server.server_close()

    # ------------------------------------------------------------------
    # 4. Skill artifact checks
    # ------------------------------------------------------------------
    def test_skill_artifacts_exist_and_are_valid(self):
        skills_cfg = REPO_ROOT / ".agents" / "skills.json"
        self.assertTrue(skills_cfg.exists(), ".agents/skills.json must exist")
        cfg_data = json.loads(skills_cfg.read_text(encoding="utf-8"))
        self.assertIn("skills", [e.get("path") for e in cfg_data.get("entries", [])])

        skill_dir = REPO_ROOT / "skills" / "auraseed-mvenv"
        skill_md = skill_dir / "SKILL.md"
        ref_md = skill_dir / "references" / "cli-and-mcp-reference.md"
        self.assertTrue(skill_md.exists())
        self.assertTrue(ref_md.exists())

        content = skill_md.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---"))
        self.assertIn("name: auraseed-mvenv", content)
        self.assertIn("description:", content)
        self.assertIn("mvenv discover", content)
        self.assertIn("mvenv create", content)
        self.assertIn("mvenv run", content)
        self.assertIn("mvenv python", content)
        self.assertIn("./references/cli-and-mcp-reference.md", content)


if __name__ == "__main__":
    unittest.main()
