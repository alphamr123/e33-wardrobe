# Research notes

What was found out about Clair Obscur: Expedition 33 (E33) and UE4SS while building E33
Wardrobe, with sources. The design built on it is described in [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

- [Sources and method](#sources-and-method)
- [The outfit pipeline](#the-outfit-pipeline)
- [Same-length relocation: evidence](#same-length-relocation-evidence)
- [Blood and dirt](#blood-and-dirt)
- [UE4SS threading](#ue4ss-threading)
- [Freezes seen during development](#freezes-seen-during-development)
- [Menu design notes](#menu-design-notes)
- [Prior art](#prior-art)
- [Roadmap: native wardrobe entries](#roadmap-native-wardrobe-entries)
- [Open questions](#open-questions)
- [References](#references)

## Sources and method

- **Game types**: E33's `Mappings.usmap` (property layouts of every class and struct, including
  Blueprint classes) and the cooked `DT_CharacterCustomizationItems`, both published with the
  open-source E33 Randomizer [R11]. Parsed with [`research/usmap.py`](../research/usmap.py) and
  `tools/e33legacy.py`.
- **Live game state**: the mod's own `dump.txt`, which lists every character actor's components,
  meshes, materials, texture and scalar parameters, and the session logs of about ten test
  sessions on the Steam version with UE4SS 3.0.1-1125-g527a483b.
- **UE4SS behaviour**: the RE-UE4SS source at the tested build [R3] and its issue tracker [R4, R5].
- **Other mods**: their mod pages, and for the blood/dirt mods their published files
  (examined, not redistributed).
- Engine: Unreal Engine 5.4 with IoStore containers (`.utoc` / `.ucas` / `.pak`).

## The outfit pipeline

```
DT_CharacterCustomizationItems  (/Game/Gameplay/CharacterCustomization/Data/)
  rows: SkinLune_Chic, SkinSciel_Chic, FaceLune_Ponytail, ...   (one row per wardrobe item)
    -> DA_CharacterCustomization_SkinLune_Chic   (/.../Data/Items/Skins/, class BP_DataAsset_Item_CharacterSkin_C)
         CharacterSkin : SoftObjectProperty  -> the skin Blueprint class
              -> BP_<...>  subclass of BP_CharacterSkinBase_C (an Actor)
                   components: Body, Face, Hair, Eyebrows, Eyelashes, Beard, Mustache,
                               Haircut_SkeletalMesh, Haircut_StaticMesh, FX_ArmRing1-3
                   AnimationProfile (S_AnimationProfile_Skins), FootStepProfile

Characters (BP_jRPG_Character_World_C, BP_jRPG_Character_Battle_Base_C, cinematic actors)
  carry BP_CharacterSkinComponent_C (or BP_CinematicCharacterSkinComponent_C):
      CurrentCharacterCustomization : S_CharacterCustomization
            { CharacterSkinBase : SoftObject, CharacterFaceBase : SoftObject }
      SpawnedCharacterSkin / SpawnedCharacterFace : the spawned skin / face actors
      CurrentCharacterSkinMaterialInstances : the game's own dynamic material instances
      OnCharacterSkinChanged / OnCharacterCustomizationChanged : delegates
S_CharacterCustomizationItemData { CharacterSkin : Name, CharacterFace : Name }  (used by game actions)
```

- **The wardrobe row struct is `S_jRPG_Item_StaticData`** (`Item_Type` 8 = customization,
  `HideInInventory` 1). A row links to its DataAsset through `Pictos_Data`, a hard import, and
  the row name equals `Item_HardcodedName`.
- DataAsset names differ from row names in 19 rows (`SkinSciel_Potatoe_Bag` →
  `DA_..._SkinSciel_PotatoeBag`), so a DataAsset path can't be derived from a row name.
- **Skins are spawned by the native `UCharacterSkinAssignPolicy`**: `AssignBodySkin(Owner,
  CharacterName, Class)`, `AssignBodySkinAsync`, the Face and BodyAndFace versions, and the
  delegates `OnBodySkinAssigned`, `OnFaceSkinAssigned`, `OnSkinAssignCompleted`. The subclass
  `CSAP_SwapAssign` has a `CachePoolSize`, so skin actors can be pooled and re-shown without a new
  BeginPlay.
- In game, the visible party member in exploration is `BP_jRPG_Character_World_C`, and its `Body`
  component **is** the skin actor's `Body`. The AI companion pawn
  (`BP_Pawn_AICompanion_<Char>_C`) shows its outfit on `CharacterMesh0`, and the menu has its
  own pawns (`BP_GameMenu_<Char>_C`).
- Example meshes: Lune's Chic outfit `/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin`
  (6 material slots: underwear, body, top, a slot the game hides with `/Game/Materials/Hide_Material`,
  bottom, jewellery). Each character's base body is `SK_<Character>_Placeholder`; Gustave's lives
  under `/Game/Characters/Heros/Noah/`.
- Outfit replacers only show on the outfit they replace (a mod for the "Potato bag" outfit
  replaces `SK_Lune_Potato_Skin`; body mods replace `SK_<Character>_Placeholder`).
- `BP_CharacterSkinComponent_C` has, among others, `ApplyCurrentCharacterSkin(Name Character
  Name)`, `ApplyCurrentCustomization`, `SetCharacterCustomization`, `OverrideCharacterSkin`,
  `UpdateCharacterSkinMaterialInstances` and `GetSkinMaterialInstances` (listed from the class at
  runtime).
- **Cutscene pawns (`BP_CineCharacter_Main_C`)** carry their own Body/Face/Hair components; their
  `BP_CinematicCharacterSkinComponent` names the character (`CharacterHardcodedName`).
- **The game keeps its own material instances** (`CurrentCharacterSkinMaterialInstances`,
  `AllMeshMaterials`) and drives wetness and camera opacity through them.
  `BP_CharacterVisualAlterationsComponent_C` handles water level, opacity and
  `DistanceTraveled`.
- **Saves store looks as row names** (`S_jRPG_CharacterSaveState.CharacterCustomization`), and
  owning an item means its row name is in the inventory
  (`AC_jRPG_InventoryManager_C:AddItemToInventory`).

So an outfit is a separate actor spawned for every outfit change, battle, cutscene and menu
preview. Hooking BeginPlay and the assign policy, and editing that actor's components, is enough
for runtime switching.

## Same-length relocation: evidence

- Tested on 245 cooked E33 packages (`tests/test_relocation.py`; the packages themselves can't be
  published): numbered names, base-only names and whole-tree relocation, each verified and packed
  with `retoc to-zen`.
- retoc, the only consumer of these files, reads the first `NamesReferencedFromExportDataCount`
  names into the zen package and finds exports by `SerialOffset - TotalHeaderSize`, which is why
  appended name entries are safe.
- Relocated `DT_CharacterCustomizationItems` and `BP_GameAction_SetCharacterCustomization` parse
  again correctly, with their import of `S_CharacterCustomizationItemData` rewritten, and retoc
  packs them into a valid UE 5.4 container with new package IDs.
- A public end-to-end test (`tests/test_relocate_e2e.py`) runs the whole relocator against a fake
  game made with `retoc gen-script-objects`.

## Blood and dirt

- Three Nexus mods change blood and dirt, all as plain pak mods without code:
  "Clean Characters and Bloody Effects Remover" [R13], "Dirt And Blood Remover" [R14] and
  "Dirt and Blood Reducer" [R15].
- Their files contain only `Texture2D` packages under `/Game/MetaHumans/BTLS_Textures/`:
  - per character: `Main_Characters/{Lune,Maelle,Sciel}_Body_BTLS`, `Body_Gustave_BTLS`, the face
    masks `Lune_Face_BTLS_4`, `Maelle_Face_BTLS_3`, `Sciel_BTLS_2`, `Gustave_BTLS_1`, and their
    normal maps (`*_Normal_BTLS`, `gustave_body_Normal`);
  - shared: `Mask_2/3/4_BTLS`, `T_BTLS_Mask_Tiling`, `T_BTLS_Normal_Tiling`, `T_Mask_RGBA_BTLS`
    (DXT5 masks, BC5 normals).
- The Remover mods make every mask and normal map all zero (RGBA 0). The Reducer keeps the masks
  but caps their values (about 120-230 of 255 per channel), so effects can only build up partly.
  One of them also packs a small label asset that only lists the textures.
- In game, the per-character masks are texture parameters on the skin materials: faces `BTLS_Map`
  and `BTLS_Normal`, bodies `BTLS_Map_Tiling` and `BTLS_Normal_Tiling`.
- The game's mappings show `BP_CineCharacter_Main_C` with `DustingLevel`, `DirtLevel`,
  `SweatLevel`, `TearsLevel` and `BloodLevel` (doubles) and `MeshesToAlter`. Nothing in the save
  state stores dirt.
- The skin materials also carry scalar values such as `BLOOD`; Clean doesn't need them.

E33 Wardrobe's Clean therefore points the mask parameters at an all-zero texture made at runtime,
and restores them when switched off ([HOW_IT_WORKS.md](HOW_IT_WORKS.md#clean)).

## UE4SS threading

Findings from reading the RE-UE4SS source at build 527a483b (v3.0.1 Beta) [R3]:

- The game thread runs all of a mod's hooks and queued actions on one shared Lua stack. The
  global Lua lock is released around every C call.
- `ExecuteInGameThread`, `LoopAsync` and `ExecuteWithDelay` called from a thread other than the
  game thread race with the game thread on that stack. In UE4SS.log this shows as
  "Ref was not function" ([R4], [R5]).
- Queuing from inside a game-thread callback is safe in this build (pending queues).
- The default `ExecuteInGameThread` method is EngineTick.
- `RegisterKeyBind` callbacks run on the event-loop thread holding its actions mutex;
  `LoopAsync` runs on the async thread without a lock.
- Available: `LoopInGameThreadWithDelay(ms, fn)` (repeats until cancelled), `IsInGameThread()`,
  `ExecuteInGameThreadWithDelay`. The mod uses the first two.
- Hot reload (Ctrl+R) can deadlock this build [R5]. The bundled BPModLoaderMod also binds the
  Insert key, so the wardrobe menu uses Delete.
- Issue [R4] was fixed upstream later (PR #1375), so newer UE4SS builds may behave differently.
  The single game-thread loop is safe either way.

## Freezes seen during development

Early test builds froze the game a few times, always inside or right after work the mod queued
from a key or async thread. After moving all work into one game-thread loop, no freeze and no
"Ref was not function" was seen again in about ten sessions, including a 36-minute session
across three areas. The exact cause was never proven with a process dump: an engine-side wait
while a mesh loads or is set was considered about as likely as the race.
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#if-the-game-freezes) explains how to capture one.

## Menu design notes

The first menu was reworked after analysing the recorded clicks of five test sessions: 28 % of
clicks went to Blueprint-only "fix" slots that change nothing visible, 34 of 54 Wear toggles
changed nothing while saying they had, half of all clicks were blind `<` / `>` cycling, and 8 of
10 menu openings lost their first click. The result: technical slots are hidden, one tab per
character, a "wears" line, Wear only where it can work, plain-language reasons after every pick,
named chooser buttons, Peek, and buttons sized to their captions.

The panel is plain UMG built from Lua (a bare `UserWidget` with a hand-made `WidgetTree`), the
technique Loud and Clear uses [R21]; nothing from the game's widget Blueprints is instantiated,
so a game update can't break the menu's assets.

## Prior art

- No wardrobe-style switching framework existed for E33 at the time of writing.
- Precedents in E33: **Weapon Skins** [R16] (a UE4SS Lua mod that swaps weapon appearance at
  runtime), **Aureole for Everyone** [R17] (effects on characters through UE4SS), and
  **Maelle's Life to Paint** [R18] (an outfit added by taking over an existing slot).
- **Stellar Blade's CNS** [R19], the model for the in-game part: a UE4SS Lua mod plus a UMG menu,
  with outfits described in JSON. Its **CNS Repacker** [R20] relocates with retoc and UAssetGUI to
  longer paths and copies the chain of vanilla parents that reference modded assets. E33 Wardrobe
  uses same-length paths instead, so headers don't need re-serialising.

## Roadmap: native wardrobe entries

New items in the game's own outfit menu are possible in principle, without overriding the game:

1. **Pak**: the relocated variant, a relocated clone of the vanilla skin Blueprint, and a
   relocated clone of the vanilla DataAsset with `CharacterSkin` pointing to the clone.
   Same-length rewriting handles all three.
2. **Lua at startup**: `DataTable:AddRow` on both `DT_CharacterCustomizationItems` and
   `DT_jRPG_Items_Composite` (the composite keeps its own copy of all rows), copying a vanilla row
   and patching `Item_HardcodedName`, `Pictos_Data` and the display name; then
   `AddItemToInventory`. This needs a UE4SS build with `UDataTable` support in Lua.
3. **A cleanup command** that re-equips the base row before uninstalling, because saves store row
   names.

Shipping an edited DataTable would conflict with other mods that rewrite it, so rows would be
added at runtime. This is not built.

## Open questions

- The root cause of the early freezes (see above).
- Game Pass: the mixer finds the default Game Pass folder, but in-game switching has only been
  tested on Steam.
- Characters other than Lune, Maelle, Sciel and Gustave (Verso, Monoco) haven't been tested with
  outfit mods; the code is not specific to any character.

## References

| # | Reference | Used for |
|---|---|---|
| R1 | UE4SS for Clair Obscur: Expedition 33 on Nexus Mods | The UE4SS build players install |
| R2 | RE-UE4SS releases, <https://github.com/UE4SS-RE/RE-UE4SS/releases> | Runtime |
| R3 | RE-UE4SS source, <https://github.com/UE4SS-RE/RE-UE4SS> (build 527a483b, v3.0.1 Beta) | Threading model, Lua API behaviour |
| R4 | RE-UE4SS issue #1180, "Crash in process_simple_actions from overlapping ExecuteInGameThread callbacks", <https://github.com/UE4SS-RE/RE-UE4SS/issues/1180> | "Ref was not function" |
| R5 | RE-UE4SS issue #1445, "Lua mod restarts crash or deadlock", <https://github.com/UE4SS-RE/RE-UE4SS/issues/1445> | Hot reload, off-thread race |
| R6 | UE4SS documentation, <https://docs.ue4ss.com/> | Lua API |
| R7 | retoc, <https://github.com/trumank/retoc> (v0.1.5) | IoStore ⇄ legacy conversion, script objects for tests |
| R8 | CUE4Parse, <https://github.com/FabianFG/CUE4Parse> | Reference for cooked texture layouts |
| R9 | bcdec, <https://github.com/iOrange/bcdec> | BC7 partition and anchor tables |
| R10 | FModel, <https://fmodel.app/> | Browsing cooked assets |
| R11 | E33 Randomizer, <https://github.com/IhorChornyi314/E33-Randomizer> | `Mappings.usmap`, cooked `DT_CharacterCustomizationItems` |
| R12 | lupa, <https://github.com/scoder/lupa> | Running the Lua mod against mocks in tests |
| R13 | Nexus Mods E33 #115, "Clean Characters and Bloody Effects Remover" | How blood/dirt masks are removed |
| R14 | Nexus Mods E33 #143, "Dirt And Blood Remover" | Same |
| R15 | Nexus Mods E33 #151, "Dirt and Blood Reducer" | Capped masks, for comparison |
| R16 | Nexus Mods E33 #908, "Weapon Skins" | Prior art |
| R17 | Nexus Mods E33 #773, "Aureole for Everyone" | Prior art |
| R18 | Nexus Mods E33 #727, "Maelle's Life to Paint" | Prior art |
| R19 | Stellar Blade "CNS" outfit framework | Model for in-game switching |
| R20 | CNS Repacker | Comparison of relocation approaches |
| R21 | Loud and Clear by DatGuySnowfox, <https://github.com/DatGuySnowfox/swgr-loud-and-clear> | The technique of building a UMG panel from UE4SS Lua |
| R22 | UAssetAPI, <https://github.com/atenfyr/UAssetAPI> | Reference for the legacy package format |

Nexus Mods pages are at `https://www.nexusmods.com/clairobscurexpedition33/mods/<number>`.
