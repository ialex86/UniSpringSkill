# Code: strategies instead of branching, maintainability, Unity, performance

## 1. No switch / else / else if

New and changed game code must not contain:

* `switch` / `case` / `default:`, including `switch` expressions;
* `else` and `else if` in any form;
* nested `if`s / chains of independent `if`s, ternary chains, `Func`/`Action` tables,
  static delegate dictionaries, hand-written factories and `GetService`/reflection used
  to **get around** this rule when choosing behaviour.

Variants of algorithms, modes, formats, material types, vehicles etc. are separate
`[Strategy]` implementations of a common `IKeyedStrategy<TKey>` interface, chosen
through `StrategyRegistry<TKey, TStrategy>` (`Require(key)` throws when the key is
missing, `TryGet` for optional behaviour; duplicate keys fail when the registry is built).

```csharp
public interface IMaterialImportStrategy : IKeyedStrategy<MaterialKind>
{
    ImportedMaterial Import(MaterialSource source);
}

[Strategy]
internal sealed class GlassImportStrategy : IMaterialImportStrategy
{
    public IEnumerable<MaterialKind> Keys
    {
        get { yield return MaterialKind.Glass; }   // a strategy may serve several keys
    }

    public ImportedMaterial Import(MaterialSource source) { /* ... */ }
}

[Service]
internal sealed class MaterialImportService
{
    private readonly StrategyRegistry<MaterialKind, IMaterialImportStrategy> m_Strategies;

    public MaterialImportService(StrategyRegistry<MaterialKind, IMaterialImportStrategy> strategies)
        => m_Strategies = strategies;

    public ImportedMaterial Import(MaterialSource source)
        => m_Strategies.Require(source.Kind).Import(source);
}
```

Allowed:

* `if` as a guard clause / fail-fast / precondition and error check with an early
  `return`/`throw`, without an `else` branch;
* ordinary boolean expressions, loops, `??`, a single ternary for a value (not to pick a
  behaviour implementation);
* a **data** table (a dictionary enum → localization key, enum → number).

Don't create a Strategy class for a `null` check, a simple validity condition or a
`throw`. Two variants of behaviour are strategies too, if they really are different
implementations. Preprocessor `#else` is not the `else` keyword.

## 2. Maintainability

* One class, one responsibility; no God classes or "manager of everything". Composition
  over inheritance for independent behaviour.
* Simple methods, early exits, little nesting. Review guides: a file up to ~250 lines, a
  method up to ~40 — guides, not limits.
* An interface where there is an architectural boundary, DI, polymorphism or a test
  need — not for every value object.
* No hidden mutable global state, static managers, side effects in mappers, stray
  access to the scene.
* Document public APIs and non-trivial algorithms where it helps.
* New third-party dependencies and "infrastructure for later" only for a real task.
* Field names: `m_Name` for instance, `s_Name` for static fields (as in Unity's C#
  reference and the skill's templates); follow the style the project already uses.

## 3. Unity runtime and Editor

* A `MonoBehaviour` handles lifecycle/events and delegates; game logic doesn't live in
  `Update`, `Awake` or inspector fields.
* A `ScriptableObject` is serialized data/settings, not a singleton or service.
* `UnityEngine`/`UnityEditor` only in adapters and outer layers; don't pull `GameObject`,
  `Transform`, `Material` or SDK types into Domain, Ports, Service, Dto, Validation or pure
  Mapping.
* `UnityEditor` only in editor-only assemblies. Importing source assets: a pure
  parser/Domain + an Editor/Integration part working with `AssetDatabase`.
* Unsubscribe from events, tear down scopes, cancel async work, respect the main thread.
* Generated content (the world, cities, baked data) is built by an editor menu into
  `<Src>/Generated/`; it is not in git, and the build is deterministic (same seed → same
  result, covered by a test).

## 4. Performance

* **No allocations on hot paths** (every frame, physics, while an effect runs): cached
  buffers, no LINQ, closures, boxing or strings. Verify in the Profiler.
* No logs and no events every frame.
* Profiler markers on heavy systems, a performance capture in builds behind a
  command-line flag (a `PerfCapture` module, `-perflog`), shader warm-up at start.
* Heavy computation: "gather on the main thread → compute in the background → apply on
  the main thread", through one shared mechanism, not threads in every module.
* Lights and shadows on budgets per quality level (shadows only for the nearest
  sources, hysteresis when switching), far LODs without fine geometry.
