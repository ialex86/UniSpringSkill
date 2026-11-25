#!/usr/bin/env python3
"""Install or update the unispring-game-dev skill in a Unity project, for any agent.

  python3 install.py --project ../MyGame --game "My Game" --prefix MG --namespace MyGame
  python3 install.py --project ../MyGame ... --agent all --git-hook --ci gitlab --baseline
  python3 install.py --project ../MyGame ... --with-bootstrap --with-lease   # a new title
  python3 install.py --project ../MyGame --update      # refresh every installed copy of the skill

--agent (comma-separated) picks where the skill and the agent's hooks go:
  claude  -> .claude/skills/  hooks in .claude/settings.json, CLAUDE.md (imports AGENTS.md), reviewer subagent
  codex   -> .agents/skills/  hooks in .codex/hooks.json (trust them once with /hooks)
  cursor  -> .agents/skills/  hooks in .cursor/hooks.json
  copilot -> .github/skills/  hooks in .github/hooks/unispring-gate.json
  opencode-> .agents/skills/  hooks as the plugin .opencode/plugins/unispring-gate.js (OpenCode 2.x)
  all     -> every one of them
Every agent's hooks call the same scripts/hooks/agent_hook.py: a session baseline at
start, quick checks after an edit, the gate (only new violations) before the turn ends.
AGENTS.md (the rules for every agent) and unispring-skill.json are always written.
--git-hook and --ci add the agent-independent gate (gate.py) to git and CI;
--baseline records today's violations as accepted legacy (existing projects).

Never overwrites an existing project file unless --force (the skill folders
themselves are always replaced). Prints what it did.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE / "skills" / "unispring-game-dev"
TEMPLATES = SKILL / "templates"
SKILL_NAME = "unispring-game-dev"
AGENT_DIRS = {
    "claude": ".claude/skills",
    "codex": ".agents/skills",
    "cursor": ".agents/skills",
    "copilot": ".github/skills",
    "opencode": ".agents/skills",
}
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def say(action: str, rel: Path | str) -> None:
    print(f"{action:>9}: {rel}")


def render(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        raise ValueError(f"unfilled placeholders: {sorted(set(left))}")
    return text


def write(project: Path, rel: str, text: str, force: bool, executable: bool = False) -> None:
    path = project / rel
    if path.exists() and not force:
        say("kept", rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)
    say("written", rel)


def parse_agents(value: str) -> list[str]:
    names = [n.strip().lower() for n in value.split(",") if n.strip()]
    if "all" in names:
        return list(AGENT_DIRS)
    unknown = [n for n in names if n not in AGENT_DIRS]
    if unknown or not names:
        raise ValueError(f"unknown agent(s) {unknown}; use {', '.join(AGENT_DIRS)} or all")
    return names


def skill_dirs(agents: list[str]) -> list[str]:
    dirs: list[str] = []
    for agent in agents:
        target = f"{AGENT_DIRS[agent]}/{SKILL_NAME}"
        if target not in dirs:
            dirs.append(target)
    return dirs


def copy_skill(project: Path, rel: str) -> None:
    target = project / rel
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    say("copied", rel)


HOOK_CONFIGS = {
    # agent: (template, target, layout); "nested" = event -> groups -> hooks (Claude, Codex),
    # "flat" = event -> entries (Cursor), "own" = a file of the skill's own (Copilot).
    "claude": ("hooks/claude-settings.json", ".claude/settings.json", "nested"),
    "codex": ("hooks/codex-hooks.json", ".codex/hooks.json", "nested"),
    "cursor": ("hooks/cursor-hooks.json", ".cursor/hooks.json", "flat"),
    "copilot": ("hooks/copilot-hooks.json", ".github/hooks/unispring-gate.json", "own"),
    "opencode": ("hooks/opencode-plugin.js", ".opencode/plugins/unispring-gate.js", "plugin"),
}


def _entry_command(entry: dict) -> str:
    return entry.get("command") or entry.get("bash") or ""


def install_hooks(project: Path, agent: str, values: dict[str, str]) -> None:
    """Add the agent's hooks to its config, keeping everything already there."""
    template, target, layout = HOOK_CONFIGS[agent]
    skill_dir = f"{AGENT_DIRS[agent]}/{SKILL_NAME}"
    text = render((TEMPLATES / template).read_text(encoding="utf-8"), {**values, "SKILL_DIR": skill_dir})
    path = project / target
    path.parent.mkdir(parents=True, exist_ok=True)
    if layout == "plugin":  # a file of the skill's own, kept in step with the skill
        path.write_text(text, encoding="utf-8")
        say("written", target)
        return
    ours = json.loads(text)
    if layout == "own" or not path.exists():
        path.write_text(json.dumps(ours, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        say("written", target)
        return
    current = json.loads(path.read_text(encoding="utf-8"))
    hooks = current.setdefault("hooks", {})
    added = 0
    if layout == "nested":
        existing = {_entry_command(h) for groups in hooks.values() for g in groups for h in g.get("hooks", [])}
        for event, groups in ours["hooks"].items():
            for group in groups:
                fresh = [h for h in group["hooks"] if _entry_command(h) not in existing]
                if fresh:
                    hooks.setdefault(event, []).append({**group, "hooks": fresh})
                    added += len(fresh)
    if layout == "flat":
        current.setdefault("version", ours["version"])
        existing = {_entry_command(e) for entries in hooks.values() for e in entries}
        for event, entries in ours["hooks"].items():
            fresh = [e for e in entries if _entry_command(e) not in existing]
            hooks.setdefault(event, []).extend(fresh)
            added += len(fresh)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    say("merged", f"{target} (+{added} hook(s))")


def ignore_cache(project: Path) -> None:
    path = project / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if ".unispring-cache/" in text:
        return
    path.write_text(text + ("" if text.endswith("\n") or not text else "\n")
                    + "# unispring-game-dev hooks: per-session baselines\n.unispring-cache/\n", encoding="utf-8")
    say("updated", ".gitignore (.unispring-cache/)")


def project_config(values: dict[str, str], project: Path, bootstrap: bool) -> str:
    data = json.loads((TEMPLATES / "unispring-skill.json").read_text(encoding="utf-8"))
    data["assemblyPrefix"] = values["PREFIX"]
    data["rootNamespace"] = values["NAMESPACE"]
    section = data["localization"]
    reference = project / section["tables"] / f"{section['languages'][0]}.json"
    if not bootstrap and not reference.is_file():
        # Strict localization in a project with no language table would fail every check on the
        # missing table itself, not on anything an agent did. Off until the tables exist.
        section["enabled"] = False
        print(f"     note: no {reference.relative_to(project)} yet: localization checks are off in "
              "unispring-skill.json; add the table (or use --with-bootstrap) and set "
              '"localization": {"enabled": true}.')
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def install_git_hook(project: Path, force: bool) -> None:
    proc = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=project, capture_output=True, text=True)
    if proc.returncode != 0:
        say("skipped", "pre-commit hook (not a git repository)")
        return
    hooks = (project / proc.stdout.strip()).resolve()
    hook = hooks / "pre-commit"
    ours = (TEMPLATES / "git-hooks/pre-commit").read_text(encoding="utf-8")
    if hook.exists() and hook.read_text(encoding="utf-8", errors="replace") != ours and not force:
        say("kept", f"{hook} (a different pre-commit hook exists; call our gate from it, see README)")
        return
    hooks.mkdir(parents=True, exist_ok=True)
    hook.write_text(ours, encoding="utf-8")
    hook.chmod(0o755)
    say("written", hook.relative_to(project.resolve()) if hook.is_relative_to(project.resolve()) else hook)


def install_ci(project: Path, kind: str, t, force: bool) -> None:
    if kind == "github":
        write(project, ".github/workflows/unispring-gate.yml", t("ci/github-actions.yml"), force)
        return
    write(project, ".gitlab/unispring-gate.yml", t("ci/gitlab-ci.yml"), force)
    main = project / ".gitlab-ci.yml"
    if main.exists():
        if ".gitlab/unispring-gate.yml" not in main.read_text(encoding="utf-8", errors="replace"):
            print("     note: add to .gitlab-ci.yml:  include:\n             - local: .gitlab/unispring-gate.yml")
        return
    write(project, ".gitlab-ci.yml", "include:\n  - local: .gitlab/unispring-gate.yml\n", force)


def run_baseline(project: Path, skill_dir: str) -> int:
    proc = subprocess.run([sys.executable, str(project / skill_dir / "scripts/gate.py"), "baseline",
                           "--root", str(project)], capture_output=True, text=True)
    print("     " + (proc.stdout + proc.stderr).strip().replace("\n", "\n     "))
    return proc.returncode


def update(project: Path) -> int:
    found = [f"{d}/{SKILL_NAME}" for d in dict.fromkeys(AGENT_DIRS.values())
             if (project / d / SKILL_NAME).is_dir()]
    if not found:
        print("ERROR: no installed copy of the skill found; install it first")
        return 2
    for rel in found:
        copy_skill(project, rel)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="Unity project root (has Assets/)")
    parser.add_argument("--game", help="display name of the game, e.g. \"No Legal\"")
    parser.add_argument("--prefix", help="assembly prefix of modules, e.g. SLRR")
    parser.add_argument("--namespace", help="root namespace of game-wide code, e.g. NoLegal")
    parser.add_argument("--agent", default="claude", help="claude, codex, cursor, copilot (comma-separated) or all")
    parser.add_argument("--git-hook", action="store_true", help="install the gate as the git pre-commit hook")
    parser.add_argument("--ci", choices=["github", "gitlab"], help="add the gate to CI")
    parser.add_argument("--baseline", action="store_true",
                        help="record today's violations as accepted legacy (unispring-baseline.json)")
    parser.add_argument("--with-bootstrap", action="store_true",
                        help="composition root, link.xml, logging.properties, language table, .gitattributes")
    parser.add_argument("--with-lease", action="store_true", help="EditorLease for several agents in one Unity")
    parser.add_argument("--update", action="store_true", help="only replace the installed skill folders")
    parser.add_argument("--force", action="store_true", help="overwrite existing project files")
    args = parser.parse_args()

    project = args.project.resolve()
    if not (project / "Assets").is_dir():
        print(f"ERROR: {project} is not a Unity project (no Assets/)")
        return 2
    if args.update:
        return update(project)
    missing = [n for n in ("game", "prefix", "namespace") if not getattr(args, n)]
    if missing:
        print("ERROR: --" + ", --".join(missing) + " required (or --update)")
        return 2
    for value in (args.prefix, args.namespace):
        if not IDENT_RE.match(value):
            print(f"ERROR: not a C# identifier: {value}")
            return 2
    try:
        agents = parse_agents(args.agent)
    except ValueError as error:
        print(f"ERROR: {error}")
        return 2

    dirs = skill_dirs(agents)
    values = {
        "GAME": args.game,
        "PREFIX": args.prefix,
        "NAMESPACE": args.namespace,
        "ENV_PREFIX": args.namespace.upper(),
        "GAME_FOLDER": args.namespace,
        "SKILL_DIR": dirs[0],
    }
    t = lambda rel: render((TEMPLATES / rel).read_text(encoding="utf-8"), values)  # noqa: E731

    for rel in dirs:
        copy_skill(project, rel)
    if args.force or not (project / "unispring-skill.json").exists():
        write(project, "unispring-skill.json", project_config(values, project, args.with_bootstrap), args.force)
    else:
        say("kept", "unispring-skill.json")
    write(project, "AGENTS.md", t("AGENTS.md.template"), args.force)

    if "claude" in agents:
        claude_dir = f"{AGENT_DIRS['claude']}/{SKILL_NAME}"
        claude_md = project / "CLAUDE.md"
        if claude_md.exists() and "@AGENTS.md" not in claude_md.read_text(encoding="utf-8") and not args.force:
            print("     note: CLAUDE.md exists and does not import AGENTS.md; add the line  @AGENTS.md")
        write(project, "CLAUDE.md", t("CLAUDE.md.template"), args.force)
        write(project, ".claude/agents/reviewer.md",
              render((TEMPLATES / "agents/reviewer.md").read_text(encoding="utf-8"), {**values, "SKILL_DIR": claude_dir}),
              args.force)
        if not (project / ".mcp.json").exists():
            write(project, ".mcp.json", '{"mcpServers": {}}\n', args.force)

    for agent in agents:
        install_hooks(project, agent, values)
    ignore_cache(project)
    if "opencode" in agents:
        print("     note: the OpenCode plugin needs OpenCode 2.x (V2 plugins); load errors appear only in"
              " ~/.local/share/opencode/log/opencode.log.")
    if "codex" in agents:
        print("     note: Codex runs repository hooks only after you trust them: open /hooks in Codex once.")

    if args.with_bootstrap:
        ns = args.namespace
        write(project, "Assets/Src/Scripts/Bootstrap/UniSpringConfiguration.cs",
              t("Bootstrap/UniSpringConfiguration.cs.template"), args.force)
        write(project, f"Assets/Src/Scripts/Bootstrap/{ns}.Bootstrap.asmdef",
              t("Bootstrap/Bootstrap.asmdef.template"), args.force)
        write(project, "Assets/Src/link.xml", t("link.xml.template"), args.force)
        write(project, "Assets/Src/Resources/logging.properties.txt",
              t("logging.properties.txt.template"), args.force)
        write(project, "Assets/Src/Resources/Localization/en.json", "{\n}\n", args.force)
        if not (project / ".gitattributes").exists():
            write(project, ".gitattributes", t("gitattributes"), args.force)
    if args.with_lease:
        ns = args.namespace
        write(project, "Assets/Src/AgentLease/Editor/EditorLease.cs", t("AgentLease/EditorLease.cs.template"), args.force)
        write(project, f"Assets/Src/AgentLease/Editor/{ns}.AgentLease.Editor.asmdef",
              t("AgentLease/AgentLease.Editor.asmdef.template"), args.force)

    if args.git_hook:
        install_git_hook(project, args.force)
    if args.ci:
        install_ci(project, args.ci, t, args.force)
    if args.baseline and run_baseline(project, dirs[0]) != 0:
        return 2

    print("\nNext: open Unity (it creates the .meta files), check the compile, then run")
    print(f"  python3 {dirs[0]}/scripts/gate.py check --root .")
    print("Existing project with legacy violations: --baseline once, then commit unispring-baseline.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
