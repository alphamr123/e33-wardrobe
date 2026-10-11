# Installation

There are two parts. Install part 1 first; part 2 is only needed for outfit switching.

1. [The in-game menu](#1-the-in-game-menu) (UE4SS mod): menu, Clean, Fix look.
2. [The tools](#2-the-tools) (Python): prepare outfit mods for switching in game.

Tested on the Steam version. Game Pass should work but is untested.

## 1. The in-game menu

**You need:** UE4SS for Clair Obscur, from its Nexus page (mod 630), file
**"UE4SS - Experimental (Newer)"**. Older UE4SS builds don't work.

1. Install UE4SS as its page describes.
2. Install E33 Wardrobe:
   - **Vortex:** click *Mod Manager Download* on the main file.
   - **By hand:** extract the main file into
     `...\Expedition 33\Sandfall\Binaries\Win64\ue4ss\Mods\`
     (Game Pass: `...\Binaries\WinGDK\ue4ss\Mods\`).
     Check that this file exists: `...\ue4ss\Mods\E33Wardrobe\Scripts\main.lua`.
3. Start the game, load a save, press **Delete**. The menu opens.

Recommended: in `ue4ss\UE4SS-settings.ini` set `EnableHotReloadSystem = 0`, and keep the UE4SS
console window closed while playing.

If Delete does nothing, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## 2. The tools

**You need:**
- [Python 3.8 or newer](https://www.python.org/downloads/). In the installer, tick
  *Add python.exe to PATH*.
- [retoc 0.1.5](https://github.com/trumank/retoc/releases), file
  `retoc_cli-x86_64-pc-windows-msvc.zip` (only for outfit switching).

**Set up once:**

1. Download `E33Wardrobe-Tools-<version>.zip` from the
   [GitHub releases page](https://github.com/alphamr123/e33-wardrobe/releases) and extract it
   outside the game folder, for example to `Documents\E33Wardrobe Tools`.
2. Put `retoc.exe` into its `tools` folder.
3. Create the mod library: a folder named `Paks_ModLibrary` next to the game's `Paks` folder:
   `...\Expedition 33\Sandfall\Content\Paks_ModLibrary\`.

**Add an outfit mod:**

1. Extract the mod, unchanged, into its own folder in the library, e.g.
   `Paks_ModLibrary\Some Outfit Mod\`.
2. If the mod is also in `Paks\~mods` (or installed with Vortex), remove it there.
3. Close the game.
4. Drag the mod's folder onto `tools\E33 Relocate.bat`.
5. Start the game and press Delete: the mod's variants are in the menu.

For a mod with variants for several outfits, one subfolder per outfit gives one menu row each:

```
Paks_ModLibrary\Some Outfit Mod\
    Outfit A\  variant 1\  variant 2\
    Outfit B\  variant 1\  variant 2\
```

If the game isn't found automatically (Steam and the default Game Pass folder are), tell the
tools where it is once:

```
py tools\e33_relocate.py --paks "D:\Games\Expedition 33\Sandfall\Content\Paks" --save
```

## Updating

- **Menu:** replace the files, or update in Vortex. Your settings, picks, presets, favorites and
  your own `config.lua` are kept.
- **Tools:** extract the new zip over the old folder. Keep the tools and the menu on the same
  version.
- **An outfit mod:** put the new version in the library and drag it onto `E33 Relocate.bat` again.

## Uninstalling

- **An outfit mod:** `py tools\e33_relocate.py --remove "<mod name>"`.
- **All relocated mods:** delete `Paks\~mods\_E33Wardrobe\`, and in `ue4ss\Mods\E33Wardrobe\`
  delete `wardrobe_registry.json` and `Scripts\variants.lua`.
- **Menu:** delete `ue4ss\Mods\E33Wardrobe\`, or uninstall it in Vortex.

The game's own files and your saves are never changed. Your original mod files stay in the
library.

## Where files go

| Path | What |
|---|---|
| `Paks\~mods\_E33Wardrobe\` | Relocated outfit mods |
| `ue4ss\Mods\E33Wardrobe\` | The menu, your settings, picks, presets, favorites, logs and `report.txt` |
| `Paks_ModLibrary\` | Your mods as downloaded |
