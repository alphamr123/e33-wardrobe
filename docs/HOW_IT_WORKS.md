# How it works

This page explains the design for people who want to understand or build on E33 Wardrobe.
For using it, see [USAGE.md](USAGE.md). The research behind it, with sources, is in
[RESEARCH.md](RESEARCH.md).

- [Replacers and a wardrobe](#replacers-and-a-wardrobe)
- [Relocation](#relocation)
- [Why runtime hooks are enough](#why-runtime-hooks-are-enough)
- [Runtime swapping](#runtime-swapping)
- [Which actors, which character](#which-actors-which-character)
- [Pick order and overlaps](#pick-order-and-overlaps)
- [Outfit mods apply as a whole; Wear and Auto Wear](#outfit-mods-apply-as-a-whole-wear-and-auto-wear)
- [Matched groups](#matched-groups)
- [Clean](#clean)
- [Fix look](#fix-look)
- [Threading model](#threading-model)
- [Session recorder and watchdog](#session-recorder-and-watchdog)
- [In-game menu](#in-game-menu)
- [Mod Mixer](#mod-mixer)

## Replacers and a wardrobe

An outfit mod for Clair Obscur: Expedition 33 is usually a *replacer*. Its pak contains an
asset at the same path as a game asset, for example a skeletal mesh at
`/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin`. The engine loads the
mod's copy instead of the game's. Only one version of a path can win, so variants of a mod
("sleeves" / "sleeveless", ten colours) are separate paks, and switching means moving files
while the game is closed.

E33 Wardrobe offers two ways around that:

1. The **Mod Mixer** keeps every mod in a library and installs exactly the paks of the chosen
   combination. It is still file switching, but done by a tool, with conflict checks.
2. **In-game switching**: the relocator gives every variant its own asset paths, so all of
   them can be installed at once and none replaces the game. The UE4SS Lua mod then puts the
   chosen variant's assets on the characters while the game runs, which is what the engine
   would have done with that variant installed as a replacer.

## Relocation

`tools/e33_relocate.py` with retoc:

1. Each variant is extracted to legacy `.uasset/.uexp/.ubulk` files with `retoc to-legacy`.
   The mod's other paks are included for lookups, so a variant that uses a material from a
   colour or common pak still resolves.
2. Every package path the variant ships is moved to a unique path of **identical length**,
   e.g. `/Game/Characters/...` → `/Game/ZW7K2Q...`.
3. The variant is packed again with `retoc to-zen` into `Paks\~mods\_E33Wardrobe\<mod>\`. A
   variant that carries its own shaders gets its own `pakchunkNNNNN` name, so its shader
   library loads.
4. One `<Mod>_Shared_P` pak keeps the mod's own new assets (paths that don't exist in the
   game) at their original paths. It replaces nothing, and keeps references between options
   working: an outfit's mesh still finds its material.
5. A `variants.lua` table maps each original path to each variant's relocated path, per
   slot. The Lua mod reads it.

### Why same-length paths are safe

E33's cooked packages are unversioned and store zeroed name-map hashes. If every occurrence of
a package path is replaced by a path of the same length:

- no header offset, export `SerialOffset`, bulk-data offset or `FString` length changes;
- imports between relocated packages follow automatically, because they are name-map entries;
- `retoc to-zen` recomputes package IDs from the new names.

The exception is names ending in `_<number>`. Unreal stores `/Game/X/T_Body_1` as the name
`/Game/X/T_Body` plus the number 2, and `T_Body_2` shares that entry. So headers are rewritten
structurally (`tools/e33legacy.py`):

- entries whose whole string is a relocated path are renamed in place;
- every header name reference (index plus number) is resolved;
- references that still need the old string, or need a numbered relocated path, point at an
  existing or newly appended entry, and later offsets are shifted.

Every rewritten header is parsed again and compared before packing. A numbered reference
*inside export data* to a vanilla sibling of a renamed entry would follow the rename; that is
rare, and the verification catches header problems either way.

### Skeletons, physics and missing imports

Replacer mods often ship a copy of a game skeleton. By default the relocator drops a copy that
*replaces* a game skeleton, and the variant uses the game's, so animations keep working
(`--skeletons override` keeps the mod's). Physics assets travel with the variant by default
(`--physics mod`); `--physics game` drops the mod's copy and uses the game's. A reference to an
asset that exists in neither the game nor the mod is kept and reported; the game sees it as
empty, as it does with the original mod installed. `--strict-imports` refuses such variants.

## Why runtime hooks are enough

An outfit in E33 is a **separate actor**: a skin Blueprint (subclass of
`BP_CharacterSkinBase_C`) that the character's `BP_CharacterSkinComponent_C` spawns through the
native `CharacterSkinAssignPolicy`. It is spawned on every outfit change, battle, cutscene and
menu preview; with the pooling policy `CSAP_SwapAssign` an existing actor can also be
re-assigned without a new BeginPlay. So hooking actor BeginPlay plus the policy's
`AssignBodySkin` / `AssignFaceSkin` / `AssignBodyAndFaceSkin` (and their `Async` versions), and
editing the spawned actor's components, reaches every appearance of a character. Details:
[RESEARCH.md](RESEARCH.md#the-outfit-pipeline).

## Runtime swapping

For every component of a character (`Body`, `Face`, `Hair`, …, and `CharacterMesh0` on AI
companion pawns), one pass:

1. Looks up the component's mesh, each material slot and each texture parameter in the table
   of the variants active for that character.
2. Loads the relocated copy (through `AssetRegistryHelpers.GetAsset`, the way UE4SS's own
   BPModLoaderMod loads mod assets, since relocated assets aren't in the game's asset
   registry) and sets it on the component.
   - Texture swaps use a dynamic material instance.
   - When it replaces one of the game's dynamic instances, it copies the game's scalar and
     vector values (wetness, opacity) and updates the game's own list of instances, so those
     effects keep working.
3. If a variant replaces the skin Blueprint itself, the Blueprint's component templates are
   copied onto the live actor.
4. When the mesh changes, each slot follows the **new mesh's own material**: a slot that
   showed the old mesh's material (or a material left by another variant) takes the new
   mesh's choice, and only then is a variant's remap applied. This matters for meshes that
   hide parts with the game's `Hide_Material`: a fresh skin's slot shows the game's instance
   of the old material, and remapping that first would leave hidden parts visible.
5. Switching a variant off restores the game's own mesh (from the live Blueprint's component
   template) and materials.

The outfit's `Body` on a skin actor and the world pawn's `Body` are the same component (the
swap policy renders the outfit through the pawn), so each component is handled once per pass.

## Which actors, which character

- Skin actors (`BP_CharacterSkinBase_C`), face actors (`BP_CharacterFaceBase_C`) and cutscene
  pawns (`BP_CineCharacter_Main_C`) are found by class.
- Body mods replace the base body `SK_<Character>_Placeholder`, which is shown by world and menu
  pawns that are not skin actors. Those are found by the meshes they show; their classes are
  remembered for later spawns, and the scan is repeated once after each level load.
- A slot belongs to the character named in its slot name (`Lune outfit`, `Sciel color`), else
  in its mod's name, else in the paths of the assets it replaces. It only touches that
  character. If the mod can't tell whose skin an actor is, only slots without a character
  apply.

## Pick order and overlaps

When two selected variants replace the same asset for the same character, the one picked last
wins. Pick order is saved in `selection.txt`. The menu marks the other one "hidden" and offers
**Bring to front**. Counts such as "6/6 pieces on screen" are per variant: a texture shown
because another mod also ships it doesn't count for both.

## Outfit mods apply as a whole; Wear and Auto Wear

Most outfit mods replace one game outfit (an outfit's skeletal mesh, often with the textures
of the body under it). A variant that brings a skeletal mesh is treated as one piece: on a
body component its materials and textures only apply where its mesh is the one shown.
Otherwise a mod made for another outfit would change that outfit's skin textures, and the
looks would mix. If two variants ship the same asset and the later one doesn't fit, the earlier
one's version is used.

**Wear** puts a variant's mesh on the character's body in place of whatever outfit is worn. The
body is one mesh, so the two never layer. The outfit that was on before is remembered (mesh and
the game's material setup), also while you switch between worn variants, and comes back on
Unwear. A skin actor that still shows a leftover worn mesh goes back to its own outfit by itself.

**Auto Wear** (on by default) switches Wear on after the pass that follows a pick, if the picked
variant's mesh shows nowhere on its character. It waits until the character is loaded. An
explicit Unwear is respected until the slot is picked again.

## Matched groups

Labels from the relocator carry their variant group ("Lace dress: …", "Non-Lace dress: …"). When
a slot's pick is in one group, sibling slots of the same mod and character that hold a pick
from another group switch to their closest variant in the same group (some mods need matching
pieces, e.g. textures that carry a group's normal maps). Slots that are off stay off, and
Blueprint-only "fix" slots never take part.

## Clean

The game draws blood, dirt, sweat and tears through masks: textures under
`/Game/MetaHumans/BTLS_Textures/` that the characters' skin materials take as texture parameters
(`BTLS_Map` on faces, `BTLS_Map_Tiling` on bodies, plus normal maps). Popular clean mods replace
those textures with all-zero ones ([RESEARCH.md](RESEARCH.md#blood-and-dirt)).

Clean does the same at runtime:

- It makes one 4×4 RGBA8 render target cleared to 0 (alpha 0 too) with
  `KismetRenderingLibrary.CreateRenderTarget2D`, owned by the game instance.
- Every texture parameter on a character's materials that currently shows a BTLS mask (not a
  normal map) is pointed at it. A slot whose material has no dynamic instance gets one.
- The game's masks are remembered per instance and put back when Clean is switched off.
- Cutscene pawns' `BloodLevel`, `DirtLevel` and `DustingLevel` are set to 0, and again every
  second while Clean is on, because sequences animate them. `SweatLevel` and `TearsLevel` stay.
- New characters are cleaned when they spawn (BeginPlay + 1 s), after level loads, and after
  each outfit pass (which can create new instances).

The render target is freed by the engine once nothing uses it, and made again when needed.

## Fix look

`BP_CharacterSkinComponent_C.ApplyCurrentCharacterSkin` re-dresses a character the way the game
does when an outfit is equipped. It takes one parameter, `Name "Character Name"`. The mod reads
the parameter list from the function at runtime, and passes the name the game itself used when
it last assigned that character's skin (recorded by the `CharacterSkinAssignPolicy` hook), or a
cutscene component's `CharacterHardcodedName`. The current picks are applied again 0.8 s later.
Wear's memory of the original outfits is only cleared if the game really re-dressed someone.

## Threading model

UE4SS runs a mod's hooks and game-thread work on one shared Lua stack. In UE4SS
3.0.1-1125-g527a483b, calling `ExecuteInGameThread`, `LoopAsync` or `ExecuteWithDelay` from a thread other
than the game thread races with the game thread on that stack ("Ref was not function" in
UE4SS.log; see [RESEARCH.md](RESEARCH.md#ue4ss-threading)). So:

- At load, the mod makes its only `ExecuteInGameThread` call. On the game thread it registers
  its hooks, reads its files and starts **one** `LoopInGameThreadWithDelay` loop (50 ms).
- Key binds and console commands only add an entry to an inbox; the loop runs them.
- Hooks already run on the game thread.
- Timers are counted in loop ticks. Picks within about 200 ms are merged into one pass.
- The menu is drawn by the same loop.
- Builds without `LoopInGameThreadWithDelay` (older than December 2025) have no safe way to do
  this, so the mod doesn't start there and says so in UE4SS.log.
- A menu that fails to draw closes itself and logs the error once.

## Session recorder and watchdog

While Record session is on, `live_log.txt` gets one timestamped line per menu click or key,
console command, setting change, spawn, map load and error, and one line per change a pass
makes (mesh, material slot, texture parameter, anim class, Wear), per character and component.
Before every asset that actually has to be loaded it writes `loading <path>`, and after every
mesh set `mesh set (N ms)`, so if the game hangs the last line says what it was doing. Lines are
flushed as they are written. The log stops at 20 MB; the previous session is kept as
`live_log_previous.txt`. Report.txt replaces Windows user names in paths with `<user>`.

Cost, measured on real sessions: about 1,800 lines (290 KB) in a busy 10 minutes, at most about
130 lines in one second (about 3 ms of writing in that second). That is why recording is on by
default.

The watchdog is an async loop (every second) that only reads a timestamp the game-thread loop
writes. If the loop hasn't run for 6 s it writes one line with the mod's state at the time
(`idle` means the mod wasn't working: the stall is in the game or engine). It never calls into
UE4SS or the engine.

## In-game menu

The menu is native UMG built from Lua: a bare `/Script/UMG.UserWidget` with a hand-made
`WidgetTree` (canvas, border, size boxes, horizontal/vertical boxes, text blocks, buttons). No
Blueprint and nothing from `/Game` is instantiated. Widgets are built once per level, then only
hidden and shown, and text, colour and visibility are only sent to UMG when they change, so an
idle tick costs nothing. Clicks are read by matching the left mouse button against the hovered
button, because `OnClicked` can't be bound from Lua. The game's input mode is left alone unless
the "UI input mode" setting is on.

## Mod Mixer

`tools/e33_mixer.py` keeps a state file in the library and a manifest in
`Paks\~mods\_E33Mixer\`, and installs selected paks there as hard links (copies across drives).
`tools/e33rules.py` turns a rules file (or the folder layout) into choices and pak lists.
`tools/e33utoc.py` reads each `.utoc`'s file list to find paks that override the same asset and
tells which one wins (load order). It refuses to change files while the game runs (process list
and locked paks).
