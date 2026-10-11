# E33 Wardrobe

Install all your outfit mods for **Clair Obscur: Expedition 33** at once and switch between them
in game, per character, without restarting.

Most outfit mods replace game files, so only one variant can be installed at a time. The
E33 Wardrobe app repacks each mod so they can all be installed together, and the in-game menu
switches between them while you play.

## What's included

- **App** (`E33 Wardrobe.exe`, Windows): the main tool. It finds the game, installs the in-game
  menu, and prepares outfit mods: drop the downloads (zip, 7z, rar) on the window. It shows what
  each mod changes (rows, options, textures, skin, overlaps) and reads the game's logs to point
  out problems.
- **In-game menu** (UE4SS mod). Press **Delete**.
  - One tab per character; pick, step through or turn off each mod.
  - **Auto Wear:** a mod made for another outfit is put on in place of the current one.
  - **Favorites:** save looks per character and order them.
  - **Clean:** removes blood and dirt from all characters. No files changed.
  - **Fix look**, presets, undo, randomize.
- **Command-line tools** (Python), for those who prefer them: the relocator the app uses.

## Install

1. Install [UE4SS](https://www.nexusmods.com/clairobscurexpedition33/mods/630), file
   "UE4SS - Experimental (Newer)".
2. Download `E33Wardrobe-App-<version>.zip` from
   [Releases](https://github.com/alphamr123/e33-wardrobe/releases), extract it and run
   `E33 Wardrobe.exe`. The Setup tab finds the game and installs the in-game menu.
3. Drop outfit mod downloads (zip, 7z, rar) on the window. Start the game and press Delete.

App guide: [docs/APP.md](docs/APP.md). Without the app (Vortex, command line):
[docs/INSTALL.md](docs/INSTALL.md).

## Keys

| Key | Action |
|---|---|
| Delete | Open / close the menu |
| Ctrl + arrows, Ctrl + Enter | Use the menu with the keyboard |
| Ctrl + F9 | Write `report.txt` (attach it to bug reports) |

To change keys, copy `Scripts\config.example.lua` to `config.lua` and edit it.

## Documentation

- [APP.md](docs/APP.md): the app
- [INSTALL.md](docs/INSTALL.md): installing without the app, updating, uninstalling
- [USAGE.md](docs/USAGE.md): the menu in detail, settings, console commands
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): common problems, freezes, reporting a bug
- [RELOCATOR.md](docs/RELOCATOR.md): the relocator and its options
- [HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) and [RESEARCH.md](docs/RESEARCH.md): design and
  research notes, with references
- [DEVELOPMENT.md](docs/DEVELOPMENT.md): code layout and tests

## Limits

- Two outfit mods can't be worn on the same character at once; each replaces the body mesh.
- The relocator needs mods with `.utoc` files (most outfit mods). Pak-only mods go into
  `~mods` as usual.
- While Clean is on, faces also lose sweat and tears.

## Other people's mods

The tools only change your local copies. Relocated files contain other authors' work: please
don't share them, and follow each mod's permissions.

## Mod Mixer (optional)

The repository also has an older tool, the Mod Mixer (`tools/e33_mixer.py`), which installs one
combination of mods from a browser page. It isn't part of the release and isn't supported; see
[MIXER.md](docs/MIXER.md) if you want to run it from a clone.

## Contributing

Bug reports and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Tests:

```
pip install -r requirements-dev.txt
python tests/run_suites.py
```

## Credits and licence

MIT licence ([LICENSE](LICENSE)). Third-party code and the projects this builds on are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): RE-UE4SS, retoc, CUE4Parse, bcdec, FModel,
E33 Randomizer, UAssetAPI, Loud and Clear, and the blood and dirt mods by DC, Imtheonlydot and
notrustk.

Written with the help of an AI coding assistant (Claude); tested in game by the author.

Clair Obscur: Expedition 33 belongs to Sandfall Interactive and Kepler Interactive. This project
is not affiliated with them and includes no game files.
