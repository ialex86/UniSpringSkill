# Localization: every player-facing text comes from language tables

Set it up in the title's first iteration: translating a finished game with texts in
code costs far more than keeping keys from the first commit. The check is strict, with
no baseline.

## The module

```text
<Scripts>/Localization/
├── Api/        <Prefix>.Localization.Api     — ILocalizationApi, TextKey, LanguageChanged
└── Internal/   <Prefix>.Localization.Runtime — service, table reader, adapters
                                                (Resources + chosen language), Config (languages)
<Src>/Resources/Localization/
├── en.json     the reference table (default language and fallback)
└── ru.json     the same keys, the same {n}
```

A working implementation exists in NoLegal (`Assets/Src/Scripts/Localization`): port it
into a new title by renaming the assembly prefix rather than writing it again. Languages
are listed in `unispring-skill.json` → `localization.languages` (the first is the
reference) and must match the module's language list.

## Rules

1. **No player text in code.** No non-English text in the game's string literals (the
   check catches Cyrillic), and no worded literal handed to UI (`.text =`, `SetText`,
   `SetStatus`, `SetMessage`, `Show*`, captions, columns, filters, key hints, titles).
   Logs, exceptions, inspector attributes and object names stay in English in code —
   they are for developers.
2. **Inject the API, don't reach for it.** `[Autowired] private ILocalizationApi m_Texts;`
   in an `AutowiredMonoBehaviour`, a constructor parameter in a `[Service]`; plain views
   and helpers receive it as a parameter from their owner. Modules reference only
   `<Prefix>.Localization.Api`.
3. **A key is a literal at the call site**: `m_Texts.Text("garage.status.lift_free")`,
   `m_Texts.Text("garage.status.restore_failed", car.DisplayName)`. A dictionary of enum →
   key literal is fine; building a key from pieces (`"reason." + code`) is not — the check
   can't see it and will call the entry unused.
4. **Key names**: `area.group.name`, lower-case segments with `_` (`tablet.chip.ready`,
   `booth.hint.car`). Reuse a key only when the text is the same in every language.
5. **Placeholders** are `{0}`, `{1}`… (invariant culture), the same in every language;
   TMP rich text (`<color=#{0}>`) is allowed.
6. **Format markers** shared by all languages (e.g. `[hold]` in a hold prompt) are listed
   in `localization.parityMarkers` — the check makes sure every translation has them or
   none does. Keep key hints in one format: `keys — action · keys — action`.
7. **Messages of domain rules** the player reads are returned as keys
   (`engine.rule.crank_first`); presentation shows them with
   `texts.TryGet(new TextKey(message), out var hint)` and falls back to a general reason
   text. Other result messages are diagnostics: log them, don't show them.
8. **Adding text** — the key goes into **all** tables in the same change. **Removing
   code** — its keys leave all tables. A key no game code uses is an error.
9. **Tests** use a fake from `<Prefix>.Localization.TestSupport` whose text is the key with
   arguments joined by `|` (`key|a|b`), and assert keys, not wording.
10. A literal that is data (a brand, a format pattern) may opt out with `// i18n-ignore`
    on its line — sparingly.

## Your own UI sinks

The base check knows `.text/.title/.tooltip/.label =`, `SetText`, `SetStatus`,
`SetMessage`, `SetLabel`, `SetTitle`, `SetCaption`, `SetHint`, `Show*`. Add your UI's
methods (`new KeyHint(`, `Column(`, `SoftKey(`…) as regexes in
`localization.extraUiSinks`, and your diagnostic calls whose strings aren't for players
in `extraDiagnostics` (example: `templates/examples/nolegal.unispring-skill.json`).
Worded literals are searched in files whose path matches `presentationPathPattern`
(default `/Presentation/`); Cyrillic — in all game code outside `Editor`.

## Check

```bash
python3 <skill>/scripts/check-localization.py --root .
python3 <skill>/scripts/check-localization.py --root . --file <changed file>
```

Codes: `TABLE` (broken table, a language without a table), `PARITY` (keys, placeholders
or markers differ), `MISSING` (code asks for a key no table has), `UNUSED` (a key nobody
uses), `HARDCODED` (text in code). The agent hooks (`scripts/hooks/agent_hook.py`) run it after each
`.cs`/`.json` edit and at the end of every turn. A game without localization turns it
off: `"localization": {"enabled": false}`.
