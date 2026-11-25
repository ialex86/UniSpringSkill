# Module layers and modularity: what goes where, how it is named, who sees whom

The running example is the `Economy` module (the player's wallet) as it is built in
NoLegal; `<Prefix>` is the game's assembly prefix. Folders a module doesn't need are
not created: `GameInput` has only `Api` and `Integration`, `Economy` has almost all.

```text
<Scripts>/Economy/
├── Api/                        <Prefix>.Economy.Api        public, Unity-free
│   ├── IWalletApi.cs           IWalletApi, IFinesApi (roles), Money (pure helper)
│   └── EconomyEvents.cs        WalletChanged, LoanChanged
├── Internal/                   <Prefix>.Economy.Runtime    all internal except what proxies need
│   ├── AssemblyInfo.cs         [assembly: InternalsVisibleTo("<Prefix>.Economy.Tests")]
│   ├── Domain/Wallet.cs        entity with invariants
│   ├── Ports/IWalletStore.cs   storage port (internal)
│   ├── Ports/EconomySaves.cs   WalletSave + [Repository] IWalletDocument (public)
│   ├── Integration/WalletFileStore.cs   [Component] port adapter + WalletFileDto + mapper (+ validator)
│   ├── Service/WalletService.cs         [Service] implements IWalletApi, IFinesApi
│   └── Config/EconomyConfig.cs          tuning, with where each number comes from
└── Presentation/               <Prefix>.Economy.Presentation
    └── WalletHud.cs            AutowiredMonoBehaviour, Api only
```

## 1. Layer map

| Layer (folder) | Contents | Visibility | Unity | UniSpring attributes |
| --- | --- | --- | --- | --- |
| `Api` | facade interfaces, snapshots/DTOs, events, contract enums, pure helpers | `public` | no | none |
| `Domain` | entities, value objects, rules, calculations | `internal` | no | none |
| `Ports` | internal interfaces (storage, spawner, SDK, data sources), `XxxSave` + `[Repository]` | ports `internal`; save type and repository `public` | no | `[Repository]` |
| `Service` / `Application` | use cases, orchestration, the Api implementation | `internal` | no | `[Service]`, `[Transactional]`, `[Strategy]` |
| `Dto` | internal DTOs; files of shipped tables | `internal`/`public` as binding requires | no | `[ConfigurationProperties]` |
| `Config` | tuning constants, typed settings | `internal` | no | — |
| `Mapping` | pure conversions Domain ↔ Api ↔ Dto | `internal static` | no | — |
| `Validation` | reusable checks | `internal` | no | `[Component] IDocumentValidator<T>` |
| `Integration` / `Adapters` | port implementations: save files, resources, Unity, SDKs, ticks | `internal` | yes | `[Component]`, `ITickable` |
| `Dao` / `Persistence` | storage adapters, when a module prefers a folder of its own for them | `internal` | if needed | `[Component]` |
| `Bootstrap` (inside a module) | the module's own installers/watchers | `internal` | yes | — |
| `Presentation` / `Controller` | MonoBehaviours, HUD, UI, input adapters | `internal` | yes | `AutowiredMonoBehaviour` |
| `Editor` | menus, builders, import, inspectors | `internal` | yes, editor-only | — |

## 2. Api — the module's contract

The only thing other modules see. A separate `<Prefix>.<Module>.Api` assembly with no
references to other Runtime assemblies (`noEngineReferences: true` unless it holds a
Unity-facing contract).

* **One interface per role, not "the whole module"**: `IWalletApi` (balance, pay, get
  paid) and `IFinesApi` (a fine that may go below zero) are implemented by one service,
  but each consumer takes only the role it needs. A big module has several narrow
  interfaces.
* **The contract is written down in XML docs**: units (dollars, game hours), limits
  (zero, negative), what is saved, who is told. That is the spec parallel work
  streams build against.
* **Outgoing data is immutable**: `readonly struct XxxSnapshot`, `sealed class` with
  get-only properties, `IReadOnlyList<T>` copies. No live entities, no internal
  collections.
* **Commands with an outcome** return `bool TryXxx(...)` or an `XxxResult` with a reason
  (reason code / localization key), not exceptions for expected refusals.
* **Events** are `public sealed class XxxChanged` in the owner's Api, get-only, with
  enough data (new value, delta, reason); the docs say how to listen and where to read
  the starting value.
* **Contract enums** live in the Api; Domain's internal enums are translated by `Mapping`.
* **Pure stateless helpers** shared by every consumer (formatting a sum, the text key
  for a sum: `Money.Key/Shown`) may be `static` in the Api.
* Forbidden: `GameObject`/`Transform`/`Material`, SDK types, DAOs, `IQueryable`, mutable
  collections, `object`/`dynamic`, `Subscribe(Action)` methods, DI details. A Unity type
  that is the point of the contract (a camera) only with
  `// unity-facing-contract: ...`.

## 3. Domain — the game's rules

* `internal sealed` classes and `readonly struct`s without Unity, DI or SDKs.
* Invariants inside: private setters, guards (`if (amount < 0) throw ...`), `checked`
  arithmetic for money. The entity itself decides whether something is possible
  (`TrySpend`).
* Created with `new` — not a bean.
* Rules with genuinely different behaviours → strategies (`code-style.md` §1); when only
  the numbers differ → a data table.
* Tested directly, fast, without mocks.

## 4. Ports — the module's internal dependencies

* Interfaces for what the service needs from outside its own pure code: storage
  (`IWalletStore`), a table source (`IShopCatalogSource`), Unity/SDK (`IVehiclePort`),
  clock, randomness, spawner. `internal`.
* Phrased in the module's terms, not the technology's: `bool TryLoad(out long balance)`,
  `void Save(long balance)` — not "read the JSON".
* A contract for another module is never declared here — it goes to `Api`.
* The **saved model and its repository** also live here:
  `public sealed class WalletSave` (get-only) and
  `[Repository] public interface IWalletDocument : IDocument<WalletSave>`. They are
  `public` because the container's proxy implements them; they are still in the
  `Internal` assembly, and other modules neither see nor use them.

## 5. Repository — storage through UniSpring.Data

Never hand-written: the container implements the interface.

| Need | Interface | Example |
| --- | --- | --- |
| one document per game | `IDocument<T>` | the wallet, tutorial progress, settings |
| many objects by id | `IRepository<T>` | cars by `vehicleId`, parts by `owner\|engine` |

* Derived queries instead of iterating: `FindByOwnerId`, `CountByOwnerId`,
  `ExistsByVehicleId`, `DeleteByOwnerId` (over public properties of `T`).
* The name of `T` is unique in the game — it names the storage area. Renaming `T` is a
  migration of player data.
* Reads are strict `Read()` (`Found`, `IsBroken`, `Status`, `Error`), never "no
  value = new player".
* After a read found the document broken, a plain `Save` of it is refused with
  `DocumentDamagedException` — that protects the player's data. Writing over it is an
  explicit decision of the game: `SaveRecovery.Replace` (§6).

## 6. Integration / Dao — adapters

`[Component]` implementations of ports; the only place with files, resources, Unity
and SDKs.

```csharp
using <Prefix>.Saves.Api;                                         // SaveRecovery: the game's recovery policy

[Component]
[Lifetime(BeanLifetime.Application)]
internal sealed class WalletFileStore : IWalletStore            // port adapter over the repository
{
    private readonly IWalletDocument m_Document;
    public WalletFileStore(IWalletDocument document)
        => m_Document = document ?? throw new ArgumentNullException(nameof(document));

    public bool TryLoad(out long balance)
    {
        balance = 0;
        var read = m_Document.Read();
        if (read.IsBroken)
            GameLog.Error("The wallet is " + read.Status + "; the starting balance is used: " + read.Error);
        if (!read.Found)
            return false;
        balance = read.Value.Balance;
        return true;
    }

    // Not a plain Save: after a broken read UniSpring refuses it, and the wallet would stop saving.
    public void Save(long balance) => m_Document.Replace(new WalletSave(balance));
}

[Serializable]
internal sealed class WalletFileDto { public int schemaVersion; public long balance; }   // the on-disk format

[Component]
internal sealed class WalletSaveMapper : IRecordMapper<WalletSave, WalletFileDto>
{
    private const int Schema = 1;
    public WalletFileDto ToRecord(WalletSave s) => new WalletFileDto { schemaVersion = Schema, balance = s.Balance };
    public WalletSave ToDomain(WalletFileDto r)
    {
        if (r.schemaVersion != Schema)
            throw new FormatException("Unknown wallet format " + r.schemaVersion + ".");
        return new WalletSave(r.balance);
    }
}
```

### Recovering a broken save

`TryLoad` above logged the broken wallet and the service went on from the starting
balance. The next save must then write over the broken document — and UniSpring refuses
that with a plain `Save` (`DocumentDamagedException`) until the game decides to. The
decision is made **once, for the whole game**, in its Saves module, not in every adapter:

```csharp
// <Scripts>/Saves/Api/SaveRecovery.cs — assembly <Prefix>.Saves.Api
// (references UniSpring.Data and UniSpring.Logging; noEngineReferences: false)
using UniSpring.Data;
using UniSpring.Logging;

namespace <Prefix>.Saves.Api
{
    /// <summary>
    /// The game's policy for a save that a read found broken (the document and its .bak both
    /// damaged, or unreadable/invalid): the module already logged it and went on from its start
    /// state, so the next save replaces the broken copy.
    /// </summary>
    public static class SaveRecovery
    {
        public static void Replace<T>(this IDocument<T> document, T value) where T : class
        {
            try
            {
                document.Save(value);
            }
            catch (DocumentDamagedException exception)
            {
                GameLog.Warn("A broken save is replaced: " + exception.Message);
                document.Delete();
                document.Save(value);
            }
        }

        public static void Replace<T>(this IRepository<T> repository, string id, T value) where T : class
        {
            try
            {
                repository.Save(id, value);
            }
            catch (DocumentDamagedException exception)
            {
                GameLog.Warn("A broken save is replaced: " + exception.Message);
                repository.Delete(id);
                repository.Save(id, value);
            }
        }
    }
}
```

* An intact or missing document is saved by the first `Save`; only a document a read found
  broken goes through `Delete` + `Save`, with a warning in the log next to the read's error.
* Every adapter saves through `Replace`, never through a bare `Save`: otherwise one broken
  file silently stops a module from saving for the rest of the session.
* This is NoLegal's policy — the game keeps going and the broken copy is lost (the store's
  `.bak` was already damaged too, or the read would have returned it). A stricter game copies
  the save folder aside or asks the player before `Replace`; then change it here, once.
  UniSpring's own guidance (`Documentation~/data.md`) is to keep damaged data and ask before
  deleting — choose deliberately and write the choice into `Doc/Saves/README.md`.
* Tests: damage the document in the in-memory store, read it (broken), `Replace`, read it
  again (found, the new value); and the same with a plain `Save` → `DocumentDamagedException`.

### What else lives in Integration

* One file per saved document: adapter + record + mapper (+ validator) side by side —
  the format and its conversion change together. Name: `XxxFileStore`.
* The record (`XxxFileDto`/`XxxRecord`) is `[Serializable]` with public fields named as
  in the file and **always a `schemaVersion`**. It is neither the domain model nor an
  Api DTO.
* The validator (`[Component] IDocumentValidator<XxxSave>`) checks owner = id, ranges,
  referential integrity.
* Shipped data sources (`ResourceShopCatalogSource : IShopCatalogSource`) live here too,
  on top of a `[ConfigurationProperties]` DTO.
* Unity adapters: an `ITickable` component, a prefab spawner, a vehicle SDK adapter.
  Unity-dependent conversions belong here, not in `Mapping`.
* No game decisions here: the adapter doesn't know how much money a new player gets.

## 7. Service / Application — the scenarios

```csharp
[Service]
[Lifetime(BeanLifetime.Application)]
internal sealed class WalletService : IWalletApi, IFinesApi
{
    public WalletService(IWalletStore store, IDocumentReset saves, IEventPublisher events) { ... }

    public bool TrySpend(long amount, string reason)
    {
        if (amount < 0) throw new ArgumentOutOfRangeException(nameof(amount));   // guard
        if (amount == 0) return true;
        if (!Current.TrySpend(amount)) return false;                               // the decision is Domain's
        Changed(-amount, reason);                                                  // save, log, event
        return true;
    }
}
```

* Implements its Api's interfaces (often several roles in one class) and internal
  service contracts.
* Depends on ports, Domain, Config, Mapping, Validation and **other modules' Api**. Not
  on adapters, `UnityEngine` or the container.
* A typical use case: guards → load (lazily, cached) → Domain decides → save through the
  port → one `GameLog` line with the outcome → event.
* New game: an `IDocumentReset.Subscribe` callback drops the cache and announces the new
  value with an event.
* Several documents at once — `[Transactional(RollbackOnError = true)]` on an interface
  method (`unispring.md` §3).
* The use-case folder may also hold the service's helpers (`ShopFilter`,
  `ShopOrderMath`, `ShopSortStrategies`): only the `*Service` class with `[Service]` is
  a bean; the rest are plain classes or `[Strategy]`/`[Component]`.

### Service, Component, Strategy — which one

| Attribute | When | Example |
| --- | --- | --- |
| `[Service]` | a game scenario; implements an Api or an internal service contract | `WalletService`, `CarShopService` |
| `[Component]` | an infrastructure bean: port adapter, mapper, validator, tick adapter, a rule without a key | `WalletFileStore`, `WalletSaveMapper` |
| `[Strategy]` | one of several interchangeable implementations, picked by key through `StrategyRegistry` | `GlassImportStrategy`, shop sort orders |
| no attribute, `new` | Domain, DTOs, value objects, snapshots, records | `Wallet`, `WalletSave`, `WalletChanged` |

## 8. Dto, Config, Mapping, Validation

* **`Dto`** — internal transfer structures and **files of shipped tables**:
  `[ConfigurationProperties("Shop/shop_catalog", Required = true)] [Serializable]
  public sealed class ShopCatalogFile` with fields named as in the JSON (`public` is a
  binding requirement). The table is checked by `IDocumentValidator<ShopCatalogFile>`.
  DTOs of the external contract live in `Api`, not here.
* **`Config`** — the module's tuning: `internal static class EconomyConfig` with
  constants, each documenting where the number comes from (the tutorial's scenario, the
  balance simulator, a playtest). Values tuned without recompiling → a table through
  `[ConfigurationProperties]`.
* **`Mapping`** — `internal static` pure conversions Domain ↔ Api ↔ Dto without side
  effects; enum ↔ enum correspondence tables (a `Dictionary` of data) are fine and
  better than a `switch`. Unity-dependent conversions go to `Integration`.
* **`Validation`** — checks needed in several places (the service and a document
  validator); a one-off check stays a guard where it is used.

## 9. Presentation / Controller

```csharp
internal sealed class WalletHud : AutowiredMonoBehaviour
{
    [Autowired] private IWalletApi m_Wallet;          // Api only (own and other modules')
    [Autowired] private IEventPublisher m_Events;
    [Autowired] private ILocalizationApi m_Texts;
    private IDisposable m_Subscription;

    protected override void OnDependenciesInjected()
    {
        if (m_Wallet == null || m_Texts == null) { enabled = false; return; }   // nothing injected: switch off quietly
        m_Subscription = m_Events.Subscribe<WalletChanged>(OnChanged);
        Show(m_Wallet.Balance);                                                  // the starting value comes from the Api
    }

    private void OnDestroy() => m_Subscription?.Dispose();
}
```

* Its own `<Prefix>.<Module>.Presentation` assembly, referencing **Api** assemblies (its
  module's and others') and the shared kit; it never reaches into `Internal`.
* Handles Unity lifecycle, UI and input, shows state, calls the Api. No scenarios, no rules.
* A global HUD/watcher that needs no scene installs itself with
  `[RuntimeInitializeOnLoadMethod(AfterSceneLoad)]` + `DontDestroyOnLoad`.
* Texts are keys through `ILocalizationApi`.

## 10. A module's Bootstrap and Editor

* `Internal/Bootstrap` — what the module itself puts into the game: a watcher over a
  scene object (`PlayerCarWatch`), an installer. It wires **only its own module** and
  runs no game operations. The global `<Scripts>/Bootstrap` only configures the container.
* `<Module>/Editor` — an editor-only assembly: `<Game>/<Module>/...` menus, builders of
  generated content, import, inspectors. The build logic lives in plain classes; the
  Editor code only connects it to `AssetDatabase`.

## 11. Who may reference whom

Inside a module (✓ — may reference; checked by `check-code-architecture.py`):

| From \ to | Api | Domain | Ports | Dto | Config | Mapping | Validation | Service | Integration |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Api** | ✓ | — | — | — | — | — | — | — | — |
| **Domain** | — | ✓ | — | — | — | — | — | — | — |
| **Ports** | ✓ | ✓ | ✓ | ✓ | — | — | — | — | — |
| **Dto** | — | ✓ | — | ✓ | — | — | — | — | — |
| **Config** | — | ✓ | — | ✓ | ✓ | — | — | — | — |
| **Mapping** | ✓ | ✓ | ✓ | ✓ | — | ✓ | — | — | — |
| **Validation** | ✓ | ✓ | ✓ | ✓ | — | — | ✓ | — | — |
| **Service** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| **Integration** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| **Presentation** | ✓ | its module only through the Api | — | — | — | — | — | — | — |

Between modules — **only the other module's Api** (`check-subsystem-boundaries.py`, and
the container with `Strict = true`). A module's Api never references its own `Internal`.

## 12. Naming

| What | Name | Layer |
| --- | --- | --- |
| module facade / role | `IWalletApi`, `IFinesApi` | Api |
| immutable outgoing data | `LoanSnapshot`, `CarSpec` | Api |
| event | `WalletChanged`, `LoanChanged` | Api |
| command outcome | `PurchaseResult` + `PurchaseFailure` | Api |
| entity / rule | `Wallet`, `Loan`, `GameDays` | Domain |
| port | `IWalletStore`, `IShopCatalogSource`, `IVehiclePort` | Ports |
| saved model | `WalletSave` | Ports |
| repository | `IWalletDocument` (`IDocument<T>`), `ICarRepository` (`IRepository<T>`) | Ports |
| storage adapter | `WalletFileStore` | Integration |
| on-disk record | `WalletFileDto` / `WalletRecord` | Integration |
| mapper / validator | `WalletSaveMapper`, `WalletSaveValidator` | Integration |
| table file | `ShopCatalogFile`, `PowertrainTableDto` | Dto |
| scenario | `WalletService`, `CarShopService` | Service |
| strategy | `GlassImportStrategy`, `PriceSortStrategy` | Service |
| tuning | `EconomyConfig` | Config |
| mapping | `DriftCourseMapping` | Mapping |
| UI | `WalletHud`, `XxxView`, `XxxPresenter`, `XxxWindow` | Presentation |

Namespace = the folder path without `Internal`: `<Prefix>.Economy.Api`,
`<Prefix>.Economy.Service`, `<Prefix>.Economy.Integration`, `<Prefix>.Economy.Presentation`.

## 13. Modularity: how to split a game

* **A module owns the data and rules of one area** the player recognises by name:
  wallet, shop, garage, paint, gangs, races, navigation, localization, settings. Not
  "all services", not "all UI", not a technical layer.
* **Signs it deserves its own module**: data of its own to save; rules that must not
  change because of someone else's edit; its own screens/events; it can be tested
  through its Api with fakes of its neighbours.
* **Split when** a module accumulates unrelated parts (a venue's world and its race
  rules — `CityWorld` and `Racing`), when two work streams need to proceed in parallel,
  when the Api grows roles needed by different consumers.
* **Don't split** for a single class, and don't extract "shared" code before its second
  consumer. Shared UI → the presentation kit (`sharedKits`); a shared mechanism
  (background computation, shader warm-up, performance capture) → an infrastructure
  module with its own Api.
* **Data belongs to one module.** The others ask its Api or listen to its events; no one
  reads another module's saves/tables with their own DAO or duplicates its rules.
* **Cross-module scenarios** (buy a part → money, inventory, an event for the tutorial):
  the initiating module's service calls the others' Api; a two-way dependency → an event
  or orchestration one level up. Cycles between Apis are forbidden.
* **TestSupport for neighbours**: a module whose Api is often faked in tests (saves,
  localization, inventory) ships a `<Prefix>.<Module>.TestSupport` assembly with fakes.
  The container doesn't scan it.
* **A new module**: `new-module.py --name <Module>` → the Api contract with docs → Domain
  with tests → ports and adapters → service → Presentation → `Doc/<Module>/README.md` →
  `link.xml`. Changing the implementation never requires consumer changes while the Api
  stays the same.
