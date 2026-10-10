# Development

How the repository is laid out, how to run the tests, and the rules the code keeps. The design
itself is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md); the research behind it in
[RESEARCH.md](RESEARCH.md).

- [Layout](#layout)
- [Running the tests](#running-the-tests)
- [What the tests cover](#what-the-tests-cover)
- [Rules for the Lua mod](#rules-for-the-lua-mod)
- [Rules for the Python tools](#rules-for-the-python-tools)
- [The variants.lua contract](#the-variantslua-contract)
- [Making a release](#making-a-release)

## Layout

| Path | What |
|---|---|
| `lua/E33Wardrobe/Scripts/main.lua` | The UE4SS mod: hooks, swapping, Wear, Clean, Fix look, recorder, console commands, the game-thread loop |
| `lua/E33Wardrobe/Scripts/menu.lua` | The in-game menu (UMG built from Lua). Gets an API table from `main.lua` |
| `lua/E33Wardrobe/Scripts/config.example.lua` | Keys and outfit names. Users copy it to `config.lua`, which no update or relocator run touches |
| `lua/E33Wardrobe/Scripts/variants.lua` | Placeholder (`return {}`); the relocator writes the real one |
| `tools/e33_mixer.py`, `e33_mixer_ui.html`, `e33rules.py`, `e33previews.py` | The Mod Mixer: library scan, rules, local web UI, previews |
| `tools/e33_relocate.py` | The relocator |
| `tools/e33legacy.py`, `e33utoc.py`, `e33tex.py` | Readers for legacy packages, IoStore `.utoc`, and textures (BC1-7 decoding for swatches) |
| `tools/e33common.py` | Version, game-process check, Paks-folder check (`global.utoc`), stale work-folder cleanup |
| `tools/rules/` | Rules files for multi-variant mods |
| `tests/` | Test suites (scripts that print `PASS` / `FAIL`), `run_suites.py` runs them all |
| `research/usmap.py` | Reader for `.usmap` mappings, used during research |
| `scripts/build_release.py` | Builds the release zips into `dist/` |

## Running the tests

```
pip install -r requirements-dev.txt
python tests/run_suites.py
```

or `pytest` from the repository root. Each suite is also a plain script
(`python tests/test_lua_menu.py`). The tools need nothing beyond Python 3.8; the tests need
[lupa](https://github.com/scoder/lupa) (Lua 5.4 in Python) for the Lua suites, and pytest only if
you want to use it.

Three suites need game-format fixtures that can't be put in the repository. They are skipped
unless these environment variables point at fixtures you build yourself:

| Suite | Variables | Fixture |
|---|---|---|
| `test_relocate_e2e.py` | `E33_E2E_PAKS`, `E33_E2E_BASE`, `E33_RETOC` | A fake game: `global.utoc` from `retoc gen-script-objects`, plus a base container built from a legacy tree with `Environment/SM_BlueCube`, `Materials/MI_BlueCube`, `Materials/M_Cube`. The suite builds its own mod library from it, relocates it and checks every import with retoc. See the file's docstring |
| `test_previews.py` | `E33_PREVIEW_GLOBAL`, `E33_PREVIEW_LEGACY`, `E33_RETOC` | Script objects that include `Texture2D`, and cooked textures in legacy form |
| `test_relocation.py` | `E33_RELOC_SRC`, `E33_RETOC` | A legacy package tree to relocate and read back |

## What the tests cover

- **Lua suites** run the real `main.lua` and `menu.lua` in lupa against a mock of the UE4SS API
  (objects, classes, hooks, key binds, the game-thread loop, UMG widgets).
  `test_lua_mock_real.py` uses a stricter mock that follows the RE-UE4SS source where it differs
  from the docs (TArray returns, class property lookups, component templates). The menu and
  strict-mock suites also record engine calls made off the game thread and fail on them.
  - `test_lua_mock.py`, `test_lua_switching.py`: swapping, reverting, spawns, the dump.
  - `test_lua_coverage.py`: pawns that aren't skin actors, Wear, the recorder, reports, settings.
  - `test_lua_outfit_whole.py`: outfit mods applying as a whole, Auto Wear, barefoot variants,
    Fix look.
  - `test_lua_clean.py`: Clean, including object address reuse and level changes.
  - `test_lua_dispatch.py`: the threading model, and refusing to start on old UE4SS builds.
  - `test_lua_menu.py`: the menu, driven by keys and clicks.
- **`test_mixer.py`**: the Mixer on a fake library (`make_fake_library.py`): rules, apply,
  pending changes, atomic copies, refusing wrong folders.
- **`test_relocate_e2e.py`**: the relocator end to end (see above).
- **`test_relocation.py`**: same-length relocation of real cooked packages, read back with retoc.
- **`test_previews.py`**: colour swatches from cooked textures, saved looks, the screenshot server.

Add a check for any behaviour you change. A good check fails when the change is reverted.

## Rules for the Lua mod

- **One game-thread loop.** UE4SS runs hooks and game-thread work on one shared Lua stack, and
  queuing work to the game thread from another thread races on it (RESEARCH.md). So:
  - only the start-up makes an `ExecuteInGameThread` call; it starts one
    `LoopInGameThreadWithDelay` loop;
  - key binds and console commands only post to `INBOX`; the loop runs them;
  - timers are counted in loop ticks (`later()` and `SCHED`), never `ExecuteWithDelay` or
    `LoopAsync` (the watchdog is the one async loop, and it only reads a timestamp).
- **Lua's 200-locals limit.** `main.lua` is close to it at the top level. Group new state into
  the existing tables (`FILES`, `REC`, `PASS`, `Clean`, `Fix`) or a `do ... end` block. If the
  file goes over, every Lua suite fails at load with "too many local variables".
- **Engine objects can die and their address can be reused.** Anything kept across ticks
  (materials, textures, the Clean render target) is checked with `IsValid`, its name and `IsA`
  before use; tables keyed by an address also keep the name and check it.
- **Every engine call that can fail is wrapped in `pcall`**, and errors are logged with what was
  being done. Diagnostic code (dump, report) must never stop at the first error.
- **Logs**: `log()` goes to UE4SS.log and the session log; `live()` only to the session log.
  Before an asset load, write `loading <path>`, so a hang shows what it was loading.
- **Text**: user-facing messages say what happened and what to do, in plain words.

## Rules for the Python tools

- Python 3.8+, standard library only. They run on Windows; the tests run on Linux too.
- Write only to the tool's own folders (`~mods\_E33Mixer`, `~mods\_E33Wardrobe`, the UE4SS mod
  folder, temporary work folders next to `Paks`), and never while the game runs.
- Write files atomically (`.tmp` + `os.replace`). Work folders carry a `.lock` file while in use;
  a later run removes stale ones.
- Never follow links out of a folder the tool deletes from.
- Treat everything read from a mod (folder names, package names) as untrusted: package paths go
  through `e33legacy.safe_package`, file names through `safe_name`.

## The variants.lua contract

The relocator writes `Scripts/variants.lua`; the Lua mod loads it as data only (no globals):

```lua
return {
  { mod = "Some Mod", slots = {
    { id = "Some Mod/Lune outfit", label = "Some Mod: Lune outfit", character = "Lune", variants = {
      { id = "Some Mod/Lune outfit/Style A", label = "Style A", map = {
        ["/Game/Characters/.../SK_Lune_X_Skin"] = { "/Game/ZW.../SK_Lune_X_Skin", "SK_Lune_X_Skin", "SkeletalMesh", true },
      } },
    } },
  } },
}
```

Each `map` entry: original package path → `{ relocated package, object name, class, overrides a
game asset }`. `character` is optional. The relocator also keeps `wardrobe_registry.json` (every
mod relocated so far) and rebuilds `variants.lua` from it. If you change the format, change both
sides and the tests in the same commit.

## Making a release

1. Set the version in `tools/e33common.py` (`VERSION`) and `main.lua` (`local VERSION`); they must
   match.
2. Add a `CHANGELOG.md` entry.
3. `python tests/run_suites.py` (with the fixtures if you have them).
4. `python scripts/build_release.py` writes `dist/E33Wardrobe-Lua-<version>.zip` (the UE4SS mod,
   root `E33Wardrobe/`, without `variants.lua`) and `dist/E33Wardrobe-Tools-<version>.zip`.
   `--with-rules` adds `tools/rules/`.
