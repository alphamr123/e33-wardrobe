# Docs: where to look

Pick the row for your task, read that page, open those files. `docs/index.md` lists every file,
app API method, game hook, config key and environment variable (generated from the code).
Terms: [glossary.md](glossary.md). Step-by-step recipes: `runbook.md` (the maintainer's local notes, not in the repository).

## For players

| I want to | Read |
|---|---|
| Install everything | [INSTALL.md](INSTALL.md), or [APP.md](APP.md) for the app |
| Use the in-game menu | [USAGE.md](USAGE.md) |
| Fix a problem, send a report | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Prepare mods by hand (no app) | [RELOCATOR.md](RELOCATOR.md) |

## For changing the code

| I want to change | Read | Open | Tests |
|---|---|---|---|
| How outfits are put on in game (meshes, materials, textures, Wear, empty-slot fill) | [HOW_IT_WORKS.md](HOW_IT_WORKS.md) "Runtime swapping" | `main.lua`: `applyToActor`, `fixSlot`, `Wear.*`, `wanted` | `test_lua_mock`, `test_lua_switching`, `test_lua_outfit_whole` |
| Which characters get changed, and when (spawns, re-checks, companions, map loads) | [HOW_IT_WORKS.md](HOW_IT_WORKS.md) "Which actors, which character" | `main.lua`: `SPAWN`, `onSkinActor`, `recheckPending`, `KNOWN_SKINS`, `isWardrobeActor`, `runApply` | `test_lua_coverage`, `test_lua_dispatch` |
| Crash or freeze safety (what may be read from the game) | `runbook.md` "Triage a freeze"; this page's known gaps | `main.lua`: `valid`, `alive`, `propOf`, `leafName`, `fullPath` | AV counter in every Lua suite (`av_check`) |
| Speed, stutter | `runbook.md` "Measure what a change costs" | `main.lua`: `TRACE` (memo, budgets, stats, hitch lines) | `tests/perf/count_crossings.py`, memo section of `test_lua_switching` |
| Threading, timers, the watchdog | [DEVELOPMENT.md](DEVELOPMENT.md) | `main.lua`: `onGT`, `loopBody`, `later`, watchdog | `test_lua_dispatch` |
| The in-game menu (look, pages, keys) | [USAGE.md](USAGE.md) | `menu.lua` (`C`, `FONT`, `PADDING` tables at the top) | `test_lua_menu`; look at `tests/render_menu.py` output |
| Keys and in-game settings | `docs/index.md` "Config keys" | `config.example.lua`, `main.lua` `SETTINGS` | `test_lua_menu` |
| The relocator (preparing mods) | [RELOCATOR.md](RELOCATOR.md), [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | `tools/e33_relocate.py`, `e33legacy.py`, `e33utoc.py`, `e33tex.py` | `test_relocate_units`, `test_relocate_e2e` |
| Fix tools (rules, row edits, disable, bundles) | [APP.md](APP.md) "Fixing mods" | `tools/e33fixes.py`, `app/backend/fixes.py`, `repair.py`, `culprit.py` | `test_app_backend` |
| The app's window and pages | [APP.md](APP.md), `app/API.md` | `app/ui/app.js`, `app.css`, `index.html`, `mock.js` | `test_app_ui`; look at `scripts/render_app.py` output |
| The app's backend (archives, library, jobs) | `app/API.md` | `app/backend/api.py`, `archives.py`, `library.py`, `jobs.py`, `paths.py` | `test_app_backend` |
| The Game log tab | `docs/index.md` "Log lines the app reads" | `app/backend/monitor.py`; the `live(...)` lines in `main.lua` | `test_app_monitor` |
| Releases, the exe build | `runbook.md` "Ship a release" | `scripts/build_release.py`, `.github/workflows/build-app.yml`, `app/e33wardrobe.spec` | CI runs all suites on Windows |
| What is known about the game and UE4SS | [RESEARCH.md](RESEARCH.md) | | |

## Known gaps (as of 1.3.1)

- Nothing since 1.2.0 is confirmed in game except through the user's logs. Seen in game on 1176
  (16-17 Oct 2026): B param swaps in world, menu, companion, battle and cutscene, with the body
  check finding the relocated mesh; the case repair of the relocator.
- UE4SS 3.0.1-1125 crashes when Lua reads a weak or soft property (UE4SS issue #1433). `propOf`
  avoids it in the mod. Fixed in UE4SS 3.0.1-1176 (14 Oct 2026), which the mod now runs on.
- Crash at camp after a fast travel (17 Oct 14:52 and 21:51, UE4SS AV in
  `FFieldClassVariant::GetFName` under `PropertyCache` / `FindProperty`, reading a camp actor's
  "Face"): UE4SS 1176's property cache returning a property of a freed, reloaded Blueprint, or the
  actor itself already freed (its class pointer garbage). The cache code is in the private UEPseudo
  submodule, so neither is confirmed. `meshComponents` now reads properties by name only on outfit
  actors, and skin components come from `TRACE.skinComps` (by class, not through the actor's
  `BP_CinematicCharacterSkinComponent` property, which the JMAP shows on 38 camp classes). Still read
  by name: `AllMeshMaterials` on the world pawn (replaceTracked), Clean's float properties, the
  dump. If a crash comes back, check those paths and `propOf`'s `ForEachProperty` listing. The JMAP
  from camp (17 Oct, `ue4ss\Sandfall-...-1ba38db4.jmap`) lists every Blueprint class's properties.
- One battle freeze (17 Oct, game code on a worker thread, a B swap in the same second) did not
  come back in later retries; cause unknown.
- Cutscene Sciel's Body has no AnimClass after a B swap; the sequencer drives it and it looks
  normal on screen. Whether the swap causes it is not known.
- Startup freezes while loading a save: one dump showed a crash inside the engine's map load,
  called through UE4SS's LoadMap hook, with no Lua running. Whether `HookLoadMap = 0` stops them
  is not tested yet.
- The quest dialogue that didn't appear (hand-over NPC) is unexplained. `scene_copies = false`
  in settings.txt is the test switch for it.
- A redesign that gives the game the picked outfit before it dresses anyone is blocked: the only
  function the game uses (`AssignBodyAndFaceSkinAsync`) takes the outfit as a soft class, which
  UE4SS 1125 can't handle from Lua. On 1176 the B test (param) does it and works in game; it is
  still off by default.
- Menu rows are in alphabetical order; in-game option labels aren't cleaned the way the app's are.
