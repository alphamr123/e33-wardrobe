# Index (generated)

Written by `scripts/gen_index.py` from the code. Do not edit by hand: run `python scripts/gen_index.py`. `tests/test_docs_index.py` fails when it is out of date.

- [Files](#files)
- [App API](#app-api)
- [Game hooks](#game-hooks)
- [Config keys](#config-keys)
- [Environment variables](#environment-variables)
- [Log lines the app reads](#log-lines-the-app-reads)

## Files


### (root)

| File | What it is |
|---|---|
| `CHANGELOG.md` | Changelog: What changed in each version, newest first |
| `CONTRIBUTING.md` | Contributing: How to report a bug, add rules for a mod, or send a code change |
| `LICENSE` | MIT licence |
| `README.md` | E33 Wardrobe: Install all your outfit mods for Clair Obscur: Expedition 33 at once and switch between them |
| `THIRD_PARTY_NOTICES.md` | Third-party notices |
| `pytest.ini` | Lets plain `pytest` run the suites: it collects tests/run_suites.py only (each suite is a script) |
| `requirements-dev.txt` | For running the tests (python tests/run_suites.py, or pytest) and the app from the repository |

### .github

| File | What it is |
|---|---|
| `.github/ISSUE_TEMPLATE/bug_report.md` | Bug report |
| `.github/workflows/build-app.yml` | Builds "E33 Wardrobe.exe" (plus the Lua and Tools zips) on Windows |

### app

| File | What it is |
|---|---|
| `app/API.md` | E33 Wardrobe app: UI <-> backend contract |
| `app/__init__.py` | E33 Wardrobe desktop app (see app/e33app.py) |
| `app/e33app.py` | E33 Wardrobe app: a window around app/ui (pywebview), or a small HTTP bridge for testing |
| `app/e33wardrobe.spec` | PyInstaller spec for "E33 Wardrobe.exe" (one folder, windowed) |
| `app/backend/__init__.py` | Backend of the E33 Wardrobe desktop app: the `Api` object the window calls (see app/API.md) |
| `app/backend/api.py` | class Api: every method of app/API.md |
| `app/backend/archives.py` | Unpacking dropped mod archives (zip, 7z, rar) and folders into a mod folder for the library |
| `app/backend/assets.py` | Reading a mod's files on demand, for the Mods tab |
| `app/backend/culprit.py` | Find the problem mod: turn half of the suspects off, ask whether the problem still happens, repeat with the half that has it, until one mod is left |
| `app/backend/fixes.py` | Fixes the user makes in the app: disable / enable, menu row edits, texture and material rules, bundled files |
| `app/backend/jobs.py` | The background queue: one worker thread runs add / reinstall / remove jobs one after another |
| `app/backend/library.py` | The mod library: sorting a mod's options by outfit, and describing each mod for the UI |
| `app/backend/monitor.py` | Live game-log watcher: the `Monitor` of app/API.md (monitor(), problems_text()) |
| `app/backend/paths.py` | Where things are: the app's own data, bundled resources, the game, UE4SS and the in-game menu |
| `app/backend/repair.py` | Check & repair: what the app made for each mod is still there and the in-game menu's list is current |
| `app/ui/app.css` | E33 Wardrobe: classic dark desktop look (MO2 / Windows 7 era utilities) |
| `app/ui/app.js` | E33 Wardrobe UI: the window's logic, in plain JS (no framework, no network) |
| `app/ui/index.html` | E33 Wardrobe app window: the page pywebview shows (app.js fills it, app.css styles it) |
| `app/ui/mock.js` | Fake backend for previewing the UI without Python |

### docs

| File | What it is |
|---|---|
| `docs/APP.md` | The E33 Wardrobe app |
| `docs/DEVELOPMENT.md` | Development: How the repository is laid out, how to run the tests, and the rules the code keeps |
| `docs/HOW_IT_WORKS.md` | How it works |
| `docs/INSTALL.md` | Installation: How to install the in-game menu and prepare outfit mods, with the app or by hand |
| `docs/MIXER.md` | Mod Mixer |
| `docs/README.md` | Docs: where to look |
| `docs/RELOCATOR.md` | Relocator (`e33_relocate.py`) |
| `docs/RESEARCH.md` | Research notes |
| `docs/TROUBLESHOOTING.md` | Troubleshooting: What to do when something doesn't work, and how to send a report |
| `docs/USAGE.md` | Using the in-game wardrobe |
| `docs/glossary.md` | Glossary: Words used in the code, the logs and the docs |

### lua

| File | What it is |
|---|---|
| `lua/E33Wardrobe/enabled.txt` | UE4SS reads it: "1" starts the mod |
| `lua/E33Wardrobe/Scripts/config.example.lua` | E33Wardrobe keys and outfit names: an example |
| `lua/E33Wardrobe/Scripts/main.lua` | E33Wardrobe - switch outfit-mod variants in game, for Clair Obscur: Expedition 33 |
| `lua/E33Wardrobe/Scripts/menu.lua` | E33Wardrobe in-game menu |
| `lua/E33Wardrobe/Scripts/variants.lua` | Replaced by e33_relocate.py with your relocated variants |

### research

| File | What it is |
|---|---|
| `research/usmap.py` | Minimal .usmap reader (versions 0-4, none/zstd compression) |

### scripts

| File | What it is |
|---|---|
| `scripts/analyze_dump.py` | Read a minidump of a frozen or crashed game: where the game thread is, the access violation on its stack if there is one, and the UE4SS / Lua … |
| `scripts/build_release.py` | Build the two release archives into dist/ |
| `scripts/collect_crash.py` | Collect a game crash in one folder: the newest crash dump, the logs, and a first reading of it |
| `scripts/dump_threads.py` | Every thread of a freeze dump: where it is, its system call, the first modules on its stack, and which add-ons (UE4SS, ReShade/relimiter, frame … |
| `scripts/gen_index.py` | Write docs/index.md: every file with its one-line purpose, the app's API, the mod's game hooks, every config key and environment variable, and the … |
| `scripts/render_app.py` | Render the app's screens (mock data) to PNG, to look at the UI without Windows or the backend |

### tests

| File | What it is |
|---|---|
| `tests/make_fake_library.py` | Build a fake library with the folder layout of the multi-variant mod in tools/rules (dummy paks, valid tiny .utoc) |
| `tests/render_menu.py` | Render the in-game menu to PNG files, to look at layout changes without the game (needs lupa and a Chromium; see docs/DEVELOPMENT.md) |
| `tests/run_suites.py` | Run every test suite: python tests/run_suites.py (or: pytest) |
| `tests/sabotage.py` | Break one line of the code on purpose, run a test suite, put the line back: a test that never fails can't be trusted |
| `tests/test_app_backend.py` | The desktop app's backend (app/backend): game folder, UE4SS and menu detection, archives, sorting by outfit, mod list and details, the job queue … |
| `tests/test_app_monitor.py` | Tests for the app's live game-log watcher, app/backend/monitor.py (run: python tests/test_app_monitor.py) |
| `tests/test_app_ui.py` | The app end to end: the real UI (app/ui) and backend (app/backend) through the dev HTTP bridge, driven in Chromium with Playwright, against a fake … |
| `tests/test_collect_crash.py` | scripts/collect_crash.py on a fake game folder: the newest dump is moved, the logs copied, the mod's last steps shown (no game, no retoc; the dump … |
| `tests/test_docs_index.py` | docs/index.md is generated from the code (scripts/gen_index.py) and must be current; every source file starts with a header line saying what it is … |
| `tests/test_lua_clean.py` | Clean: blood and dirt off the characters (needs lupa) |
| `tests/test_lua_coverage.py` | Which actors get swapped, for which character, and which pick wins (needs lupa) |
| `tests/test_lua_dispatch.py` | Threading model (needs lupa): after start-up nothing is queued to the game thread from anywhere |
| `tests/test_lua_menu.py` | In-game menu (Scripts/menu.lua) against a mock UE4SS + UMG (needs lupa) |
| `tests/test_lua_mock.py` | Run E33Wardrobe/Scripts/main.lua against a mock UE4SS API (needs: pip install lupa) |
| `tests/test_lua_mock_real.py` | Stricter variant of test_lua_mock.py: the mock follows RE-UE4SS source behaviour |
| `tests/test_lua_outfit_whole.py` | Outfit mods apply as a whole, and Auto Wear (needs lupa) |
| `tests/test_lua_redesign.py` | The redesign-B probe in main.lua: reading the outfit the game asks for, coverage of new skins, the variants' own Blueprints, and the two swap tests … |
| `tests/test_lua_switching.py` | Live-switching material regressions (needs lupa) |
| `tests/test_mixer.py` | Scenario tests for e33_mixer on a fake library (run: python -I tests/test_mixer.py) |
| `tests/test_previews.py` | Preview tests: swatches from real cooked textures, saved looks, screenshot serving, VT tiles |
| `tests/test_relocate_e2e.py` | End-to-end relocator test against a fake game (no real E33 files needed) |
| `tests/test_relocate_units.py` | Small pure functions of the relocator (no game files, no retoc) |
| `tests/test_relocation.py` | Relocation tests on real cooked legacy assets |
| `tests/perf/count_crossings.py` | Count the mod's calls into UE4SS ("crossings") per scenario, to measure what a change costs |
| `tests/perf/count_mock.lua` | Counting UE4SS mock: every index on an engine proxy (UObject, struct, TArray, FName) is one Lua->C++ crossing in real UE4SS |
| `tests/perf/count_scenario.lua` | Sciel skin copy showing SK_Sciel_Placeholder, Wear on for Sciel (forced relocated SK_Sciel_Chic_skin), plus a cutscene Esquie pawn |

### tools

| File | What it is |
|---|---|
| `tools/E33 Mod Mixer.bat` | Starts the E33 Mod Mixer in your browser |
| `tools/E33 Relocate.bat` | Drag one or more mod folders from your library onto this file to relocate them for in-game switching |
| `tools/e33_mixer.py` | E33 Mod Mixer - keep variant mods in a library and switch combinations without hand-copying |
| `tools/e33_mixer_ui.html` | E33 Mod Mixer page, served by e33_mixer.py (optional tool, not in releases) |
| `tools/e33_relocate.py` | E33 Relocator - turn replacer variant paks into side-by-side "wardrobe" paks |
| `tools/e33common.py` | Shared by the E33 Wardrobe tools: version, "is the game running?", console set-up |
| `tools/e33fixes.py` | Per-mod edits and fix rules for the in-game menu, kept in fixes.json in the menu folder (ue4ss\\Mods\\E33Wardrobe) |
| `tools/e33legacy.py` | Legacy (.uasset/.uexp) helpers for cooked UE5.4 packages, as produced by `retoc to-legacy` |
| `tools/e33previews.py` | Outfit previews for the E33 Mod Mixer |
| `tools/e33rules.py` | Variant-mod model: scan a mod folder into choices, evaluate rules, resolve pak lists |
| `tools/e33tex.py` | Read a cooked UE5 texture (legacy .uasset/.uexp/.ubulk as written by `retoc to-legacy`) and decode a small mip to RGBA - pure Python, no dependencies |
| `tools/e33utoc.py` | Read the file list of an Unreal IoStore container (.utoc) without the game |

## App API

The UI calls these through pywebview (`window.pywebview.api.<method>`), or in dev and tests through `POST /api/<method>` on `app/e33app.py --dev PORT`. The contract is `app/API.md`.

| Method | Defined in | In API.md |
|---|---|---|
| `get_state` | `app/backend/api.py` | yes |
| `set_game_folder` | `app/backend/api.py` | yes |
| `pick_game_folder` | `app/backend/api.py` | yes |
| `detect_game` | `app/backend/api.py` | yes |
| `pick_files` | `app/backend/api.py` | yes |
| `pick_folder` | `app/backend/api.py` | yes |
| `add_paths` | `app/backend/api.py` | yes |
| `poll` | `app/backend/api.py` | yes |
| `list_mods` | `app/backend/api.py` | yes |
| `mod_details` | `app/backend/api.py` | yes |
| `reinstall_mod` | `app/backend/api.py` | yes |
| `remove_mod` | `app/backend/api.py` | yes |
| `install_menu` | `app/backend/api.py` | yes |
| `open_path` | `app/backend/api.py` | yes |
| `open_url` | `app/backend/api.py` | yes |
| `monitor` | `app/backend/api.py` | yes |
| `problems_text` | `app/backend/api.py` | yes |
| `get_settings` | `app/backend/api.py` | yes |
| `save_settings` | `app/backend/api.py` | yes |
| `clear_jobs` | `app/backend/api.py` | yes |
| `pick_library_folder` | `app/backend/api.py` | yes |
| `reinstall_mods` | `app/backend/api.py` | yes |
| `remove_mods` | `app/backend/api.py` | yes |
| `texture_preview` | `app/backend/api.py` | yes |
| `monitor_file` | `app/backend/api.py` | yes |
| `set_disabled` | `app/backend/api.py` | yes |
| `rows_editor` | `app/backend/api.py` | yes |
| `save_rows` | `app/backend/api.py` | yes |
| `texture_choices` | `app/backend/api.py` | yes |
| `set_texture_rule` | `app/backend/api.py` | yes |
| `material_choices` | `app/backend/api.py` | yes |
| `set_material_rule` | `app/backend/api.py` | yes |
| `bundle_plan` | `app/backend/api.py` | yes |
| `bundle` | `app/backend/api.py` | yes |
| `undo_fix` | `app/backend/api.py` | yes |
| `undo_all_fixes` | `app/backend/api.py` | yes |
| `check_mods` | `app/backend/api.py` | yes |
| `repair` | `app/backend/api.py` | yes |
| `repair_option` | `app/backend/api.py` | yes |
| `compare_mods` | `app/backend/api.py` | yes |
| `culprit` | `app/backend/api.py` | yes |
| `reconcile` | `app/backend/api.py` | yes |

Dev bridge paths (`app/e33app.py`): `/`, `/api/`

## Game hooks

Where the in-game mod is entered from the game (UE4SS registrations).

| Registration | Target | File |
|---|---|---|
| `RegisterBeginPlayPostHook` |  | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterLoadMapPreHook` |  | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterLoadMapPostHook` |  | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterInitGameStatePostHook` |  | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterConsoleCommandHandler` |  | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterHook` | `/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkin` | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterHook` | `/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkinAsync` | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterHook` | `/Script/SandFall.CharacterSkinAssignPolicy:AssignFaceSkin` | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterHook` | `/Script/SandFall.CharacterSkinAssignPolicy:AssignFaceSkinAsync` | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterHook` | `/Script/SandFall.CharacterSkinAssignPolicy:AssignBodyAndFaceSkin` | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterHook` | `/Script/SandFall.CharacterSkinAssignPolicy:AssignBodyAndFaceSkinAsync` | `lua/E33Wardrobe/Scripts/main.lua` |
| `RegisterLoadMapPostHook` |  | `lua/E33Wardrobe/Scripts/menu.lua` |
| `RegisterLoadMapPreHook` |  | `lua/E33Wardrobe/Scripts/menu.lua` |

## Config keys

### In-game settings (`Mods/E33Wardrobe/settings.txt`, defaults in `main.lua` SETTINGS)

| Key | Default |
|---|---|
| `scoping` | `true` |
| `auto_apply` | `true` |
| `recheck_ms` | `700` |
| `side` | `"right"` |
| `scale` | `100` |
| `block_look` | `true` |
| `cursor` | `true` |
| `ui_input` | `false` |
| `legacy_keys` | `false` |
| `random_off` | `false` |
| `slideshow_s` | `4` |
| `locks` | `""` |
| `wear` | `""` |
| `match_groups` | `true` |
| `record` | `true` |
| `auto_report` | `false` |
| `show_technical` | `false` |
| `tab` | `""` |
| `peek_s` | `3` |
| `auto_wear` | `true` |
| `clean` | `false` |
| `scene_copies` | `true` |
| `trace` | `true` |
| `b_soft` | `"auto"` |
| `b_swap` | `"off"` |

### Keys (`Scripts/config.lua`, example in `config.example.lua`)

| Name | Default key |
|---|---|
| `menu` | `DEL` |
| `menuUp` | `CONTROL+UP_ARROW` |
| `menuDown` | `CONTROL+DOWN_ARROW` |
| `menuLeft` | `CONTROL+LEFT_ARROW` |
| `menuRight` | `CONTROL+RIGHT_ARROW` |
| `menuOk` | `CONTROL+RETURN` |
| `menuPageUp` | `CONTROL+PAGE_UP` |
| `menuPageDown` | `CONTROL+PAGE_DOWN` |
| `apply` | `CONTROL+F7` |
| `reload` | `CONTROL+F8` |
| `dump` | `CONTROL+F9` |
| `nextSlot` | `CONTROL+F5` |
| `prevSlot` | `CONTROL+SHIFT+F5` |
| `nextVariant` | `CONTROL+F6` |
| `prevVariant` | `CONTROL+SHIFT+F6` |

### App settings (app data folder, `app/backend/api.py`)

`game_root`, `library`, `watch_game`

### Relocator config (`tools/e33wardrobe_config.json`, `tools/e33_relocate.py --save`)

`library`, `paks_dir`, `retoc`

## Environment variables

| Variable | Used in |
|---|---|
| `E33_APPDATA` | `app/backend/paths.py`, `tests/test_app_backend.py`, `tests/test_app_ui.py` |
| `E33_CHROME` | `tests/test_app_ui.py` |
| `E33_CONFIG` | `app/backend/paths.py`, `tests/test_app_backend.py`, `tests/test_relocate_e2e.py`, `tools/e33_relocate.py` |
| `E33_E2E_BASE` | `tests/run_suites.py`, `tests/test_app_backend.py`, `tests/test_app_ui.py` |
| `E33_E2E_PAKS` | `tests/run_suites.py`, `tests/test_app_backend.py`, `tests/test_app_ui.py` |
| `E33_LUA_TEMPLATE` | `app/backend/paths.py`, `tests/test_app_backend.py`, `tools/e33_relocate.py` |
| `E33_OFFLINE` | `app/backend/archives.py`, `tests/test_app_backend.py`, `tests/test_app_ui.py` |
| `E33_PREVIEW_GLOBAL` | `tests/run_suites.py` |
| `E33_PREVIEW_LEGACY` | `tests/run_suites.py` |
| `E33_RELOC_SRC` | `tests/run_suites.py` |
| `E33_RENDER_FONTS` | `scripts/render_app.py` |
| `E33_REQUIRE_BIN` | `.github/workflows/build-app.yml`, `app/e33wardrobe.spec` |
| `E33_RETOC` | `app/backend/paths.py`, `tests/run_suites.py`, `tests/test_app_backend.py`, `tests/test_app_ui.py` |
| `E33_SAMPLE_ARCHIVES` | `tests/run_suites.py`, `tests/test_app_ui.py` |
| `E33_SAMPLE_MOD` | `tests/run_suites.py`, `tests/test_app_backend.py` |
| `E33_SHOTS` | `tests/test_app_ui.py` |
| `E33_WIN64` | `scripts/collect_crash.py` |

## Log lines the app reads

`app/backend/monitor.py` turns these lines into Game log problems. Changing their text in `main.lua` or `menu.lua` breaks the app; `tests/test_app_monitor.py` covers them. Source: `mod` = the menu's own messages (`[E33Wardrobe] …` in UE4SS.log, `log: …` in live_log.txt), `live` = other live_log.txt lines, `ue4ss` = UE4SS.log.

| Source | Line (regular expression) | Shown in the Game log as |
|---|---|---|
| mod | `This UE4SS build is too old for E33Wardrobe` | UE4SS is too old for the in-game menu |
| mod | `^LoopInGameThreadWithDelay failed \((?P<err>.*)\)` | The in-game menu couldn't start |
| mod | `^could not reach the game thread \((?P<err>.*)\)` | The in-game menu couldn't start |
| mod | `^menu not available: (?P<err>.*)` | The in-game menu failed to load |
| mod | `^menu could not be built: (?P<err>.*)` | The in-game menu couldn't open |
| mod | `^menu closed after an error while drawing it: (?P<err>.*)` | The in-game menu closed after an error |
| mod | `^menu: no player controller yet` | The menu needs a loaded save |
| mod | `^variants\.lua missing or invalid \((?P<err>.*)\)` | The menu couldn't read its outfit list |
| mod | `^config\.lua has an error, so the default keys are used: (?P<err>.*)` | config.lua has an error |
| mod | `^config\.lua: (?P<what>.*)` | A key in config.lua was not bound |
| mod | `^could not bind (?P<k>\S+): (?P<err>.*)` | Couldn't bind the {k} key |
| mod | `^menu action '(?P<action>[^']*)' failed: (?P<err>.*)` | The menu button '{action}' failed |
| mod | `^apply failed(?: on (?P<actor>\S+))?: (?P<err>.*)` | Applying the picks failed |
| mod | `^error: (?P<err>.*)` | The menu hit a Lua error |
| mod | `^\[(?:Error\|Fatal)\]\s*(?P<err>.*)` | The menu hit a Lua error |
| mod | `^could not load (?P<path>\S+)` | Couldn't load {leaf} |
| mod | `^(?P<file>dump\.txt\|report\.txt) stopped early: (?P<err>.*)` | {file} is incomplete |
| mod | `^cannot write (?P<path>.+)` | Couldn't write {name} |
| mod | `^dropped (?P<n>\d+) pick\(s\) of mods no longer in the wardrobe` | Cleared {n} pick(s) of removed mods |
| mod | `^dropped Wear from slots that have no mesh to wear` | Wear was switched off on some rows |
| mod | `^RegisterBeginPlayPostHook unavailable` | New characters are dressed a little later |
| mod | `\.lua:\d+: \|stack traceback\|attempt to (?:index\|call\|compare\|perform\|concatenate)` | The menu hit a Lua error |
| mod | `\bfailed\b` | Something in the menu failed |
| mod | `\bcould not\b` | The menu could not finish something |
| live | `^WATCHDOG: the game thread has not run for (?P<s>\d+) s; mod state: (?P<state>.+?)(?: \(since (?P<since>[\d:]+)\))?$` | handled by _watchdog |
| live | `^WATCHDOG: last mod step: (?P<step>.+)$` | handled by _watchdog_step |
| live | `^WATCHDOG: the game thread ran again after (?P<s>\d+) s$` | handled by _watchdog_resumed |
| live | `^Auto Wear: (?P<slot>.+) doesn't fit what (?P<char>.+?) wears; worn in place of it` | handled by _autowear |
| live | `^change \S+ \[(?P<char>[^\]]*)\]\.\S+: mat\d+ texture (?P<param>.+?): empty \(the mod's material points at a texture it doesn't have\) -> (?P<tex>\S+)(?: \((?P<src>[^)]*)\))?` | Filled in a missing texture for {char} |
| live | `^change \S+ \[(?P<char>[^\]]*)\]\.\S+: mat(?P<idx>\d+) empty \(the mod's mesh has no material for slot (?P<slot>[^)]*)\) and nothing to fill it with` | An outfit part shows grey: the mod's mesh has no material for slot {slot} |
| live | `^change \S+ \[(?P<char>[^\]]*)\]\.\S+: mat(?P<idx>\d+) empty \(the mod's mesh has no material for slot (?P<slot>[^)]*)\) -> (?P<mat>\S+)(?: \((?P<src>[^)]*)\))?` | Filled an empty material slot on {char}'s outfit |
| live | `^Fix look: ApplyCurrentCharacterSkin failed on (?P<who>\S+): (?P<err>.*)` | Fix look didn't work on some characters |
| live | `^clean: could not make the all-zero texture: (?P<err>.*)` | Clean couldn't make its blank texture |
| live | `live log reached 20 MB` | The session log is full (20 MB) |
| ue4ss | (no pattern: a handler passes it the line) | Lua error in the in-game menu |
| ue4ss | `Ref was not function` | UE4SS reported 'Ref was not function' |
| ue4ss | `E33Wardrobe[\\/\'"\]]` | handled by _ue_lua |
| any | `nothing on screen changed: made for (?P<made>[^;]+); (?P<char>\S+) wears (?P<worn>[^.;]+)` | The picked outfit is made for {made} |
| any | `nothing on screen changed: (?P<why>.+)` | Nothing on screen changed |
