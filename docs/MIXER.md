# Mod Mixer

> **Optional, not supported.** The Mixer isn't part of the release download. It stays in the
> repository for people who prefer installing one combination of mods with the game closed. Run it
> from a clone: `py tools\e33_mixer.py gui` (or `tools\E33 Mod Mixer.bat`). For switching outfits
> in game, use the relocator ([RELOCATOR.md](RELOCATOR.md)).

The Mixer keeps every outfit mod in a library folder and installs exactly the paks of the
combination you choose. Changes apply the next time the game starts (paks are loaded at launch).
It doesn't need UE4SS. Set it up first: [INSTALL.md](INSTALL.md).

- [Starting it](#starting-it)
- [Choosing a combination](#choosing-a-combination)
- [Presets](#presets)
- [Conflicts and priority](#conflicts-and-priority)
- [Previews](#previews)
- [Settings file](#settings-file)
- [Command line](#command-line)
- [Rules files](#rules-files)
- [Safety](#safety)

## Starting it

Double-click **`tools\E33 Mod Mixer.bat`**. A page opens in your browser at
`http://127.0.0.1:47333` (another free port if that one is taken). The page is only reachable
from your own PC.

## Choosing a combination

- Switch a mod on in the left list, then pick its options with the buttons. "Will install" shows
  the exact pak folders.
- **Close the game**, press **Apply to game**, then start the game. The Mixer refuses to change
  paks while the game is running, because a half-swapped pak can crash it.
- **Mods without a rules file** get an automatic layout: each folder of sibling options becomes
  "pick one or none", and folders whose name starts with `_` become on/off toggles.
- **Mods with a rules file** get a page built from the author's install instructions, for example
  "choose a dress per character, then sleeves, shoes and a colour that fits that dress", with the
  extra fix paks the instructions call for added automatically. The GitHub repository has an
  example ([below](#example-a-rules-file-from-the-repository)).
- Mods that also contain **LogicMods** or **UE4SS** parts get a warning: the Mixer only installs
  `~mods` paks, so install those parts by hand.
- **Disable all** removes everything the Mixer installed.

## Presets

Presets save the state of the whole library (which mods are on, all their choices). Load one and
press **Apply to game**.

## Conflicts and priority

The Mixer reads each `.utoc`'s file list and warns when paks override the same asset. That covers
enabled mods and paks you installed by hand anywhere under `Paks`. The warning says **which one
wins in game**.

Each mod is installed into `~mods\_E33Mixer\<NN> <Mod>\`, where `NN` is its **priority** (0-99,
default 50). A lower number wins ties. Give a mod a lower number to let it win. The Mixer also warns
about duplicate file names and clashing container IDs.

## Previews

Each mod's page has a **Preview** card.

### Screenshots ("looks")

1. Apply a combination and start the game.
2. Take a screenshot as usual: Steam F12, Win+Alt+PrtScn, Win+PrtScn, or `HighResShot` in the game
   console.
3. Click **Add screenshot…**. It lists your newest screenshots from the Steam screenshots folder
   for the game, `Videos\Captures`, `Pictures\Screenshots` (also on OneDrive) and the game's own
   `Saved\Screenshots`, or you can pick any image file.
4. Drag a box around the character and save.

The picture is stored with the choices that were selected. It shows as the preview whenever that
combination (or the closest one) is selected, as a thumbnail on the option buttons, and under
**Saved looks**: click one to switch back to that exact combination.

### Colour swatches

**Make color swatches** builds a small swatch for every option without starting the game. It
extracts each option's base-colour texture from its pak with retoc (see
[INSTALL.md](INSTALL.md#2-the-tools)) and decodes it. This works for colour variants; options that only
change shape (sleeves, shoes) have no texture of their own, so use screenshots for those. From the
command line, `swatches` only rebuilds options whose pak changed (`--force` rebuilds all); the
page's **Update color swatches** button rebuilds all of them.

Previews are kept in `<library>\.e33mixer_previews\`, outside `Paks`, so the game never loads them.

## Settings file

`tools\e33mixer_config.json` (written by `e33_mixer.py --paks ... --library ... config --save`, which
stores `paks_dir` and `library`; add the other keys by hand; it holds paths from your PC):

| Key | Meaning |
|---|---|
| `paks_dir` | The game's `Sandfall\Content\Paks` folder |
| `library` | The mod library folder |
| `rules_dirs` | Folders with rules files (default `tools\rules`; a list here replaces it, so include it if you still want it) |
| `screenshot_dirs` | Extra folders to look for screenshots, e.g. `["D:\\MyShots"]` |
| `retoc` | Path to `retoc.exe` if it isn't next to the tools |

## Command line

Everything in the UI works from the command line too:

```
python tools\e33_mixer.py gui [--port N] [--no-browser]
python tools\e33_mixer.py scan
python tools\e33_mixer.py set "<Mod>" enabled=1 priority=40 <choice>=<value> ...
python tools\e33_mixer.py apply
python tools\e33_mixer.py off
python tools\e33_mixer.py preset save|load|list|delete [name]
python tools\e33_mixer.py swatches "<Mod>" [--force]
python tools\e33_mixer.py --paks "<game>\Sandfall\Content\Paks" --library "<library>" config --save
```

- `set` takes `CHOICE=VALUE` pairs as shown on the mod's page, plus `enabled=1/0` and
  `priority=NN`.
- `preset load` only selects; run `apply` afterwards.
- `--paks` and `--library` override the settings file for one run; `config --save` remembers them.

## Rules files

A rules file turns a mod's folders into choices, so the page offers what the author's instructions
describe instead of raw folder names. The Mixer looks for them in the folders listed in `rules_dirs`
(default `tools\rules\`), or as `e33mixer.rules.json` inside the mod's own folder.

### Example: a rules file from the repository

The GitHub repository has a rules file in `tools/rules/` for one multi-variant outfit mod (the
Nexus download leaves it out; copy it into `tools\rules\` to use it). With it the Mixer offers, per
character: the game's outfit or one of the mod's two dress styles; sleeves and shoes; and only the
colours that work with the chosen dress. It adds the fix paks the author's instructions require for
"only one character modded" and "colour on the game's outfit", and supports the mod's optional
add-on folders when you put them inside the mod folder.

### Writing your own rules file

Start from the example and adjust it. Its keys:

| Key | Meaning |
|---|---|
| `format` | Rules format version |
| `name`, `source`, `notes` | Display name, the mod's page, a short note shown on the page |
| `match` | `{"paths": [...]}`: sub-folders that must exist for the rules to apply to a mod folder |
| `choices` | The choices shown on the page: `id`, options, help text; `show_if` / `allow_none_if` expressions decide when a choice appears or may be empty (`none_label`) |
| `paks` | Which pak folders each combination of choices installs (templates with `{choice}` placeholders) |
| `checks` | `{"when": <expression>, "level": "warn" or "error", "message": ...}`: messages for combinations the author warns about |
| `flags` | `{"<flag>": "<folder name>"}`: true when that optional folder exists inside the mod (for add-ons) |

Pull requests with rules files for more mods are welcome ([CONTRIBUTING.md](../CONTRIBUTING.md)).

## Safety

- Among the game's paks, the Mixer only writes inside `Paks\~mods\_E33Mixer\` (its state and
  previews live in the library; colour swatches use a temporary `_e33mixer_swatch_*` folder next
  to `Paks`), and that folder belongs to it: anything
  there that isn't selected is removed. It never touches the game's own paks or your saves.
- Files are hard-linked (instant, no extra disk space) or copied when the library is on another
  drive.
- It refuses to run while the game is open: it checks the process list (Steam and Game Pass
  executables) and whether its paks are locked.
- It warns when it finds hand-installed copies of a library mod in `~mods`.
