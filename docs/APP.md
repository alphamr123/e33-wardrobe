# The E33 Wardrobe app

`E33 Wardrobe.exe` sets everything up and prepares outfit mods for the in-game menu. No Python,
no command line.

- [Install](#install)
- [Setup tab](#setup-tab)
- [Adding mods](#adding-mods)
- [The mod list](#the-mod-list)
- [Mod details](#mod-details)
- [Fixing mods](#fixing-mods)
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
   Civilian Skirt for Lune), each outfit gets its own row in the in-game menu.
3. **Prepares** every option for the in-game menu (the relocator). The progress bar counts options.

Then start the game and press Delete: the mod is in the menu.

Dropping a newer version of a mod you already have updates it. **Reinstall** prepares a mod again,
**Remove** takes it out of the game and can also delete its files from the library. Your original
downloads are never changed. **Reinstall all** prepares every mod again (one task per mod).

Mods that only have `.pak` files (no `.utoc`) can't be prepared; put those into `Paks\~mods` as
usual.

## The mod list

- Tick the box in front of mods (or Ctrl+click, Shift+click for a range, Space on the selected
  one) to work on several at once: the buttons become **Reinstall selected (N)** and
  **Remove selected (N)...**. Remove asks once and lists the mods. The box in the header ticks
  every mod in the list.
- **Filter** below the list shows only mods whose name, character or outfit contains the text.
- Drag the right edge of a column header to make the column wider or narrower; double-click it to
  fit the column to its text. The app remembers the widths. Right-click a header for
  **Reset column widths**. This works in every list.
- Text that doesn't fit shows in full when you hold the mouse over it.

## Mod details

Select a mod to see:

- which characters it changes and which outfits it replaces ("Base body" when it replaces the
  character's body mesh);
- every menu row and its options: what each option changes (outfit mesh, materials, textures),
  texture sizes (for example "Body 4K, outfit 2K"), physics, colour swatches. Select an option to
  see its textures (name, size, format) and **Show N files**, the game paths it changes;
- **Skin**: whether it brings its own body textures;
- **Notes**: things worth knowing. They name the options and files: for example which options link
  to a file the mod doesn't include, and which file that is when the mod's paks still name it.
  **Show N options** / **Show N files** opens the full list;
- **Overlaps**: other mods that change the same things, with the files. In game, the one picked
  last shows.

Click a swatch (or a texture name) to open the image viewer: a bigger picture read from the
prepared mod, its size and format, **Fit** / **100%** / mouse wheel to zoom, drag to move,
**Previous** / **Next** through the mod's pictures, Esc to close. It shows a smaller copy of very
large textures (up to 1024 px; **Load 2048 px** for more).

Text in the details can be selected and copied. Right-click for **Copy**, **Copy option text**,
**Copy file paths** and **Copy all details** (everything about the mod as plain text, for a bug
report or a message). Right-click a mod in the list for the same, and Ctrl+C copies the selected
row.

## Fixing mods

**Experimental.** These tools are new and have only been tested on a few mods. Check the result in
game, and use Undo (or Enable, or Reinstall) if something looks wrong. Please report what didn't
work, with `report.txt`.

Every fix is kept in `fixes.json` in the menu folder, so Reinstall doesn't undo it. Your downloads
in the library are never changed. After a fix, press **Reload** in the in-game menu.

- **Disable / Enable** (toolbar, details, right-click): takes a mod out of the game without
  removing it. Its prepared files move to `Sandfall\Content\E33Wardrobe_Disabled`, the menu
  leaves it out, and your picks are kept for when you enable it again.
- **Edit rows...** (details, right-click): rename rows and options, make a new row, move options to
  another row, change the order, hide options. Hidden options are still prepared; the menu just
  doesn't list them. **Reset all** goes back to the rows the mod comes with.
- **Choose texture...**: when a mod's material points at a texture the mod doesn't include, pick
  which texture fills it (one of the option's textures, or the game's own). The button is on the
  option in the details, and on the Game log problem "Filled in a missing texture".
- **Choose material...**: when a mod's mesh leaves a material slot empty, pick what it shows: the
  body's own material, one of the option's materials, or nothing. On the Game log problem.
- **Bundle it...**: when the file a link points to is in another mod of your library (often an
  older version of the same mod), copy it into this mod. The copy is the app's own: it stays when
  the other mod is removed. The mod is prepared again afterwards.
- **Fixes** in the details lists every fix of the mod with **Undo** (and **Undo all**).
- **Compare...** on the note "Two versions of one mod?": both mods side by side (downloads,
  version, date added, options, size, the shared files). Remove the one you don't want.

**Tools** in the toolbar:

- **Check & repair...**: checks that every enabled mod's prepared files are there and the menu's
  list is current. **Repair** prepares the affected options again or rewrites the list.
- **Find the problem mod...**: when something goes wrong in game and you don't know which mod
  causes it. Each round turns half of the suspects off; start the game, try to make the problem
  happen, close the game, and answer. Mods found not to cause it stay on ("Cleared"). After a
  few rounds it names the mod and leaves it off. Turning that mod off stops the problem, even if
  it also needs another mod to happen. Mods that were already disabled are left alone. It can
  wait while you play: the bar above the mod list continues it, also after the app was closed.
- **Reinstall all**.

## Game log tab

While the game runs, the app reads the in-game menu's log (`live_log.txt`) and UE4SS's log, and
lists problems in plain words:

- the menu didn't start, UE4SS is too old, Lua errors;
- the game stopped responding (and whether the menu was busy at the time);
- an outfit that shows nothing because it's made for another outfit;
- textures filled in for a mod, assets that couldn't be loaded;
- the game crashed or closed while the menu was working.

**On screen now** shows what each picked option currently shows. Click a problem or an on-screen
row to see only the log lines about it ("Showing lines for: ..."); click it again, **Show all** or
Esc to see every line.

When the game isn't running, the tab shows the last session (with the time it ended). **Show:**
picks **This session**, **Previous session** (`live_log_previous.txt`, the session before) or
**UE4SS.log**; each is read through the same checks.

Some problems have a button: **Choose texture...** / **Choose material...** (see above) or
**Repair** for a prepared file that didn't load.

**Copy problems** copies the list, with the log lines of each problem, for a bug report.
Right-click the session log for **Copy shown lines**. The app only reads files; it never touches
the running game. Switch it off in Setup ("Follow the game's logs while it runs").

## Files and folders

| Path | What |
|---|---|
| `%APPDATA%\E33Wardrobe\` | The app's settings |
| `Sandfall\Content\Paks_ModLibrary\` | Your mods as downloaded |
| `Paks\~mods\_E33Wardrobe\` | Prepared mods (what the game loads) |
| `ue4ss\Mods\E33Wardrobe\` | The in-game menu, its settings, logs and `report.txt` |
| `ue4ss\Mods\E33Wardrobe\fixes.json`, `bundles\` | Your fixes (disabled mods, row edits, rules, bundled files) |
| `Sandfall\Content\E33Wardrobe_Disabled\` | Prepared files of disabled mods |

## Problems

- **A mod failed to add**: the task list says why. Common: the game was running, or the download
  has no outfit files.
- **Something looks wrong in game**: press Ctrl+F9 in game and attach `report.txt` (Game log tab:
  **Open report.txt**) with **Copy problems** to a bug report.
- More: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
