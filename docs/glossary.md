# Glossary

Words used in the code, the logs and the docs. Add a term when you introduce one.

**Mod (outfit mod)**: a download from Nexus that replaces game assets (meshes, materials,
textures) for an outfit. Usually several **options** (variants) as separate paks.

**Option / variant**: one choice of a mod, e.g. "Lace dress: sleeves, barefoot". In `variants.lua`
a variant has an `id` and a `map` from original asset paths to relocated ones.

**Slot / row**: a group of options of which one (or none) is picked, e.g. "Lune outfit",
"Sciel color". One menu row. A slot for several characters is split per character: id
`<slot id>@<Character>`.

**Relocate**: copy a mod's assets to new, unique paths of the same length (`/Game/ZW…/…`), so all
options can be installed at once without overwriting each other. Done by `tools/e33_relocate.py`.

**Shared pak**: `<Mod>_Shared_P`, the mod's own new assets (paths the game doesn't have), used by
all its options.

**Library**: the folder where the app keeps the downloads (`Paks_ModLibrary` by default).

**Pick / selection**: the option chosen per slot, kept in `selection.txt`.

**Wear**: put an option's mesh on over whatever outfit the character wears now. **Auto Wear**
switches Wear on when a pick doesn't fit the worn outfit.

**Skin actor**: the actor the game spawns to show a character's outfit
(`BP_CharacterSkinBase_<Char>_C` and subclasses; faces `BP_CharacterFaceBase_*`). The visible
character's `Body` component is the skin actor's `Body`.

**Copy (scene copy, "Default" copy)**: skin actors the game dresses with the character name
"Default": copies kept for camp companions, dialogue, cutscenes and battles. Many are hidden. The
game puts their base body back often; Wear stops after 3 quick resets. `scene_copies = false`
leaves them alone.

**Companion**: `BP_Pawn_AICompanion_<Char>_C`, the party members walking behind the leader. Shows
the outfit on `CharacterMesh0`. Re-created after battles; found by the 2 s watch.

**Pass**: one run over every skin actor and every actor showing a replaced mesh (`runApply`), after
a pick, a map load or Fix look. **Re-check**: a look at newly spawned or re-assigned actors about
1 s and 3 s later (`recheckPending`).

**Look (actor look)**: one `applyToActor` call on one actor. Counted in the `stats` line.

**Fix look**: asks the game to re-dress every character (`ApplyCurrentCharacterSkin`), then a pass.

**Clean**: blood and dirt off the characters (zero masks).

**Placeholder**: `SK_<Char>_Placeholder`, the base body mesh under outfits.

**Policy / assign**: `CharacterSkinAssignPolicy`, the game's code that spawns and assigns skins.
The game uses `AssignBodyAndFaceSkinAsync` (outfit passed as a soft class).

**Crossing**: one call from the mod's Lua into UE4SS/the engine (a method call, a property read,
`GetFullName`, `FindAllOf`). The cost unit of `tests/perf/count_crossings.py`.

**Memo**: what the mod has read from the game, kept for the rest of one game-thread call
(`TRACE.memo`) and dropped at its end, after loads and after the game re-dresses a character.

**Invalid object**: what UE4SS returns for a missing link or property. Calling anything on it
other than `IsValid` crashes inside UE4SS (pcall can't catch it). See `valid`, `alive`.

**alive**: valid for UE4SS and not being destroyed, not garbage, fully loaded (object flags).

**propOf**: reads a property by name only if the class lists it as a safe type (plain object
pointer, name, number, bool, array). Weak/soft properties crash UE4SS 1125. It also reads nothing
of an object whose class is loading or being removed (**class-loading guard**; logged once per
class as "skipped reading … its class is …").

**Step / trace**: breadcrumbs (`step(...)`) written before risky engine calls; the watchdog prints
the last 40 when the game thread stops (`WATCHDOG: last mod step: …`).

**Watchdog**: a background loop that writes `WATCHDOG:` lines when the game thread hasn't run for
6 s, with the mod's state. "idle" means the stop was outside the mod's own calls.

**Hitch**: a frame longer than 150 ms, logged with the mod's work in the tick before.

**Busy / calm**: a burst of new actors or a long frame in the last 0.5 s; new skins and passes wait
for calm (at most 10 s).

**live_log.txt / report.txt / dump.txt**: the session log (one line per event, read by the app);
the report written by Ctrl+F9 (settings, selection, logs, dump); the list of characters and
their components.

**B (redesign B)**: giving the game the picked variant's own skin Blueprint in its own dressing
call, so the game dresses everyone itself. `B:` lines in the live log are its probe; `b_swap = param`
switches its test on. **Body check**: 2 s after a swap took, the dressed character's body (`Body`,
or the component named `CharacterMesh0` / `Body`) must show a mesh; one without stops swaps to that
Blueprint for the session.

**Companion watch**: every 2 s the classes of characters seen showing a replaced mesh are looked
up (`FindAllOf`) and re-dressed if their body changed; one class after another within 8 ms.

**Case repair**: the relocator respells a link that differs from one of the mod's own packages
only in letter case (the game ignores case, retoc doesn't). Game packages are never respelled.

**Soft reference**: a link to an asset by path (`TSoftClassPtr`); the game's
`AssignBodyAndFaceSkinAsync` takes the outfit as one. UE4SS 1125 crashes reading them (#1433),
1176 doesn't.

**Minidump**: a small process dump from ProcDump (`-mm`), read with `scripts/analyze_dump.py`.

**fixes.json**: the user's fixes from the app (row edits, hidden options, disabled mods, texture
and material rules, bundles), applied whenever the menu list is written.
