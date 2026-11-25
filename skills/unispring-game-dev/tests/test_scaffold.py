"""install.py + new-module.py produce a project that passes every check."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
INSTALL = BASE.parents[1] / "install.py"   # present in the skill repository, not in a game
SCRIPTS = BASE / "scripts"
CHECKS = ["check-asset-layout.py", "check-code-architecture.py",
          "check-subsystem-boundaries.py", "check-localization.py"]


def run(*args, cwd=None):
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True)


@unittest.skipUnless(INSTALL.is_file(), "install.py lives in the skill repository")
class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "Assets").mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def install(self, *extra):
        proc = run(INSTALL, "--project", self.root, "--game", "Test Game", "--prefix", "TG",
                   "--namespace", "TestGame", *extra)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def test_new_title_with_a_module_is_clean(self):
        self.install("--with-bootstrap", "--with-lease")
        scripts = self.root / ".claude/skills/unispring-game-dev/scripts"
        proc = run(scripts / "new-module.py", "--root", self.root, "--name", "Garage", "--presentation")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        src = self.root / "Assets/Src"
        for entry in [src, *src.rglob("*")]:  # Unity would create these on import
            entry.with_name(entry.name + ".meta").write_text("fileFormatVersion: 2")
        for check in CHECKS:
            result = run(scripts / check, "--root", self.root)
            self.assertEqual(result.returncode, 0, check + "\n" + result.stdout + result.stderr)
        self.assertIn("TG.Garage.Runtime", (src / "link.xml").read_text())
        for path in [self.root / "CLAUDE.md", *src.rglob("*.cs"), *src.rglob("*.asmdef")]:
            self.assertNotIn("{{", path.read_text(), path)

    def test_reinstall_keeps_files_and_does_not_duplicate_hooks(self):
        self.install()
        (self.root / "CLAUDE.md").write_text("mine")
        out = self.install()
        self.assertIn("+0 hook(s)", out)
        self.assertEqual((self.root / "CLAUDE.md").read_text(), "mine")
        hooks = json.loads((self.root / ".claude/settings.json").read_text())["hooks"]
        self.assertEqual({k: len(v) for k, v in hooks.items()},
                         {"SessionStart": 1, "PostToolUse": 1, "Stop": 1})

    def test_all_agents_get_the_skill_their_hooks_and_the_shared_rules(self):
        out = self.install("--agent", "all", "--git-hook", "--ci", "gitlab")
        for rel in (".claude/skills", ".agents/skills", ".github/skills"):
            self.assertTrue((self.root / rel / "unispring-game-dev/SKILL.md").is_file(), rel)
        for rel in ("AGENTS.md", "CLAUDE.md", ".claude/agents/reviewer.md", ".claude/settings.json",
                    ".codex/hooks.json", ".cursor/hooks.json", ".github/hooks/unispring-gate.json",
                    ".gitlab/unispring-gate.yml", ".gitlab-ci.yml", ".git/hooks/pre-commit",
                    ".opencode/plugins/unispring-gate.js"):
            path = self.root / rel
            self.assertTrue(path.is_file(), rel)
            self.assertNotIn("{{", path.read_text(), rel)
        self.assertTrue((self.root / "CLAUDE.md").read_text().startswith("@AGENTS.md"))
        self.assertIn(".unispring-cache/", (self.root / ".gitignore").read_text())
        self.assertIn("/hooks", out)  # the Codex trust note
        codex = (self.root / ".codex/hooks.json").read_text()
        self.assertIn(".agents/skills/unispring-game-dev/scripts/hooks/agent_hook.py\\\" codex stop", codex)
        copilot = (self.root / ".github/hooks/unispring-gate.json").read_text()
        self.assertIn(".github/skills/unispring-game-dev/scripts/hooks/agent_hook.py", copilot)
        again = self.install("--agent", "all")
        self.assertEqual(again.count("+0 hook(s)"), 3, again)  # claude, codex, cursor merged without duplicates

    def test_opencode_gets_the_skill_rules_and_its_plugin_only(self):
        out = self.install("--agent", "opencode")
        self.assertTrue((self.root / ".agents/skills/unispring-game-dev/SKILL.md").is_file())
        self.assertTrue((self.root / "AGENTS.md").is_file())
        plugin = (self.root / ".opencode/plugins/unispring-gate.js").read_text()
        self.assertIn('".agents/skills/unispring-game-dev/scripts/hooks/agent_hook.py"', plugin)
        self.assertNotIn("{{", plugin)
        for rel in (".claude/settings.json", ".codex/hooks.json", ".cursor/hooks.json", ".github/hooks", "CLAUDE.md"):
            self.assertFalse((self.root / rel).exists(), rel)
        self.assertIn("OpenCode 2.x", out)

    def test_localization_is_off_until_the_project_has_a_language_table(self):
        out = self.install()
        config = json.loads((self.root / "unispring-skill.json").read_text())
        self.assertFalse(config["localization"]["enabled"])
        self.assertIn("localization checks are off", out)
        gate = run(self.root / ".claude/skills/unispring-game-dev/scripts/gate.py", "check", "--root", self.root)
        self.assertNotIn("TABLE", gate.stdout)

        (self.root / "unispring-skill.json").unlink()
        self.install("--with-bootstrap")
        config = json.loads((self.root / "unispring-skill.json").read_text())
        self.assertTrue(config["localization"]["enabled"])
        self.assertTrue((self.root / "Assets/Src/Resources/Localization/en.json").is_file())

    def test_existing_agent_hooks_are_kept(self):
        (self.root / ".cursor").mkdir()
        (self.root / ".cursor/hooks.json").write_text(
            json.dumps({"version": 1, "hooks": {"afterFileEdit": [{"command": "./format.sh"}]}}))
        self.install("--agent", "cursor")
        hooks = json.loads((self.root / ".cursor/hooks.json").read_text())["hooks"]
        self.assertEqual(len(hooks["afterFileEdit"]), 2)
        self.assertEqual(hooks["afterFileEdit"][0]["command"], "./format.sh")
        self.assertIn("stop", hooks)

    def test_update_refreshes_every_installed_copy(self):
        self.install("--agent", "claude,copilot")
        marker = self.root / ".github/skills/unispring-game-dev/stale.txt"
        marker.write_text("old")
        proc = run(INSTALL, "--project", self.root, "--update")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(proc.stdout.count("copied"), 2)

    def test_existing_module_is_not_overwritten(self):
        self.install()
        scripts = self.root / ".claude/skills/unispring-game-dev/scripts"
        self.assertEqual(run(scripts / "new-module.py", "--root", self.root, "--name", "Shop").returncode, 0)
        self.assertEqual(run(scripts / "new-module.py", "--root", self.root, "--name", "Shop").returncode, 1)
        self.assertEqual(run(scripts / "new-module.py", "--root", self.root, "--name", "shop").returncode, 2)


if __name__ == "__main__":
    unittest.main()
