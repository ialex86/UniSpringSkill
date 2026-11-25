#!/usr/bin/env python3
"""Scaffold a closed UniSpring subsystem (skill unispring-game-dev).

Creates, using unispring-skill.json (assemblyPrefix, scriptsRoot,
testsRoot, docsRoot, srcRoot):

  <Scripts>/<Name>/Api/<Prefix>.<Name>.Api.asmdef        Unity-free contracts
  <Scripts>/<Name>/Api/I<Name>Api.cs
  <Scripts>/<Name>/Internal/<Prefix>.<Name>.Runtime.asmdef
  <Scripts>/<Name>/Internal/AssemblyInfo.cs              InternalsVisibleTo tests
  <Scripts>/<Name>/Internal/Service/<Name>Service.cs [Service] implementing the Api
  <Scripts>/<Name>/Presentation/<Prefix>.<Name>.Presentation.asmdef   (--presentation)
  <Tests>/<Name>/EditMode/<Prefix>.<Name>.Tests.asmdef + a first test
  <Docs>/<Name>/README.md
  and a <Prefix>.<Name>.Runtime line in <Src>/link.xml when the file exists.

Never overwrites an existing file. Unity creates the .meta files on import
(refresh_unity). Exit 0 = created, 1 = the module already exists, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_config  # noqa: E402

NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
UNISPRING = ["UniSpring.DependencyInjection", "UniSpring.Data", "UniSpring.Transactions", "UniSpring.Logging"]


def asmdef(name: str, references: list[str], editor_only: bool = False, tests: bool = False,
           no_engine: bool = False) -> str:
    data = {
        "name": name,
        # Namespaces follow the folders without "Internal": <Prefix>.<Module>.Service.
        "rootNamespace": name[: -len(".Runtime")] if name.endswith(".Runtime") else name,
        "references": references,
        "includePlatforms": ["Editor"] if editor_only else [],
        "excludePlatforms": [],
        "allowUnsafeCode": False,
        "overrideReferences": tests,
        "precompiledReferences": ["nunit.framework.dll"] if tests else [],
        "autoReferenced": False,
        "defineConstraints": ["UNITY_INCLUDE_TESTS"] if tests else [],
        "versionDefines": [],
        "noEngineReferences": no_engine,
    }
    return json.dumps(data, indent=4) + "\n"


def files(cfg: dict, name: str, presentation: bool) -> dict[Path, str]:
    prefix = cfg["assemblyPrefix"]
    ns = f"{prefix}.{name}"
    scripts = Path(project_config.norm_dir(cfg["scriptsRoot"])) / name
    tests = Path(project_config.norm_dir(cfg["testsRoot"])) / name / "EditMode"
    docs = Path(project_config.norm_dir(cfg["docsRoot"])) / name
    api, runtime, tests_asm = f"{ns}.Api", f"{ns}.Runtime", f"{ns}.Tests"
    result = {
        scripts / "Api" / f"{api}.asmdef": asmdef(api, [], no_engine=True),
        scripts / "Api" / f"I{name}Api.cs": (
            f"namespace {ns}.Api\n{{\n"
            f"    /// <summary>The public contract of {name}: the only type other modules may use.</summary>\n"
            f"    public interface I{name}Api\n    {{\n    }}\n}}\n"),
        scripts / "Internal" / f"{runtime}.asmdef": asmdef(runtime, [api, *UNISPRING]),
        scripts / "Internal" / "AssemblyInfo.cs": (
            "using System.Runtime.CompilerServices;\n\n"
            f"[assembly: InternalsVisibleTo(\"{tests_asm}\")]\n"),
        scripts / "Internal" / "Service" / f"{name}Service.cs": (
            "using UniSpring.DependencyInjection;\n"
            f"using {ns}.Api;\n\n"
            f"namespace {ns}.Service\n{{\n"
            "    [Service]\n"
            f"    internal sealed class {name}Service : I{name}Api\n    {{\n    }}\n}}\n"),
        tests / f"{tests_asm}.asmdef": asmdef(
            tests_asm, ["UnityEngine.TestRunner", "UnityEditor.TestRunner", api, runtime, *UNISPRING],
            editor_only=True, tests=True),
        tests / f"{name}ServiceTests.cs": (
            "using NUnit.Framework;\n"
            f"using {ns}.Api;\n"
            f"using {ns}.Service;\n\n"
            f"namespace {ns}.Tests\n{{\n"
            f"    public sealed class {name}ServiceTests\n    {{\n"
            "        [Test]\n"
            "        public void IsBuiltThroughItsConstructorWithoutTheContainer()\n        {\n"
            f"            I{name}Api api = new {name}Service();\n\n"
            "            Assert.That(api, Is.Not.Null);\n"
            "        }\n    }\n}\n"),
        docs / "README.md": (
            f"# {name}\n\n"
            "What the subsystem does for the player, in one paragraph.\n\n"
            "## Contracts (`Api`)\n\n"
            f"- `I{name}Api` — …\n\n"
            "## Behaviour\n\n## Data and saves\n\n"
            "## Editor menus and builds\n\n## Budgets and limitations\n\n## Tests\n"),
    }
    if presentation:
        name_p = f"{ns}.Presentation"
        result[scripts / "Presentation" / f"{name_p}.asmdef"] = asmdef(
            name_p, [api, "UniSpring.DependencyInjection", "UniSpring.Logging"])
    return result


def add_to_link_xml(root: Path, cfg: dict, runtime: str) -> bool:
    link = root / project_config.norm_dir(cfg["srcRoot"]) / "link.xml"
    if not link.is_file():
        return False
    text = link.read_text(encoding="utf-8")
    if f'"{runtime}"' in text or "</linker>" not in text:
        return False
    line = f'  <assembly fullname="{runtime}" preserve="all"/>\n'
    link.write_text(text.replace("</linker>", line + "</linker>", 1), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--name", required=True, help="PascalCase module name, e.g. Garage")
    parser.add_argument("--presentation", action="store_true", help="also create the Presentation assembly")
    args = parser.parse_args()
    root = args.root.resolve()
    if not NAME_RE.match(args.name):
        print(f"ERROR: module name must be PascalCase: {args.name}")
        return 2
    if not (root / "Assets").is_dir():
        print(f"ERROR: Assets/ not found (root={root})")
        return 2
    try:
        cfg = project_config.load(root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {project_config.CONFIG_NAME}: {exc}")
        return 2
    module_dir = root / project_config.norm_dir(cfg["scriptsRoot"]) / args.name
    if module_dir.exists():
        print(f"EXISTS: {module_dir.relative_to(root)} — nothing created")
        return 1
    for rel, text in files(cfg, args.name, args.presentation).items():
        path = root / rel
        if path.exists():
            print(f"skip (exists): {rel}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"created: {rel}")
    runtime = f"{cfg['assemblyPrefix']}.{args.name}.Runtime"
    if add_to_link_xml(root, cfg, runtime):
        print(f"link.xml: added {runtime}")
    print("Next: refresh_unity (Unity creates the .meta files), compile, run the module's tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
