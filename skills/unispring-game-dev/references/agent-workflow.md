# Agent workflow

## 1. Unity MCP and the editor lease

Unity MCP (`mcp-for-unity`) is connected in each client's own settings (the Claude app,
Claude Code, Codex, Cursor, Copilot), not through an MCP config in the repository: the
path to `uvx` differs per machine, so the repository's MCP config stays empty.

* C# through `execute_code` — with `compiler: "codedom"` (Roslyn may hang in this setup).
* A new `.cs` gets its `.meta` only after an import: `refresh_unity`, wait for the
  compile, read the console (`read_console`).
* Compile errors in the console may belong to another session: fix only your own.

**Several sessions work with one Unity at the same time.** Unity can't tell which
session calls it, so the rule rests on the agent: change the project through Unity MCP
(scenes, scripts through Unity, assets, prefabs, Play, tests, baking) **only while
holding the lease** (`templates/AgentLease/EditorLease.cs`, installed into
`<Src>/AgentLease/Editor`).

```csharp
return <RootNs>.AgentLease.Editor.EditorLease.Acquire("<short-session-name>", "<what I'm doing>"); // OK token=... | BUSY
return <RootNs>.AgentLease.Editor.EditorLease.Renew("<token>");    // when the work takes longer than 10 min
return <RootNs>.AgentLease.Editor.EditorLease.Release("<token>");
return <RootNs>.AgentLease.Editor.EditorLease.Status();
```

* Take the lease before the first changing call; remember the `token`.
* `BUSY` is not an error: do the work that needs no Unity (code in files, logic tests, a
  plan) and check `Status()` later; tell the user if the wait is long. Never release or
  bypass someone else's lease.
* Read-only calls (`read_console`, `find_gameobjects`, `find_in_file`, `unity_docs`,
  `unity_reflect`, `validate_script`, `Status()`) need no lease.
* Prepare changes in advance and do the Unity work in one block; release the lease once
  you are done and the compile has finished — in any case before your reply ends.
* Without renewal the lease expires after 10 minutes; the user can drop it with
  `Tools/Agent Lease/Force Release`; the holder is shown in the Unity window title.

## 2. A big feature: contracts first, then parallel streams

This is how NoLegal's big features (the drift park, the drag strip) were built: 5–7
streams in parallel without conflicts.

1. **Slicing.** Split the feature into streams by owner: world/geometry (`world`),
   lighting (`lights`), stands/dressing (`stands`), rules and AI (`race`, `gangs`), UI and
   texts (`ui`), navigation (`nav`)… A stream = one owning module or clearly separate files.
2. **Shared contracts in one change on the base branch** (`<feature>/base`): Api
   interfaces, DTOs, venue/plan data, events, text keys — "the contracts the helpers build
   against". No implementation, but compiling.
3. **Streams** are `<feature>/<stream>` branches (one git worktree per session) off the
   base. Each implements its side of the contract, tests it against fakes of the
   neighbours and **never changes the contract silently**: a contract change is a
   separate commit on the base, announced to the other streams.
4. **First buildable increment** before polish: plan → Api service → builder skeleton →
   tests; dressing, lights and UI come in later passes.
5. **Integration** on `<feature>/int`: `Merge <feature>/<stream>: <what the player got>`,
   compile and fast tests after every merge; a conflict or a "compile fix" is its own
   clearly named commit. Then `main`.
6. **Every stream is reviewed** by the independent reviewer (§4) before its merge; fixes
   go in as `<Area>: review fixes (<what exactly>)`.
7. The Unity lease (§1) serialises the streams' work in one editor: prepare changes
   outside Unity and keep Unity sessions short.

## 3. The gate, hooks and baseline

The checks are enforced at three levels, so they hold whatever agent (or person) writes
the code:

| Level | What runs | Baseline | Installed by |
| --- | --- | --- | --- |
| the agent's own hooks | `scripts/hooks/agent_hook.py <agent> start\|edit\|stop` | this session's snapshot (`.unispring-cache/`) | `install.py --agent ...` |
| git | `templates/git-hooks/pre-commit` → `gate.py check` | committed `unispring-baseline.json` | `install.py --git-hook` |
| CI | `templates/ci/*` → `gate.py check` | committed `unispring-baseline.json` | `install.py --ci github\|gitlab` |

Agent hooks, by agent:

| Agent | Config | At start | After an edit | Before the turn ends |
| --- | --- | --- | --- | --- |
| Claude Code | `.claude/settings.json` | session baseline | exit 2 + reason | exit 2 + reason, one retry |
| Codex | `.codex/hooks.json` (trust once in `/hooks`) | session baseline | `decision: block` | `decision: block` → a continuation, one retry |
| Cursor | `.cursor/hooks.json` | session baseline | — (no feedback channel) | `followup_message`, one retry |
| Copilot (CLI, cloud agent) | `.github/hooks/unispring-gate.json` | session baseline | `additionalContext` | `decision: block`, one retry |
| OpenCode 2.x | `.opencode/plugins/unispring-gate.js` (V2 plugin) | session baseline (first user message) | text appended to the tool result | a synthetic message, one retry per user message |

* After an edit: direct `Debug.Log*`/`Console.Write*`/`print`, a growing number of
  `switch`/`else` compared with `HEAD`, localization of the file.
* Before the turn ends: the three architecture checks against the session baseline
  (line numbers dropped, so moved legacy isn't "new") plus strict localization. After one
  retry the hook reports instead of looping.
* Cursor and Copilot can also run Claude's hooks from `.claude/settings.json`; the adapter
  recognises the real host and skips when that host's own config is installed.
* Any other agent, or no hooks at all: run `python3 <skill>/scripts/gate.py check --root .`
  before reporting work as done; the git hook and CI catch the rest.

Baseline (legacy) violations are not fixed as part of someone else's task. Shrink the
committed baseline with `gate.py baseline` after fixing legacy; never grow it to hide new
code. `<Src>/Doc/QualityBaseline.md` is where the team records known debt.

## 4. Independent review

Before reporting a change under `Assets/` as done (and before a commit), the diff is
reviewed by someone with a fresh context — `references/review.md` has the procedure and
how to start the reviewer in each agent (the `reviewer` subagent in Claude Code, a
subagent or new session elsewhere). Fix the confirmed findings; explain the rest.

## 5. Tests

* Module logic — EditMode unit tests without the Unity runtime; Unity behaviour —
  EditMode integration/PlayMode; saves — through the TestSupport facade (`unispring.md` §8).
* **Two runs.** The fast one on every change — everything except `[Category("Slow")]`
  (`-testCategory "!Slow"`, Unity MCP `run_tests` with `category_names: ["!Slow"]`). The
  full one before merging into `main` and before a build.
* Mark a test `Slow` right away if it takes over ~5 s after the shared caches (checks
  over the whole world, determinism "build it twice").
* Heavy fixtures (city, world) are built **once per domain** in a shared cache and handed
  out read-only; a test that needs to change one builds its own.
* A timing helper writes `Temp/test-timings.csv` after a run and logs the slowest
  fixtures — that decides what to mark `Slow`.
* Tests check behaviour (text keys, not wording; Api results, not internal fields).
* In a report: the exact command, Unity version and pass/fail/skip, separately for
  EditMode, PlayMode and the player. EditMode doesn't prove an IL2CPP player works.

## 6. Documentation

* `<Src>/Doc/<Module>/README.md` — the subsystem's release docs: contracts, behaviour,
  budgets, limitations, editor menus. Kept inside `<Src>` so it doesn't get lost;
  `<Src>/Doc/README.md` is the index. Plans and task statements don't go there.
* Captures and draft images go into `name~` folders (Unity doesn't import them).
* `<Src>/Doc/ReleaseNotes/YYYY-MM-DD.md` — notes for players for the day's release: only
  what the player sees; no tests, tools, website or promotion. Written from `git log`
  since the previous release.
* Documentation disagrees with code — trust the code, fix the document, say so.
* The project's `AGENTS.md` holds short invariants and links to the skill for every
  agent; `CLAUDE.md` imports it (`@AGENTS.md`) and adds only what is Claude-specific.
  The rules live in the skill.

## 7. Git

* Large binary assets (textures, OBJ/FBX, audio, native plugins) — **Git LFS**; Unity
  assets (`.unity`, `.prefab`, `.asset`, `.mat`, `.meta`) stay text so they diff and
  merge. Force Text serialization.
* Asset Store packages are not in git: the README lists the folder, the package and where
  it is needed.
* Generated content (`<Src>/Generated/`) is in `.gitignore` and built by a menu.
* A commit message says what changed for the game, in plain words
  (`Nitrous: a gamepad button of its own, nothing allocated while it fires`); the body
  says what was rebuilt/baked and why.
* **Commit, push, merge — only when asked.** No `--no-verify` (it skips the gate), no
  rewriting published history.

## 8. Playtests and balance

* The user's playtest numbers are the source of truth for balance ("the leader's target
  is 6000: 5700 in the playtest with effort"). Record them in the commit and in the
  balance table/config; don't "improve" them without a new playtest.
* The user's description of a behaviour ("as asked: the camera on the wheel, four zones")
  is a requirement; deviating from it needs agreement.

## 9. Reporting the work

Briefly: owning module; changed public Api; cross-module dependencies and asmdefs; DI
registrations and new strategies; new text keys; checks (scripts, tests, compile) with
results; `.meta`; what remains risky or unverified. No step-by-step recap.
