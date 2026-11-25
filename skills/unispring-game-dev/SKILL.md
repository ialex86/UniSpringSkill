---
name: unispring-game-dev
description: Build Unity games on the UniSpring framework (com.ialex86.unispring) - isolated Api/Internal subsystems with clear layers (Api, Domain, Ports, Repository, Integration, Service, Dto, Config, Mapping, Presentation), constructor DI, repositories with mappers and validators for saves, transactions, events, ticks, typed settings, keyed strategies instead of switch/else, GameLog-only diagnostics, player text from language tables, and a multi-agent workflow (Unity lease, contracts-first parallel work, baseline hooks, independent review). Apply to every change under the game's Assets/Src, to designing a subsystem, and to starting a new UniSpring title.
---

# UniSpring game development

Rules and workflow for Unity games built on UniSpring, distilled from NoLegal (an
SLRR remake: ~70 subsystems, several agents sharing one Unity Editor). Apply them
before **every** creation, change, move or deletion of files under `Assets/`, when
designing a subsystem, and when starting a new title.

The skill follows the open Agent Skills format and works in any agent that reads it
(Claude Code, Codex, Cursor, Copilot, …). Per-game settings (code roots, assembly prefix,
shared UI kits, languages, legacy files) live in the project's `unispring-skill.json`;
without it the standard `Assets/Src` / `Assets/Src/Scripts` apply. Below, `<skill>` is
the folder this skill is installed in (e.g. `.claude/skills/unispring-game-dev` or
`.agents/skills/unispring-game-dev`), `<Src>` the game's root (`srcRoot`), `<Scripts>`
the C# root (`scriptsRoot`), `<Prefix>` the assembly prefix.

## Invariants (always)

1. **The only editable zone is `<Src>/`.** `Packages/`, `ProjectSettings/`,
   `Assets/Settings/`, vendor folders and Asset Store packages are read-only without
   the user's explicit yes. Assets move together with their `.meta`; GUIDs never change.
   → `references/architecture.md` §1
2. **A feature is a closed subsystem**: `<Scripts>/<Module>/Api` + `Internal/<Layer>`
   (+ `Presentation`, `Editor`), separate assemblies `<Prefix>.<Module>.Api` and
   `<Prefix>.<Module>.Runtime`. → `references/architecture.md` §2, `references/layers.md`
3. **Modules talk only through another module's `*.Api`**: interfaces, immutable
   DTOs/snapshots, events. Never another module's `Internal`, `Service`, `Dao`,
   `Ports`, or Runtime assembly in an `.asmdef`. `public` ≠ "available to other
   modules". The container enforces this (`ModuleBoundaryOptions { Strict = true }`).
   → `references/architecture.md` §3
4. **DI is UniSpring.** Services are `[Service]` with constructor injection of
   interfaces; MonoBehaviours derive from `AutowiredMonoBehaviour` with `[Autowired]`
   fields and `OnDependenciesInjected()` — **never declare `Awake`**. No `new` for
   beans, `static Instance`, `Find*`, Service Locator or `RuntimeContext.Get` in game
   logic. One composition root (`UniSpringConfiguration`). → `references/unispring.md` §1
5. **Use UniSpring's contracts instead of home-made ones**: saves — `[Repository]` +
   `IRecordMapper` + `IDocumentValidator` + `schemaVersion` + `[Migration]`; several
   documents at once — `[Transactional]`; cross-module notifications —
   `IEventPublisher` + an event in `*.Api`; per-frame logic — `ITickable`/`ILifecycle`;
   shipped tables — `[ConfigurationProperties]`/`[Catalog]`. → `references/unispring.md` §2–7
6. **No `switch` / `case` / `else` / `else if` in new code.** Choose behaviour with
   `[Strategy]` + `IKeyedStrategy<TKey>` + `StrategyRegistry<TKey,T>`; `if` only as a
   guard clause with an early `return`/`throw`. → `references/code-style.md` §1
7. **Diagnostics only through `UniSpring.Logging.GameLog`.** No `Debug.Log*`,
   `Console.Write*`, `print`; never pass `caller`; pass the exception itself, not
   `.Message`. → `references/logging.md`
8. **Player-facing text only from language tables** (`<lang>.json`; keys in code,
   identical keys and placeholders in every language, no unused keys).
   → `references/localization.md`
9. **Read the actual API first** (UniSpring in
   `Library/PackageCache/com.ialex86.unispring@*/Documentation~` and `Runtime/`,
   neighbours' asmdefs and interfaces) — never guess signatures.
10. **Don't fix unrelated legacy violations**, and **don't commit or push** unless asked.
11. **One Unity Editor is shared by all agents**: change the project through Unity MCP
    only while holding the lease (`EditorLease`). → `references/agent-workflow.md` §1
12. **When documentation and code disagree, trust the code** and report the mismatch.

## Working on a task

**Before editing**
1. Classify every path: `<Src>/**` — allowed; anything else — STOP and propose an
   alternative inside `<Src>` (wrapper, adapter, subclass, own prefab, versioned fork).
2. Name the owning module, its public `Api` (what neighbours need) and its hidden
   `Internal`; pick the layer of every new type (`references/layers.md`). Check that
   all outside dependencies are `Other.Api` only.
3. Read the neighbouring contracts, asmdefs and the relevant UniSpring docs.
4. Large or parallel work → **shared contracts first** as a separate change, then the
   work streams (`references/agent-workflow.md` §2).

**While editing**
1. Right layer, constructor DI, strategies instead of branching, `GameLog`,
   localization keys, a `.meta` for every new asset (via `refresh_unity`).
2. Every new `[Service]` can be built in a unit test through its constructor with fakes.
3. Unity changes (scenes, prefabs, Play, tests) in one block under the lease.

**After editing**
1. Run the gate — `python3 <skill>/scripts/gate.py check --root .` (the agent hooks do
   it at the end of the turn where they are installed). It fails only on **new**
   violations; report legacy separately from what you introduced.
2. Unity compiles without your errors; EditMode tests of the touched modules (the
   fast run, without `Slow`); PlayMode/player where behaviour depends on Unity.
3. Have the diff reviewed independently (`references/review.md`: the `reviewer`
   subagent in Claude Code, a subagent or new session elsewhere); fix confirmed
   findings or explain why they don't apply.
4. Report: owning module, changed public API, asmdefs/DI registrations, new
   strategies, checks and their results, remaining risks. No step-by-step recap.

## References (read the relevant one before working)

| File | When |
| --- | --- |
| `references/architecture.md` | asset layout, modules, boundaries, asmdefs, shared kits |
| `references/layers.md` | each layer in detail: Api, Domain, Ports, Repository, Integration/Dao, Service/Component/Strategy, Dto, Config, Mapping, Validation, Presentation, Editor; who may reference whom; naming; how to split a game into modules |
| `references/unispring.md` | DI, saves, transactions, events, ticks, settings, IL2CPP, testing with UniSpring |
| `references/code-style.md` | strategies instead of switch/else, maintainability, Unity runtime and Editor, performance |
| `references/logging.md` | the `GameLog` API, sources, configuration, what and how to log |
| `references/localization.md` | the localization module, keys, tables, the check |
| `references/agent-workflow.md` | Unity MCP and the lease, contracts first and parallel streams, the gate and each agent's hooks, tests, docs, git |
| `references/review.md` | the independent review: how to start it in each agent, what the reviewer checks, the answer format |
| `references/new-project.md` | starting a new title: package, composition root, assemblies, first modules, installing the skill |

## Checks

One gate for every agent, the git pre-commit hook and CI — it fails only on violations
the change added (legacy is listed in the committed `unispring-baseline.json`) and on any
localization problem:

```bash
python3 <skill>/scripts/gate.py check --root .     # the gate: all four checks below
python3 <skill>/scripts/gate.py baseline --root .  # accept today's violations as legacy (once)
```

The individual checks, from the Unity project root:

```bash
S=<skill>/scripts
python3 $S/check-asset-layout.py --root .          # assets outside <Src>, .meta, vendor edits
python3 $S/check-code-architecture.py --root .     # layers, Unity in pure layers, DI, direct logs, switch/else
python3 $S/check-subsystem-boundaries.py --root .  # Api-only between modules, asmdefs
python3 $S/check-localization.py --root .          # tables, parity, MISSING/UNUSED/HARDCODED
python3 -m unittest discover -s <skill>/tests
```

Where installed, each agent's own hooks (Claude Code, Codex, Cursor, Copilot, OpenCode — all through
`scripts/hooks/agent_hook.py`) take a session baseline at start, check every edited file,
and run the gate before the turn ends (`references/agent-workflow.md` §3). Never bypass
the gate (`--no-verify`) and never grow the baseline to hide new code.

A new subsystem: `python3 $S/new-module.py --root . --name <Module> [--presentation]`
— Api/Internal(/Presentation) folders, asmdefs with the right references, a
`[Service]` stub, a test assembly with a first test, `Doc/<Module>/README.md`, and a
line in `link.xml`.

Exit codes: `0` clean, `1` violations, `2` the check could not run. The scripts are
heuristics, not Roslyn: they don't replace compilation, Unity tests and review of the
public API (reflection, serialized scene references and complex C# need a human look).

## When a rule conflicts with existing code

List the conflict, propose a staged migration that doesn't touch vendor files, and
don't move old files "for consistency". The legacy layout `<Scripts>/<Layer>/<Module>/`
is accepted until an agreed migration, but Api boundaries apply to it too.
