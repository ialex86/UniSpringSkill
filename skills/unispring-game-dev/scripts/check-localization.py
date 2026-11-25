#!/usr/bin/env python3
"""Localization guard (skill `unispring-game-dev`, references/localization.md).

Settings: the "localization" section of unispring-skill.json
(tables folder, languages, extra UI sinks, parity markers).

Checks, under the project's srcRoot:
  * TABLE    every language table parses as one flat JSON object of strings,
             without duplicate keys, and every configured language has one;
  * PARITY   all tables have the same keys and the same {n} placeholders;
  * MISSING  a key the code asks for is in the tables;
  * UNUSED   every table key is used by game code (a string literal);
  * HARDCODED  game code carries no player-facing text: no Cyrillic literal
             anywhere in game code, and no worded literal handed to a UI sink
             (label .text, SetText, SetStatus/SetMessage, Show*, plus the
             project's extraUiSinks) in presentation code. Log, exception and
             inspector strings are fine.

Game code = <scriptsRoot>/**/*.cs outside Editor folders. Tests and
editor tooling are not player-facing. A line can opt out with the comment
`// i18n-ignore` (data such as brand names or format patterns).

Usage: check-localization.py --root <repo> [--file <path>]
Output: "VIOLATION: <path>:<line>: <CODE>: <message>". Exit 0 clean, 1 violations, 2 error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_config  # noqa: E402

# Set by configure() from unispring-skill.json.
TABLES = "Assets/Src/Resources/Localization"
SCRIPTS = "Assets/Src/Scripts"
LANGUAGES: list[str] = ["en"]
PARITY_MARKERS: list[str] = []
PRESENTATION_RE = re.compile("/Presentation/")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
PLACEHOLDER_RE = re.compile(r"\{(\d+)(?:[^{}]*)\}")
CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
# Words a player reads: two words, a "Label:" prefix or one Title-case word.
PROSE_RE = re.compile(r"[A-Za-z]{2,}\S*\s+\S*[A-Za-z]{2,}|[A-Za-z]{2,}:\s*$|^\s*[A-Z][a-z]{2,}\s*$")
MARKUP_RE = re.compile(r"<[^>]*>|\{\d*\}")
# Where Presentation code hands text to the player. A literal with words in
# such a statement must come from the tables.
BASE_UI_SINKS = (
    r"\.(?:text|title|tooltip|label)\s*=|\.SetText\s*\(|"
    r"\bSet(?:Status|Message|StatusLine|Header|Label|Title|Caption|Hint|Tooltip)\s*\(|"
    r"\bShow(?:State|Error|Page|Loading|Message|Toast|Hint)?\s*\(|\b(?:Caption|DisplayTitle)\b")
UI_SINK_RE = re.compile(BASE_UI_SINKS)
KEY_CALL_RE = re.compile(r"(?:\.Text|\bTextKey|\.Get|\.TryGet)\s*\(\s*(?:new\s+TextKey\s*\(\s*)?$")
# Statements whose strings are for developers, not players.
BASE_DIAGNOSTICS = (
    r"GameLog\.|Exception\s*\(|\bnameof\s*\(|\[\s*(?:Tooltip|Header|Range|Menu|MenuItem|ContextMenu|"
    r"AddComponentMenu|Obsolete)\b|\.name\s*=|new\s+GameObject\s*\(|\bFind\w*\s*\(|Shader\.Find|"
    r"Resources\.Load|PropertyToID|\.ToString\s*\(|"
    r"\bDebug\.|Assert\.|Profiler\w*\.|\bUnityEngine\.Debug")
DIAGNOSTIC_RE = re.compile(BASE_DIAGNOSTICS)
IGNORE_MARK = "i18n-ignore"


def violation(path: str, line: int, code: str, message: str) -> str:
    return f"VIOLATION: {path}:{line}: {code}: {message}"


# ------------------------------------------------------------------ C# lexing

def lex(source: str):
    """Yield ('comment'|'string', start, end, value) and return masked code.

    Handles // and /* */ comments, regular, verbatim (@"") and interpolated
    ($"", $@"") strings and char literals. Interpolation holes are kept as
    code; only the literal text parts are reported.
    """
    tokens = []
    code = list(source)
    i, n = 0, len(source)

    def blank(a: int, b: int) -> None:
        for j in range(a, b):
            if code[j] not in "\r\n":
                code[j] = " "

    while i < n:
        c = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
            tokens.append(("comment", i, end, source[i:end]))
            blank(i, end)
            i = end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end < 0 else end + 2
            blank(i, end)
            i = end
            continue
        if c == "'":
            j = i + 1
            while j < n and source[j] != "'":
                j += 2 if source[j] == "\\" else 1
            blank(i, min(n, j + 1))
            i = j + 1
            continue
        m = re.match(r'(\$@|@\$|\$|@)?"', source[i:i + 3])
        if m:
            prefix = m.group(1) or ""
            verbatim = "@" in prefix
            interpolated = "$" in prefix
            j = i + len(m.group(0))
            text = []
            depth = 0
            while j < n:
                ch = source[j]
                if interpolated and depth == 0 and ch == "{":
                    if source.startswith("{{", j):
                        text.append("{")
                        j += 2
                        continue
                    depth = 1
                    text.append("{}")
                    j += 1
                    continue
                if depth > 0:
                    depth += {"{": 1, "}": -1}.get(ch, 0)
                    j += 1
                    continue
                if not verbatim and ch == "\\":
                    text.append(source[j:j + 2])
                    j += 2
                    continue
                if ch == '"':
                    if verbatim and source.startswith('""', j):
                        text.append('"')
                        j += 2
                        continue
                    break
                if ch == "\n" and not verbatim:
                    break
                text.append(ch)
                j += 1
            end = min(n, j + 1)
            tokens.append(("string", i, end, decode("".join(text))))
            blank(i, end)
            i = end
            continue
        i += 1
    return tokens, "".join(code)


def decode(text: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return bytes(text, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return text


def line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def statement(code: str, start: int, end: int) -> str:
    a = max(code.rfind(";", 0, start), code.rfind("{", 0, start), code.rfind("}", 0, start))
    b = code.find(";", end)
    b = len(code) if b < 0 else b
    return code[a + 1:b]


# ------------------------------------------------------------------ tables

def configure(cfg: dict) -> bool:
    """Apply the project's settings; False when localization checks are off."""
    global TABLES, SCRIPTS, LANGUAGES, PARITY_MARKERS, PRESENTATION_RE, UI_SINK_RE, DIAGNOSTIC_RE
    section = cfg["localization"]
    TABLES = project_config.norm_dir(section["tables"])
    SCRIPTS = project_config.norm_dir(cfg["scriptsRoot"])
    LANGUAGES = list(section["languages"]) or ["en"]
    PARITY_MARKERS = list(section["parityMarkers"])
    PRESENTATION_RE = re.compile(section["presentationPathPattern"] or ".")
    UI_SINK_RE = re.compile("|".join([BASE_UI_SINKS, *section["extraUiSinks"]]))
    DIAGNOSTIC_RE = re.compile("|".join([BASE_DIAGNOSTICS, *section["extraDiagnostics"]]))
    return bool(section["enabled"])


def load_languages(root: Path) -> list[str]:
    return list(LANGUAGES)


def load_tables(root: Path, out: list[str]) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {}
    folder = root / TABLES
    for path in sorted(folder.glob("*.json")):
        rel = path.relative_to(root).as_posix()
        duplicates: list[str] = []

        def pairs(items):
            seen = {}
            for key, value in items:
                if key in seen:
                    duplicates.append(key)
                seen[key] = value
            return seen

        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)
        except json.JSONDecodeError as error:
            out.append(violation(rel, error.lineno, "TABLE", f"not valid JSON: {error.msg}"))
            continue
        if not isinstance(data, dict):
            out.append(violation(rel, 1, "TABLE", "a table is one flat JSON object"))
            continue
        for key in duplicates:
            out.append(violation(rel, 1, "TABLE", f"duplicate key \"{key}\""))
        for key, value in data.items():
            if not isinstance(value, str):
                out.append(violation(rel, 1, "TABLE", f"\"{key}\" is not a string"))
            if not KEY_RE.match(key):
                out.append(violation(rel, 1, "TABLE", f"\"{key}\" is not a key (lower_case.dotted.segments)"))
        tables[path.stem] = {k: v for k, v in data.items() if isinstance(v, str)}
    return tables


def table_line(root: Path, language: str, key: str) -> int:
    path = root / TABLES / f"{language}.json"
    for number, text in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if f'"{key}"' in text:
            return number
    return 1


def check_tables(root: Path, tables: dict[str, dict[str, str]], languages: list[str], out: list[str]) -> None:
    for language in languages:
        if language not in tables:
            out.append(violation(f"{TABLES}/{language}.json", 1, "TABLE", f"no table for configured language \"{language}\""))
    for language in tables:
        if language not in languages:
            out.append(violation(f"{TABLES}/{language}.json", 1, "TABLE",
                                 f"\"{language}\" is not a configured language (localization.languages)"))
    reference = languages[0] if languages and languages[0] in tables else None
    if reference is None:
        return
    base = tables[reference]
    for language, table in tables.items():
        if language == reference:
            continue
        rel = f"{TABLES}/{language}.json"
        for key in sorted(set(base) - set(table)):
            out.append(violation(rel, 1, "PARITY", f"\"{key}\" is missing (present in {reference})"))
        for key in sorted(set(table) - set(base)):
            out.append(violation(rel, table_line(root, language, key), "PARITY", f"\"{key}\" is not in {reference}"))
        for key in sorted(set(base) & set(table)):
            if sorted(set(PLACEHOLDER_RE.findall(base[key]))) != sorted(set(PLACEHOLDER_RE.findall(table[key]))):
                out.append(violation(rel, table_line(root, language, key), "PARITY",
                                     f"\"{key}\" placeholders differ from {reference}"))
            for marker in PARITY_MARKERS:
                if (marker in base[key]) != (marker in table[key]):
                    out.append(violation(rel, table_line(root, language, key), "PARITY",
                                         f"\"{key}\" {marker} marker differs from {reference}"))


# ------------------------------------------------------------------ code

def game_sources(root: Path) -> list[Path]:
    result = []
    for path in sorted((root / SCRIPTS).rglob("*.cs")):
        parts = path.relative_to(root).parts
        if "Editor" in parts:
            continue
        result.append(path)
    return result


def check_code(root: Path, path: Path, known: set[str], prefixes: set[str],
               used: set[str] | None, out: list[str]) -> None:
    rel = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8-sig")
    tokens, code = lex(source)
    lines = source.splitlines()
    presentation = PRESENTATION_RE.search("/" + rel) is not None
    for kind, start, end, value in tokens:
        if kind != "string":
            continue
        number = line_of(source, start)
        line_text = lines[number - 1] if number - 1 < len(lines) else ""
        if KEY_RE.match(value):
            if used is not None:
                used.add(value)
            asks = KEY_CALL_RE.search(code[max(0, start - 60):start]) is not None
            if value not in known and (asks or value.split(".")[0] in prefixes):
                out.append(violation(rel, number, "MISSING", f"\"{value}\" is not in the language tables"))
            continue
        if IGNORE_MARK in line_text:
            continue
        if CYRILLIC_RE.search(value):
            out.append(violation(rel, number, "HARDCODED",
                                 f"text in code: \"{value[:60]}\" — move it to the language tables"))
            continue
        if not presentation or not PROSE_RE.search(MARKUP_RE.sub(" ", value)):
            continue
        context = statement(code, start, end)
        if not UI_SINK_RE.search(context) or DIAGNOSTIC_RE.search(context):
            continue
        out.append(violation(rel, number, "HARDCODED",
                             f"player-facing text in code: \"{value[:60]}\" — use ILocalizationApi"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--file", default=None, help="check one changed file (fast hook mode)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        enabled = configure(project_config.load(root))
    except (OSError, ValueError, re.error) as error:
        print(f"error: {project_config.CONFIG_NAME}: {error}", file=sys.stderr)
        return 2
    if not enabled:
        print("localization: disabled in " + project_config.CONFIG_NAME)
        return 0
    if not (root / SCRIPTS).exists():
        print(f"error: {root / SCRIPTS} not found", file=sys.stderr)
        return 2

    out: list[str] = []
    languages = load_languages(root)
    tables = load_tables(root, out)
    known = set().union(*tables.values()) if tables else set()
    prefixes = {key.split(".")[0] for key in known}

    if args.file:
        path = Path(args.file).resolve()
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            return 0
        if rel.startswith(TABLES + "/"):
            check_tables(root, tables, languages, out)
        is_game = rel.startswith(SCRIPTS + "/") and rel.endswith(".cs") and "/Editor/" not in "/" + rel
        if is_game and path.exists():
            check_code(root, path, known, prefixes, None, out)
    else:
        check_tables(root, tables, languages, out)
        used: set[str] = set()
        for path in game_sources(root):
            check_code(root, path, known, prefixes, used, out)
        reference = languages[0] if languages and languages[0] in tables else next(iter(tables), None)
        if reference is not None:
            for key in sorted(set(tables[reference]) - used):
                out.append(violation(f"{TABLES}/{reference}.json", table_line(root, reference, key), "UNUSED",
                                     f"\"{key}\" is not used by any game code"))

    for line in out:
        print(line)
    if not out:
        print("localization: OK" + ("" if args.file else f" ({len(known)} keys, {len(tables)} languages)"))
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
