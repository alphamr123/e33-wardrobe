# Changelog

What changed in each version, newest first.

## 1.4.0

In short: a skin mod now shows under the outfit worn (the game's or a mod's) instead of replacing
it; switching outfits off puts the character's own outfit back as it was, also after Fix look;
"pieces on screen" no longer reports pieces as missing that can't show. Recommended UE4SS build as
for 1.3.1: 3.0.1-1176 or newer.

In-game menu, skin mods and outfits (a comment on the mod page, and the 17 Nov game session):
- A skin mod (a base body `SK_<Character>_Placeholder` whose textures and materials are all the
  body's or the skin's by name, such as a skin texture replacer) now puts its textures under the outfit the
  character wears, the game's own outfits included, wherever that outfit brings no version of its
  own. This is what installing it as a replacer shows. Before, a variant with a mesh applied only
  where its own mesh showed: the skin mod showed nothing under an outfit ("0/3 asset(s)" on 17
  Oct), and Auto Wear then put its bare body on in place of the outfit, so you had the skin or the
  outfit, not both.
  - Auto Wear leaves the outfit on then. The row reads `on · skin under outfit` and still has
    **Wear**, which puts the skin mod's own body on instead.
  - Settings > "Auto Wear / skin mods under outfits" > **Skin mods** switches this off
    (`skin_under = false` in settings.txt): then a skin mod only shows as its own body, as in 1.3.1.
  - Unchanged: an outfit that brings its own body texture keeps it; a costume built on the base
    body that also brings belt, coat or pants textures is an outfit and is worn in place as before;
    an outfit made for another outfit lends nothing.
  - Confirmed in game 17 Nov evening: a skin mod for Lune picked while she wore the game's Chic;
    Chic stayed on, its skin material got all 5 of the mod's body textures (walking and menu
    Lune), Auto Wear left it, and switching it off put the game's 5 textures back.
- Removing a worn outfit put the character's own outfit back wrong, and Fix look and All off
  didn't repair it (17 Nov: Sciel's coat and accessories showed skin, and two parts her outfit
  ships without a material got her skin material). Three causes, all fixed:
  - Fix look threw away the mod's record of what the game had on each body under a worn mesh, for
    every character, though the game re-dresses only the one it shows. The records are kept now.
  - The game moves the walking character's body between the party and the outfit actors when you
    switch leader. The mod took the moved body for a different object and dropped its record. It
    now checks the body by its own name. (Seen in the 17 Nov evening session: Sciel's record was
    gone before Fix look ran.)
  - Without a record, the mod put the outfit's mesh back but left the worn mesh's materials on its
    slots, and filled the slots the game leaves empty. It now clears every slot first, sets what
    the outfit's Blueprint sets, and reuses the game's own material copies where it still has
    them. Nothing is filled on the game's own meshes any more.
  - The walking character's body is one object for the whole party, so the record is now kept per
    character: Lune's Unwear no longer goes back to the outfit of whoever led last.
  - Confirmed in game 17 Nov evening: every switch-off of a worn outfit (a two-character outfit
    mod, Altered Flower Suit, Fitting Outfits, Cheekier Chic, for Lune and Sciel, on walking and menu characters, also
    after Fix look) put back the game's materials from the record, slot for slot as they were.
- With "Test: game dresses (B)" on, the game can dress a character in the variant's own copy of
  an outfit Blueprint. With that pick switched off, the mod set the same mesh again and reset the
  materials on every pass (seen once in game, 17 Nov). Such an outfit now shows the game's
  version of the mesh, and later passes leave it alone; Fix look gives the game's outfit back.
- Found by a run over every option in game (17 Nov evening), all fixed:
  - On a hidden outfit actor the game frees its own material copies while a mesh is worn over
    them; switching it off then put the plain materials back. The record now keeps each copy's
    parent and settings and rebuilds it when the game has freed it (a copy is checked by name, so
    a new object at the same address isn't taken for it).
  - An option that brings an outfit's own Blueprint (such as Cheekier Chic "Separate colors"): its
    Blueprint's materials were replaced by the defaults of the mesh it puts on, and switching the
    option off left that mesh on the character. The Blueprint's materials now stay, and switching
    it off puts the outfit's own part back.
  - A texture the mod puts into an empty link of an option's material counted as "not used" in
    the pass that put it there.
  - An outfit worn over another (Wear), then a second pick that replaces the same game mesh (an
    outfit option and a skin mod both replace the base body): the second pick's mesh took the
    worn one's place, the record of the outfit under it was lost, and with everything off Lune
    stood in the game's base body instead of her Chic. A body showing its worn mesh now keeps it.
  - Empty material slots the mod fills on a mod's mesh stayed filled when the game's own mesh came
    back (Sciel's own outfit kept a skin material on a slot the game leaves empty). They are
    cleared when the mesh changes.
- Found by a second run over every option (17 Nov, late), both fixed:
  - A mod that replaces the game's own outfit mesh, switched off without Wear: a slot the game's
    mesh ships empty kept the mod's material there. A skin mod for Sciel has the scarf material on
    the slot Sciel's own body leaves empty (`lambert1`), the game made its own copy of it, and that
    copy stayed after the pick was off, through Fix look and All off, for the rest of the run. Such
    a slot is now emptied when the game's mesh comes back, if what it holds came from the mod's
    mesh or a variant; a material the game put there itself stays. Fix look now also empties
    those slots on the party's own outfits, except where the outfit's Blueprint sets a material.
    (A first version also looked at the 13 cutscene NPCs and every part of their Blueprints, and
    the pass after Fix look took 458 ms instead of 55; it now looks only at party characters'
    bodies.) A third run didn't reproduce the leftover: that time the game made no copy on that
    slot, so this fix is tested in the mock only.
  - A skin mod under an outfit that replaces the same base body (under Lune Outfit Options or
    Neurolink Suit) read "5/6, not shown: SK_Lune_Placeholder". Its own body is left off
    on purpose, so it is no longer counted; the log says "its own body left off (skin under the
    outfit), not counted".
  - Everything else matched the game's own look after each switch-off: every option of all 27
    slots with Auto Wear, every slot worn by hand, the skin mods with the setting on and off, and
    nine combinations.
- The hitch line now names the steps of a pick (undo history, matched slots, writing
  selection.txt). One pick in that run took 2.4 s there, and the line could only say "idle".
- "Pieces on screen" no longer counts a piece nothing on the character's body uses as missing (a
  texture only another character's skin uses, an outfit Blueprint that isn't the one worn). The
  log says how many were left out. In game 17 Nov: Cheekier Chic "Lace lune-sleeves-barefoot" reads
  7/7 instead of 7/8. A pick that shows nothing keeps its whole count. A body whose character
  can't be told (an NPC) doesn't count for a character's pick.
- A cutscene NPC that carries a party member's weapon was taken for that character (the
  expeditioners counted as Gustave). An actor whose body shows a mesh is now told by that mesh.
- Auto Wear no longer judges a pick by the pass before it. A look at a new character between a
  pick and its pass, or a pick made while a pass was on its last actors, could find the pick's
  mesh "not shown" and wear it over the outfit it was made for. It now waits for the pick's own
  pass. Found by reading the code; tested in the mock.
- While a pass is under way (it takes several loop ticks since the change below), the menu shows
  the slot as it was and "<character> wears" as before the pass, instead of "not visible" and "not
  in this area" for a moment.
- A material the mod swaps on a battle, menu, companion or cutscene character is now also swapped
  in that character's own list of material instances (the game drives effects through it). The
  code meant to do this, but looked at nothing when the character had no owner, which is the
  usual case. What this changes on screen is not known.
- Of a variant's several meshes, the one Wear puts on is now the same in every game session (the
  first outfit mesh in a-z order). It depended on Lua's table order.

In-game menu, crash safety and logs:
- The "new skin" line in live_log.txt read a new battle, companion or camp character's body by
  property name. 1.3.1 stopped doing that everywhere else after the two camp crashes; this line
  was missed. It now uses the component list.
- dump.txt finds a character's skin component through the component list too, and now lists it
  for characters without an owner (it never did: 1 of 83 actors in the 17 Oct dump).
- If live_log.txt can't be renamed at game start (another program has it open), the last session
  is copied to live_log_previous.txt before the new log starts. Before, it was lost.
- More in live_log.txt, to check outfits from the log alone: "under it" (what the game had on each
  slot when a mesh is worn over it), "now" (each slot once a body is back on its outfit), and after
  every pass a "wears" line with what each character's body shows. dump.txt adds, per outfit actor,
  the body its own Blueprint defines, and per body the component (with its address), the mod's
  Wear record for it and the game's list of material copies.
- commands.txt: `wear` with an unknown slot id says so instead of saving the id; `set trace` and
  `set scoping` take effect at once. Lines may be up to 4000 characters (they were cut off at 300
  without a word, so `set wear` with a whole Wear list did nothing); a longer one is logged.

In-game menu:
- The pass after a map load is spread over several frames (at most ~12 ms of work per loop tick)
  instead of one long frame: at camp it took 244-259 ms for 48 actors (17 Oct) and 283 ms for 89
  (18 Oct) in one go, a visible stutter. A character removed while the pass waits for its turn is
  skipped. In the 19 Oct session the camp pass (70 actors, 203 ms of work) logged no long frame.
- A map that loads while the previous map's pass is still waiting (camp right after the world
  map) no longer gets that old pass 1-2 s after loading, before its own 6 s wait. Requests made
  just before a map load now wait for it. Found while writing the book (ch 16), not confirmed in
  game; the 17 Oct 14:52 camp crash fits this timing (a guess).
- The mod now learns which character an outfit actor dresses from the game's skin component
  ("component hook" lines in live_log.txt). The old way, by the outfit actor's owner, never
  matched: outfit actors have no owner. With it, on the walking character:
  - an outfit the game shows again without spawning it (switching the party leader back) is
    dressed again, and cleaned again when Clean is on (seen in game 22 Oct: the hook fires);
  - the walking character's own character comes from the outfit, not from its meshes (Sciel in
    the game's Chic outfit wears a Lune mesh);
  - a material the mod swaps on the outfit is also swapped in the game's list for the character.
  In game on 23 Oct the hook found 16 outfits shown again; each was looked at again (a "game
  re-assigned" line), and the pooled outfits had kept the mod's dressing, so nothing needed
  changing. The re-clean and list update are tested in the mock only.
- The 2 s companion watch no longer skips a class whose object lookup alone takes over its 8 ms
  budget, and a class cut short goes on where it stopped. Seen in the test mock only.
- The "on screen" count in live_log.txt no longer lists another character's assets as "not
  shown" (Sciel's body textures in a Lune option); they are counted only when they show.
- An empty texture link is no longer filled with a texture of a variant that is off (for example
  a colour you picked earlier). The next pass took it out again and the fill put it back, so the
  material was rebuilt on every pass. This also holds when you chose "the game's own" texture for
  that link; if the game's texture isn't available, that link now stays empty instead of getting
  a mod texture. Found in the test mock, not seen in a game log since 15 Oct.
- An NPC whose class name only mentions a party member (such as BP_Cine_Lune_Mother_C) is no
  longer taken for that character. Camp characters are still recognised by their skin component.
- Outfit actors' parts are read by property first again, so a body part the game names at run
  time keeps its "Body" label and Wear finds it (1.3.1 could miss it).

Logs and reports (found while writing the book, chapters 17 and 19):
- The minute's stats line counts BeginPlay calls in the minute they happened; after a long frame
  they went into the next minute.
- The watchdog's breadcrumb times were 1 ms early (the last step read "-1 ms").
- report.txt no longer doubles line ends ("\r\r\n") in the files it bundles, and its "errors"
  section no longer lists UE4SS offset names like ArIsError. Its "last 80 lines" held 81.
- dump.txt starts with its date and the session it belongs to (reports bundle the latest dump,
  which can be days old).
- An outfit actor at an address a dead one had is recorded as new; the component hook checks the
  objects by the names taken when it fired; the name Fix look sends is kept with the character's
  full name. All three guard against reused addresses (tested in the mock).

App and relocator:
- Tests: the check that a class the mod never dresses is matched only once counted nothing (the
  mock hid the count); the empty-slot tie rule had no test; the perf scenario "re-dress" gave skin
  actors an owner, which they never have in game, so it measured no work. All three fixed.
- Relocator: a new path is also checked against the game's own packages (before, only against the
  run's and the wardrobe's). No clash was ever found; the check is cheap.
- Game log: a stall after one that went on by itself (a load) is its own item. Before, a load and
  a later freeze were one item reading "normal during a loading screen". An idle stall of 30 s or
  more no longer calls itself normal, and a stall while the menu worked names "the last thing it
  logged" instead of a second "last step" (the breadcrumb line is the call it was making).
- The note "Two versions of one mod? Keep only one in the library." now says what happens and
  covers both cases: only one copy of each shared file loads in game; an older download should
  go, but two different mods (such as Fitting Outfits for Lune and for Sciel) can both stay, and
  one may use the other's copy. The Compare dialog is now called "Same files in two mods".

Tools:
- e33legacy.split_number splits ten-digit FName numbers the way the engine does. No effect on
  real mods (such names are made at run time, not cooked).

## 1.3.1

Recommended UE4SS build: 3.0.1-1176 or newer (the second line of UE4SS.log gives its Git SHA:
1176 is 1ba38db4, 1125 is 527a483b). 1125 still runs the menu; "Test: game dresses (B)" needs 1176.

In-game menu, crashes and freezes:
- Crash at camp right after a fast travel (twice on 17 Oct, UE4SS 1176): UE4SS crashed inside its
  property cache while the mod read a camp character's "Face" by name. The likely cause: camp
  Blueprints are loaded again on each visit, and UE4SS hands back a property of the freed one. The
  mod now finds a character's parts through the game's own component list, by their names, and
  reads parts by property only on outfit actors (their parts belong to the walking character).
  Also: nothing is read from an object whose class is loading or being removed, and a map that
  loads within 30 s of the previous one gets 6 s before the mod dresses anyone. Not yet confirmed
  in game.
- No longer touches a character that the game has already removed (seen a second after a
  battle, as "change None" in the log). Writing to it could corrupt memory.
- Never calls a method on an object UE4SS returns as "invalid" (a missing owner, parent or
  property). Inside UE4SS that is an access violation the mod can't catch. Eight such places were
  found and guarded, among them the character-name lookup in the first look at a new character,
  where earlier freezes stopped.
- When the game re-assigns a character's outfit at the start of a battle, the mod no longer reads
  the character's skin component (it can point to an object the game already freed).
- Reads a property by name only when the class says it is a plain object reference (or a name,
  number or yes/no value). A character's "Face" property is a weak reference, which UE4SS reads
  wrongly and crashes on (UE4SS issue #1433).
- Checks more than UE4SS's "valid": an object being destroyed, already garbage or still loading
  is not read or changed. It is looked at again later.
- Looks at new characters about 1 second after they appear and again 2 seconds later, never on
  the frame they appear, and leaves them to the map-load pass for 3 seconds after a map loads.
  New characters and that pass wait until the game is calm (no burst of new actors and no long
  frame in the last half second, at most 10 seconds).
- Leaves cutscene actors of no party character (Esquie, for example) alone, and Fix look leaves
  cutscene characters alone (re-dressing them during a dialogue could stop it from showing).
- Forgets objects of the previous map on every map load, so a new object at a reused address is
  never mistaken for an old one.
- A new map is also noticed through the game state starting, not only through UE4SS's LoadMap
  hook, so `HookLoadMap = 0` in UE4SS-settings.ini can be tested.

In-game menu, outfits:
- Battle and companion characters are dressed as soon as they appear. Before, no battle character
  was looked at until a pass had seen one, and no pass runs when a battle starts.
- Party members walking behind the leader get their outfit back after a battle without Fix look:
  every 2 seconds the mod checks them and dresses any whose body changed (nothing to do when
  nothing changed).
- Wear stops re-dressing a character when the game puts its own body back 3 times in a row
  within seconds (copies the game keeps for scenes; it caused stutter). It tries again after 30 s.
- An actor whose character can't be told counts as the character whose relocated mesh it shows.
  The walking character's body no longer flips between the game's mesh and the worn one.
- An outfit mesh with empty skin slots now gets the character's own skin material when the
  previous outfit's was another character's (Sciel's Chic outfit is a Lune mesh, so her lower body
  had Lune's skin tone): of the candidates, the one the mod's textures fit best.
- Colour-variant mods: textures the parent material shows too are no longer put back on every look
  (needless material rebuilds, up to 6 per character).
- Settings > "Test: game dresses (B)", off by default (experimental, needs UE4SS 1176): the game is
  given the worn variant's own outfit Blueprint when it dresses a character. 2 s after a swap the
  character's body is checked; a body without a mesh stops swaps to that Blueprint for the session.
- In-game menu: classic look like the desktop app (title bar, classic tabs, square buttons,
  aligned value column, status bar). Same pages, buttons and keys.
- `scene_copies = false` in settings.txt leaves alone the copies the game dresses for dialogue and
  battle.

In-game menu, speed:
- Mod assets are found with the engine's GetAsset instead of UE4SS's StaticFindObject first: each
  miss cost 13-27 ms, most of the 150-360 ms looks.
- Within one frame the mod keeps what it has already read (texture lists, mesh paths, property
  types): a first look at a new character takes about half the engine calls, the pass after a map
  load about a seventh (tests/perf/count_crossings.py, 1.3.0 against 1.3.1).
- New characters get about 8 ms of the mod's time per frame; the four party-menu characters took
  95-309 ms each, all in one frame, after every map load.
- The check the mod runs for every actor the game creates (thousands a minute in battle) matches
  each class against the party's class names once, not once per actor (the class name is still
  read for the cache key).
- Run-time named components are no longer looked up as Blueprint templates.

In-game menu, logs (live_log.txt, report.txt):
- Freeze trace: before each engine call that could hang, the mod notes what it is about to do. If
  the game thread stops, the watchdog writes the last 40 steps, ending with the call that never
  returned; "the game thread ran again after N s" says it was a stall, not a freeze.
  `trace = false` in settings.txt turns it off.
- `hitch:` lines for long frames with the mod's work just before, "slow look" lines over 100 ms,
  and a `stats` line every minute (including the time spent on every actor the game creates).
- `scene:` lines when battle, cutscene and dialogue actors appear; "game spawned ... for <actor>"
  names what each new character belongs to; "new skin" lines say which mesh it shows, and a new
  skin that isn't looked at says why.
- dump.txt shows each skeletal mesh's running animation class and mode.
- commands.txt next to the mod: its lines (console words, pick, wear, set) are run about once a
  second and logged.

Relocator:
- Mods whose internal links differ from their own file names only in letter case now prepare
  completely. The game ignores the case, but the converter didn't, and such links were lost (a
  multi-outfit Sciel mod's outfit Blueprints showed no body). Links to game files are never
  changed. Reinstall such a mod to get the fix.
- Reinstall of a disabled mod failed with "Access is denied" on Windows. Fixed.

App:
- Game log: a "last step" line after a stall while the menu was idle no longer changes the details
  of an earlier stall.

Known, not fixed:
- After "All off", menu characters can show the game's version of the worn mesh until the game
  re-dresses them (Fix look, reopening the menu).

For developers:
- scripts/collect_crash.py (moves the newest crash dump and copies the logs into one folder, with
  a first reading), scripts/analyze_dump.py (names UE4SS frames with Windows' dbghelp when
  llvm-symbolizer is missing; all threads), scripts/dump_threads.py, scripts/gen_index.py,
  tests/sabotage.py (break a line, run a suite, restore), tests/perf/count_crossings.py.
- The test suites no longer fail when the game is running on the same PC.
- The Tools zip ships a fixed list of docs.

## 1.3.0

The fix tools below are experimental: check the result in game; every fix can be undone.

App:
- **Disable / Enable** a mod without removing it: its prepared files move out of the game, the
  menu leaves it out, picks are kept.
- **Edit rows...**: rename, add, move, order and hide rows and options of a mod in the in-game
  menu. Kept in fixes.json, so Reinstall keeps them.
- **Choose texture...** / **Choose material...** for empty texture links and empty material
  slots, from the option's details or from the Game log problem. Saved as rules for that option.
- **Bundle it...**: copy a missing file from another mod of the library (often an older version
  of the same mod) into this one.
- **Fixes** group in the details: every fix of a mod with Undo and Undo all.
- **Tools** button: **Check & repair...** (missing prepared files, an old menu list), **Find the
  problem mod...** (turns half of the suspects off per round; cleared mods stay on; survives an
  app restart), **Reinstall all**.
- **Compare...** on "Two versions of one mod?": both mods side by side, then remove one.
- The app remembers which downloads a mod came from (for Compare).

In-game menu:
- Uses the rules chosen in the app (Choose texture / Choose material) before its own guesses.
- Its lines about filled textures and material slots name the option, material or mesh and
  slot, so the app can offer a Fix button for them.

Relocator:
- Applies fixes.json (row edits, hidden options, disabled mods, rules, bundles) whenever it writes
  the menu list. A disabled mod stays disabled when it's prepared again; `--remove` also deletes
  its parked copy.
- Bundled files count as part of the mod: links to them resolve and they go into its shared pak.
  They aren't reported as "two versions of one mod".
- Safer with your files: moves of prepared folders are all or nothing, two mods whose names clean
  to the same folder no longer touch each other's files, and repairing one option never overwrites
  another's pak.
- The Tools zip of 1.2.0 and 1.2.1 was missing `e33tex.py`, so the command-line relocator didn't
  start. Fixed (the app was not affected).

## 1.2.1

App:
- Mod list: tick boxes (and Ctrl+click, Shift+click) for **Reinstall selected** and **Remove
  selected** with one dialog; **Reinstall all**; a filter box.
- Every list: drag a column header's edge to resize, double-click to fit; widths are remembered.
- Mod details name things: notes list the options and files they mean (expandable), overlaps list
  the shared files, each option lists its textures (size, format) and files. Links to files the mod
  doesn't include name the missing file when the mod's paks still say it.
- "Two versions of one mod?" no longer counts PrimaryAssetLabels (cook metadata that does nothing in
  game), which two mods by one author often share.
- Replaces says "Base body" instead of the mod's name; CamelCase folder names read as words.
- Options without a swatch show no empty square. Texture sizes that weren't recorded say
  "(size ?)"; Reinstall records them.
- Image viewer for swatches and skin textures: a bigger picture read from the prepared mod, zoom,
  pan, previous / next.
- Copy: details text can be selected; right-click menus with Copy, Copy option text, Copy file paths,
  Copy all details; Ctrl+C.
- Game log: click a problem or an on-screen row to see only its log lines. When the game is closed
  it shows the last session; Show: This session / Previous session / UE4SS.log. Copy problems
  includes each problem's log lines.
- Game log: explains the menu's new lines about empty material slots of a worn mod mesh (filled with
  the body's material, or left grey).

In-game menu:
- Fixed grey bodies from outfit mods whose mesh leaves a material slot empty for the game to fill
  (a Sciel outfit mod). When such a mesh is worn, an empty slot gets the body's own material (same
  slot name, else the skin material), with the mod's textures named like the body's ones on it.
  live_log.txt says what filled each slot.

Relocator:
- Texture sizes come from the texture header when the full read fails (colour-only options showed
  no sizes), and the reason is recorded.
- The "Two versions of one mod?" warning skips PrimaryAssetLabels.

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
