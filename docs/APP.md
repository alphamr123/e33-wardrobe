# The E33 Wardrobe app

`E33 Wardrobe.exe` sets everything up and prepares outfit mods for the in-game menu. No Python,
no command line.

- [Install](#install)
- [Setup tab](#setup-tab)
- [Adding mods](#adding-mods)
- [Mod details](#mod-details)
- [Game log tab](#game-log-tab)
- [Files and folders](#files-and-folders)
- [Problems](#problems)

## Install

1. Install UE4SS for Clair Obscur (Nexus mod 630, file "UE4SS - Experimental (Newer)").
2. Download `E33Wardrobe-App-<version>.zip` from the
   [GitHub releases page](https://github.com/alphamr123/e33-wardrobe/releases).
3. Extract it anywhere (not into the game folder) and run `E33 Wardrobe.exe`.

Windows 10 or 11. The app uses Microsoft Edge WebView2, which both already have.

Windows SmartScreen may warn about an unknown app the first time. That's because the exe isn't
signed; the source and the build steps are on GitHub.

## Setup tab

Opens by itself the first time.

- **Game**: found automatically for Steam and the default Game Pass folder. If not, press
  **Browse...** and pick the game folder, for example
  `C:\Program Files (x86)\Steam\steamapps\common\Expedition 33`. Picking `Sandfall` or `Paks`
  inside it works too.
- **UE4SS**: shows the installed version. If it's missing or too old, **Open UE4SS page** takes you
  to the right file.
- **In-game menu**: **Install** (or **Update**) copies the menu into `ue4ss\Mods\E33Wardrobe`.
  Your keys, settings, picks and favorites are kept.
- **Mod library**: where your mods are kept, as downloaded. Default:
  `Sandfall\Content\Paks_ModLibrary` in the game folder. **Change...** picks another folder.

Until setup is done, a bar above the mod list says what's missing.

## Adding mods

Drag zip, 7z or rar files (or folders) onto the window, or use **Add mods...** / **Add folder...**.
Close the game first. For each drop the app:

1. **Unpacks** it into the library. Several downloads of the same Nexus mod dropped together
   become one mod with one option per file, named after the mod on Nexus (if online).
2. **Sorts by outfit**: when a mod's options replace different outfits (for example Clea, Sirene and
   Bikini for Lune), each outfit gets its own row in the in-game menu.
3. **Prepares** every option for the in-game menu (the relocator). The progress bar counts options.

Then start the game and press Delete: the mod is in the menu.

Dropping a newer version of a mod you already have updates it. **Reinstall** prepares a mod again,
**Remove** takes it out of the game and can also delete its files from the library. Your original
downloads are never changed.

Mods that only have `.pak` files (no `.utoc`) can't be prepared; put those into `Paks\~mods` as
usual.

## Mod details

Select a mod to see:

- which characters it changes and which outfits it replaces;
- every menu row and its options: what each option changes (outfit mesh, materials, textures),
  texture sizes (for example "Body 4K, outfit 2K"), physics, colour swatches;
- **Skin**: whether it brings its own body textures;
- **Notes**: things worth knowing, for example a texture the mod points to but doesn't include
  (the menu fills it in game);
- **Overlaps**: other mods that change the same things. In game, the one picked last shows.

## Game log tab

While the game runs, the app reads the in-game menu's log (`live_log.txt`) and UE4SS's log, and
lists problems in plain words:

- the menu didn't start, UE4SS is too old, Lua errors;
- the game stopped responding (and whether the menu was busy at the time);
- an outfit that shows nothing because it's made for another outfit;
- textures filled in for a mod, assets that couldn't be loaded;
- the game crashed or closed while the menu was working.

**On screen now** shows what each picked option currently shows. **Copy problems** copies the list
for a bug report. The app only reads files; it never touches the running game. Switch it off in
Setup ("Follow the game's logs while it runs").

## Files and folders

| Path | What |
|---|---|
| `%APPDATA%\E33Wardrobe\` | The app's settings |
| `Sandfall\Content\Paks_ModLibrary\` | Your mods as downloaded |
| `Paks\~mods\_E33Wardrobe\` | Prepared mods (what the game loads) |
| `ue4ss\Mods\E33Wardrobe\` | The in-game menu, its settings, logs and `report.txt` |

## Problems

- **A mod failed to add**: the task list says why. Common: the game was running, or the download
  has no outfit files.
- **Something looks wrong in game**: press Ctrl+F9 in game and attach `report.txt` (Game log tab:
  **Open report.txt**) with **Copy problems** to a bug report.
- More: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
