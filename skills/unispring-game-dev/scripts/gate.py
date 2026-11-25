#!/usr/bin/env python3
"""Agent-independent quality gate of the unispring-game-dev skill.

Runs the four checks of the skill and fails only on NEW violations:

  gate.py baseline [--root .]   record today's architecture violations as accepted
                                legacy in unispring-baseline.json (commit that file)
  gate.py check    [--root .]   fail when the architecture checks find a violation
                                the baseline doesn't list, or localization finds any

Used by the git pre-commit hook (templates/git-hooks/pre-commit), CI
(templates/ci/*) and any agent, whatever runs it; the agents' own hooks
(hooks/agent_hook.py: Claude Code, Codex, Cursor, Copilot, OpenCode) use the same functions
with a per-session baseline.

Line numbers are dropped when comparing, so legacy code that only moved does not
count as new. Localization is strict: it has no baseline.
Exit 0 = passed, 1 = new violations, 2 = a check could not run.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import project_config  # noqa: E402

ARCHITECTURE_CHECKS = ("check-asset-layout.py", "check-code-architecture.py", "check-subsystem-boundaries.py")
LOCALIZATION_CHECK = "check-localization.py"


def normalize(line: str) -> str:
    """'VIOLATION: path:123: MESSAGE' -> 'VIOLATION: path: MESSAGE'."""
    return re.sub(r"^(VIOLATION: [^:]+):\d+:", r"\1:", line.strip())


def _run(root: Path, name: str, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / name), "--root", str(root), *(extra or [])],
                          cwd=root, capture_output=True, text=True)


def architecture_violations(root: Path) -> tuple[Counter, list[str]]:
    """Normalised violations of the three architecture checks, and checks that could not run."""
    found: Counter = Counter()
    errors: list[str] = []
    for name in ARCHITECTURE_CHECKS:
        proc = _run(root, name)
        if proc.returncode == 2:
            errors.append(name + ": " + (proc.stdout + proc.stderr).strip()[-400:])
        for line in proc.stdout.splitlines():
            if line.startswith("VIOLATION: "):
                found[normalize(line)] += 1
    return found, errors


def localization_violations(root: Path, file: str | None = None) -> tuple[list[str], list[str]]:
    proc = _run(root, LOCALIZATION_CHECK, ["--file", file] if file else [])
    errors = []
    if proc.returncode == 2:
        errors.append(LOCALIZATION_CHECK + ": " + (proc.stdout + proc.stderr).strip()[-300:])
    return [line for line in proc.stdout.splitlines() if line.startswith("VIOLATION: ")], errors


def baseline_path(root: Path) -> Path:
    return root / project_config.BASELINE_NAME


def read_baseline(path: Path) -> Counter:
    if not path.is_file():
        return Counter()
    return Counter(json.loads(path.read_text(encoding="utf-8")).get("violations", {}))


def write_baseline(path: Path, found: Counter) -> None:
    data = {
        "comment": "Legacy violations accepted by the unispring-game-dev gate; only new ones fail. "
                   "Shrink it with `gate.py baseline` after fixing legacy; never grow it to hide new code.",
        "violations": dict(sorted(found.items())),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def new_violations(found: Counter, baseline: Counter) -> list[str]:
    return [v + (f" (x{n})" if n > 1 else "") for v, n in sorted((found - baseline).items())]


def cmd_baseline(root: Path, path: Path) -> int:
    found, errors = architecture_violations(root)
    if errors:
        print("gate: checks could not run, baseline not written:\n" + "\n".join(errors))
        return 2
    write_baseline(path, found)
    print(f"gate: {sum(found.values())} legacy violation(s) recorded in {path.name}; commit it.")
    return 0


def cmd_check(root: Path, path: Path) -> int:
    baseline = read_baseline(path)
    found, errors = architecture_violations(root)
    localization, loc_errors = localization_violations(root)
    errors += loc_errors
    new = new_violations(found, baseline)
    fixed = sum((baseline - found).values())
    for line in new + localization:
        print(line)
    if fixed:
        print(f"gate: {fixed} baseline violation(s) are fixed; run `gate.py baseline` to shrink the baseline.")
    for error in errors:
        print("ERROR: " + error)
    if errors:
        return 2
    if new or localization:
        print(f"\ngate: FAILED — {len(new)} new architecture violation(s), {len(localization)} localization "
              "problem(s). Rules: the unispring-game-dev skill (SKILL.md and references/).")
        return 1
    print(f"gate: OK ({sum(found.values())} legacy violation(s) in the baseline, none new).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["baseline", "check"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline", type=Path, help=f"default: <root>/{project_config.BASELINE_NAME}")
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "Assets").is_dir():
        print(f"ERROR: Assets/ not found (root={root})")
        return 2
    path = args.baseline.resolve() if args.baseline else baseline_path(root)
    return cmd_baseline(root, path) if args.mode == "baseline" else cmd_check(root, path)


if __name__ == "__main__":
    raise SystemExit(main())
