"""gate.py, the per-agent hook adapter and the git pre-commit hook."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
GATE = BASE / "scripts" / "gate.py"
HOOK = BASE / "scripts" / "hooks" / "agent_hook.py"
PRE_COMMIT = BASE / "templates" / "git-hooks" / "pre-commit"
SERVICE = "Assets/Src/Scripts/Garage/Internal/Service/GarageService.cs"
CLEAN = "namespace G.Garage.Service\n{\n    [Service] internal sealed class GarageService\n    {\n        int F(int x) { if (x > 0) return 1; return 2; }\n    }\n}\n"
DIRTY = CLEAN.replace("return 1; return 2;", "return 1; else return 2;")


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CURSOR_", "CLAUDE_", "UNISPRING_"))}
    env.update(extra)
    return env


class Project(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for rel, text in {
            SERVICE: CLEAN,
            "Assets/Src/Scripts/Garage/Api/IGarageApi.cs": "namespace G.Garage.Api { public interface IGarageApi {} }",
            "Assets/Src/Scripts/Garage/Api/G.Garage.Api.asmdef": '{"name":"G.Garage.Api","references":[]}',
            "Assets/Src/Scripts/Garage/Internal/G.Garage.Runtime.asmdef": '{"name":"G.Garage.Runtime","references":["G.Garage.Api"]}',
            "Assets/Src/Resources/Localization/en.json": "{}",
        }.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        src = self.root / "Assets/Src"
        for entry in [src, *src.rglob("*")]:
            entry.with_name(entry.name + ".meta").write_text("fileFormatVersion: 2")
        (self.root / ".gitignore").write_text(".unispring-cache/\n")
        self.git("init", "-q")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=check)

    def dirty(self):
        (self.root / SERVICE).write_text(DIRTY, encoding="utf-8")

    def gate(self, mode):
        return subprocess.run([sys.executable, str(GATE), mode, "--root", str(self.root)],
                              capture_output=True, text=True, env=clean_env())

    def hook(self, agent, event, payload, **env):
        return subprocess.run([sys.executable, str(HOOK), agent, event], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=self.root, env=clean_env(**env))


class GateTests(Project):
    def test_clean_project_passes_and_new_violation_fails(self):
        self.assertEqual(self.gate("check").returncode, 0, self.gate("check").stdout)
        self.dirty()
        result = self.gate("check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("BRANCH", result.stdout)

    def test_baseline_accepts_legacy_and_reports_fixed_entries(self):
        self.dirty()
        self.assertEqual(self.gate("baseline").returncode, 0)
        self.assertTrue((self.root / "unispring-baseline.json").is_file())
        self.assertEqual(self.gate("check").returncode, 0)
        (self.root / SERVICE).write_text(CLEAN, encoding="utf-8")
        result = self.gate("check")
        self.assertEqual(result.returncode, 0)
        self.assertIn("fixed", result.stdout)

    def test_direct_log_is_a_violation(self):
        (self.root / SERVICE).write_text(CLEAN.replace("return 2;", 'UnityEngine.Debug.Log("x"); return 2;'))
        self.assertIn("LOG:", self.gate("check").stdout)


class AgentHookTests(Project):
    def edit_payload_claude(self):
        return {"session_id": "s", "cwd": str(self.root), "hook_event_name": "PostToolUse",
                "tool_name": "Edit", "tool_input": {"file_path": str(self.root / SERVICE)}}

    def test_claude_blocks_with_exit_2_and_stops_after_one_retry(self):
        env = {"CLAUDE_PROJECT_DIR": str(self.root)}
        self.assertEqual(self.hook("claude", "start", {"cwd": str(self.root)}, **env).returncode, 0)
        self.dirty()
        edit = self.hook("claude", "edit", self.edit_payload_claude(), **env)
        self.assertEqual(edit.returncode, 2)
        self.assertIn("switch/else count grew", edit.stderr)
        stop = self.hook("claude", "stop", {"cwd": str(self.root)}, **env)
        self.assertEqual(stop.returncode, 2)
        self.assertIn("NEW violations", stop.stderr)
        again = self.hook("claude", "stop", {"cwd": str(self.root), "stop_hook_active": True}, **env)
        self.assertEqual(again.returncode, 0)
        self.assertIn("systemMessage", again.stdout)

    def test_codex_reads_apply_patch_and_answers_with_decision_json(self):
        self.hook("codex", "start", {"cwd": str(self.root), "turn_id": "t"})
        self.dirty()
        patch = f"*** Begin Patch\n*** Update File: {SERVICE}\n@@\n-x\n+y\n*** End Patch"
        edit = self.hook("codex", "edit", {"cwd": str(self.root), "turn_id": "t", "tool_name": "apply_patch",
                                           "tool_input": {"command": patch}})
        self.assertEqual(edit.returncode, 0)
        self.assertEqual(json.loads(edit.stdout)["decision"], "block")
        stop = self.hook("codex", "stop", {"cwd": str(self.root), "turn_id": "t", "stop_hook_active": False})
        self.assertEqual(json.loads(stop.stdout)["decision"], "block")
        (self.root / SERVICE).write_text(CLEAN)
        clean = self.hook("codex", "stop", {"cwd": str(self.root), "turn_id": "t"})
        self.assertEqual(json.loads(clean.stdout), {})

    def test_cursor_answers_at_stop_with_a_followup_once(self):
        env = {"CURSOR_PROJECT_DIR": str(self.root), "CURSOR_VERSION": "1"}
        self.hook("cursor", "start", {"session_id": "s"}, **env)
        self.dirty()
        edit = self.hook("cursor", "edit", {"file_path": str(self.root / SERVICE), "edits": []}, **env)
        self.assertEqual((edit.returncode, edit.stdout), (0, ""))
        stop = self.hook("cursor", "stop", {"status": "completed", "loop_count": 0}, **env)
        self.assertIn("followup_message", json.loads(stop.stdout))
        again = self.hook("cursor", "stop", {"status": "completed", "loop_count": 1}, **env)
        self.assertEqual(json.loads(again.stdout), {})

    def test_copilot_reads_tool_args_string_and_blocks_agent_stop(self):
        base = {"sessionId": "s", "timestamp": 1, "cwd": str(self.root)}
        self.hook("copilot", "start", base)
        self.dirty()
        edit = self.hook("copilot", "edit", {**base, "toolName": "edit",
                                             "toolArgs": json.dumps({"path": SERVICE})})
        self.assertIn("additionalContext", json.loads(edit.stdout))
        stop = self.hook("copilot", "stop", {**base, "stopReason": "end_turn", "stop_hook_active": False})
        self.assertEqual(json.loads(stop.stdout)["decision"], "block")
        again = self.hook("copilot", "stop", {**base, "stop_hook_active": True})
        self.assertEqual(json.loads(again.stdout)["decision"], "allow")

    def test_opencode_gets_plain_text_and_nothing_after_one_retry(self):
        base = {"cwd": str(self.root)}
        self.hook("opencode", "start", base)
        self.dirty()
        edit = self.hook("opencode", "edit", {**base, "tool_name": "edit",
                                              "tool_input": {"path": SERVICE, "oldString": "a", "newString": "b"}})
        self.assertEqual(edit.returncode, 0)
        self.assertIn("switch/else count grew", edit.stdout)
        stop = self.hook("opencode", "stop", {**base, "stop_hook_active": False})
        self.assertIn("NEW violations", stop.stdout)
        again = self.hook("opencode", "stop", {**base, "stop_hook_active": True})
        self.assertEqual(again.stdout, "")
        (self.root / SERVICE).write_text(CLEAN)
        self.assertEqual(self.hook("opencode", "stop", base).stdout, "")

    @unittest.skipIf(shutil.which("bun") is None, "needs bun (OpenCode's runtime)")
    def test_opencode_plugin_end_to_end_under_bun(self):
        skill = self.root / ".agents/skills/unispring-game-dev"
        shutil.copytree(BASE, skill, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        template = (BASE / "templates/hooks/opencode-plugin.js").read_text()
        plugin = self.root / ".opencode/plugins/unispring-gate.js"
        plugin.parent.mkdir(parents=True)
        plugin.write_text(template.replace("{{SKILL_DIR}}", ".agents/skills/unispring-game-dev"))
        stub = self.root / "node_modules/@opencode/plugin"
        stub.mkdir(parents=True)
        (stub / "package.json").write_text('{"name":"@opencode/plugin","type":"module","main":"index.js"}')
        (stub / "index.js").write_text("export const Plugin = { define: (p) => p }\n")
        run = subprocess.run(["bun", str(BASE / "tests/opencode_harness.js"), str(plugin), str(self.root)],
                             capture_output=True, text=True, timeout=180,
                             env=clean_env(EDITED_PATH=SERVICE, DIRTY_TEXT=DIRTY))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertTrue(result["baseline"], result)
        self.assertEqual(result["editContent"][0], "Edited (1 replacement)")
        self.assertIn("switch/else count grew", result["editContent"][1])
        # one continuation for the first turn, none after its retry or from another project,
        # and one again after the user's next message
        self.assertEqual(len(result["messages"]), 2, result)
        self.assertIn("NEW violations", result["messages"][0])

    def test_a_host_running_claude_hooks_is_skipped_when_its_own_config_exists(self):
        (self.root / ".github/hooks").mkdir(parents=True)
        (self.root / ".github/hooks/unispring-gate.json").write_text("{}")
        self.dirty()
        stop = self.hook("claude", "stop", {"session_id": "s", "timestamp": "2026-01-01T00:00:00Z",
                                            "cwd": str(self.root), "hook_event_name": "Stop"})
        self.assertEqual(stop.returncode, 0)
        self.assertEqual(json.loads(stop.stdout), {"decision": "allow"})


@unittest.skipIf(shutil.which("sh") is None, "needs a POSIX shell")
class PreCommitTests(Project):
    def test_commit_with_a_new_violation_is_rejected(self):
        skill = self.root / ".agents/skills/unispring-game-dev"
        shutil.copytree(BASE, skill, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        hook = self.root / ".git/hooks/pre-commit"
        shutil.copy(PRE_COMMIT, hook)
        hook.chmod(0o755)
        self.git("add", ".")
        self.assertEqual(self.git("commit", "-qm", "skill", check=False).returncode, 0)
        self.dirty()
        self.git("add", ".")
        rejected = self.git("commit", "-qm", "bad", check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("gate: FAILED", rejected.stdout + rejected.stderr)


if __name__ == "__main__":
    unittest.main()
