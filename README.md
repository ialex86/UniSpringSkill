# UniSpringSkill

An agent skill for building Unity games on
[UniSpring](https://github.com/ialex86/UniSpring) (`com.ialex86.unispring`). It collects
the rules and workflow worked out on NoLegal (an SLRR remake): around 70 closed
subsystems, several agents sharing one Unity Editor, and a gate that keeps new
violations out.

It is not tied to one agent:

* the skill itself is in the open **Agent Skills** format (`SKILL.md` + references +
  scripts), read by Claude Code, Codex, Cursor, GitHub Copilot and others;
* the rules every agent reads are in **`AGENTS.md`**; Claude Code's `CLAUDE.md` imports it;
* the checks run through **one gate** (`gate.py`) — from **each agent's own hooks**
  (Claude Code, Codex, Cursor, Copilot, OpenCode), from the **git pre-commit hook** and from **CI**,
  so they hold whoever writes the code;
* the **independent review** is a procedure (`references/review.md`) any agent can run;
  in Claude Code it is also a ready subagent.

## Contents

```text
install.py                         install/update the skill in a Unity project, for any agents
skills/unispring-game-dev/
├── SKILL.md                       invariants and how to work on a task
├── references/
│   ├── architecture.md            Assets/Src layout, Api/Internal modules, boundaries, asmdefs, shared kits
│   ├── layers.md                  every layer: Api, Domain, Ports, Repository, Integration/Dao,
│   │                              Service/Component/Strategy, Dto, Config, Mapping, Validation,
│   │                              Presentation, Editor; who sees whom; naming; modularity
│   ├── unispring.md               DI, repositories/mappers/validators, transactions, events, ticks, settings, IL2CPP, tests
│   ├── code-style.md              strategies instead of switch/else, maintainability, Unity, performance
│   ├── logging.md                 GameLog: API, sources, configuration, what to log
│   ├── localization.md            keys and language tables, the check
│   ├── agent-workflow.md          Unity lease, contracts → parallel streams → int, the gate and hooks, tests, docs, git
│   ├── review.md                  the independent review in every agent
│   └── new-project.md             starting a new title step by step
├── scripts/
│   ├── gate.py                    the gate: the four checks, only new violations fail
│   ├── check-asset-layout.py      assets outside Assets/Src, .meta, vendor edits
│   ├── check-code-architecture.py layers, Unity in pure layers, DI, direct logs, switch/else
│   ├── check-subsystem-boundaries.py  Api-only between modules, asmdefs
│   ├── check-localization.py      tables, parity, MISSING/UNUSED/HARDCODED
│   ├── new-module.py              scaffold a subsystem
│   ├── project_config.py          reads unispring-skill.json
│   └── hooks/agent_hook.py        one hook adapter for Claude Code, Codex, Cursor, Copilot
├── templates/                     AGENTS.md, CLAUDE.md, reviewer, hook configs per agent,
│                                  git pre-commit hook, CI (GitHub, GitLab), UniSpringConfiguration,
│                                  EditorLease, link.xml, logging.properties, .gitattributes,
│                                  unispring-skill.json (+ examples/nolegal.unispring-skill.json)
└── tests/                         unittest for the checks, gate, hooks, installer and scaffolder
```

## Installing into a project

```bash
# a new title, every agent, the gate in git and GitLab CI
python3 install.py --project ~/Games/MyGame --game "My Game" --prefix MG --namespace MyGame \
    --agent all --git-hook --ci gitlab --with-bootstrap --with-lease

# an existing project: accept today's violations as legacy, then commit unispring-baseline.json
python3 install.py --project ~/Games/MyGame --game "My Game" --prefix MG --namespace MyGame \
    --agent claude,codex --git-hook --baseline

# after changes in this repository: refresh every installed copy of the skill
python3 install.py --project ~/Games/MyGame --update
```

| `--agent` | Skill goes to | Hooks go to | Also |
| --- | --- | --- | --- |
| `claude` (default) | `.claude/skills/` | `.claude/settings.json` | `CLAUDE.md` (imports `AGENTS.md`), `reviewer` subagent |
| `codex` | `.agents/skills/` | `.codex/hooks.json` | trust the hooks once with `/hooks` |
| `cursor` | `.agents/skills/` | `.cursor/hooks.json` | |
| `copilot` | `.github/skills/` | `.github/hooks/unispring-gate.json` | Copilot CLI and cloud agent |
| `opencode` | `.agents/skills/` | `.opencode/plugins/unispring-gate.js` | a V2 plugin (OpenCode 2.x) |
| `all` | all of the above | all of the above | |

Always written: `AGENTS.md`, `unispring-skill.json`, `.unispring-cache/` in `.gitignore`.
`--git-hook` installs `.git/hooks/pre-commit` (an existing different hook is kept — call
`gate.py check` from it); `--ci github|gitlab` adds the CI job. Existing project files are
kept unless `--force`; existing hooks in agents' configs are kept and ours are added once.

Then open Unity (it creates the `.meta` files), check the compile and run
`python3 <skill>/scripts/gate.py check --root .`. The order of the first modules:
`references/new-project.md`.

### What each agent's hooks do

| | Claude Code | Codex | Cursor | Copilot | OpenCode |
| --- | --- | --- | --- | --- | --- |
| session start | baseline | baseline | baseline | baseline | baseline (first user message) |
| after an edit | blocks with the reason | `decision: block` | — (checked at stop) | `additionalContext` | appended to the tool result |
| turn end | blocks, one retry | continuation, one retry | `followup_message`, one retry | `decision: block`, one retry | a synthetic message, one retry |

Agents without hooks follow `AGENTS.md`: run the gate before reporting work as done; the
pre-commit hook and CI catch what they miss.

The OpenCode plugin uses the V2 API (`Plugin.define`, checked on OpenCode 2.2.5): V1
`server()` exports are not loaded there. A plugin that fails to load says so only in
`~/.local/share/opencode/log/opencode.log`.

## Per-game settings

`unispring-skill.json` at the Unity project root (`.claude/unispring-skill.json` is read
as a fallback); every key is optional.

| Key | Default | Meaning |
| --- | --- | --- |
| `srcRoot` | `Assets/Src` | the only editable zone |
| `scriptsRoot` | `Assets/Src/Scripts` | modules' C# |
| `assemblyPrefix` / `rootNamespace` | `Game` | `<Prefix>.<Module>.Api`, `<Namespace>.Bootstrap` |
| `testsRoot` / `docsRoot` | `Assets/Src/Tests` / `Assets/Src/Doc` | where `new-module.py` puts tests and the README |
| `compositionRoot` | `Bootstrap` | the composition root's folder |
| `sharedKits` | `[]` | shared presentation kits (`Workshop` in NoLegal) |
| `legacyProjectPrefixes` / `legacyProjectFiles` | Unity template files | known legacy outside `srcRoot` |
| `localization.enabled` | `true` | turn the check off for a game without localization |
| `localization.tables` / `languages` | `…/Resources/Localization`, `["en"]` | tables; the first language is the reference |
| `localization.extraUiSinks` / `extraDiagnostics` | `[]` | regexes of your own UI methods and diagnostic calls |
| `localization.parityMarkers` | `[]` | markers shared by every language (`[hold]`) |
| `localization.presentationPathPattern` | `/Presentation/` | files searched for worded literals |

`UNISPRING_SKILL_CONFIG=<file>` points at another file (CI, trying someone else's
settings). A full example is `templates/examples/nolegal.unispring-skill.json`: with it the
scripts report exactly what NoLegal's original checks report.

## Developing the skill

```bash
cd skills/unispring-game-dev && python3 -m unittest discover -s tests -v
```

Rules specific to one game (importing cars, content, balance) don't belong here: they go
into that project's own skills. This repository holds what will repeat in the next title.
