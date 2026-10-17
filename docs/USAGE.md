# Using the in-game wardrobe

The E33Wardrobe UE4SS mod adds a menu to the game. Install it first ([INSTALL.md](INSTALL.md)).
Outfit switching needs mods prepared with the relocator ([RELOCATOR.md](RELOCATOR.md)); Clean and
Fix look work without.

- [Opening the menu](#opening-the-menu)
- [Keys](#keys)
- [The menu at a glance](#the-menu-at-a-glance)
- [Outfits tab](#outfits-tab)
- [Choosing a variant](#choosing-a-variant)
- [Favorites](#favorites)
- [Clean](#clean)
- [Fix look](#fix-look)
- [Peek](#peek)
- [Presets tab](#presets-tab)
- [Settings tab](#settings-tab)
- [Console commands](#console-commands)
- [Changing keys and outfit names](#changing-keys-and-outfit-names)
- [Files the mod keeps](#files-the-mod-keeps)
- [Limitations](#limitations)

## Opening the menu

Load a save and press **Delete**. The menu appears on the right edge of the screen (Settings can
move it). The mouse cursor is shown and the camera stays still while it is open. If clicks don't
reach the menu in exploration, use the keys below, or open the game's own menu first (the outfit
screen shows the character up close) and then press Delete.

## Keys

| Key | Action |
|---|---|
| Delete | Open / close the menu |
| Ctrl+Up / Ctrl+Down | Highlight the previous / next row |
| Ctrl+Left / Ctrl+Right | Highlight the previous / next button in the row |
| Ctrl+Enter | Press the highlighted button |
| Ctrl+PageUp / Ctrl+PageDown | Previous / next page |
| Ctrl+F7 | Apply the picks to everyone again |
| Ctrl+F8 | Reload `variants.lua` and `selection.txt` |
| Ctrl+F9 | Write `dump.txt` and `report.txt` now |

The first menu key you press only shows the yellow focus ring; the next ones move it.

## The menu at a glance

- **Top row**: **Outfits**, **Presets**, **Settings**, **Peek**, **Close**.
- **Status bar** at the bottom: what the last action did, in words. For example
  `Lune · Outfit · Some Mod: sleeves · boots - 2/2 pieces on screen`, or
  `nothing on screen changed: made for Potato bag; Lune wears Chic`.
- **Help line** at the bottom: what the row you last clicked or highlighted does. The key help
  appears there after you use a menu key, and always on the Settings tab.
- A greyed button says why when you click it ("Off: already off (the game's own)", "Undo: nothing to undo").

## Outfits tab

- **Character tabs**: one per character that has slots, plus **All**. A `-` after a name
  (`Sciel -`) means that character isn't loaded in this area; picks are still saved and show when
  they appear. The menu opens on the tab you used last, or on the first character on screen.
- **"Lune wears Chic"**: the outfit the character has on right now. With Wear on it reads
  "Some Mod (Wear: in place of Chic)".
- **One row per slot**, named by what tells it apart, e.g. `Outfit · Some Mod`, `Color · Some Mod`,
  `Another Mod`. The value shows the picked variant the same way, e.g. `Style A: sleeves · boots`.
  - Slots with several variants: `<` / `>` step through them, **Choose** lists them all by name,
    **Off** puts the game's own back.
  - One-option mods: **On** / **Off**.
  - `[lock]` after a name: the slot is locked (see [Choosing a variant](#choosing-a-variant)).
- **What the value tells you**:
  - `… · worn`: the mod is worn in place of the character's outfit (see Auto Wear below).
  - `… · made for Potato bag` (orange): the mod replaces a different outfit than the one worn, so
    nothing shows yet. A **Wear** button on the row puts it on anyway.
  - `… · hidden`: another pick changes the same pieces and was picked later. **Bring to front** on
    the line below fixes that.
  - `… · not visible`: what the pick changes isn't used by anything on screen right now.
- **After a pick**, the status bar says what happened, and a line under the row repeats the
  reason and offers the fix (**Wear**, **Bring to front**, or **OK** to dismiss it). Rows that were
  switched to match (see below) are named too.
- **Bottom row**: **Undo** (says what it undid; up to 30 steps), **All off** and **Randomize**
  (this tab only; locked slots stay), **Clean**, **Fix look**.

### Outfit mods, Wear and Auto Wear

Most outfit mods replace one of the game's outfits: a mod for the Potato bag outfit only shows
while the character wears the Potato bag. E33 Wardrobe treats such a mod as one piece: while the
character wears another outfit, none of the mod's parts touch it, so the two looks never mix.

**Auto Wear** (on by default): when you pick a mod made for an outfit the character isn't wearing,
it is put on **in place of** the current outfit by itself, and the status bar says so. The body
is one mesh, so the two don't layer; the original outfit is remembered and comes back with
**Unwear**. After Unwear, Auto Wear leaves that slot alone until you pick it again. With Auto Wear
off (Settings), use the **Wear** button instead.

Colours and other texture-only slots follow the outfit they were made for: a mod's colour shows on
the outfit it belongs to.

### Matched groups

Some mods have variant groups that only work together (for example "Style A" outfits need "Style
A" colours). When you pick a variant from one group, a sibling slot of the same mod and character
that holds a pick from another group switches to its closest variant in the same group, and back.
Slots that are off stay off. Settings can switch this off.

### Technical slots

Blueprint-only "fix" paks that some mods include change nothing you can see. They are hidden from
the list, Randomize, All off and presets; Settings can show them. With per-character slots you
usually don't need them: a slot for one character never touches another.

## Choosing a variant

**Choose** on a row lists every variant as a button, named by what tells it apart, three to a row,
under its group's name. The blue one is in use; the help line lists the full names.

- **Off (game's own)** and **Random** sit at the bottom; **Page** buttons appear when there are
  many variants.
- **Back** returns to the list.
- **Lock** / **Unlock**: a locked slot is kept by Randomize and All off.
- **Slides** steps through all variants on a timer; it keeps going while the menu is closed, so you
  can watch the character. **Stop** ends it.
- **Wear** / **Unwear**, as on the row.

## Favorites

Each character has a list of saved looks. Press **Favorites** on the "Lune wears" row to open
Lune's list.

- **Save look** stores everything that character has on from your mods: outfit, colours and
  one-option mods. Saving the same look twice is refused.
- **Use** puts that look back. Slots that weren't part of the look are switched off. The look
  that is on now is highlighted.
- **Up** / **Down** set the order; **Remove** deletes a look.

Looks are kept in `favorites.txt`, next to `settings.txt`. Updates never overwrite it.

## Clean

**Clean** (bottom row of Outfits) takes blood and dirt off every character, and stays on for
characters that appear later: battles, cutscenes, menus. The button then reads **Clean: on**; press
it again to bring blood and dirt back. The setting is saved.

While Clean is on, faces also lose sweat and tears, because the game draws all of them through the
same masks. How it works: [HOW_IT_WORKS.md](HOW_IT_WORKS.md#clean).

## Fix look

If a character looks wrong, **Fix look** asks the game to dress everyone again (as re-equipping
the outfit does) and then applies your picks again. Wear's memory of the original outfits is kept
unless the game really re-dressed someone.

## Peek

**Peek** (top row) hides the menu for a few seconds (3 by default) and frees the camera, so you can
look at the character. A menu key or a click brings it back sooner; Delete closes the menu.

## Presets tab

- **8 presets**: **Save** stores every slot's current pick, **Load** applies it, **Clear** empties
  it. Each row says what it holds per character. Kept in `presets.txt`.
- **A/B compare**: **Store A**, **Store B**, then **Swap** to flip between two looks.
- **Undo**, **Randomize all**, **All off, everyone**: like the Outfits buttons, for every
  character.

## Settings tab

Kept in `settings.txt` next to the mod.

| Setting | Default | What it does |
|---|---|---|
| Character scoping | on | A slot for one character only changes that character. Off: every slot applies to everyone, like a replacer. |
| Apply to new skins automatically | on | Swap as soon as the game spawns a character (battle, cutscene, menu). Off: only menu changes, Fix look and Ctrl+F7 swap. |
| Randomize may pick vanilla | off | Let Randomize / Random choose "off" for a slot. |
| Keep a mod's groups matched | on | See [Matched groups](#matched-groups). |
| Auto Wear | on | See [Outfit mods, Wear and Auto Wear](#outfit-mods-wear-and-auto-wear). |
| Show technical slots (fix paks) | off | List Blueprint-only fix slots too. |
| Slideshow / Peek seconds | 4 s / 3 s | Seconds per slideshow step (1-60); how long Peek hides the menu (1-15). |
| Menu side / scale | right / 100 % | Left or right edge; 50-200 % in steps of 10. The menu also shrinks to fit small screens. |
| Mouse cursor / freeze camera | on / on | While the menu is open: show the cursor; stop the mouse from turning the camera. |
| Test: game dresses (B) | off | Experimental test of a new way of switching. **param**: the game's own dressing call is given the picked outfit's own skin Blueprint (with Wear on for that row: whatever the character wears). Press Fix look after switching. Needs UE4SS 3.0.1-1176 or newer. |
| UI input mode (try if clicks fail) | off | Switch the game to game-and-UI input while the menu is open. Try it only if clicks don't reach the menu; other mods saw trouble with input modes during cutscenes. |
| Record session / auto report | on / off | Record: write `live_log.txt` ([TROUBLESHOOTING.md](TROUBLESHOOTING.md#session-recording)). Auto report: rewrite `dump.txt` and `report.txt` 4 s after each change (only while recording). |

The last row shows how many characters the last pass found, and has **Reload** (re-read
`variants.lua` and `selection.txt`), **Dump**, **Report** and **Defaults** (resets every setting in
`settings.txt`, including Clean, which goes off, and `recheck_ms` and `legacy_keys`; locks and Wear
stay).

Only in `settings.txt`: `recheck_ms` (how long after a character spawns to look again for
materials the game sets late; default 700) and `legacy_keys` (`true` switches on slot cycling with
Ctrl+F5 / Ctrl+F6, plus Shift for backwards), `b_soft` (`auto`: read the game's soft
references only on a UE4SS build where bug #1433 is fixed, 1176; `on` / `off` force it), `trace`
(default `true`: the steps before a freeze in live_log.txt; `false` turns them off, read at game
start) and `scene_copies` (default `true`; `false` leaves alone the copies the game dresses for
dialogue and battle).

## Console commands

In the UE4SS console or the game console:

| Command | Action |
|---|---|
| `wardrobe` | List the slots and their picks |
| `wardrobe menu` | Open / close the menu |
| `wardrobe <slot> <variant>` | Pick variant number `<variant>` for slot number `<slot>` (as listed); `off` or nothing switches the slot off |
| `wardrobe apply` | Apply the picks to everyone again (Ctrl+F7) |
| `wardrobe reload` | Reload `variants.lua` and `selection.txt` (Ctrl+F8) |
| `wardrobe dump` | Write `dump.txt` |
| `wardrobe report` | Write `dump.txt` and `report.txt` |
| `wardrobe fix` | Fix look |
| `wardrobe clean` / `wardrobe clean off` | Switch Clean on / off |

The same commands can come from a file: lines written into `commands.txt` next to the mod are run
about once a second (without the word `wardrobe`), logged and the file is deleted. The file also
takes `pick <slot id> | <variant id or off>`, `wear <slot id> | on|off` and `set <setting> <value>`
(for scripts and testing).

## Changing keys and outfit names

Copy `ue4ss\Mods\E33Wardrobe\Scripts\config.example.lua` to `config.lua` in the same folder and
edit the copy (without a `config.lua` the defaults are used). Key names come from UE4SS's key table (F1-F12,
A-Z, HOME, END, INS, DEL, PAGE_UP, UP_ARROW, RETURN, …); modifiers are CONTROL, SHIFT and ALT. Set a key
to `false` to switch it off. Avoid F10 (UE4SS's console) and Insert (UE4SS's BPModLoaderMod reloads
Blueprint mods with it).

Outfit names in messages ("made for Potato bag") come from the mesh names. To rename one, add for
example `outfit_names = { Potato = "Potato bag" }` to the table in `config.lua`.

Updating the mod or re-running the relocator replaces `config.example.lua` but never `config.lua`, `favorites.txt`,
`settings.txt`, `presets.txt` or `selection.txt`.

## Files the mod keeps

| File | What |
|---|---|
| `Scripts\config.lua` | Your keys and outfit names, if you made one from `config.example.lua` |
| `Scripts\variants.lua`, `wardrobe_registry.json` | The wardrobe, written by the relocator |
| `settings.txt` | Settings |
| `selection.txt` | Your picks, in pick order (the last pick wins where variants overlap) |
| `presets.txt` | Presets |
| `favorites.txt` | Favorites, per character, in your order |
| `live_log.txt`, `live_log_previous.txt`, `dump.txt`, `report.txt` | Recording and reports ([TROUBLESHOOTING.md](TROUBLESHOOTING.md)) |

## Limitations

- An outfit mod replaces the whole body mesh, so two outfit mods never layer.
- Textures that a mod's *base* material uses directly (not as a material parameter) can't be swapped
  at runtime. `dump.txt` shows whether that matters for a mod.
- Mods whose materials sample only virtual textures need virtual textures themselves; that is a
  property of the mod.
- Switching a slot off restores mesh and materials. If something still looks off, use Fix look or
  re-equip the outfit once.
- While Clean is on, faces also lose sweat and tears.
- Only `~mods` paks are handled; LogicMods or UE4SS parts of a mod are installed by hand.
