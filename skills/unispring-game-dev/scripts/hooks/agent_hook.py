#!/usr/bin/env python3
"""One hook for every agent: Claude Code, Codex, Cursor, GitHub Copilot and OpenCode.

  agent_hook.py <agent> start   session start: snapshot today's violations (this session's baseline)
  agent_hook.py <agent> edit    after a file edit: quick checks of the edited file(s)
  agent_hook.py <agent> stop    the agent is about to finish: the full gate, only NEW violations

<agent> is claude | codex | cursor | copilot | opencode — the format the agent's own hook config
(installed by install.py) speaks. The checks are gate.py's; only reading the event and
answering differ:

  agent    config                     edit feedback                     stop feedback
  claude   .claude/settings.json      exit 2 + stderr                   exit 2 + stderr
  codex    .codex/hooks.json          {"decision":"block","reason"}     {"decision":"block","reason"}
  cursor   .cursor/hooks.json         none (checked at stop)            {"followup_message"}
  copilot  .github/hooks/*.json       {"additionalContext"}             {"decision":"block","reason"}
  opencode .opencode/plugins/*.js     plain text on stdout: the plugin  plain text on stdout: the plugin
                                      appends it to the tool result     posts it as a synthetic message

Each agent gets one extra turn to fix what the stop check found; after that the result
is reported and the turn ends (stop_hook_active / loop_count), so a hook never loops.
Cursor and Copilot can also run hooks from .claude/settings.json: a run whose payload
shows another host than the one named is answered in that host's format, or skipped
when that host has its own config installed (no double runs).
"""

from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import gate  # noqa: E402
import project_config  # noqa: E402

AGENTS = ("claude", "codex", "cursor", "copilot", "opencode")
OWN_CONFIG = {
    "claude": ".claude/settings.json",
    "codex": ".codex/hooks.json",
    "cursor": ".cursor/hooks.json",
    "copilot": ".github/hooks/unispring-gate.json",
    "opencode": ".opencode/plugins/unispring-gate.js",
}
CACHE_DIR = ".unispring-cache"
BRANCH_RE = re.compile(r"\belse\b|\bswitch\b")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$", re.M)
PATH_KEYS = ("file_path", "filePath", "path", "target_file", "targetFile")
MAX_LINES = 40


# ----------------------------------------------------------------- input

def read_payload() -> dict:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def detect_host(claimed: str, payload: dict) -> str:
    """The agent actually running the hook (Cursor and Copilot also run Claude's hooks)."""
    if os.environ.get("CURSOR_VERSION") or os.environ.get("CURSOR_PROJECT_DIR"):
        return "cursor"
    if "timestamp" in payload or "toolName" in payload or "sessionId" in payload:
        return "copilot"
    return claimed


def project_root(payload: dict) -> Path:
    for name in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR"):
        if os.environ.get(name):
            return Path(os.environ[name]).resolve()
    cwd = payload.get("cwd") or os.getcwd()
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    # <root>/<agent dir>/skills/unispring-game-dev/scripts
    return SCRIPTS.parents[3]


def edited_files(payload: dict, root: Path) -> list[Path]:
    """Every file path the edit event names: plain fields, tool arguments, apply_patch text."""
    found: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in PATH_KEYS and isinstance(item, str):
                    found.append(item)
                walk(item)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, str):
            return
        stripped = value.strip()
        if stripped[:1] in "{[":
            try:
                walk(json.loads(stripped))
            except ValueError:
                pass
        for match in PATCH_FILE_RE.finditer(value):
            found.append((match.group(1) or match.group(2)).strip())

    walk({k: v for k, v in payload.items() if k not in ("tool_response", "tool_result", "toolResult")})
    result: list[Path] = []
    for item in dict.fromkeys(found):
        path = Path(item)
        result.append((path if path.is_absolute() else root / path).resolve())
    return result


# ----------------------------------------------------------------- checks

def strip_code(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'@?"(?:[^"\\\n]|\\.)*"', '""', text)
    return re.sub(r"(?m)^[ \t]*#.*$", "", text)


def head_version(root: Path, rel: str) -> str:
    proc = subprocess.run(["git", "show", "HEAD:" + rel], cwd=root, capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def file_problems(root: Path, path: Path) -> list[str]:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return []
    src = project_config.norm_dir(project_config.load(root)["srcRoot"])
    if not path.is_file() or not rel.startswith(src + "/"):
        return []
    problems: list[str] = []
    if path.suffix == ".cs":
        current = strip_code(path.read_text(encoding="utf-8", errors="replace"))
        if gate_log_re().search(current):
            problems.append(f"{rel}: direct Debug.Log*/Console.Write*/print — use UniSpring.Logging.GameLog "
                            "(references/logging.md)")
        before = len(BRANCH_RE.findall(strip_code(head_version(root, rel))))
        after = len(BRANCH_RE.findall(current))
        if after > before:
            problems.append(f"{rel}: switch/else count grew {before} -> {after} — choose behaviour with "
                            "[Strategy] + StrategyRegistry, use guard clauses (SKILL.md, rule 6)")
    if path.suffix in (".cs", ".json"):
        findings, errors = gate.localization_violations(root, str(path))
        problems += findings + errors
    return problems


@functools.lru_cache(maxsize=1)
def gate_log_re():
    import importlib.util
    spec = importlib.util.spec_from_file_location("unispring_arch", SCRIPTS / "check-code-architecture.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.DIRECT_LOG_RE


def session_baseline_path(root: Path, host: str) -> Path:
    return root / CACHE_DIR / f"{host}-session-baseline.json"


def stop_problems(root: Path, host: str) -> list[str]:
    session = session_baseline_path(root, host)
    committed = gate.baseline_path(root)
    found, errors = gate.architecture_violations(root)
    if not session.is_file() and not committed.is_file():
        # No start snapshot (a resumed session) and no committed baseline: what is new can't
        # be told from legacy, so take the snapshot now and judge from the next turn on.
        session.parent.mkdir(parents=True, exist_ok=True)
        gate.write_baseline(session, found)
        return []
    baseline = gate.read_baseline(session if session.is_file() else committed)
    localization, loc_errors = gate.localization_violations(root)
    return gate.new_violations(found, baseline) + localization + ["could not run: " + e for e in errors + loc_errors]


def message(title: str, problems: list[str], tail: str) -> str:
    lines = problems[:MAX_LINES]
    more = f"\n... and {len(problems) - MAX_LINES} more" if len(problems) > MAX_LINES else ""
    return f"unispring-game-dev: {title}\n" + "\n".join(lines) + more + "\n" + tail


# ----------------------------------------------------------------- answers per agent

FIX = "Fix them (or explain why they are intended) before finishing; rules: the unispring-game-dev skill."
RETRY_DONE = "(not fixed after one retry; review manually)"


def answer_start(host: str, note: str) -> int:
    if host == "opencode":
        return 0  # the plugin has nowhere to put start context; the baseline file is what matters
    if host == "cursor":
        print(json.dumps({"additional_context": note}))
        return 0
    if host == "copilot":
        print(json.dumps({"additionalContext": note}))
        return 0
    print(note)  # Claude Code and Codex add SessionStart stdout to the context
    return 0


def answer_edit(host: str, problems: list[str]) -> int:
    if not problems:
        return 0
    text = message("problems in the edited file(s):", problems, "Fix them before going on.")
    if host == "opencode":
        print(text)  # the plugin appends it to the tool result the model reads
        return 0
    if host == "claude":
        print(text, file=sys.stderr)
        return 2
    if host == "codex":
        print(json.dumps({"decision": "block", "reason": text}))
        return 0
    if host == "copilot":
        print(json.dumps({"additionalContext": text}))
        return 0
    return 0  # cursor: afterFileEdit has no feedback channel; the stop check reports it


def let_stop(host: str) -> None:
    """The 'nothing to add' answer: Codex and Copilot expect JSON from a stop hook."""
    if host == "copilot":
        print(json.dumps({"decision": "allow"}))
        return
    if host in ("codex", "cursor"):
        print(json.dumps({}))


def answer_stop(host: str, payload: dict, problems: list[str]) -> int:
    retried = bool(payload.get("stop_hook_active")) or int(payload.get("loop_count") or 0) > 0
    if not problems:
        let_stop(host)
        return 0
    text = message("NEW violations introduced in this session:", problems, FIX)
    if retried:
        if host == "opencode":
            print(text + "\n" + RETRY_DONE, file=sys.stderr)  # stdout stays empty: no further continuation
            return 0
        if host == "claude":
            print(json.dumps({"systemMessage": text + "\n" + RETRY_DONE}))
            return 0
        print(text + "\n" + RETRY_DONE, file=sys.stderr)
        let_stop(host)
        return 0
    if host == "claude":
        print(text, file=sys.stderr)
        return 2
    if host == "cursor":
        print(json.dumps({"followup_message": text}))
        return 0
    if host == "opencode":
        print(text)  # the plugin posts it to the session once
        return 0
    print(json.dumps({"decision": "block", "reason": text}))  # codex, copilot
    return 0


# ----------------------------------------------------------------- main

def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in AGENTS or sys.argv[2] not in ("start", "edit", "stop"):
        print("usage: agent_hook.py claude|codex|cursor|copilot|opencode start|edit|stop", file=sys.stderr)
        return 1
    claimed, event = sys.argv[1], sys.argv[2]
    payload = read_payload()
    host = detect_host(claimed, payload)
    root = project_root(payload)
    if host != claimed and (root / OWN_CONFIG[host]).is_file():
        # e.g. Copilot running Claude's hooks while its own config is installed: it runs ours anyway.
        if event == "stop":
            let_stop(host)
        return 0
    if not (root / "Assets").is_dir():
        return 0

    if event == "start":
        found, errors = gate.architecture_violations(root)
        path = session_baseline_path(root, host)
        path.parent.mkdir(parents=True, exist_ok=True)
        gate.write_baseline(path, found)
        note = (f"unispring-game-dev: {sum(found.values())} existing violation(s) recorded for this session; "
                "only new ones will block. Load the unispring-game-dev skill before changing Assets/.")
        if errors:
            note += " Some checks could not run: " + "; ".join(errors)
        return answer_start(host, note)
    if event == "edit":
        problems: list[str] = []
        for path in edited_files(payload, root):
            problems += file_problems(root, path)
        return answer_edit(host, problems)
    return answer_stop(host, payload, stop_problems(root, host))


if __name__ == "__main__":
    sys.exit(main())
