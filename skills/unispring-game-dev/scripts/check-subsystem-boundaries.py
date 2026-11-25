#!/usr/bin/env python3
"""Heuristic API-only subsystem boundary checks for UniSpring Unity modules (unispring-game-dev).

Supports new module-first Scripts/<Module>/Api|Internal and legacy
Scripts/<Layer>/<Module> layouts without forcing migration.
Checks C# namespace references and Unity asmdef assembly dependencies.

Exit 0=clean, 1=violations, 2=verification error. Not a Roslyn compiler.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_config  # noqa: E402

ROOT_LAYER_NAMES = frozenset({
    "Api", "Controller", "Service", "Domain", "Dto", "Dao", "Ports",
    "Integration", "Validation", "Mapping", "Config", "Bootstrap",
    "DependencyInjection",
})
INTERNAL_LAYER_NAMES = ROOT_LAYER_NAMES - {"DependencyInjection"}
SPECIAL_MODULES = frozenset({"_global_bootstrap", "_di_infrastructure", "_ungrouped_legacy"})
# Shared Unity presentation kits (common UI, tool modes, windows...) listed in
# unispring-skill.json "sharedKits". Like DI they are infrastructure,
# not feature modules: presentation/editor code of any module may use them,
# core layers may use only their Api. Set by configure().
SHARED_KIT_FOLDERS: frozenset[str] = frozenset()
COMPOSITION_ROOT = "Bootstrap"
SHARED_KIT = "_shared_presentation_kit"
CORE_LAYERS = frozenset({"Api", "Domain", "Service", "Dao", "Dto", "Ports", "Validation", "Mapping", "Config"})
NAMESPACE_RE = re.compile(r"\bnamespace\s+([\w.]+)\s*[;{]")
USING_RE = re.compile(r"(?m)^\s*(?:global\s+)?using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;")
QUALIFIED_RE = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){2,}\b")
GUID_RE = re.compile(r"(?m)^guid:\s*([0-9a-fA-F]{32})\s*$")


def load_mask():
    """Use the existing C# masker so comments/strings are not parsed as code."""
    path = Path(__file__).with_name("check-code-architecture.py")
    spec = importlib.util.spec_from_file_location("unispring_code_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load check-code-architecture.py")
    import sys
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.mask_non_code


@dataclass(frozen=True)
class Owner:
    module: str
    layer: str
    layout: str


@dataclass(frozen=True)
class Source:
    path: Path
    owner: Owner
    text: str
    namespaces: tuple[str, ...]


def ownership(path: Path, scripts: Path) -> Owner | None:
    """Interpret filesystem ownership, never rely on prefixes of class names."""
    parts = path.relative_to(scripts).parts
    if not parts:
        return None
    if parts[0] == COMPOSITION_ROOT:
        return Owner("_global_bootstrap", "Bootstrap", "infrastructure")
    if parts[0] == "DependencyInjection":
        return Owner("_di_infrastructure", "DependencyInjection", "infrastructure")
    if parts[0] in SHARED_KIT_FOLDERS:
        layer = "Api" if len(parts) >= 2 and parts[1] == "Api" else "Presentation"
        return Owner(SHARED_KIT, layer, "infrastructure")
    if parts[0] in ROOT_LAYER_NAMES:
        if len(parts) >= 3:
            return Owner(parts[1], parts[0], "legacy")
        return Owner("_ungrouped_legacy", parts[0], "legacy")
    if len(parts) >= 2 and parts[1] == "Api":
        return Owner(parts[0], "Api", "module")
    if len(parts) >= 3 and parts[1] == "Internal" and parts[2] in INTERNAL_LAYER_NAMES:
        return Owner(parts[0], parts[2], "module")
    if len(parts) >= 2 and parts[1] == "Internal":
        return Owner(parts[0], "Internal", "module")
    return Owner(parts[0], "Unknown", "module")


def namespace_owner(identifier: str, sources: list[Source]) -> Source | None:
    """Resolve the most specific declared namespace prefix with unique owner.

    A bare module namespace without an explicit Api/Internal marker can be
    ambiguous; in that case no claim is made rather than inventing ownership.
    """
    options: list[tuple[int, Source]] = []
    for src in sources:
        for ns in src.namespaces:
            if identifier == ns or identifier.startswith(ns + "."):
                options.append((len(ns), src))
    if not options:
        return None
    longest = max(length for length, _ in options)
    best = [src for length, src in options if length == longest]
    different = {(x.owner.module, x.owner.layer) for x in best}
    return best[0] if len(different) == 1 else None


def check_cs(scripts: Path, root: Path) -> list[str]:
    mask = load_mask()
    sources: list[Source] = []
    result: list[str] = []
    for path in sorted(scripts.rglob("*.cs")):
        owner = ownership(path, scripts)
        if owner is None:
            continue
        text = mask(path.read_text(encoding="utf-8-sig"))
        sources.append(Source(path, owner, text, tuple(NAMESPACE_RE.findall(text))))

    for src in sources:
        seen = set()
        for match in [*USING_RE.finditer(src.text), *QUALIFIED_RE.finditer(src.text)]:
            identifier = match.group(1) if match.re is USING_RE else match.group(0)
            target = namespace_owner(identifier, sources)
            if target is None or target.path == src.path:
                continue
            if src.owner.module in {"_global_bootstrap", "_di_infrastructure"}:
                continue
            if target.owner.module == SHARED_KIT and src.owner.module != SHARED_KIT:
                if src.owner.layer not in CORE_LAYERS or target.owner.layer == "Api":
                    continue
                issue = ("SHARED: a shared presentation kit may be used by "
                         f"presentation/editor code only, not by {src.owner.layer}")
                line = src.text.count("\n", 0, match.start()) + 1
                if (line, issue) not in seen:
                    seen.add((line, issue))
                    result.append(f"{src.path.relative_to(root)}:{line}: {issue}")
                continue
            if target.owner.module in SPECIAL_MODULES:
                continue  # Legacy without module owner: manual audit needed.
            if src.owner.module == target.owner.module:
                if src.owner.layer != "Api" or target.owner.layer == "Api":
                    continue
                issue = ("API: public module API must not reference its own "
                         f"internal {target.owner.layer} implementation")
            else:
                if target.owner.layer == "Api":
                    continue
                issue = ("MODULE: cross-module reference to internal "
                         f"{target.owner.module}.{target.owner.layer}; "
                         f"use {target.owner.module}.Api only")
            line = src.text.count("\n", 0, match.start()) + 1
            key = (line, issue)
            if key in seen:
                continue
            seen.add(key)
            result.append(f"{src.path.relative_to(root)}:{line}: {issue}")
    return result


def parse_asmdef(path: Path):
    definition = json.loads(path.read_text(encoding="utf-8-sig"))
    name = definition.get("name")
    refs = definition.get("references", [])
    if not isinstance(name, str) or not isinstance(refs, list):
        raise ValueError(f"Invalid name/references in {path}")
    return name, refs


def check_asmdefs(scripts: Path, root: Path) -> list[str]:
    messages = []
    by_name = {}
    by_guid = {}
    files = sorted(scripts.rglob("*.asmdef"))
    for path in files:
        name, refs = parse_asmdef(path)
        info = (path, ownership(path, scripts), refs)
        if name in by_name:
            messages.append(f"{path.relative_to(root)}: ASMDEF: duplicate assembly name {name}")
        by_name[name] = info
        meta = path.with_name(path.name + ".meta")
        if meta.exists():
            match = GUID_RE.search(meta.read_text(encoding="utf-8-sig"))
            if match:
                by_guid[match.group(1).lower()] = info

    # New module-first code must have contract and implementation assemblies.
    firsts = {p.relative_to(scripts).parts[0] for p in scripts.rglob("*.cs")
              if ownership(p, scripts) and ownership(p, scripts).layout == "module"}
    for module in sorted(firsts):
        module_path = scripts / module
        for sub in ("Api", "Internal"):
            if not (module_path / sub).exists():
                messages.append(f"{module_path.relative_to(root)}: MODULE: missing {sub}/ boundary")
                continue
            if not list((module_path / sub).rglob("*.asmdef")):
                messages.append(f"{(module_path / sub).relative_to(root)}: ASMDEF: "
                                f"new subsystem requires separate {sub} assembly")

    for _, (path, src, refs) in by_name.items():
        if src is None:
            continue
        for reference in refs:
            if not isinstance(reference, str):
                continue
            if reference.startswith("GUID:"):
                target_info = by_guid.get(reference[5:].lower())
            else:
                target_info = by_name.get(reference)
            if target_info is None:
                continue  # External/unresolved: do not guess.
            target_path, target, _ = target_info
            if target is not None and target.module == SHARED_KIT and src.module != SHARED_KIT:
                if src.layer in CORE_LAYERS and target.layer != "Api":
                    messages.append(f"{path.relative_to(root)}: ASMDEF: core assembly must not "
                                    f"reference a shared presentation kit ({target_path.relative_to(root)})")
                continue
            if target is None or target.module in SPECIAL_MODULES:
                continue
            if src.module in {"_global_bootstrap", "_di_infrastructure"}:
                continue
            if src.module == target.module:
                if src.layer != "Api" or target.layer == "Api":
                    continue
                reason = "API assembly must not reference its own internal assembly"
            else:
                if target.layer == "Api":
                    continue
                reason = ("cross-module assembly dependency on internal "
                          f"{target.module}.{target.layer}; reference its Api assembly")
            messages.append(f"{path.relative_to(root)}: ASMDEF: {reason} "
                            f"({target_path.relative_to(root)})")
    return messages


def configure(cfg: dict) -> None:
    global SHARED_KIT_FOLDERS, COMPOSITION_ROOT
    SHARED_KIT_FOLDERS = frozenset(cfg["sharedKits"])
    COMPOSITION_ROOT = cfg["compositionRoot"]


def verify_sources(root: Path, cfg: dict | None = None) -> list[str]:
    cfg = cfg or project_config.load(root)
    configure(cfg)
    scripts = root / project_config.norm_dir(cfg["scriptsRoot"])
    if not scripts.is_dir():
        return []
    return check_cs(scripts, root) + check_asmdefs(scripts, root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    opts = parser.parse_args()
    root = opts.root.resolve()
    if not (root / "Assets").is_dir():
        print(f"ERROR: Assets/ not found (root={root})")
        return 2
    try:
        issues = verify_sources(root)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as e:
        print(f"ERROR: subsystem boundary verification failed: {e}")
        return 2
    for issue in issues:
        print("VIOLATION: " + issue)
    if issues:
        print(f"\n{len(issues)} subsystem boundary violation(s); compile/review Unity asmdefs too.")
        return 1
    print("OK: no detected inter-module API/asmdef boundary violations (heuristic only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
