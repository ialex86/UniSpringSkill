# Architecture: layout, subsystems, boundaries

`<Src>` is `srcRoot` from `unispring-skill.json` (default `Assets/Src`),
`<Scripts>` is `scriptsRoot` (`Assets/Src/Scripts`), `<Prefix>` the game's assembly
prefix (`SLRR` in NoLegal).

## 1. Asset layout: one editable zone

```text
Assets/
├── Src/                      # EVERYTHING the game owns: editable
│   ├── Scripts/              # C#, asmdef, asmref
│   ├── Scenes/
│   ├── Prefabs/
│   ├── Resources/            # SOs, tables (JSON), logging.properties, Localization/
│   ├── Input/                # InputActions
│   ├── Art/  Audio/
│   ├── Doc/                  # release docs of the subsystems (agent-workflow.md §6)
│   ├── Generated/            # built by editor menus (in .gitignore)
│   ├── Tests/                # EditMode/PlayMode
│   └── link.xml
├── Settings/                 # Unity-generated: never edit by hand
├── TutorialInfo/             # Unity sample: read-only
└── <VendorPackage>/          # Asset Store / SDK: read-only
Packages/                      # UPM / agreed procedure only
ProjectSettings/               # Unity Editor / agreed procedure only
```

* New `.cs`, `.asmdef`, `.asmref`, `.unity`, `.prefab`, `.mat`, `.shader`, `.hlsl`,
  `.cginc`, `.shadergraph`, `.inputactions`, project `.asset`, `.controller`, `.anim`
  go **only** into `<Src>/<Area>/`. Project files in the `Assets/` root are forbidden.
* A move **always includes the `.meta`**; the GUID is kept. Folders have `.meta` too.
  Check references in Unity after a move.
* Unity creates new `.meta` files (through Unity MCP `refresh_unity`); by hand only in
  the format of the neighbouring files. Folders named `name~` or `.name` are not
  imported and need no `.meta` (that is where captures live, `Captures~`).
* Vendor packages **contain** `.cs`, `.prefab`, `.shader` — that is not a violation;
  never treat a vendor file as the project's because of its extension.
* Legacy from the Unity template (`Assets/Scenes/`, `Assets/InputSystem_Actions.inputactions`,
  `Assets/Readme.asset`) is listed in the config and migrates **only when agreed**.

### Protecting vendors

Without the user's explicit decision, nothing outside `<Src>/` is created, changed,
renamed, moved or deleted. A vendor needs a fix → propose a wrapper/adapter, subclass,
extension method, own prefab or versioned fork inside `<Src>/`. Edit the original only
after "yes, edit the vendor", with the reason and the upgrade risk explained. Settings
through the Unity Editor/UPM are a separate, agreed operation.

## 2. Subsystems first, layers inside

New functionality is a **self-contained, closed subsystem**. No global `Service/`,
`Dao/`, `Controller/` folders that everyone reaches into.

```text
<Scripts>/
├── WorldTime/
│   ├── Api/                         # ONLY public contracts, their DTOs and events
│   │   ├── IWorldTimeApi.cs
│   │   ├── WorldTimeSnapshot.cs
│   │   ├── WorldTimeChanged.cs
│   │   └── <Prefix>.WorldTime.Api.asmdef
│   ├── Internal/                    # the implementation, closed to other subsystems
│   │   ├── Service/ (Application)   # use cases and orchestration, [Service] implements the Api
│   │   ├── Domain/                  # invariants and models, no Unity
│   │   ├── Ports/                   # INTERNAL ports + XxxSave and [Repository] IXxxDocument
│   │   ├── Integration/ (Adapters)  # [Component]: XxxFileStore + record + mapper + validator,
│   │   │                            #   table sources, Unity/SDK, ITickable adapters
│   │   ├── Dto/                     # internal DTOs, [ConfigurationProperties] table files
│   │   ├── Config/  Mapping/  Validation/  Bootstrap/
│   │   ├── AssemblyInfo.cs          # InternalsVisibleTo for the tests
│   │   └── <Prefix>.WorldTime.Runtime.asmdef
│   ├── Presentation/ (Controller)   # MonoBehaviour adapters, UI; own assembly
│   └── Editor/                      # editor-only assembly: menus, builders, import
├── Bootstrap/                       # the global composition root (DI configuration only)
└── <SharedKit>/                     # shared presentation kit (sharedKits in the config)
```

Every layer in detail (contents, visibility, naming, code examples, the "who may
reference whom" table, how to split a game into modules) — `references/layers.md`.

Folder synonyms the checks understand: `Application` = Service, `Presentation` =
Controller, `Persistence` = Dao, `Adapters` = Integration. Don't create empty layers.

### Responsibilities and dependency direction

* `Controller/Presentation` receives Unity lifecycle, UI, input; calls its module's
  Api or other modules' Api; implements no game scenarios.
* `Api` — public interfaces/facades, external DTOs, events. Never references
  `Internal`, DAOs, Unity SDK, implementations.
* `Service/Application` — use cases; depends on `Ports`, `Domain`, `Dto`,
  `Validation`, `Mapping`, `Config` and other modules' `Api`. **Not** on `Dao`,
  `Integration`, `Controller`, `UnityEngine`, `UnityEditor` or SDKs.
* `Domain` — game rules without Unity, DI and SDKs.
* `Ports` — the module's internal interfaces; a contract for another module goes to `Api`.
* `Dao/Integration` implements storage and adapters; makes no game decisions and
  never calls `Service`. Unity-dependent conversions live here, not in pure `Mapping`.
* `Config` — typed settings; `Dto` — data across boundaries, no logic.
* The global `Bootstrap` is the **only composition root**: container configuration,
  store, logging, boundary policy. It runs no game operations and resolves no beans.

Dependency rule: outer layers know inner contracts; inner layers never know outer
implementations. No cycles, hidden global registries or Service Locator.
For an SDK: `Controller -> IServicePort -> Service -> IVehiclePort <- Integration/SDK`.

## 3. Sealed boundaries: Api only

**Subsystem A's code knows only `B/Api` of B.**

* An Api is a minimal set of interfaces, commands, queries/results, immutable DTOs,
  snapshots and events. The implementation is inside the module; the container wires it.
* Injecting or calling another module's `Service`, `Dao`, `Repository`, `Ports`,
  `Domain`, `Controller`, `Integration`, `Config` or implementations is forbidden —
  even when they are `public`. Make implementations `internal` wherever possible.
* Api contracts contain no `GameObject`, `Transform`, `MonoBehaviour`, `Material`, SDK
  types, DAOs, `IQueryable`, mutable collections or DI details. A Unity-facing contract
  is allowed only when proven necessary and is marked with
  `// unity-facing-contract: <why it can't do without the Unity type>` (the check skips it).
* An Api never hands out live entities, internal collections, implementations,
  `object`/`dynamic`.
* Cross-module notifications are events in the owner's Api (`unispring.md` §4); not a
  global mutable bus, not direct calls into another module's MonoBehaviours, not
  searching the scene for its components. No per-frame event streams.
* Data belongs to one module: A never reads B's files/tables/caches with its own DAO
  and never duplicates B's rules.
* No cycles: mutual scenarios use orchestration one level up, events, or a separate
  shared **contract** — never a God module.
* `Bootstrap` may know modules only to configure DI. No other exceptions (test scenes
  included).

### Assemblies (.asmdef)

* At least `<Prefix>.<Module>.Api` and `<Prefix>.<Module>.Runtime` (+ `.Presentation`,
  `.Editor`, `.Tests`, and `.TestSupport` with fakes for neighbours when needed).
* Runtime depends on its own Api and other modules' Api, **never** on another Runtime.
  Nobody references a Runtime assembly — the container's scanner finds the beans — so
  **add every new Runtime assembly to `<Src>/link.xml`** (or stripping removes it).
* Assemblies with `Editor`/`Tests` in their name are not scanned
  (`UniSpringConfiguration.IsScanned`).
* Reference `UniSpring.DependencyInjection` / `.Data` / `.Transactions` / `.Logging`
  only where actually needed.
* If the configuration prevents splitting assemblies, report the exact problem — don't
  work around the rule by referencing another module's Runtime.

### Example boundary

```csharp
// WorldTime/Api/IWorldTimeApi.cs
public interface IWorldTimeApi { WorldTimeSnapshot GetSnapshot(); }

// WorldTime/Api/WorldTimeSnapshot.cs
public readonly struct WorldTimeSnapshot
{
    public readonly float Hour;
    public WorldTimeSnapshot(float hour) => Hour = hour;
}

// Traffic/Internal/Service — only another module's public Api
[Service]
internal sealed class TrafficLightingService
{
    private readonly IWorldTimeApi m_WorldTime;
    public TrafficLightingService(IWorldTimeApi worldTime) => m_WorldTime = worldTime;
}
```

Wrong: `TrafficLightingService(WorldTimeService service)`, `(IWorldTimeDao dao)`,
`using <Prefix>.WorldTime.Service;`, a `<Prefix>.WorldTime.Runtime` reference in
Traffic's asmdef.

### Shared presentation kit

Reusable UI (catalog popups, windows, tool modes, aiming, a first-person controller)
is not a feature module but infrastructure, like DI: a folder listed in `sharedKits`
with an `Api` (Unity-free contracts) and a `Presentation`.

* Only presentation and editor code of modules uses the kit; modules' Domain,
  Service, Dao and Api do not (check `SHARED`). The kit's Api is open to everyone.
* The kit depends only on modules' `*.Api` and knows no concrete module: it reaches the
  scene's HUD through an interface (`IWorkshopHud`), not a concrete `GarageHud`.
* New shared UI goes into the kit, not into the module that needed it first.

## Checklist before implementing

1. Owning module and its responsibilities.
2. Public interfaces, DTOs and events the neighbours need.
3. Hidden Service/Dao/Ports/Integration.
4. Dependency directions; no cycles; no internal or Unity types leaking into the Api.
5. asmdefs and DI: a consumer gets only the Api; Runtime is in `link.xml`.
6. Test the module through its Api with fakes, and the implementation separately.
   Changing the implementation requires no consumer changes while the Api stays.
