#!/usr/bin/env python3
"""Project settings shared by the unispring-game-dev checks and hooks.

Each game keeps its own values in `unispring-skill.json` at the root of the
Unity project (template: `templates/unispring-skill.json`); `.claude/unispring-skill.json`
is still read when the root file is absent. The file belongs to the project, not
to one agent: Claude Code, Codex, Cursor, Copilot, the git hook and CI read it alike. Every key is
optional; a missing key keeps the default below, so a fresh Unity project with
the standard `Assets/Src` layout needs no file at all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_NAME = "unispring-skill.json"
CONFIG_FALLBACKS = (".claude/unispring-skill.json",)
CONFIG_ENV = "UNISPRING_SKILL_CONFIG"
# Legacy violations accepted when the gate was introduced; committed with the project.
BASELINE_NAME = "unispring-baseline.json"

DEFAULTS: dict = {
    # The only editable zone of the project; everything else under Assets/ is vendor.
    "srcRoot": "Assets/Src",
    # C# of the game: Scripts/<Module>/Api|Internal/<Layer>/...
    "scriptsRoot": "Assets/Src/Scripts",
    # Prefix of module assemblies and namespaces: <Prefix>.<Module>.Api / .Runtime.
    "assemblyPrefix": "Game",
    # Root namespace of game-wide code (composition root, AgentLease).
    "rootNamespace": "Game",
    # Where EditMode/PlayMode tests and module docs live.
    "testsRoot": "Assets/Src/Tests",
    "docsRoot": "Assets/Src/Doc",
    # Global composition root folder under scriptsRoot (DI wiring only).
    "compositionRoot": "Bootstrap",
    # Shared presentation kits: infrastructure folders under scriptsRoot whose
    # Api any layer may use and whose presentation only presentation/editor code may use.
    "sharedKits": [],
    # Project files from the Unity template that still live outside srcRoot.
    "legacyProjectPrefixes": ["Assets/Scenes/"],
    "legacyProjectFiles": ["Assets/InputSystem_Actions.inputactions", "Assets/Readme.asset"],
    "localization": {
        "enabled": True,
        # Language tables <lang>.json; the first language is the reference and fallback.
        "tables": "Assets/Src/Resources/Localization",
        "languages": ["en"],
        # Extra regex (joined with |) of game UI calls that take player text.
        "extraUiSinks": [],
        # Extra regex of statements whose strings are diagnostics, not player text.
        "extraDiagnostics": [],
        # Literal markers that must appear in every language or in none (e.g. "[hold]").
        "parityMarkers": [],
        # Regex of a code line that hands text to the player (for HARDCODED); empty = all game code.
        "presentationPathPattern": "/Presentation/",
    },
}


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
            continue
        result[key] = value
    return result


def load(root: Path) -> dict:
    """Defaults merged with the project's file; a broken file is an error, not a silent default.

    UNISPRING_SKILL_CONFIG=<path> points at another file (CI, trying settings out).
    """
    override = os.environ.get(CONFIG_ENV)
    if override and not Path(override).is_file():
        raise ValueError(f"{CONFIG_ENV} points at a missing file: {override}")
    path = Path(override) if override else find(root)
    if path is None:
        return _merge(DEFAULTS, {})
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_NAME} must be a JSON object")
    return _merge(DEFAULTS, data)


def find(root: Path) -> Path | None:
    """The project's settings file, or None when the project keeps the defaults."""
    for name in (CONFIG_NAME, *CONFIG_FALLBACKS):
        path = Path(root) / name
        if path.is_file():
            return path
    return None


def norm_dir(value: str) -> str:
    """'Assets/Src/' -> 'Assets/Src'."""
    return value.strip().strip("/")
