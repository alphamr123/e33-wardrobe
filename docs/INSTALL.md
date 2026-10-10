# Installation

E33 Wardrobe has two parts. You can use either or both.

| Part | What it gives you | Needs |
|---|---|---|
| **E33Wardrobe UE4SS mod** | The in-game menu (Delete): live outfit switching, Auto Wear, Clean (blood and dirt), Fix look, presets | UE4SS |
| **Tools** | The Mod Mixer (install mod combinations from your browser) and the relocator (prepares mods for live switching) | Python 3.8+; retoc for the relocator and colour swatches |

The UE4SS mod alone already gives you **Clean** and the menu. Switching outfits live needs mods
prepared by the relocator.

- [Requirements](#requirements)
- [1. The UE4SS mod](#1-the-ue4ss-mod)
- [2. The tools](#2-the-tools)
- [3. The mod library](#3-the-mod-library)
- [4. retoc](#4-retoc)
- [What goes where](#what-goes-where)
- [Updating](#updating)
- [Uninstalling](#uninstalling)

## Requirements

- Windows, Clair Obscur: Expedition 33. Tested on the Steam version. The Mixer also finds the
  default Game Pass folder; live switching on Game Pass is untested.
- **UE4SS, experimental build from December 2025 or later**, for the in-game part: the E33 UE4SS
  page on Nexus Mods (mod 630), file "UE4SS - Experimental (Newer)" (v3.0.1-1125-g527a483b is the
  tested build), or the latest experimental build from
  [RE-UE4SS releases](https://github.com/UE4SS-RE/RE-UE4SS/releases). The mod needs
  `LoopInGameThreadWithDelay`, which older builds (including the tagged 3.0.1 release) don't have; on
  those it stays off and says so in `UE4SS.log`.
- **Python 3.8 or newer** for the tools: <https://www.python.org/downloads/>. In the installer,
  tick "Add python.exe to PATH" and, at the end, click "Disable path length limit".
- **retoc v0.1.5** for the relocator and colour swatches: <https://github.com/trumank/retoc/releases>,
  file `retoc_cli-x86_64-pc-windows-msvc.zip`.

## 1. The UE4SS mod

1. Install UE4SS first (follow its page). It goes into
   `...\Expedition 33\Sandfall\Binaries\Win64\` (Game Pass: `...\Binaries\WinGDK\`).
2. Install E33Wardrobe:
   - **Vortex**: install the main file with the E33 Vortex extension, or
   - **by hand**: extract the main file into `...\Sandfall\Binaries\Win64\ue4ss\Mods\`, so that
     `...\ue4ss\Mods\E33Wardrobe\Scripts\main.lua` exists. Not one folder deeper
     (`Mods\E33Wardrobe\E33Wardrobe\...` doesn't load).
3. Start the game. `ue4ss\UE4SS.log` shows `Mod 'E33Wardrobe' has enabled.txt, starting mod.` and
   then `[E33Wardrobe] 1.0.0 ready (...) - press DEL for the menu.`,
   and **Delete** opens the menu once a save is loaded. If it instead says `This UE4SS build is too
   old for E33Wardrobe`, install a newer UE4SS (see [Requirements](#requirements)).

Recommended UE4SS settings:

- In `ue4ss\UE4SS-settings.ini` set `EnableHotReloadSystem = 0`. Ctrl+R hot reload can freeze
  UE4SS 3.0.1-1125-g527a483b for good (UE4SS issue #1445).
- Keep the UE4SS GUI / Live View closed while playing.

## 2. The tools

Extract the tools file (or clone the repository) anywhere **outside** the game folder, for example
`Documents\E33Wardrobe Tools`. Keep its `tools` and `lua` folders side by side: the relocator
installs the UE4SS mod from its own `lua\E33Wardrobe` copy.

## 3. The mod library

Both tools work from a **library**: one folder per mod, each holding the mod exactly as
downloaded.

1. Create the library. By default it is `...\Expedition 33\Sandfall\Content\Paks_ModLibrary\`, a
   folder next to `Paks` (not inside it). Keep it on the same drive as the game, so files can be
   hard-linked instead of copied. Move it out before you uninstall the game: it lives inside the
   game folder by default.
2. Extract every outfit or body mod into its own subfolder, unchanged. An extra wrapper folder
   from "Extract to <archive name>\" is fine.
   ```
   Paks_ModLibrary\
     Some Outfit Mod\Style A\...  \Style B\...
     Another Mod\...
   ```
3. **Remove those mods' files from `~mods`** (and don't also install them with Vortex). From now
   on the Mixer or the relocator installs them. The Mixer warns when it finds hand-installed
   copies.

If the game isn't found automatically (Steam and the default Game Pass folder are), tell the
tools where it is once:

```
py tools\e33_mixer.py --paks "D:\Games\Expedition 33\Sandfall\Content\Paks" config --save
```

The relocator uses this setting too.

## 4. retoc

Download `retoc_cli-x86_64-pc-windows-msvc.zip` (v0.1.5) from
<https://github.com/trumank/retoc/releases> and put `retoc.exe` into the `tools` folder, next to
`e33_relocate.py`. On first use retoc downloads `oo2core_9_win64.dll` next to itself, so it needs
internet once. Other retoc versions may work; the relocator warns when the version differs.

Next steps: the Mixer is described in [MIXER.md](MIXER.md); preparing mods for live switching in
[RELOCATOR.md](RELOCATOR.md); the in-game menu in [USAGE.md](USAGE.md).

## What goes where

| Path | Written by | What |
|---|---|---|
| `Paks\~mods\_E33Mixer\` | Mixer | The paks of the selected combination. Belongs to the Mixer: anything else there is removed. |
| `Paks\~mods\_E33Wardrobe\` | Relocator | Relocated variant paks per mod, logs and reports |
| `<UE4SS>\Mods\E33Wardrobe\` | You / Vortex / relocator | The UE4SS mod; `Scripts\variants.lua` and `wardrobe_registry.json` are written by the relocator |
| `<UE4SS>\Mods\E33Wardrobe\settings.txt`, `selection.txt`, `presets.txt` | UE4SS mod | Your settings, picks (in pick order) and presets |
| `<UE4SS>\Mods\E33Wardrobe\live_log.txt`, `live_log_previous.txt`, `dump.txt`, `report.txt` | UE4SS mod | Session recording and reports ([TROUBLESHOOTING.md](TROUBLESHOOTING.md)) |
| `<library>\.e33mixer_state.json`, `<library>\.e33mixer_previews\` | Mixer | Its state, screenshots and swatches |
| `tools\e33mixer_config.json` | Mixer | Paths on your PC |
| `Sandfall\Content\_e33wardrobe_work_*`, `_e33mixer_swatch_*` | Relocator, swatch builder | Temporary; removed at the end of a run, or by the next run if one was interrupted |

The game's own paks and your save files are never changed.

## Updating

- **UE4SS mod**: replace the files (or update in Vortex). Your settings, presets, picks and your
  own `config.lua` are kept: the download only contains `config.example.lua`.
- **Tools**: replace the folder. Keep `tools\e33mixer_config.json` if you set paths by hand. Keep
  the tools and the UE4SS mod on the same version: the relocator installs its own copy of the mod.
- **An outfit mod you relocated**: put the new version in the library and run the relocator for
  it again.

## Uninstalling

- **Mixer**: press **Disable all** (or `py tools\e33_mixer.py off`), then delete the tools folder.
- **Relocated mods**: `py tools\e33_relocate.py --remove "<mod name>"` for each mod. To remove all
  of them at once, delete `Paks\~mods\_E33Wardrobe\`, and `wardrobe_registry.json` and
  `Scripts\variants.lua` in `<UE4SS>\Mods\E33Wardrobe\`.
- **UE4SS mod**: delete `<UE4SS>\Mods\E33Wardrobe\` (or uninstall it in Vortex).

Characters go back to the outfits the game has equipped. Your original mod files stay in the
library.
