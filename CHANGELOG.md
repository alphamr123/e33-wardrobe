# Changelog

What changed in each version, newest first.

## 1.3.1

Recommended UE4SS build: 3.0.1-1176 or newer (the first line of UE4SS.log says which one you
have). 1125 still runs the menu; "Test: game dresses (B)" needs 1176.

In-game menu, crashes and freezes:
- Crash at camp right after a fast travel (twice on 17 Oct, UE4SS 1176): UE4SS crashed inside its
  property cache while the mod read a camp character's "Face" by name. The likely cause: camp
  Blueprints are loaded again on each visit, and UE4SS hands back a property of the freed one. The
  mod now finds a character's parts through the game's own component list, by their names, and
  reads parts by property only on outfit actors (their parts belong to the walking character).
  Also: nothing is read from an object whose class is loading or being removed, and a map that
  loads within 30 s of the previous one gets 6 s before the mod dresses anyone. Not yet confirmed
  in game.
- No longer touches a character that the game has already removed (seen a second after a
  battle, as "change None" in the log). Writing to it could corrupt memory.
- Never calls a method on an object UE4SS returns as "invalid" (a missing owner, parent or
  property). Inside UE4SS that is an access violation the mod can't catch. Eight such places were
  found and guarded, among them the character-name lookup in the first look at a new character,
  where earlier freezes stopped.
- When the game re-assigns a character's outfit at the start of a battle, the mod no longer reads
  the character's skin component (it can point to an object the game already freed).
- Reads a property by name only when the class says it is a plain object reference (or a name,
  number or yes/no value). A character's "Face" property is a weak reference, which UE4SS reads
  wrongly and crashes on (UE4SS issue #1433).
- Checks more than UE4SS's "valid": an object being destroyed, already garbage or still loading
  is not read or changed. It is looked at again later.
- Looks at new characters about 1 second after they appear and again 2 seconds later, never on
  the frame they appear, and leaves them to the map-load pass for 3 seconds after a map loads.
  New characters and that pass wait until the game is calm (no burst of new actors and no long
  frame in the last half second, at most 10 seconds).
- Leaves cutscene actors of no party character (Esquie, for example) alone, and Fix look leaves
  cutscene characters alone (re-dressing them during a dialogue could stop it from showing).
- Forgets objects of the previous map on every map load, so a new object at a reused address is
  never mistaken for an old one.
- A new map is also noticed through the game state starting, not only through UE4SS's LoadMap
  hook, so `HookLoadMap = 0` in UE4SS-settings.ini can be tested.

In-game menu, outfits:
- Battle and companion characters are dressed as soon as they appear. Before, no battle character
  was looked at until a pass had seen one, and no pass runs when a battle starts.
- Party members walking behind the leader get their outfit back after a battle without Fix look:
  every 2 seconds the mod checks them and dresses any whose body changed (nothing to do when
  nothing changed).
- Wear stops re-dressing a character when the game puts its own body back 3 times in a row
  within seconds (copies the game keeps for scenes; it caused stutter). It tries again after 30 s.
- An actor whose character can't be told counts as the character whose relocated mesh it shows.
  The walking character's body no longer flips between the game's mesh and the worn one.
- An outfit mesh with empty skin slots now gets the character's own skin material when the
  previous outfit's was another character's (Sciel's Chic outfit is a Lune mesh, so her lower body
  had Lune's skin tone): of the candidates, the one the mod's textures fit best.
- Colour-variant mods: textures the parent material shows too are no longer put back on every look
  (needless material rebuilds, up to 6 per character).
- Settings > "Test: game dresses (B)", off by default (experimental, needs UE4SS 1176): the game is
  given the worn variant's own outfit Blueprint when it dresses a character. 2 s after a swap the
  character's body is checked; a body without a mesh stops swaps to that Blueprint for the session.
- In-game menu: classic look like the desktop app (title bar, classic tabs, square buttons,
  aligned value column, status bar). Same pages, buttons and keys.
- `scene_copies = false` in settings.txt leaves alone the copies the game dresses for dialogue and
  battle.

In-game menu, speed:
- Mod assets are found with the engine's GetAsset instead of UE4SS's StaticFindObject first: each
  miss cost 13-27 ms, most of the 150-360 ms looks.
- Within one frame the mod keeps what it has already read (texture lists, mesh paths, property
  types): a first look at a new character takes about half the engine calls, the pass after a map
  load about a quarter.
- New characters get about 8 ms of the mod's time per frame; the four party-menu characters took
  95-309 ms each, all in one frame, after every map load.
- The check the mod runs for every actor the game creates (thousands a minute in battle) reads
  each class's name once instead of once per actor.
- Run-time named components are no longer looked up as Blueprint templates.

In-game menu, logs (live_log.txt, report.txt):
- Freeze trace: before each engine call that could hang, the mod notes what it is about to do. If
  the game thread stops, the watchdog writes the last 40 steps, ending with the call that never
  returned; "the game thread ran again after N s" says it was a stall, not a freeze.
  `trace = false` in settings.txt turns it off.
- `hitch:` lines for long frames with the mod's work just before, "slow look" lines over 100 ms,
  and a `stats` line every minute (including the time spent on every actor the game creates).
- `scene:` lines when battle, cutscene and dialogue actors appear; "game spawned ... for <actor>"
  names what each new character belongs to; "new skin" lines say which mesh it shows, and a new
  skin that isn't looked at says why.
- dump.txt shows each skeletal mesh's running animation class and mode.
- commands.txt next to the mod: its lines (console words, pick, wear, set) are run about once a
  second and logged.

Relocator:
- Mods whose internal links differ from their own file names only in letter case now prepare
  completely. The game ignores the case, but the converter didn't, and such links were lost (a
  multi-outfit Sciel mod's outfit Blueprints showed no body). Links to game files are never
  changed. Reinstall such a mod to get the fix.
- Reinstall of a disabled mod failed with "Access is denied" on Windows. Fixed.

App:
- Game log: a "last step" line after a stall while the menu was idle no longer changes the details
  of an earlier stall.

Known, not fixed:
- After "All off", menu characters can show the game's version of the worn mesh until the game
  re-dresses them (Fix look, reopening the menu).

For developers:
- scripts/collect_crash.py (moves the newest crash dump and copies the logs into one folder, with
  a first reading), scripts/analyze_dump.py (names UE4SS frames with Windows' dbghelp when
  llvm-symbolizer is missing; all threads), scripts/dump_threads.py, scripts/gen_index.py,
  tests/sabotage.py (break a line, run a suite, restore), tests/perf/count_crossings.py.
- The test suites no longer fail when the game is running on the same PC.
- The Tools zip ships a fixed list of docs.

## 1.3.0

The fix tools below are experimental: check the result in game; every fix can be undone.

App:
- **Disable / Enable** a mod without removing it: its prepared files move out of the game, the
  menu leaves it out, picks are kept.
- **Edit rows...**: rename, add, move, order and hide rows and options of a mod in the in-game
  menu. Kept in fixes.json, so Reinstall keeps them.
- **Choose texture...** / **Choose material...** for empty texture links and empty material
  slots, from the option's details or from the Game log problem. Saved as rules for that option.
- **Bundle it...**: copy a missing file from another mod of the library (often an older version
  of the same mod) into this one.
- **Fixes** group in the details: every fix of a mod with Undo and Undo all.
- **Tools** button: **Check & repair...** (missing prepared files, an old menu list), **Find the
  problem mod...** (turns half of the suspects off per round; cleared mods stay on; survives an
  app restart), **Reinstall all**.
- **Compare...** on "Two versions of one mod?": both mods side by side, then remove one.
- The app remembers which downloads a mod came from (for Compare).

In-game menu:
- Uses the rules chosen in the app (Choose texture / Choose material) before its own guesses.
- Its lines about filled textures and material slots name the option, material or mesh and
  slot, so the app can offer a Fix button for them.

Relocator:
- Applies fixes.json (row edits, hidden options, disabled mods, rules, bundles) whenever it writes
  the menu list. A disabled mod stays disabled when it's prepared again; `--remove` also deletes
  its parked copy.
- Bundled files count as part of the mod: links to them resolve and they go into its shared pak.
  They aren't reported as "two versions of one mod".
- Safer with your files: moves of prepared folders are all or nothing, two mods whose names clean
  to the same folder no longer touch each other's files, and repairing one option never overwrites
  another's pak.
- The Tools zip of 1.2.0 and 1.2.1 was missing `e33tex.py`, so the command-line relocator didn't
  start. Fixed (the app was not affected).

## 1.2.1

App:
- Mod list: tick boxes (and Ctrl+click, Shift+click) for **Reinstall selected** and **Remove
  selected** with one dialog; **Reinstall all**; a filter box.
- Every list: drag a column header's edge to resize, double-click to fit; widths are remembered.
- Mod details name things: notes list the options and files they mean (expandable), overlaps list
  the shared files, each option lists its textures (size, format) and files. Links to files the mod
  doesn't include name the missing file when the mod's paks still say it.
- "Two versions of one mod?" no longer counts PrimaryAssetLabels (cook metadata that does nothing in
  game), which two mods by one author often share.
- Replaces says "Base body" instead of the mod's name; CamelCase folder names read as words.
- Options without a swatch show no empty square. Texture sizes that weren't recorded say
  "(size ?)"; Reinstall records them.
- Image viewer for swatches and skin textures: a bigger picture read from the prepared mod, zoom,
  pan, previous / next.
- Copy: details text can be selected; right-click menus with Copy, Copy option text, Copy file paths,
  Copy all details; Ctrl+C.
- Game log: click a problem or an on-screen row to see only its log lines. When the game is closed
  it shows the last session; Show: This session / Previous session / UE4SS.log. Copy problems
  includes each problem's log lines.
- Game log: explains the menu's new lines about empty material slots of a worn mod mesh (filled with
  the body's material, or left grey).

In-game menu:
- Fixed grey bodies from outfit mods whose mesh leaves a material slot empty for the game to fill
  (a Sciel outfit mod). When such a mesh is worn, an empty slot gets the body's own material (same
  slot name, else the skin material), with the mod's textures named like the body's ones on it.
  live_log.txt says what filled each slot.

Relocator:
- Texture sizes come from the texture header when the full read fails (colour-only options showed
  no sizes), and the reason is recorded.
- The "Two versions of one mod?" warning skips PrimaryAssetLabels.

## 1.2.0

- **App** (`E33 Wardrobe.exe`, on GitHub Releases): finds the game (or asks for the folder),
  checks UE4SS, installs the in-game menu, and prepares mods dropped on the window (zip, 7z, rar,
  folders). Several downloads of one Nexus mod become one mod; options are sorted into one menu row
  per outfit. Shows each mod's rows, options, texture sizes, skin textures, notes and overlaps.
  The Game log tab reads the game's logs while it runs and lists problems.
- Relocator: records texture sizes and saves small colour swatches for the app; retoc runs without
  console windows.
- In-game menu: an empty texture link is filled with a texture of the mod that fits the parameter
  (for mods whose material borrows another option's), before falling back to the previous one.

## 1.1.0

- **Favorites**: saved looks per character, in your own order (Favorites on the "wears" row; Save look,
  Use, Up, Down, Remove). Kept in `favorites.txt`.
- A mod with options for several characters (one costume for Lune, Maelle and Sciel) gets one menu
  row per character, so each is switched on its own. Old picks carry over.
- Wear and Auto Wear work for such mods: each character gets their own mesh.
- A mod material whose texture link is broken no longer shows grey: the empty texture is filled
  with the mod's own texture of the same name, or the one the body had before.
- The release Tools zip has only the relocator. The Mod Mixer stays in the repository as an
  optional, unsupported tool.
- Relocator: `--save` remembers the Paks folder (and `--library`, `--retoc`) in its own
  `tools\e33wardrobe_config.json`; the Mixer's settings file is still read if present.
- Docs: shorter README and install guide; tools download moved to GitHub Releases.

## 1.0.0 (first public release)

- **Mod Mixer**: a library of pak mods with a browser UI and a command line. Combinations,
  presets, rules files for multi-variant mods, conflict warnings that say which pak wins,
  priorities, previews from your own screenshots and colour swatches.
- **Relocator** (`e33_relocate.py`): repacks every variant of a mod to unique asset paths of the
  same length, so all variants can be installed side by side.
- **E33Wardrobe UE4SS mod**: an in-game menu (Delete) with one tab per character, step or choose
  variants by name, Wear / Auto Wear, Clean (blood and dirt), Fix look, Undo, Randomize, Lock,
  slideshow, Peek, 8 presets, A/B compare; a session recorder and `report.txt` for bug reports.

## Development history

Pre-release builds, tested on one PC (Steam version, UE4SS 3.0.1 build 527a483b, retoc 0.1.5).

- **Build 1**: the Lua mod loads and hooks `CharacterSkinAssignPolicy`; swaps on skin actors. The
  relocator handles a package directly under `/Game` and paks with a flat file index.
- **Build 2**: the in-game menu works with the mouse; live switching. A reference to an asset that
  exists nowhere is a note instead of an error (`--strict-imports` refuses it).
- **Build 3**: body mods on pawns that aren't skin actors; one-option mods get a character and a
  name; overlaps are reported.
- **Build 4**: the `Body` shared by the skin actor and the world pawn is handled once; outfits can
  be worn over any outfit (Wear); a fix for short menu stalls.
- **Build 5**: session recorder; asset loads are traced; Wear keeps the original outfit across
  variant switches; self-heal and Fix look.
- **Build 6**: automatic dump made opt-in; watchdog; Blueprint-only fix slots no longer change a
  colour group.
- **Build 7**: all work runs in one game-thread loop (after reading the UE4SS source); the menu was
  reworked from recorded click statistics: hidden technical slots, character tabs, the "wears"
  line, Wear only where it works, plain-language reasons, named chooser buttons, Peek.
- **Build 8**: buttons size to their captions; outfit mods apply as a whole; Auto Wear.
- **Build 9**: a later pick that doesn't fit gives way to the earlier outfit; "on screen" counts
  each variant's own pieces; Fix look logs why the game ignored it.
- **Build 10**: Fix look passes each character's name to the game. A 36-minute session across three
  areas with no freeze and no Lua errors.
- **Build 11**: Clean (blood and dirt), modelled on how the Nexus clean mods work; masks on plain
  materials are handled; barefoot outfit variants no longer show boot parts on freshly spawned
  characters.
- **Build 12** (release candidate): the menu key is Delete (Insert also reloads Blueprint mods in
  UE4SS's BPModLoaderMod); the mod refuses to start on UE4SS builds without
  `LoopInGameThreadWithDelay` and says why; report.txt hides user names; a menu that fails to
  draw closes itself; the relocator can `--remove` a mod, takes folders dropped on
  `E33 Relocate.bat`, and finds the Game Pass UE4SS folder.
