# E33 Wardrobe

Switch outfit mods for **Clair Obscur: Expedition 33** without restarting the game, or install
mod combinations from your browser with one click.

Most E33 outfit mods are *replacers*: each variant overwrites the same game files, so you can only
have one installed, and switching means moving files around with the game closed. E33 Wardrobe
gives you three tools for that:

| Part | What it does | Needs |
|---|---|---|
| **In-game menu** (UE4SS Lua mod) | Press **Delete** in game: pick outfit-mod variants per character and see them right away. Also **Clean** (blood and dirt off), **Fix look**, presets, Undo, Randomize. | UE4SS |
| **Relocator** | Repacks every variant of a mod to its own asset paths, so all of them can be installed at once. The in-game menu then switches between them live. | Python 3.8+, retoc |
| **Mod Mixer** | A library of your mods and a page in your browser: choose a combination, press Apply, start the game. Knows multi-variant mod layouts, warns about conflicts. | Python 3.8+ |

**Status: 1.0.0, beta.** Tested on the Steam version with UE4SS 3.0.1-1125-g527a483b and
retoc 0.1.5, over many sessions on one PC. Game Pass is detected but untested.

## Quick start

1. **Install UE4SS**: Nexus Mods, E33 UE4SS page (mod 630), file "UE4SS - Experimental (Newer)".
   An experimental build from December 2025 or later is required.
2. **Install the E33Wardrobe UE4SS mod** with Vortex, or extract it into
   `...\Sandfall\Binaries\Win64\ue4ss\Mods\` so that `...\Mods\E33Wardrobe\Scripts\main.lua`
   exists. Load a save and press **Delete**: Clean and Fix look work already.
3. **For live outfit switching**, extract the tools anywhere outside the game folder, install
   [Python](https://www.python.org/downloads/) and put
   [retoc](https://github.com/trumank/retoc/releases) `retoc.exe` into `tools\`. Put each outfit
   mod, unchanged, into its own folder in the library (`...\Sandfall\Content\Paks_ModLibrary\`),
   remove its files from `~mods`, and drag its folder onto **`tools\E33 Relocate.bat`**.
   In game, its variants appear in the menu.
4. **Or use the Mixer**: double-click **`tools\E33 Mod Mixer.bat`**, choose options, close the
   game, press **Apply to game**.

Step by step: [docs/INSTALL.md](docs/INSTALL.md).

## In game

| Key | Action |
|---|---|
| Delete | Open / close the menu (the mouse works in it) |
| Ctrl+arrows, Ctrl+Enter | Move through the menu and press buttons with the keyboard |
| Ctrl+PageUp / PageDown | Previous / next page |
| Ctrl+F7 / F8 / F9 | Apply again / reload the wardrobe / write a report |

- One tab per character. Each row is a slot (an outfit, a colour, a part); step through its
  variants or choose one by name. **Off** puts the game's own back.
- An outfit mod only shows on the outfit it was made for. **Auto Wear** puts it on in place of the
  current outfit for you, and **Unwear** brings the original back.
- **Clean** takes blood and dirt off every character, in battles and cutscenes too, until you
  switch it off. It changes no files.
- The status line says what each pick did, or why nothing changed.

All of it: [docs/USAGE.md](docs/USAGE.md). To change keys, copy `Scripts\config.example.lua` to `config.lua` and edit it.

## How it works

The relocator (Python + [retoc](https://github.com/trumank/retoc)) unpacks each variant, moves
every asset path to a unique path of the **same length** (so the cooked packages stay valid
without re-serialising them), and packs it again. Nothing it installs replaces a game file. The
UE4SS Lua mod hooks the game's character-skin system and, while you play, swaps meshes,
materials and textures on the character actors to the variant you picked; switching a slot off
restores the game's own. Clean blanks the game's blood and dirt mask textures at runtime with a
tiny all-zero render target, the same effect the Nexus "clean" mods get by replacing those
textures.

Details: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md). The research behind it, with evidence and
references (UE4SS source and issues, the game's type mappings, studied mods):
[docs/RESEARCH.md](docs/RESEARCH.md).

## Documentation

| | |
|---|---|
| [INSTALL.md](docs/INSTALL.md) | Requirements, installing, updating, uninstalling, what goes where |
| [USAGE.md](docs/USAGE.md) | The in-game menu, settings, console commands, limits |
| [RELOCATOR.md](docs/RELOCATOR.md) | Preparing mods for live switching; options; removing a mod |
| [MIXER.md](docs/MIXER.md) | The Mod Mixer, presets, conflicts, previews, rules files |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems, report.txt, freezes, reporting a bug |
| [HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Design: relocation, runtime swapping, Clean, threading |
| [RESEARCH.md](docs/RESEARCH.md) | Findings, evidence and references |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Repository layout, tests, code rules, releases |

## Known limits

- An outfit mod replaces the whole body mesh, so two outfit mods never layer on one character.
- The relocator handles IoStore mods (with `.utoc` / `.ucas` files), which most E33 outfit mods
  are; pak-only mods can be installed with the Mixer. LogicMods and UE4SS parts of a mod are
  installed by hand.
- Textures a mod's *base* material uses directly can't be swapped at runtime (`dump.txt` shows
  whether that matters for a mod).
- While Clean is on, faces also lose sweat and tears (the game draws them through the same masks).

## Other people's mods

The tools work on your local copies of mods you downloaded. Relocated paks contain those authors'
work: **don't share relocated paks or presets with their files** without the authors' permission,
and follow each mod's own permissions.

## Contributing

Bug reports, rules files for more mods and code are welcome: [CONTRIBUTING.md](CONTRIBUTING.md).
For a bug, attach `report.txt` (Settings > **Report** in the menu).

```
pip install -r requirements-dev.txt
python tests/run_suites.py
```

## Credits and licence

MIT licence ([LICENSE](LICENSE)). Parts of `tools/e33tex.py` follow CUE4Parse (Apache-2.0) and use
bcdec's tables; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for these and for the
projects and mods this work learned from: RE-UE4SS, retoc, FModel, E33 Randomizer, UAssetAPI, Loud
and Clear, and the Nexus blood and dirt mods by DC, Imtheonlydot and notrustk.

This project was written with an AI coding assistant (Claude) and tested in the game by a person.

Clair Obscur: Expedition 33 belongs to Sandfall Interactive and Kepler Interactive. This project
is not affiliated with them and ships no game files.
