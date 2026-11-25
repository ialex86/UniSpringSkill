#!/usr/bin/env python3
"""Validate Unity asset ownership (unispring-game-dev) and protect immutable vendor trees.

Existing vendor assets (including .cs/.shader/.prefab) are NOT project-layout
violations. Files known to be project-owned outside Assets/Src ARE violations.

Exit 0 = clean, 1 = violations, 2 = verification unavailable.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_config  # noqa: E402

PROJECT_EXTS = frozenset({
    ".cs", ".asmdef", ".asmref", ".unity", ".prefab",
    ".prefabvariant", ".mat", ".shader", ".hlsl", ".cginc",
    ".shadergraph", ".inputactions", ".inputaction", ".controller",
    ".anim", ".mask", ".asset",
})

# Confirmed project-owned legacy zones come from unispring-skill.json
# (legacyProjectPrefixes / legacyProjectFiles). Do NOT list vendor folders there.
IGNORED_SOURCE_NAMES = frozenset({".DS_Store", "Thumbs.db", ".gitkeep"})


def repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "Assets").is_dir():
            return parent
    return start


def asset_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def src_dir(cfg: dict) -> str:
    return project_config.norm_dir(cfg["srcRoot"])


def check_project_file_locations(root: Path, cfg: dict | None = None) -> list[str]:
    """Only scan known project-owned legacy and loose root assets; not vendors."""
    cfg = cfg or project_config.load(root)
    legacy_prefixes = tuple(cfg["legacyProjectPrefixes"])
    legacy_files = frozenset(cfg["legacyProjectFiles"])
    assets = root / "Assets"
    problems: list[str] = []

    for entry in sorted(assets.iterdir()):
        if not entry.is_file() or entry.suffix == ".meta":
            continue
        if entry.suffix.lower() in PROJECT_EXTS:
            problems.append(f"PROJECT ASSET IN Assets/ ROOT: {asset_path(entry, root)}")

    for prefix in legacy_prefixes:
        folder = root / prefix.rstrip("/")
        if not folder.is_dir():
            continue
        for entry in sorted(folder.rglob("*")):
            if entry.is_file() and entry.suffix != ".meta":
                problems.append(f"LEGACY PROJECT FILE OUTSIDE {src_dir(cfg)}: {asset_path(entry, root)}")

    for rel in sorted(legacy_files):
        file = root / rel
        if file.is_file() and file.parent != assets:
            problems.append(f"LEGACY PROJECT FILE OUTSIDE {src_dir(cfg)}: {rel}")
    return problems


def check_meta(root: Path, cfg: dict | None = None) -> list[str]:
    """Inspect ownership zone only; do not judge third-party package contents."""
    cfg = cfg or project_config.load(root)
    src = root / src_dir(cfg)
    problems: list[str] = []
    if not src.exists():
        return problems

    candidates = [src, *sorted(src.rglob("*"))]
    for entry in candidates:
        if entry.name in IGNORED_SOURCE_NAMES or entry.suffix == ".meta":
            continue
        # Unity never imports hidden folders (name~ or .name), so they need no .meta.
        if any(part.endswith("~") or part.startswith(".") for part in entry.relative_to(src).parts):
            continue
        if not entry.is_file() and not entry.is_dir():
            continue
        meta = entry.with_name(entry.name + ".meta")
        if not meta.is_file():
            problems.append(f"MISSING .meta: {asset_path(entry, root)}")

    for meta in src.rglob("*.meta"):
        source = meta.with_name(meta.name[:-5])
        if not source.exists():
            problems.append(f"ORPHAN .meta: {asset_path(meta, root)}")
    return problems


def check_git_vendor_changes(root: Path, cfg: dict | None = None) -> tuple[list[str], str | None]:
    """Use -z to correctly parse paths, whitespace and renames."""
    cfg = cfg or project_config.load(root)
    src = src_dir(cfg)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "Assets/"],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"git status unavailable: {exc}"

    if result.returncode != 0:
        return [], f"git status failed: {result.stderr.decode('utf-8', 'replace').strip()}"

    fields = result.stdout.decode("utf-8", "surrogateescape").split("\0")
    problems: list[str] = []
    i = 0
    while i < len(fields):
        item = fields[i]
        i += 1
        if not item:
            continue
        if len(item) < 4 or item[2] != " ":
            return [], f"unexpected git status record: {item!r}"
        code = item[:2]
        paths = [item[3:]]
        if "R" in code or "C" in code:
            if i >= len(fields) or not fields[i]:
                return [], f"incomplete rename/copy record: {item!r}"
            paths.append(fields[i])
            i += 1
        outside = [p for p in paths if not (p in {src, src + ".meta"} or p.startswith(src + "/"))]
        if outside:
            problems.append(f"ASSET CHANGE OUTSIDE {src} [{code}]: {' -> '.join(paths)}")
    return problems, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = repo_root(args.root.resolve())
    if not (root / "Assets").is_dir():
        print(f"ERROR: Assets/ not found (root={root})")
        return 2

    try:
        cfg = project_config.load(root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {project_config.CONFIG_NAME}: {exc}")
        return 2
    errors = check_project_file_locations(root, cfg) + check_meta(root, cfg)
    vendor_changes, git_error = check_git_vendor_changes(root, cfg)
    errors.extend(vendor_changes)

    for item in errors:
        print("VIOLATION: " + item)
    if git_error:
        print("ERROR: " + git_error)
        print("Vendor changes could not be verified; result is incomplete.")
        return 2
    if errors:
        print(f"\n{len(errors)} violation(s). Legacy migrations require approval; vendor edits require explicit approval.")
        return 1
    print(f"OK: project-owned assets in {src_dir(cfg)}; no modified vendor paths detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
