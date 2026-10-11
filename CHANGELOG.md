# Changelog

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
