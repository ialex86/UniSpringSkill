# Logging: only UniSpring.Logging.GameLog

**All diagnostic output of game code** under `<Src>` (Runtime, Presentation, Editor,
Demo, Sandbox, tests) goes through `UniSpring.Logging.GameLog`. Direct
`UnityEngine.Debug.Log/LogWarning/LogError/LogException/LogFormat`,
`System.Console.Write*` and `MonoBehaviour.print` are forbidden; no home-made loggers or
a second global backend. The Unity sink and the startup fallback live in the UniSpring
package, so there is no legitimate place for `Debug.Log*` in `<Src>`.

`Debug.DrawRay`/`Debug.DrawLine` and `LogAssert.Expect` in tests are a different API —
leave them alone.

## API (check against `Runtime/Logging/GameLog.cs` of the installed package)

* `GameLog.Debug/Info/Warn/Error(object message, Object context = null)`.
* `GameLog.Debug/Info/Warn/Error(Func<object> messageFactory, ...)` — lazy construction of
  an expensive message.
* `GameLog.Debug/Warn/Error(object message, Exception exception, Object context = null)` —
  **the** way to log a handled exception: one entry, the stack kept, a double click
  leads to the throw site. Passing only `exception.Message` is forbidden.
* `GameLog.Error(Exception exception, Object context = null)` — an exception without text.
* `context` is a `UnityEngine.Object` (Renderer, GameObject, MonoBehaviour), **not** a
  textual stage/path. Stage ids, asset paths, resource ids go into the `message`.
* **Never pass** the `caller` argument (`[CallerFilePath]`) — neither `null` nor a string:
  per-source levels depend on it. A guard test in the project that checks the sources
  for this is worth having.
* No module prefix in the text (`[Garage] ...`): the source is printed anyway.
* `GameLog.IsEnabled(level)` / `GameLog.IsDebugEnabled()` — check before building
  expensive data. `GameLog.Reload()` re-reads the configuration.
* Log and exception texts are for developers: English, in code (not in localization tables).

## Sources and levels

A source is the file's path relative to `<Src>/` without `Scripts/` and `Internal/`:
`Garage/Internal/Service/LiftService.cs` → `Garage.Service.LiftService`. It is configured
once in the composition root:
`GameLog.ConfigureSource(new GameLogSourceOptions { SourceRoot = "/Assets/Src/",
IgnoredSegments = new[] { "Scripts", "Internal" } })` — for Play and for the editor
(`[InitializeOnLoadMethod]`) so the names match.

`logging.properties` (levels `Debug`, `Info`, `Warn`, `Error`, `None`):

```properties
root=Info
Garage=Debug
Garage.Presentation=Warn
LiftService=Debug
```

A key matches the full source, the file name or any enclosing prefix; the longest
prefix wins.

Where the file is found is set by `LoggingPathOptions` in the composition root: the
game's environment variable (`<GAME>_LOG_CONFIG`), in the editor
`<Src>/Resources/logging.properties.txt` (`RequiredInEditor = true`), in a player
`persistentDataPath` → `StreamingAssets` → the `Resources` asset `logging.properties`.
On Android/WebGL `StreamingAssets` is not read — ship the config through `Resources`.

## asmdef and lifecycle

* An assembly that logs references `UniSpring.Logging`.
* Never call `GameLog.InstallBackend` or create a `GameLogService` by hand. The
  container installs its backend and removes it on `Dispose`; a second context in a test
  is safe.

## What to log

* A handled exception — through `GameLog` with the original `Exception`; or rethrow; or
  return an explicit error/result. Never silently swallow failures of saves, DI,
  pipelines or queues. Expected absence of optional data — `Try...` without an exception
  and without spam.
* A failed pipeline stage changes the structured result and blocks publishing; a log
  line is not handling and no reason to report success.
* Meaningful points: errors, warnings, the outcome of an editor/batch operation, lost
  input data, asset save/import failures, significant state transitions.
* **Don't log** every frame, mesh, renderer or element of a big loop: one aggregated
  Info/Warn/Error, details in a lazy `Debug`.

## Check

```bash
rg -n 'Debug\.(Log|LogWarning|LogError|LogException|LogFormat)|Console\.(Write|WriteLine)|\bprint\s*\(' Assets/Src --glob '*.cs'
```

`check-code-architecture.py` reports it as `LOG:` (so the gate, the git hook and CI
catch it), and the agent hooks flag it right after the edit. A static search doesn't
prove exceptions are handled correctly — that takes tests.
