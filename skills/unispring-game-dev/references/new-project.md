# Starting a new UniSpring title

The order NoLegal had to establish after the fact. In a new project it is done on day
one, while there is nothing to violate yet: every check is strict from the start.

## 1. Project and repository

1. Unity 6 (URP or the pipeline you need), **Force Text** serialization, Visible Meta Files.
2. `git init`, `git lfs install`; `.gitattributes` from `templates/gitattributes` (binaries
   in LFS, Unity assets as text); the standard Unity `.gitignore` + `Assets/Src/Generated/`
   (the installer adds `.unispring-cache/`).
3. The UniSpring package in `Packages/manifest.json` **pinned to a version tag** (not a
   branch): `"com.ialex86.unispring": "https://github.com/ialex86/UniSpring.git#vX.Y.Z"`.
   Read `Documentation~/getting-started.md` of the installed version.
4. Asset Store packages are not in git; a "folder / package / where needed" table in
   `README.md`.

## 2. Skill, hooks, gate

From the skill repository, for the agents the team uses:

```bash
python3 install.py --project /path/to/Game --game "Game Name" --prefix GAME --namespace GameName \
    --agent all --git-hook --ci gitlab --with-bootstrap --with-lease
```

The installer (`install.py`, never overwrites a project file without `--force`):

* copies the skill where each agent looks for skills — `.claude/skills/` (Claude Code),
  `.agents/skills/` (Codex, Cursor), `.github/skills/` (Copilot);
* writes `unispring-skill.json` (paths, prefix, languages, kits) and `AGENTS.md` (the
  rules for every agent); for Claude Code also `CLAUDE.md` (imports `AGENTS.md`) and the
  `reviewer` subagent;
* adds each agent's hooks to its own config, keeping the hooks already there
  (`references/agent-workflow.md` §3); Codex asks to trust them once in `/hooks`;
* `--git-hook` — the gate as the git pre-commit hook; `--ci github|gitlab` — the gate in CI;
* `--baseline` — record today's violations as accepted legacy (an existing project);
  commit `unispring-baseline.json`;
* `--with-bootstrap` — `UniSpringConfiguration.cs`, the composition root's asmdef,
  `link.xml`, `logging.properties.txt`, an empty language table, `.gitattributes`;
* `--with-lease` — `EditorLease` in `Assets/Src/AgentLease/Editor/`.

Then open Unity (it creates the `.meta` files), check the compile, and run
`python3 <skill>/scripts/gate.py check --root .` — it must pass.

Update the skill in a project later: `python3 install.py --project ... --update`
(refreshes every installed copy).

## 3. Composition root

`<Scripts>/Bootstrap/UniSpringConfiguration.cs` is the **only** place that configures the
container (template `templates/Bootstrap/UniSpringConfiguration.cs.template`):

* `ModuleBoundaryOptions { Enabled = true, Strict = true }`, the composition root's
  assembly in `SharedAssemblies`;
* a scan filter: assemblies with `Editor`/`Tests` in the name are not scanned (TestSupport
  fakes don't end up in the game);
* `FileDocumentStore.Install(context, SaveRoot())` — `persistentDataPath/<Game>/Store`,
  overridable with `<GAME>_SAVE_ROOT`;
* `LoggingPathOptions` (`<GAME>_LOG_CONFIG`, `Src/Resources/logging.properties.txt`,
  `RequiredInEditor = true`) and `GameLog.ConfigureSource` for Play and the editor;
* `[RuntimeInitializeOnLoadMethod(SubsystemRegistration)]` — before the first scene and
  the first log entry.

It only configures; it resolves no beans.

## 4. First modules (in this order)

1. **Saves** — an `IDocumentSerializer` (JSON through `JsonUtility`) as a `[Component]`,
   `SaveRecovery.Replace` in `<Prefix>.Saves.Api` — the game's one policy for writing over a
   broken save (`references/layers.md` §6), `<Prefix>.Saves.TestSupport` with an in-memory
   facade for every module's tests. Repositories need the serializer to exist.
2. **Localization** — `ILocalizationApi`, tables `en.json` (+ languages), a fake for tests
   (`references/localization.md`). Port it from NoLegal with the prefix renamed.
3. **GameSettings** — graphics/audio/controls through `IDocument<T>` +
   `[ConfigurationProperties]` for the defaults.
4. **GameInput** — InputActions in `<Src>/Input`, an Api of the game's actions rather than
   InputSystem types.
5. Then the gameplay modules, each: `python3 scripts/new-module.py --name <Module>`
   (folders `Api/`, `Internal/`, `Presentation/`, tests and asmdefs with the right
   references, the `link.xml` line, `<Src>/Doc/<Module>/README.md`), then the layers as in
   `references/layers.md`.

For mobile/console games: an IL2CPP build with `Generate IL2CPP Proxies` in the very first
iteration, so unexplained AOT behaviour doesn't pile up.

## 5. Infrastructure that paid off in NoLegal

* a shared presentation kit for recurring UI (`sharedKits`), as soon as a second module
  needs it;
* background computation through one module ("gather → compute → apply");
* a performance capture in builds behind a command-line flag, and profiler markers;
* shader warm-up at start, with the collection recorded by a benchmark;
* a test timing helper and the `Slow` category;
* the Unity lease for parallel agents;
* generating the world from an editor menu into `Generated/` instead of building scenes
  by hand.

## 6. Checklist: "ready for parallel work"

- [ ] `gate.py check` passes; the agent hooks fire (an edit adding `else` is flagged) and the
      pre-commit hook rejects a commit with a new violation; CI runs the gate.
- [ ] The container starts in Play without resolution errors, `Strict = true`.
- [ ] Saves and Localization with TestSupport exist; EditMode tests are green.
- [ ] `EditorLease` acquires and releases; the window title shows the holder.
- [ ] The independent review (`references/review.md`) can be started in every agent the team uses.
- [ ] README: Unity version, LFS, Asset Store packages, how to build generated content.
