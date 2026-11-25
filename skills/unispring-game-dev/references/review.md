# Independent review

Before reporting a change under `Assets/` as done, and before a commit, the diff is
reviewed by someone who did not write it. The procedure is the same in every agent;
only how the reviewer is started differs:

| Agent | How to start the reviewer |
| --- | --- |
| Claude Code | the `reviewer` subagent (`.claude/agents/reviewer.md`, installed by `install.py`) |
| Codex, Cursor, Copilot, OpenCode, others with subagents or background agents | a subagent / new agent session with the prompt: "Review the current diff following `<skill>/references/review.md`. Change nothing; report findings." |
| an agent without subagents | a new chat/session with that prompt; only if that is impossible, review yourself after re-reading every changed file whole, and say in the report that the review was not independent |

`<skill>` is the folder the skill is installed in (`.claude/skills/unispring-game-dev`,
`.agents/skills/unispring-game-dev`, `.github/skills/unispring-game-dev`).

The author then fixes every **CONFIRMED** finding or explains why it doesn't apply, and
checks the **PLAUSIBLE** ones in Unity.

## The reviewer's procedure

You did not see the code being written and must not trust it. You **change nothing**:
you only read and report. Shell commands are read-only (`git diff`, `git show`,
`git log`, `rg`, the check scripts); no file edits, `git add`, `commit`, `checkout`,
`reset`, `stash`.

1. **Scope**: the commits or files the caller named; otherwise `git diff HEAD` plus the
   untracked files from `git status --porcelain -- Assets/`.
2. **Rules**: read `AGENTS.md` (or `CLAUDE.md`), `<skill>/SKILL.md` and the references for
   the topics the diff touches — layers in `references/layers.md`.
3. **Context**: for every changed file read **the whole file** and its neighbours
   (interfaces, asmdefs, callers), not only the diff. Check DI/Data/GameLog signatures
   against the package (`Library/PackageCache/com.ialex86.unispring@*/Runtime/`,
   `Documentation~/`) and `Assets/Src/Scripts/Bootstrap/UniSpringConfiguration.cs`.
4. **Checks**: run `python3 <skill>/scripts/gate.py check --root .` and separate the
   violations the diff introduced from legacy.

## What to look for (most important first)

- **Correctness:** logic errors, nulls, Unity initialisation order
  (`Awake`/`OnEnable`/`DefaultExecutionOrder`), main thread, unsubscribing, dispose, saves
  (strict `Read`, a broken document not overwritten, `schemaVersion`, migrations),
  transactions (called through an interface, rollback), backward compatibility of data.
- **Module boundaries and layers:** dependencies only on other modules' `*.Api`; each type
  in the right layer; internal types, Unity types and mutable collections not leaking into
  a public Api; `.asmdef` references; a new Runtime assembly added to `link.xml`.
- **DI:** constructor injection; `AutowiredMonoBehaviour` without its own `Awake`; no `new`
  for services, `Find*`, singletons, Service Locator; lifetimes; `[Primary]` with several
  implementations; IL2CPP proxies regenerated after `[Repository]`/`[Catalog]`/
  `[Transactional]` changes.
- **Branching:** no new `switch`/`else`/`else if`; behaviour chosen through `[Strategy]` +
  `StrategyRegistry`; `if` only as guard clauses.
- **Logging:** only `GameLog`; exceptions not swallowed and passed whole; no per-frame
  logs; expensive messages lazy.
- **Localization:** no player text in code; keys in every table; removed code took its keys.
- **Performance:** no allocations or events on hot paths.
- **Assets:** changes only in `Assets/Src/`; new assets have `.meta`, moved ones kept their
  GUID; vendors, `Packages/`, `ProjectSettings/` untouched.
- **Tests:** new logic is covered; tests check behaviour, not implementation.

## Answer format

Findings, most serious first. For each:
- `path:line` — one sentence on what is wrong;
- a concrete failure scenario (input or state → result);
- confidence: **CONFIRMED** (verified in code) or **PLAUSIBLE** (needs a check in Unity).

No style nitpicks and no retelling of the diff. If there are no serious problems, say so
in one line and list what you checked. Finish with one line giving the number of legacy
violations that the diff did not introduce.
