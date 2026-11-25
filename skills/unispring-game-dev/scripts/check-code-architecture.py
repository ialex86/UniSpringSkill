#!/usr/bin/env python3
"""Static architecture guard for UniSpring Unity C# sources (unispring-game-dev).

Checks layer boundaries, Unity API leakage, DI-only service construction hints,
MonoBehaviour bases, forbidden C# `switch`/`else` syntax, and module-first layout.
Not a C# compiler or a replacement for architecture review and Unity tests.

Exit 0 = clean, 1 = violations, 2 = verification unavailable.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_config  # noqa: E402

LAYERS = frozenset({
    "Api", "Controller", "Service", "Domain", "Dto", "Dao", "Ports",
    "Integration", "Validation", "Mapping", "Config", "Bootstrap",
    "DependencyInjection",
})

# Allowed references to other *project* layers. A layer may always refer to itself.
ALLOWED: dict[str, frozenset[str]] = {
    "Domain": frozenset(),
    "Dto": frozenset({"Domain"}),
    "Ports": frozenset({"Domain", "Dto", "Api"}),
    "Validation": frozenset({"Domain", "Dto", "Ports", "Api"}),
    "Mapping": frozenset({"Domain", "Dto", "Ports", "Api"}),
    "Config": frozenset({"Domain", "Dto"}),
    # DI attributes ([Service], [Strategy]) are mandatory, so beans may use the DI core.
    "Service": frozenset({"Domain", "Dto", "Ports", "Validation", "Mapping", "Config", "Api", "DependencyInjection"}),
    "Dao": frozenset({"Ports", "Domain", "Dto", "Config", "Mapping", "DependencyInjection"}),
    "Integration": frozenset({"Ports", "Domain", "Dto", "Config", "Mapping", "Validation", "Api", "DependencyInjection"}),
    "Api": frozenset({"Api", "Ports", "Domain", "Dto"}),
    "Controller": frozenset({"Api", "Ports", "Domain", "Dto", "Validation", "DependencyInjection"}),
    "Bootstrap": LAYERS,
    "DependencyInjection": frozenset(),
}
# Folder names used by existing modules, mapped to the canonical layer whose
# rules they follow (Application = use cases, Presentation = Unity adapters).
LAYER_ALIASES = {
    "Application": "Service",
    "Presentation": "Controller",
    "Persistence": "Dao",
    "Adapters": "Integration",
    "Editor": "Bootstrap",  # editor tooling composes its own module
}


def canonical_layer(name: str):
    if name in LAYERS:
        return name
    return LAYER_ALIASES.get(name)


PURE_LAYERS = frozenset({
    "Domain", "Dto", "Ports", "Validation", "Mapping", "Config", "Service", "Api",
})
BUSINESS_LAYERS = PURE_LAYERS | {"Api", "Dao"}
NAMESPACE_RE = re.compile(r"\bnamespace\s+([\w.]+)\s*[;{]")
USING_RE = re.compile(r"(?m)^\s*(?:global\s+)?using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;")
SYNTAX_RE = re.compile(r"\b(switch|case|else)\b|\bdefault\s*:")
UNITY_API_RE = re.compile(r"\b(?:UnityEngine|UnityEditor)\b")
# SKILL.md section 3: an Api file may be an explicitly marked Unity-facing
# adapter contract when a Unity type is the point of the contract (a Camera).
UNITY_FACING_RE = re.compile(r"(?m)^\s*//\s*unity-facing-contract:\s*\S")
# Other namespace references such as Game.Integration.SomeClass (without using).
QUALIFIED_RE = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){2,}\b")
MANUAL_LOOKUP_RE = re.compile(
    r"\b(?:FindObjectOfType|FindFirstObjectByType|FindAnyObjectByType)\s*(?:<|\()"
    r"|\bRuntimeContext\s*\.\s*Get\s*<"
    r"|\bApplicationContext\b"
)
# references/logging.md: all diagnostics go through UniSpring.Logging.GameLog.
DIRECT_LOG_RE = re.compile(
    r"\b(?:UnityEngine\s*\.\s*)?Debug\s*\.\s*(?:Log|LogWarning|LogError|LogException|LogFormat)\b"
    r"|\bConsole\s*\.\s*Write(?:Line)?\b|(?<![\w.])print\s*\(")
STATIC_INSTANCE_RE = re.compile(r"\bstatic\s+[\w<>?,.]+\s+Instance\b")
DIRECT_MONO_RE = re.compile(r"\bclass\s+\w+[^\n{]*:\s*MonoBehaviour\b")
ATTR_RE = re.compile(r"\[\s*(?:\w+\.)?(?:Service|Component|Strategy)(?:Attribute)?\b")
CLASS_RE = re.compile(r"\b(?:(?:public|internal|private|protected|sealed|partial|abstract|static)\s+)*class\s+(\w+)")
NEW_RE = re.compile(r"\bnew\s+(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)\s*(?:<[^\n()]*>)?\s*\(")
STRING_START_RE = re.compile(r'(?:\$@|@\$|@|\$)?"')


@dataclass(frozen=True)
class Source:
    path: Path
    layer: str
    code: str
    namespaces: tuple[str, ...]


def mask_non_code(source: str) -> str:
    """Keep code positions/newlines while masking comments and strings.

    Supports ordinary, verbatim and raw C# string literals and char literals.
    Interpolation expressions within strings are masked; Roslyn is needed to
    analyze code inside interpolations and all language constructs completely.
    """
    chars = list(source)
    n = len(chars)

    def blank(start: int, end: int) -> None:
        for j in range(start, end):
            if chars[j] not in "\r\n":
                chars[j] = " "

    i = 0
    while i < n:
        if source.startswith("//", i):
            end = source.find("\n", i)
            if end == -1:
                end = n
            blank(i, end)
            i = end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            blank(i, end)
            i = end
            continue
        # C# 11 raw strings with arbitrary quote count.
        prefix_start = i
        j = i
        while j < n and source[j] == "$":
            j += 1
        if j < n and source[j] == '"':
            q = j
            while q < n and source[q] == '"':
                q += 1
            count = q - j
            if count >= 3:
                closing = source.find('"' * count, q)
                end = n if closing == -1 else closing + count
                blank(prefix_start, end)
                i = end
                continue
        # $@"...", @$"...", @"...", $"...", "...".
        head = STRING_START_RE.match(source, i)
        if head:
            verbatim = "@" in head.group(0)
            j = i + len(head.group(0))
            while j < n:
                if not verbatim and source[j] == "\\":
                    j += 2
                    continue
                if verbatim and source.startswith('""', j):
                    j += 2
                    continue
                if source[j] == '"':
                    j += 1
                    break
                j += 1
            blank(i, min(j, n))
            i = min(j, n)
            continue
        if source[i] == "'":
            j = i + 1
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "'":
                    j += 1
                    break
                j += 1
            blank(i, min(j, n))
            i = min(j, n)
            continue
        i += 1

    result = "".join(chars)
    # Preprocessor #else is not the C# `else` keyword.
    return re.sub(r"(?m)^[ \t]*#.*$", lambda m: " " * len(m.group(0)), result)


def line_of(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def find_project_layer(namespace: str, sources: list[Source]) -> str | None:
    """Match the deepest declared project namespace, never vendor namespace names."""
    matches: list[tuple[int, str]] = []
    for source in sources:
        for declared in source.namespaces:
            if namespace == declared or namespace.startswith(declared + ".") or declared.startswith(namespace + "."):
                matches.append((len(declared), source.layer))
    if not matches:
        return None
    # If a namespace prefix maps to several layers, there is no reliable target.
    # Namespace declarations should normally align with folders.
    max_len = max(length for length, _ in matches)
    winners = {layer for length, layer in matches if length == max_len}
    return next(iter(winners)) if len(winners) == 1 else None


def verify_sources(root: Path, cfg: dict | None = None) -> list[str]:
    cfg = cfg or project_config.load(root)
    scripts = root / project_config.norm_dir(cfg["scriptsRoot"])
    composition_root = cfg["compositionRoot"]
    if not scripts.exists():
        return []
    messages: list[str] = []
    sources: list[Source] = []
    for path in sorted(scripts.rglob("*.cs")):
        rel = path.relative_to(scripts)
        if len(rel.parts) >= 2 and rel.parts[0] == composition_root:
            layer = "Bootstrap"  # The global composition root, whatever its folder name.
        elif len(rel.parts) >= 2 and rel.parts[0] in LAYERS:
            layer = rel.parts[0]  # Legacy Scripts/<Layer>/<Module>/... layout.
        elif len(rel.parts) >= 3 and rel.parts[1] == "Api":
            layer = "Api"        # New Scripts/<Module>/Api/... layout.
        elif (len(rel.parts) >= 4 and rel.parts[1] == "Internal"
              and canonical_layer(rel.parts[2])):
            layer = canonical_layer(rel.parts[2])  # Scripts/<Module>/Internal/<Layer>/...
        elif len(rel.parts) == 3 and rel.parts[1] == "Internal":
            layer = "Bootstrap"  # Assembly-level files such as AssemblyInfo.cs.
        elif len(rel.parts) >= 3 and canonical_layer(rel.parts[1]):
            layer = canonical_layer(rel.parts[1])  # Scripts/<Module>/Presentation|Editor/...
        else:
            messages.append(f"{path.relative_to(root)}:1: LAYER: use Scripts/<Module>/Api/ or Scripts/<Module>/Internal/<Layer>/ (legacy Scripts/<Layer>/... accepted)")
            continue
        code = mask_non_code(path.read_text(encoding="utf-8-sig"))
        namespaces = tuple(NAMESPACE_RE.findall(code))
        sources.append(Source(path=path, layer=layer, code=code, namespaces=namespaces))

    # Match explicit construction of known DI-managed classes. This is a hint,
    # not a complete semantic C# resolver (namespaces/generics require Roslyn).
    managed: set[str] = set()
    for source in sources:
        for declaration in CLASS_RE.finditer(source.code):
            preceding = source.code[max(0, declaration.start() - 600):declaration.start()]
            attrs = re.search(r"(?:\[\s*[\w.,()=<> \t]+\s*\]\s*)+$", preceding)
            if attrs and ATTR_RE.search(attrs.group(0)):
                managed.add(declaration.group(1))

    for source in sources:
        code = source.code
        rel = source.path.relative_to(root).as_posix()
        layer = source.layer

        def report(at: int, reason: str) -> None:
            messages.append(f"{rel}:{line_of(code, at)}: {reason}")

        # Forbid ALL else/switch, even in layers not constrained by Unity purity.
        for match in SYNTAX_RE.finditer(code):
            report(match.start(), f"BRANCH: forbidden '{match.group(1) or 'default:'}'; use DI keyed strategies for behavior dispatch")
        unity_facing = layer == "Api" and UNITY_FACING_RE.search(source.path.read_text(encoding="utf-8-sig")) is not None
        if layer in PURE_LAYERS and not unity_facing:
            for match in UNITY_API_RE.finditer(code):
                report(match.start(), f"UNITY: {layer} cannot depend on UnityEngine/UnityEditor")
        if layer not in {"Bootstrap", "Controller", "Integration", "DependencyInjection"}:
            for match in MANUAL_LOOKUP_RE.finditer(code):
                report(match.start(), f"DI: {layer} must not access context / find runtime services")
        for match in DIRECT_LOG_RE.finditer(code):
            report(match.start(), "LOG: direct Debug.Log*/Console.Write*/print; use UniSpring.Logging.GameLog")
        for match in STATIC_INSTANCE_RE.finditer(code):
            report(match.start(), "DI: static Instance singleton is forbidden")
        # The DI core's AutowiredMonoBehaviour is the one class that must derive MonoBehaviour itself.
        for match in (DIRECT_MONO_RE.finditer(code) if layer != "DependencyInjection" else ()):
            report(match.start(), "DI: use AutowiredMonoBehaviour instead of direct MonoBehaviour")
        for match in NEW_RE.finditer(code):
            if match.group(1) in managed:
                report(match.start(), f"DI: do not construct DI-managed '{match.group(1)}' with new")

        if layer == "Service":
            for match in CLASS_RE.finditer(code):
                declaration = match.group(0)
                if re.search(r"\b(?:abstract|static)\b", declaration):
                    continue
                # Use-case folders also hold state and record types; only *Service classes are beans.
                name = re.search(r"\b(?:class|record)\s+(\w+)", declaration)
                if name and not name.group(1).endswith("Service"):
                    continue
                # Inspect adjacent attributes, not arbitrary attributes elsewhere.
                preceding = code[max(0, match.start() - 600):match.start()]
                attrs = re.search(r"(?:\[\s*[\w.,()=<> \t]+\s*\]\s*)+$", preceding)
                if not attrs or not ATTR_RE.search(attrs.group(0)):
                    report(match.start(), "DI: concrete Service class must be annotated [Service]")

        # Resolve local using aliases and fully qualified namespace references.
        candidate_matches = [*USING_RE.finditer(code), *QUALIFIED_RE.finditer(code)]
        checked: set[tuple[int, str]] = set()
        for match in candidate_matches:
            identifier = match.group(1) if match.re is USING_RE else match.group(0)
            target = find_project_layer(identifier, sources)
            if target is None or target == layer or target in ALLOWED[layer]:
                continue
            key = (line_of(code, match.start()), target)
            if key in checked:
                continue
            checked.add(key)
            report(match.start(), f"BOUNDARY: {layer} must not reference project {target}; depend on Ports/contracts")

    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "Assets").is_dir():
        print(f"ERROR: Assets/ not found (root={root})")
        return 2
    try:
        violations = verify_sources(root)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: could not scan sources: {exc}")
        return 2
    for problem in violations:
        print("VIOLATION: " + problem)
    if violations:
        print(f"\n{len(violations)} architecture violation(s); run Unity compilation/tests too.")
        return 1
    print("OK: no detected C# architecture/branching violations (static heuristic only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
