# UniSpring: DI, saves, transactions, events, ticks, settings

The package `com.ialex86.unispring` (`Packages/manifest.json`, pinned to a git tag).
Check the API against the installed version: `Library/PackageCache/com.ialex86.unispring@*/`
— `Documentation~/` (`dependency-injection.md`, `data.md`, `transactions.md`,
`lifecycle-events-ticks.md`, `catalogs-and-settings.md`, `logging.md`, `testing.md`,
`il2cpp.md`, `spring-cheatsheet.md`, `troubleshooting.md`) and `Runtime/`.

Every task uses a ready UniSpring contract when one fits. Don't invent a save manager,
an event bus, a table loader, a host with `Update()` or a DI helper. Don't copy
framework code into `<Src>` or edit it in `Library/PackageCache`: framework changes are
made in the UniSpring repository and arrive as a new package version.

## 1. Dependency injection

* Game logic — `[Service]`; adapters, mappers, validators — `[Component]`;
  interchangeable algorithms — `[Strategy]` + `IKeyedStrategy<TKey>`
  (which one: `layers.md` §7).
* One public constructor with the dependencies; `[Autowired]` on a constructor only when
  there are several. Depend on an **interface**.
* Several implementations of a contract — `[Primary]` on the default one, or
  `IEnumerable<T>` / `IReadOnlyList<T>` / `StrategyRegistry<TKey,T>`.
  `IList<T>`/`ICollection<T>` are not populated.
* Default lifetime `Application`; `Scene` for a scene scope; `Transient` for unshared
  state (disposal is the consumer's job). Never inject scene objects into application
  beans.
* `[PostConstruct]` — synchronous `void` without arguments; `[Profile]` is selected
  when the context is built.
* **A MonoBehaviour is not a bean.** `AutowiredMonoBehaviour`, `[Autowired]` fields,
  initialisation in `OnDependenciesInjected()`; never declare your own `Awake`.
  `ScriptableObject`s, prefabs and scene objects are not beans. DTOs, Domain and value
  objects are created with `new`.
* Forbidden: `new` for services/DAOs/integrations, `static Instance`, Service Locator,
  `FindObjectOfType`/`FindFirstObjectByType`/`FindAnyObjectByType`, `GetComponent` to
  find a service (fine for a local technical component),
  `RuntimeContext.Get<T>`/`ApplicationContext` in game logic.
* Don't hide `new` of another implementation in a "convenience" constructor
  (`?? new X()`): the dependency is required, a test passes it explicitly.
* Every `[Service]` can be built in a plain unit test through its constructor with
  fakes, without the Unity runtime or the container.
* A resolution error prints `Resolution path: A -> B -> C`; a failed `WarmUp` disposes
  the beans created so far and throws the first error — read the path, don't guess.
* **The container enforces module boundaries**: `ModuleBoundaryOptions { Enabled = true,
  Strict = true }`, shared assemblies (the composition root) in `SharedAssemblies`. For a
  report without failing — temporarily `Strict = false` and read
  `ApplicationContext.BoundaryViolations`.
* The container is configured **only** in the `UniSpringConfiguration` composition root
  (`templates/Bootstrap/UniSpringConfiguration.cs.template`); `RuntimeContext.Configure`
  is called nowhere else.

## 2. Saves — repositories (`UniSpring.Data`)

The chain: `object → validators → mapper → serializer → store`, and back.
Where each piece lives — `layers.md` §4–6.

* A module's saved data is a `[Repository]` interface: `IRepository<T>` (many objects by
  id: `owner`, `owner|engine`, `vehicleId`) or `IDocument<T>` (one document per game).
  The container implements it. Derived queries (`FindByOwnerId`, `CountBy…`,
  `ExistsBy…`, `DeleteBy…`) instead of iterating `Ids()`.
* The type `T` (an `XxxSave` wrapper) and the repository interface are `public` (a proxy
  implements them); members with internal types are `internal`. **The name of `T` is
  unique in the game**: it names the storage area.
* The on-disk format is a separate `[Serializable]` record with `schemaVersion` and a
  `[Component] IRecordMapper<TSave, TRecord>`. An unknown schema in the mapper throws
  (the document becomes `Unreadable`); no silent defaults.
* Checks (owner = id, schema, integrity) — `[Component] IDocumentValidator<TSave>`.
* The module's port (`IXxxStore`) is in `Ports`; the adapter in `Integration` reads
  strictly (`Read()`), on a broken document logs
  `GameLog.Error("... " + read.Error + " (" + read.Status + ")")` and falls back to the starting state.
  A missing result from `Load()`/`Find()` is no proof of a new game.
* **A broken save is never overwritten by a plain `Save`**: after a read found it broken,
  UniSpring refuses that `Save` with `DocumentDamagedException`. Adapters therefore save
  through the game's one recovery policy, `SaveRecovery.Replace` in `<Prefix>.Saves.Api`
  (`Save`; on `DocumentDamagedException` a warning, `Delete`, `Save`) — code, policy choice
  and tests in `layers.md` §6. A bare `Save` in an adapter means one broken file stops the
  module from saving for the whole session.
* The composition root installs one `IDocumentSerializer` and one `FileDocumentStore`
  (`FileDocumentStore.Install(context, root)`; root `persistentDataPath/<Game>/Store`,
  overridable by an environment variable for tests and QA). Modules never register
  their own store/serializer or write save files directly.
* New game — `IDocumentReset` (`DeleteAll`, `Subscribe` to drop a service's cache).
* Changing the format: a new `schemaVersion` + `[Migration(n)] IMigration` — replay-safe,
  with tests for old/new/broken/unknown records and a second run. Never parse old
  schemas inside the mapper.
* Binary data (PNG etc.) — a separate "raw document" record type in the game's Saves
  module (`RawDocument` in NoLegal), not base64 inside a module's JSON.

## 3. Transactions (`UniSpring.Transactions`)

* A use case that changes several documents — `[Transactional]` on a service method
  **called through an interface** (self-invocation and concrete classes are not
  intercepted), or `ITransactionManager.Run/RunAsync`.
* By default it commits **even on an exception**; `RollbackOnError = true` when a
  rollback is needed (almost always for multi-document changes).
* Manual `Begin()`: `Dispose` without `Commit` rolls back. `[AfterCommit]` sees only
  `[Transactional]`/`Run`/`RunAsync`. The commit is logical: the file is written after
  it; a deferred listener is no proof of a disk write.
* No `async void` and no parallel work inside a transaction.

## 4. Events

* A state-change notification is an immutable `public sealed class XxxChanged` in the
  owner's `*.Api`, published with `IEventPublisher.Publish`. Never add
  `Subscribe(Action…)` methods to an Api.
* An application bean listens through `IEventListener<T>` (`[AfterCommit]` when the
  reaction must follow the commit).
* A MonoBehaviour subscribes with `m_Events.Subscribe<T>(…)`, keeps the token and
  `Dispose()`s it in `OnDestroy`; it reads the starting value from the Api right after
  subscribing.
* Publishing is synchronous, on the publishing thread. An event doesn't replace a call
  when a result is needed.

## 5. Ticks and lifecycle

* Per-frame logic of application beans — `ITickable` / `ILateTickable` /
  `IFixedTickable` (a `[Component]` adapter in `Integration`, order via `[Order]`), not a
  MonoBehaviour host that only calls `Tick`. Session start/stop — `ILifecycle` (started
  after warm-up, stopped in reverse order).
* Ticks run at the end of the Update phase: logic that needs an early
  `[DefaultExecutionOrder]` keeps a host.
* A MonoBehaviour host is justified only when it owns scene objects (a transform,
  `OnGUI`, inspector fields).

## 6. Tables and settings

* A shipped JSON table/settings — `[ConfigurationProperties(path, Required = true)]` on a
  DTO, the DTO injected into the constructor. Checks — `IDocumentValidator<TDto>`.
* "One asset per item" content — `[Catalog("Folder")] ICatalog<T>`.
* No `Resources.Load<TextAsset>` + `JsonUtility.FromJson` for tables in new code.
* Balance (prices, rewards, curves) lives in tables or documented `Config`, not magic
  numbers in code: then a playtest can change it without hunting through code.

## 7. IL2CPP and stripping

* After changing a `[Repository]`, `[Catalog]`, `[Transactional]` or interceptors —
  **Tools > UniSpring > Generate IL2CPP Proxies** and commit `UniSpring.Generated.cs`.
  EditMode tests don't prove the player works.
* Module Runtime assemblies go into `<Src>/link.xml` (`preserve="all"`).
* A release build for the target platform is the only proof of AOT/stripping behaviour.

## 8. Testing with UniSpring

| Level | How | Proves |
| --- | --- | --- |
| Domain / Service | `new` + fakes | rules, branches, invariants |
| Strategies | `new StrategyRegistry<K,T>(impls)` | routing, duplicate/missing keys |
| Data | `DocumentData.InMemory(serializer).With(...)` | mapping, queries, validation, rollback |
| Container | explicit assemblies/types, `using var context` | discovery, primary, scopes, proxies |
| Files | a unique temporary root, the real store | flush, reopen, recovery |
| PlayMode | a real scene/PlayerLoop | Awake, scene scopes, ticks, shutdown |
| Player | the target platform | AOT, resources, threads, linker |

* Give the game a `<Prefix>.Saves.TestSupport` with a facade over the in-memory store
  holding all the game's mappers/validators (in NoLegal `TestSaves.Game()`,
  `.Repository<IXxx>()`, `saves.Damage(key)`, `saves.Put(...)`, `saves.TextOf(...)`), so
  module tests don't rebuild the infrastructure.
* A service built with `new` has no advice: test transactional behaviour through the
  proxy/container separately. A fake publisher records calls, not `[AfterCommit]` delivery.
* Never run destructive tests on the real save folder; never delete a player's save as a
  test workaround.
