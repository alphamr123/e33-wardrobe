# Relocator (`e33_relocate.py`)

The relocator prepares outfit mods for **in-game switching**. Normally a mod's variants are
*replacers*: each one overwrites the same game files, so only one can be installed. The relocator
repacks every variant so its files live at their own unique paths. Then all variants can be
installed side by side, none of them replaces anything in the game, and the E33Wardrobe UE4SS mod
puts the one you pick on the character while you play.

How it works inside: [HOW_IT_WORKS.md](HOW_IT_WORKS.md#relocation).

- [Before you run it](#before-you-run-it)
- [Running it](#running-it)
- [Removing a mod](#removing-a-mod)
- [What it produces](#what-it-produces)
- [How slots and characters are named](#how-slots-and-characters-are-named)
- [Options](#options)
- [Skeletons and physics](#skeletons-and-physics)
- [When a variant is refused](#when-a-variant-is-refused)
- [References to assets that exist nowhere](#references-to-assets-that-exist-nowhere)
- [Limits](#limits)

## Before you run it

- Install UE4SS and put `retoc.exe` next to `e33_relocate.py` ([INSTALL.md](INSTALL.md)).
- Keep the mod unchanged in its own folder in the library.
- **Close the game.**
- If the mod is also installed in `~mods` (by hand or with Vortex), remove it there. A mod must not
  be installed as a replacer and as relocated variants at the same time.

## Running it

The easy way: drag one or more mod folders from the library onto **`tools\E33 Relocate.bat`**.

From a command prompt in the E33 Wardrobe folder:

```
py tools\e33_relocate.py --mod "<library>\<mod folder>"
```

`--mod` also takes just the folder name of a mod in the library (`--mod "Some Mod"`): the
saved library, or `Paks_ModLibrary` next to `Paks`. The game's
`Paks` folder comes from the saved setting (`--paks ... --save`) or is found automatically (Steam, and the default
Game Pass folder, where the UE4SS mod is then looked for under `Binaries\WinGDK`); otherwise add
`--paks "<game>\Sandfall\Content\Paks"`.

Several mods in one run: repeat `--mod`. Running it again for another mod **adds** to the wardrobe;
mods relocated earlier stay. Run it again for a mod after you update that mod.

It prints what each variant contains (mesh, material, texture, Blueprint) and what it skipped and
why. The same output is appended to `relocate_console.txt` (see below).

## Removing a mod

```
py tools\e33_relocate.py --remove "<mod name>"
```

deletes that mod's relocated paks and takes it out of the wardrobe (`variants.lua`); picks for it
are dropped when the game reads the wardrobe again (Settings > **Reload** in the menu, or the next
start). The mod's original files in the library stay. If the name isn't found, the relocator lists
the names it knows. To remove everything, delete `Paks\~mods\_E33Wardrobe\`, and
`wardrobe_registry.json` and `Scripts\variants.lua` in `<UE4SS>\Mods\E33Wardrobe\`.

## What it produces

| Where | What |
|---|---|
| `Paks\~mods\_E33Wardrobe\<Mod>\` | The relocated variant paks, plus `<Mod>_Shared_P` (the mod's own new assets, at paths the game doesn't have). The folder name is the mod's name with spaces and symbols turned into `_`; a short hash is added if the name has other characters (brackets, `&`, non-Latin letters), is very long, or clashes with another mod's folder. |
| `Paks\~mods\_E33Wardrobe\<Mod>\relocate_log.txt`, `relocate_report.json` | What was done for that mod |
| `Paks\~mods\_E33Wardrobe\relocate_report.json` | Every mod relocated so far |
| `Paks\~mods\_E33Wardrobe\relocate_console.txt` | The relocator's console output, appended per run (moved to `relocate_console_old.txt` above 5 MB) |
| `<UE4SS>\Mods\E33Wardrobe\` | The Lua mod itself, `Scripts\variants.lua` (the wardrobe table) and `wardrobe_registry.json` (the record of every relocated mod; delete it to start the wardrobe from scratch) |

Your own `config.lua`, settings, presets and picks are never overwritten; the relocator only
updates `main.lua`, `menu.lua`, `config.example.lua` and `enabled.txt` when they differ.

A temporary work folder of hard links is made next to `Paks` and deleted afterwards. Outputs are
written there first and only moved into place when they are complete, and paks of variants that no
longer exist in the mod are removed on a full run.

## How slots and characters are named

- A **slot** is one choice in the menu ("Lune outfit", "Lune color"). Sibling option folders in
  the mod become the variants of one slot. A folder whose name starts with `_` becomes its own
  on/off slot. A mod with just one set of paks becomes a one-option slot named after the mod.
- Variant groups in a mod's folders ("Lace dress", "Non-Lace dress") are kept in the labels, so
  the menu can keep a character's pieces in the same group.
- A slot belongs to the **character** named in the slot (`Lune outfit`, `Sciel color`), otherwise
  in the mod's name (`Maelle - <Something>`, and CamelCase names like `SomethingSciel` too),
  otherwise in the paths of the assets it replaces. It then only changes that character.

## Options

| Option | Meaning |
|---|---|
| `--paks DIR` | The game's `Sandfall\Content\Paks` folder. Default: the saved setting, or found automatically |
| `--library DIR` | The mod library, for `--mod` with just a name. Default: the saved setting, or `Paks_ModLibrary` next to `Paks` |
| `--save` | Remember `--paks`, `--library` and `--retoc` for later runs (in `tools\e33wardrobe_config.json`) |
| `--mod DIR` | A mod folder, or the name of a folder in the library (see `--library`) (repeatable) |
| `--remove NAME` | Take a relocated mod out of the wardrobe (repeatable) |
| `--version` | Print the version |
| `--only REGEX` | Only re-do the option folders whose path matches. The shared pak is still rebuilt from all of the mod's paks. |
| `--retoc PATH` | Where `retoc.exe` is, if it isn't next to the tools, in the saved setting or on `PATH` |
| `--lua-dir DIR` | The `ue4ss\Mods\E33Wardrobe` folder. By default it's derived from `--paks`: `Sandfall\Binaries\Win64\ue4ss\Mods\E33Wardrobe`, or `Binaries\WinGDK\...` when the game has a `Binaries\WinGDK` folder and no `Binaries\Win64` (Game Pass). Use this for another UE4SS layout. |
| `--out DIR` | Where to write the relocated paks (default `Paks\~mods\_E33Wardrobe`) |
| `--work DIR` | Parent folder for the temporary work folder. It must be on the same drive as the game. |
| `--keep-work` | Keep the work folder (for debugging) |
| `--skeletons original\|override\|relocate` | What to do with a mod's copy of a game skeleton (see below). Default `original`. |
| `--physics mod\|game` | What to do with a mod's copy of a game physics asset (see below). Default `mod`. |
| `--strict-imports` | Refuse variants that reference assets found in neither the game nor the mod |

## Skeletons and physics

Replacer mods often ship a copy of a game skeleton or physics asset.

- **Skeletons**, by default (`original`), a copy that would replace a game skeleton is dropped and
  the variant uses the game's, so animations keep working. A skeleton at a new path is kept.
  - `--skeletons override`: the mod's skeleton replaces the game's for everyone, the way the
    replacer did. Use it if a mod's mesh needs its own skeleton (extra bones).
  - `--skeletons relocate`: the skeleton is relocated with the variant like other assets.
- **Physics assets**, by default (`mod`), travel with the variant. `--physics game` drops the
  mod's copy and uses the game's instead. Try it if a variant makes a character fall through the
  floor, or if cloth and hair behave oddly.

## When a variant is refused

The relocator stops a variant and explains why, instead of producing a broken pak, when:

- the folder has no `.utoc` (a pak-only mod; install it in `~mods` as usual);
- a pak is encrypted;
- a pak was built for a different Unreal version;
- its container lists no `/Game` packages, or the real path of a package can't be found;
- something couldn't be extracted;
- with `--strict-imports`: it references assets that are neither in the game nor in the mod.

If a variant fails on a later run but worked before, its earlier build is kept, so it stays in the
wardrobe.

## References to assets that exist nowhere

Some cooked mods point at an asset that is neither in the game nor in the mod. The game can't find
it either when the original mod is installed, so the reference is simply empty in game. The
relocator keeps such variants and prints a note naming the package. `--strict-imports` refuses
them instead; use it to check whether a pak the mod page asks for is missing.

A reference that differs from one of the mod's own packages only in letter case (a multi-outfit mod's
Sciel Blueprint asks for `SK_Sciel_Chic_Skin`, the mod's mesh is `SK_Sciel_Chic_skin`) does work in
game: the game ignores case. retoc doesn't, so before extracting, the relocator respells such
references like the package's own name (from its header), in a copy of the container in the work
folder. The run prints `fixed the letter case of N link(s) in <container>: <old> -> <new>`.
References to game packages are never respelled: mods link to them by the package's own name, and
the game's file index can spell a folder differently (`Civil/Textures` in the index, `Civil/textures`
in the package).

## Edits and fixes (`fixes.json`)

The app's fix tools (Edit rows, Disable, Choose texture, Choose material, Bundle) save their
changes in `<UE4SS>\Mods\E33Wardrobe\fixes.json`. The relocator applies the file every time it
writes `variants.lua`, so edits survive Reinstall:

- **Edit rows**: row and option names, options moved to another row or a new one, hidden options
  (still prepared, just not in the menu), order.
- **Disabled** mods: their prepared folder sits in `Sandfall\Content\E33Wardrobe_Disabled\`
  (outside `Paks`, so the game doesn't load it) and they're left out of the menu. Relocating a
  disabled mod prepares it as usual and moves it back out; `--remove` deletes that copy too.
- **Texture and material rules**: written into the variant's entry in `variants.lua`. The menu
  uses them before its own guesses when a link or a material slot of the mod is empty.
- **Bundles**: files copied from another mod into a small container under
  `<UE4SS>\Mods\E33Wardrobe\bundles\`. The relocator treats it as part of the mod: links to
  those files resolve while it unpacks the mod, and the files go into the mod's shared pak.
  Bundled files are not reported as "two versions of one mod".

Delete `fixes.json` to drop all edits; the next run (or Reload after the app rewrites the list)
shows the mods as they come.

## Limits

- Mods packed only as a legacy `.pak` (no `.utoc` / `.ucas`) can't be relocated yet; install
  them in `~mods` as usual.
- Only `~mods` paks are relocated. LogicMods or UE4SS parts of a mod are installed by hand.
- Textures that a mod's *base* material uses directly (not as a material parameter) can't be
  swapped at runtime ([USAGE.md](USAGE.md#limitations)).
