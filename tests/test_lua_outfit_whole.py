"""Outfit mods apply as a whole, and Auto Wear (needs lupa).

PC session 6 (Lune in Chic, "Lune Body Test: Body" picked): the mod's body mesh replaces
SK_Lune_Placeholder, which Chic doesn't show, but its body textures (Lune_Body_BaseColor, the
UnderwearMask...) are also used by Chic's skin material, so they were swapped there: a mixed look
reported as "5/6 on screen". Checks:
  * a variant that brings a skeletal mesh only touches a body whose mesh is that mesh: nothing on
    Chic, state "unused", textures left vanilla
  * a texture-only slot (a colour) still applies to Chic
  * Wear puts the mesh on and its textures come with it; Wear off restores Chic's textures
  * Auto Wear (default on): the pick is worn in place of Chic by itself, once, after the pass;
    not when the mod's mesh already shows; not again after the player's own Unwear
"""
import os
import shutil
import sys
import tempfile

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_lua_mock as base  # noqa: E402

EXTRA = r'''
-- a "barefoot" outfit mesh that hides its boots' slot with the game's Hide_Material
asset("Material", "/Game/Materials/Hide_Material", "Hide_Material", {})
asset("SkeletalMesh", "/Game/Characters/ZWBARE/Chic/SK_Lune_Chic", "SK_Lune_Chic",
  { Materials = TArray({ { MaterialInterface = get("/Game/Materials/Hide_Material.Hide_Material") } }) })
-- a skin component like the PC's: ApplyCurrentCharacterSkin(Name "Character Name")
FIXARG = "none"
HOOKS = {}
function RegisterHook(name, pre, post) HOOKS[name] = post; return 1, 2 end
local prop = { GetFName = function() return { ToString = function() return "Character Name" end } end,
               GetClass = function() return { GetFName = function() return { ToString = function() return "NameProperty" end } end } end }
local fnObj = { GetFName = function() return { ToString = function() return "ApplyCurrentCharacterSkin" end } end,
                ForEachProperty = function(self, cb) cb(prop) end }
local skinCls = { IsValid = function() return true end, GetSuperStruct = function() return nil end,
                  ForEachFunction = function(self, cb) cb(fnObj) end }
SKINCOMP = new("BP_CharacterSkinComponent_C", "/Game/Map.PersistentLevel.Pawn.BP_CharacterSkinComponent", {},
  { ApplyCurrentCharacterSkin = function(self, ...)
      if select("#", ...) ~= 1 then error("UFunction expected 1 parameters, received " .. select("#", ...)) end
      FIXARG = (...):ToString() end,
    GetOwner = function() return OWNER end })
SKINCOMP._class = skinCls
OWNER = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_1", { BP_CharacterSkinComponent = SKINCOMP })
function assignHook(name)                    -- the game's skin policy assigning a skin to OWNER as `name`
  ExecuteInGameThread(function()
    HOOKS["/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkin"](nil, { get = function() return OWNER end },
      { get = function() return FName(name) end })
  end)
end
local fao = FindAllOf
function FindAllOf(n) if n == "BP_CharacterSkinComponent_C" then return { SKINCOMP } end return fao(n) end
asset("Texture2D", "/Game/Characters/ZWOUTTEX/Chic/T_Chic_D", "T_Chic_D")
asset("SkeletalMesh", "/Game/Characters/Lune/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })
asset("SkeletalMesh", "/Game/Characters/ZWLIGHT/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })
-- a mod body material whose base colour points at a texture nobody shipped (PC: Lune showed grey)
asset("MaterialInstanceConstant", "/Game/Characters/ZWGREY/Body/MI_Body_Mod", "MI_Body_Mod",
  { TextureParameterValues = TArray({ { ParameterInfo = { Name = FName("BaseColor") },
      ParameterValue = NULLOBJ() } }) })
asset("Texture2D", "/Game/Characters/ZWGREY/Chic/T_Chic_D-mod", "T_Chic_D-mod")
asset("SkeletalMesh", "/Game/Characters/ZWGREY2/Body/SK_Lune_Bikini_C_Skin", "SK_Lune_Bikini_C_Skin",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/ZWGREY/Body/MI_Body_Mod.MI_Body_Mod") } }) })
asset("Texture2D", "/Game/Characters/ZWGREY2/Body/body_high_BaseColor-mod", "body_high_BaseColor-mod")
asset("Texture2D", "/Game/Characters/ZWGREY2/Body/underwear_color-mod", "underwear_color-mod")
asset("SkeletalMesh", "/Game/Characters/ZWGREY/Body/SK_Lune_Bikini_B_Skin", "SK_Lune_Bikini_B_Skin",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/ZWGREY/Body/MI_Body_Mod.MI_Body_Mod") } }) })
-- a mod mesh with empty material slots, left for the game's skin Blueprint to fill (PC report
-- 2026-10-11: Cheeki's Sciel mesh, mat1 and mat2 nil, grey body). Chic's slot is named "Body".
get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic")._p.Materials._items[1].MaterialSlotName = FName("Body")
asset("MaterialInstanceConstant", "/Game/Characters/ZWGREY3/Body/MI_Bikini_Mod", "MI_Bikini_Mod", { TextureParameterValues = TArray({}) })
asset("SkeletalMesh", "/Game/Characters/ZWGREY3/Body/SK_Lune_Bikini_D_Skin", "SK_Lune_Bikini_D_Skin",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/ZWGREY3/Body/MI_Bikini_Mod.MI_Bikini_Mod"), MaterialSlotName = FName("Bikini") },
                         { MaterialSlotName = FName("Body") },
                         { MaterialSlotName = FName("Extra") } }) })
asset("Texture2D", "/Game/Characters/ZWGREY3/Chic/T_Chic_D-alt", "T_Chic_D-alt")
-- PC 17 Oct: Sciel's Chic outfit is a Lune mesh, so "the body's skin material" was Lune's; the
-- game's own version of the mod's mesh has the character's skin material, whose textures the mod
-- replaces (body_other_D -> body_other_D-alt)
asset("Texture2D", "/Game/Characters/Lune/Body/body_other_D", "body_other_D")
asset("MaterialInstanceConstant", "/Game/Characters/Lune/Body/MI_Body_Other", "MI_Body_Other",
  { TextureParameterValues = TArray({ { ParameterInfo = { Name = FName("Color_MAIN") },
      ParameterValue = get("/Game/Characters/Lune/Body/body_other_D.body_other_D") } }) })
asset("SkeletalMesh", "/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_G_Skin", "SK_Lune_Bikini_G_Skin",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/ZWGREY3/Body/MI_Bikini_Mod.MI_Bikini_Mod"), MaterialSlotName = FName("Bikini") },
                         { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Other.MI_Body_Other"), MaterialSlotName = FName("Skin_Other") } }) })
asset("SkeletalMesh", "/Game/Characters/ZWGREY6/Body/SK_Lune_Bikini_G_Skin", "SK_Lune_Bikini_G_Skin",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/ZWGREY3/Body/MI_Bikini_Mod.MI_Bikini_Mod"), MaterialSlotName = FName("Bikini") },
                         { MaterialSlotName = FName("Skin_Other-alt") } }) })
asset("Texture2D", "/Game/Characters/ZWGREY6/Body/body_other_D-alt", "body_other_D-alt")
-- rules chosen in the app (fixes.json -> v.fix): a texture for an empty link, a material for a slot
asset("MaterialInstanceConstant", "/Game/Characters/ZWGREY4/Body/MI_Body_Mod4", "MI_Body_Mod4",
  { TextureParameterValues = TArray({ { ParameterInfo = { Name = FName("BaseColor") },
      ParameterValue = NULLOBJ() } }) })
asset("SkeletalMesh", "/Game/Characters/ZWGREY4/Body/SK_Lune_Bikini_E_Skin", "SK_Lune_Bikini_E_Skin",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/ZWGREY4/Body/MI_Body_Mod4.MI_Body_Mod4") } }) })
asset("Texture2D", "/Game/Characters/ZWGREY4/Chic/T_Chic_D-mod", "T_Chic_D-mod")
asset("Texture2D", "/Game/Characters/ZWGREY4/Body/T_Picked", "T_Picked")
-- the body's own texture and skin material; an outfit for Chic whose skin shows them; a skin mod's
-- base body and its version of the body texture; an outfit's own version
asset("Texture2D", "/Game/Characters/Lune/Body/Lune_Body_BaseColor", "Lune_Body_BaseColor")
asset("Texture2D", "/Game/Characters/ZWSKIN/Body/Lune_Body_BaseColor", "Lune_Body_BaseColor")
asset("Texture2D", "/Game/Characters/ZWOWN/Body/Lune_Body_BaseColor", "Lune_Body_BaseColor")
asset("MaterialInstanceConstant", "/Game/Characters/Lune/Body/MI_Body_Lune", "MI_Body_Lune",
  { TextureParameterValues = TArray({ { ParameterInfo = { Name = FName("BaseColor") },
      ParameterValue = get("/Game/Characters/Lune/Body/Lune_Body_BaseColor.Lune_Body_BaseColor") } }) })
asset("SkeletalMesh", "/Game/Characters/ZWCOMP/Chic/SK_Lune_Chic", "SK_Lune_Chic",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune") } }) })
asset("SkeletalMesh", "/Game/Characters/ZWSKIN/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune") } }) })
-- PC 17 Nov: the game's first outfit of a character (three slots here: skin, coat, and one the
-- game ships without a material, as its own meshes have), and a skin Blueprint whose Body template
-- names that mesh
asset("MaterialInstanceConstant", "/Game/Characters/Lune/Base/MI_Base_Coat", "MI_Base_Coat", { TextureParameterValues = TArray({}) })
asset("SkeletalMesh", "/Game/Characters/Lune/Base/SK_Lune_Base", "SK_Lune_Base",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune"), MaterialSlotName = FName("Skin") },
                         { MaterialInterface = get("/Game/Characters/Lune/Base/MI_Base_Coat.MI_Base_Coat"), MaterialSlotName = FName("Coat") },
                         { MaterialSlotName = FName("lambert1") } }) })
function BASE_OUTFIT()
  ACTORS[1].Body._mesh = get("/Game/Characters/Lune/Base/SK_Lune_Base.SK_Lune_Base")
  local t = meshComp("Body_GEN_VARIABLE", get("/Game/Characters/Lune/Base/SK_Lune_Base.SK_Lune_Base"))
  t._p.OverrideMaterials = TArray({})
  REGSET("/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C:Body_GEN_VARIABLE", t)
end
function SLOTS3()                 -- what the body's three slots show: the material, or its parent for an instance
  local b, out = ACTORS[1].Body, {}
  for i = 0, 2 do
    local m = b:GetMaterial(i)
    out[#out + 1] = m and ((m._p.Parent and ("instance of " .. m._p.Parent._path)) or m._path) or "empty"
  end
  return table.concat(out, " | ")
end
-- the walking character's body is ONE component for the whole party: the game puts each leader's
-- outfit on it. Sciel's outfit actor shares Lune's body component here.
asset("SkeletalMesh", "/Game/Characters/Sciel/Base/SK_Sciel_Base", "SK_Sciel_Base",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })
asset("SkeletalMesh", "/Game/Characters/ZWZ/Skin/SK_Sciel_Worn", "SK_Sciel_Worn",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })
function PARTY()
  LUNE = ACTORS[1]
  local body = LUNE.Body
  SCIEL = new("BP_Sciel_Skin_C", "/Game/Map.PersistentLevel.BP_Sciel_Skin_C_1", { Body = body },
    { K2_GetComponentsByClass = function() return TArray({ body }) end })
  SCIEL._class = new("BlueprintGeneratedClass", "/Game/Characters/Sciel/BP_Sciel_Skin.BP_Sciel_Skin_C")
  SCIEL._class._super = LUNE._class._super
  SCIEL._skin = "BP_CharacterSkinBase_C"
end
function LEAD(a, meshFull)        -- the game shows that character's outfit on the shared body
  ACTORS[1] = a
  a.Body._mesh = get(meshFull)
  for i = 0, 5 do a.Body:SetMaterial(i, nil) end
end
-- a second character whose body uses a texture that a Lune pick also brings (and Lune doesn't use)
asset("Texture2D", "/Game/Characters/Lune/Body/Lune_Belt_BaseColor", "Lune_Belt_BaseColor")
asset("MaterialInstanceConstant", "/Game/Characters/Sciel/Base/MI_Sciel_Belt", "MI_Sciel_Belt",
  { TextureParameterValues = TArray({ { ParameterInfo = { Name = FName("BaseColor") },
      ParameterValue = get("/Game/Characters/Lune/Body/Lune_Belt_BaseColor.Lune_Belt_BaseColor") } }) })
asset("SkeletalMesh", "/Game/Characters/Sciel/Base/SK_Sciel_Belted", "SK_Sciel_Belted",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Sciel/Base/MI_Sciel_Belt.MI_Sciel_Belt") } }) })
function ADD_SCIEL_BELTED()
  local b = meshComp("Body", get("/Game/Characters/Sciel/Base/SK_Sciel_Belted.SK_Sciel_Belted"))
  b._path = "/Game/Map.PersistentLevel.BP_Sciel_Skin_C_2.Body"
  local a = new("BP_Sciel_Skin_C", "/Game/Map.PersistentLevel.BP_Sciel_Skin_C_2", { Body = b },
    { K2_GetComponentsByClass = function() return TArray({ b }) end })
  a._class = new("BlueprintGeneratedClass", "/Game/Characters/Sciel/BP_Sciel_Skin.BP_Sciel_Skin_C")
  a._class._super = ACTORS[1]._class._super
  a._skin = "BP_CharacterSkinBase_C"
  table.insert(ACTORS, a)
end
asset("SkeletalMesh", "/Game/Characters/ZWGREY5/Body/SK_Lune_Bikini_F_Skin", "SK_Lune_Bikini_F_Skin",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/ZWGREY3/Body/MI_Bikini_Mod.MI_Bikini_Mod"), MaterialSlotName = FName("Bikini") },
                         { MaterialSlotName = FName("Body") },
                         { MaterialSlotName = FName("Extra") } }) })
-- PC 17 Nov, rerun: a mod's version of the game's first outfit mesh with a material on the slot
-- the game ships empty (a skin mod for Sciel: the scarf material on her lambert1)
asset("SkeletalMesh", "/Game/Characters/ZWEMPTY/Base/SK_Lune_Base", "SK_Lune_Base",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune"), MaterialSlotName = FName("Skin") },
                         { MaterialInterface = get("/Game/Characters/Lune/Base/MI_Base_Coat.MI_Base_Coat"), MaterialSlotName = FName("Coat") },
                         { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"), MaterialSlotName = FName("lambert1") } }) })
-- an outfit option made for the base body whose mesh shows the body's skin material (PC: Lune
-- Outfit Options)
asset("SkeletalMesh", "/Game/Characters/ZWOPT/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder",
  { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune") } }) })
'''

VARIANTS = r'''return {
  { mod = "Lune Body Test", slots = {
    { id = "L/Body", label = "Lune Body Test: Body", character = "Lune", variants = {
      { id = "L/Clean", label = "Clean", map = {
        ["/Game/Characters/Lune/Body/SK_Lune_Placeholder"] = { "/Game/Characters/ZWLIGHT/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder", "SkeletalMesh" },
        ["/Game/Characters/Lune/Chic/T_Chic_D"] = { "/Game/Characters/ZWCOLOR01/Chic/T_Chic_D", "T_Chic_D", "Texture2D" } } } } } } },
  { mod = "Colours", slots = {
    { id = "C/color", label = "Colours: Lune color", character = "Lune", variants = {
      { id = "C/red", label = "red", map = {
        ["/Game/Characters/Lune/Chic/T_Chic_D"] = { "/Game/Characters/ZWCOLOR01/Chic/T_Chic_D", "T_Chic_D", "Texture2D" } } } } } } },
  { mod = "Bare", slots = {
    { id = "B/main", label = "Bare: Lune outfit", character = "Lune", variants = {
      { id = "B/bare", label = "barefoot", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWBARE/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" },
        ["/Game/Characters/Lune/Chic/MI_Chic"] = { "/Game/Characters/ZWOUTFITA/Chic/MI_Chic", "MI_Chic", "MaterialInstanceConstant" } } } } } } },
  { mod = "Outfit", slots = {
    { id = "O/main", label = "Outfit: Lune outfit", character = "Lune", variants = {
      { id = "O/a", label = "A", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" },
        ["/Game/Characters/Lune/Chic/T_Chic_D"] = { "/Game/Characters/ZWOUTTEX/Chic/T_Chic_D", "T_Chic_D", "Texture2D" } } } } } } },
  { mod = "Grey", slots = {
    { id = "G/main", label = "Grey: Lune outfit", character = "Lune", variants = {
      { id = "G/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_B_Skin"] = { "/Game/Characters/ZWGREY/Body/SK_Lune_Bikini_B_Skin", "SK_Lune_Bikini_B_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Chic/T_Chic_D-mod"] = { "/Game/Characters/ZWGREY/Chic/T_Chic_D-mod", "T_Chic_D-mod", "Texture2D" } } } } } } },
  { mod = "Grey2", slots = {
    { id = "G2/main", label = "Grey2: Lune outfit", character = "Lune", variants = {
      { id = "G2/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_C_Skin"] = { "/Game/Characters/ZWGREY2/Body/SK_Lune_Bikini_C_Skin", "SK_Lune_Bikini_C_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/underwear_color-mod"] = { "/Game/Characters/ZWGREY2/Body/underwear_color-mod", "underwear_color-mod", "Texture2D" },
        ["/Game/Characters/Lune/Body/body_high_BaseColor-mod"] = { "/Game/Characters/ZWGREY2/Body/body_high_BaseColor-mod", "body_high_BaseColor-mod", "Texture2D" } } } } } } },
  { mod = "Grey3", slots = {
    { id = "G3/main", label = "Grey3: Lune outfit", character = "Lune", variants = {
      { id = "G3/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_D_Skin"] = { "/Game/Characters/ZWGREY3/Body/SK_Lune_Bikini_D_Skin", "SK_Lune_Bikini_D_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Bikini/MI_Bikini_Mod"] = { "/Game/Characters/ZWGREY3/Body/MI_Bikini_Mod", "MI_Bikini_Mod", "MaterialInstanceConstant" },
        ["/Game/Characters/Lune/Chic/T_Chic_D-alt"] = { "/Game/Characters/ZWGREY3/Chic/T_Chic_D-alt", "T_Chic_D-alt", "Texture2D" } } } } } } },
  { mod = "Grey4", slots = {
    { id = "G4/main", label = "Grey4: Lune outfit", character = "Lune", variants = {
      { id = "G4/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_E_Skin"] = { "/Game/Characters/ZWGREY4/Body/SK_Lune_Bikini_E_Skin", "SK_Lune_Bikini_E_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Bikini/MI_Body_Mod4"] = { "/Game/Characters/ZWGREY4/Body/MI_Body_Mod4", "MI_Body_Mod4", "MaterialInstanceConstant", false },
        ["/Game/Characters/Lune/Chic/T_Chic_D-mod"] = { "/Game/Characters/ZWGREY4/Chic/T_Chic_D-mod", "T_Chic_D-mod", "Texture2D" },
        ["/Game/Characters/Lune/Body/T_Picked"] = { "/Game/Characters/ZWGREY4/Body/T_Picked", "T_Picked", "Texture2D" } },
        fix = { tex = { ["/game/characters/lune/bikini/mi_body_mod4|*"] = "/Game/Characters/Lune/Body/T_Picked" } } } } } } },
  { mod = "Grey5", slots = {
    { id = "G5/main", label = "Grey5: Lune outfit", character = "Lune", variants = {
      { id = "G5/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_F_Skin"] = { "/Game/Characters/ZWGREY5/Body/SK_Lune_Bikini_F_Skin", "SK_Lune_Bikini_F_Skin", "SkeletalMesh" } },
        fix = { mat = { ["/game/characters/lune/customization/skin/sk_lune_bikini_f_skin|1"] = "hide",
                        -- a rule naming something that isn't a material is ignored (never set on a slot)
                        ["/game/characters/lune/customization/skin/sk_lune_bikini_f_skin|2"] = "/Game/Characters/ZWGREY4/Body/T_Picked" } } } } } } },
  { mod = "Grey6", slots = {
    { id = "G6/main", label = "Grey6: Lune outfit", character = "Lune", variants = {
      { id = "G6/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_G_Skin"] = { "/Game/Characters/ZWGREY6/Body/SK_Lune_Bikini_G_Skin", "SK_Lune_Bikini_G_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/body_other_D-alt"] = { "/Game/Characters/ZWGREY6/Body/body_other_D-alt", "body_other_D-alt", "Texture2D" } } } } } } },
  -- one costume for two characters (PC: "Altered Flower Suit Costume", Lune + Maelle + Sciel):
  -- the slot is tied to nobody; each mesh's path says whose it is
  { mod = "Costume", slots = {
    { id = "K/main", label = "Costume: Main", variants = {
      { id = "K/a", label = "Main", map = {
        ["/Game/Characters/Maelle/Body/SK_Maelle_Placeholder"] = { "/Game/Characters/ZWMAEL/Body/SK_Maelle_Placeholder", "SK_Maelle_Placeholder", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/SK_Lune_Placeholder"] = { "/Game/Characters/ZWLIGHT/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder", "SkeletalMesh" } } } } } } },
  -- an outfit built on someone else's skin textures: its mesh replaces Chic, its material shows the
  -- game's body texture, and it brings no body texture of its own (the player adds a skin mod)
  { mod = "Composite", slots = {
    { id = "X/main", label = "Composite: Lune outfit", character = "Lune", variants = {
      { id = "X/a", label = "A", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWCOMP/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" } } } } } } },
  -- a skin mod (PC: two such mods): a base body and the body's textures, nothing else
  { mod = "Skin Light", slots = {
    { id = "Y/main", label = "Skin Light: Lune", character = "Lune", variants = {
      { id = "Y/a", label = "A", map = {
        ["/Game/Characters/Lune/Body/SK_Lune_Placeholder"] = { "/Game/Characters/ZWSKIN/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/Lune_Body_BaseColor"] = { "/Game/Characters/ZWSKIN/Body/Lune_Body_BaseColor", "Lune_Body_BaseColor", "Texture2D" } } } } } } },
  -- the same outfit with a body texture of its own
  { mod = "Own", slots = {
    { id = "W/main", label = "Own: Lune outfit", character = "Lune", variants = {
      { id = "W/a", label = "A", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWCOMP/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/Lune_Body_BaseColor"] = { "/Game/Characters/ZWOWN/Body/Lune_Body_BaseColor", "Lune_Body_BaseColor", "Texture2D" } } } } } } },
  -- a costume built on the base body (PC library: three such mods): it brings the body texture AND
  -- a belt texture, so it is an outfit, not a skin mod
  { mod = "Cat", slots = {
    { id = "C2/main", label = "Cat: Lune costume", character = "Lune", variants = {
      { id = "C2/a", label = "A", map = {
        ["/Game/Characters/Lune/Body/SK_Lune_Placeholder"] = { "/Game/Characters/ZWLIGHT/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/Lune_Body_BaseColor"] = { "/Game/Characters/ZWSKIN/Body/Lune_Body_BaseColor", "Lune_Body_BaseColor", "Texture2D" },
        ["/Game/Characters/Lune/Body/Lune_Belt_BaseColor"] = { "/Game/Characters/ZWCAT/Body/Lune_Belt_BaseColor", "Lune_Belt_BaseColor", "Texture2D" } } } } } } },
  -- an outfit made for another outfit that also changes the body texture: not a skin mod
  { mod = "Swim", slots = {
    { id = "S/main", label = "Swim: Lune outfit", character = "Lune", variants = {
      { id = "S/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_C_Skin"] = { "/Game/Characters/ZWGREY2/Body/SK_Lune_Bikini_C_Skin", "SK_Lune_Bikini_C_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/Lune_Body_BaseColor"] = { "/Game/Characters/ZWSKIN/Body/Lune_Body_BaseColor", "Lune_Body_BaseColor", "Texture2D" } } } } } } },
  -- an outfit for Sciel, made for an outfit she isn't wearing
  { mod = "Zed", slots = {
    { id = "Z/main", label = "Zed: Sciel outfit", character = "Sciel", variants = {
      { id = "Z/a", label = "A", map = {
        ["/Game/Characters/Sciel/Customization/Skin/SK_Sciel_Worn"] = { "/Game/Characters/ZWZ/Skin/SK_Sciel_Worn", "SK_Sciel_Worn", "SkeletalMesh" } } } } } } },
  -- a Blueprint-only fix option (PC: Cheekier Chic "_only Separate colors_P"): the outfit's own
  -- Blueprint, whose Body uses another of the game's meshes and sets one of the option's materials
  { mod = "BpFix", slots = {
    { id = "P/main", label = "BpFix: Lune fix", character = "Lune", variants = {
      { id = "P/a", label = "A", map = {
        ["/Game/Characters/Lune/BP_Lune_Skin_Chic"] = { "/Game/Characters/ZWBPFIX/BP_Lune_Skin_Chic", "BP_Lune_Skin_Chic_C", "BlueprintGeneratedClass" },
        ["/Game/Characters/Lune/Base/MI_Base_Coat"] = { "/Game/Characters/ZWBPFIX/MI_Base_Coat", "MI_Base_Coat", "MaterialInstanceConstant" } } } } } } },
  -- a mod that replaces the game's first outfit mesh itself (PC: a skin mod for Sciel)
  { mod = "Empty", slots = {
    { id = "E/main", label = "Empty: Lune base", character = "Lune", variants = {
      { id = "E/a", label = "A", map = {
        ["/Game/Characters/Lune/Base/SK_Lune_Base"] = { "/Game/Characters/ZWEMPTY/Base/SK_Lune_Base", "SK_Lune_Base", "SkeletalMesh" } } } } } } },
  -- an outfit option for the base body, no body texture of its own (PC: Lune Outfit Options)
  { mod = "Options", slots = {
    { id = "Q/main", label = "Options: Lune outfit", character = "Lune", variants = {
      { id = "Q/a", label = "A", map = {
        ["/Game/Characters/Lune/Body/SK_Lune_Placeholder"] = { "/Game/Characters/ZWOPT/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder", "SkeletalMesh" } } } } } } },
  -- an outfit for Chic whose mesh can't be loaded (its pak is missing): the game's Chic stays on
  { mod = "Broken", slots = {
    { id = "N/main", label = "Broken: Lune outfit", character = "Lune", variants = {
      { id = "N/a", label = "A", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWMISSING/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" } } } } } } },
}
'''

CHIC = '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic'
TEX_VANILLA = '/Game/Characters/Lune/Chic/T_Chic_D.T_Chic_D'
TEX_MOD = '/Game/Characters/ZWCOLOR01/Chic/T_Chic_D.T_Chic_D'
TEX_OUTFIT = '/Game/Characters/ZWOUTTEX/Chic/T_Chic_D.T_Chic_D'
BODY_GAME = '/Game/Characters/Lune/Body/Lune_Body_BaseColor.Lune_Body_BaseColor'
BODY_SKIN = '/Game/Characters/ZWSKIN/Body/Lune_Body_BaseColor.Lune_Body_BaseColor'
BODY_OWN = '/Game/Characters/ZWOWN/Body/Lune_Body_BaseColor.Lune_Body_BaseColor'


RUNTIMES = []                   # every Lua state made, for the access-violation check at the end


def run(settings, selection=None):
    tmp = tempfile.mkdtemp(prefix='e33whole_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(VARIANTS)
    open(os.path.join(mod, 'settings.txt'), 'w').write(settings)
    if selection:
        open(os.path.join(mod, 'selection.txt'), 'w').write(selection)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    RUNTIMES.append(L)
    L.execute(base.MOCK)
    body, _actor = L.execute(base.SCENARIO)
    L.execute(EXTRA)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    G.settle()
    mesh = lambda: L.eval('function(b) return b._mesh._path end')(body)  # noqa: E731
    tex = lambda: L.eval('''function(b)
        local m = b:GetMaterial(0); local tex
        local ok, arr = pcall(function() return m.TextureParameterValues end)
        if ok and arr then arr:ForEach(function(_, e) tex = e:get().ParameterValue._path end) end
        if not tex and m._p.Parent then
          m._p.Parent._p.TextureParameterValues:ForEach(function(_, e) tex = e:get().ParameterValue._path end)
        end
        return tex end''')(body)  # noqa: E731
    return tmp, mod, L, G, G.API_OUT, mesh, tex


def main():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    # ---- Auto Wear off: the outfit mod waits for its outfit
    tmp, mod, L, G, W, mesh, tex = run('auto_wear = false\n')
    W.setVariant(1, 1)                                           # Body Test: Body = Clean, Lune wears Chic
    G.settle()
    check('an outfit mod made for another outfit leaves Chic alone: mesh', mesh() == CHIC, mesh())
    check('  and its textures stay off Chic\'s material (the PC "overlap")', tex() == TEX_VANILLA, tex())
    check('  state "unused", 0 pieces on screen', W.slotState(1) == 'unused' and W.slotShown('L/Body').shown == 0,
          (W.slotState(1), W.slotShown('L/Body').shown))
    check('  Auto Wear off: nothing worn', not W.isWear('L/Body'))
    W.setVariant(2, 1)                                           # a colour (texture only)
    G.settle()
    check('a texture-only slot still applies to Chic', tex() == TEX_MOD and W.slotState(2) == 'on', (tex(), W.slotState(2)))
    W.setVariant(2, 0)
    G.settle()
    check('  and goes back off', tex() == TEX_VANILLA, tex())
    W.setWear('L/Body', True)
    G.settle()
    check('Wear: the mod\'s mesh in place of Chic', mesh().startswith('/Game/Characters/ZWLIGHT/'), mesh())
    check('  with its textures', tex() == TEX_MOD and W.slotState(1) == 'on', (tex(), W.slotState(1)))
    check('  "Lune wears" = the mod\'s outfit, with Chic remembered under it',
          W.wornBy('Lune').under == '/Game/Characters/Lune/Chic/SK_Lune_Chic', W.wornBy('Lune').under)
    W.setWear('L/Body', False)
    G.settle()
    check('Wear off: Chic and its own textures again', mesh() == CHIC and tex() == TEX_VANILLA, (mesh(), tex()))
    W.setVariant(1, 0)
    G.settle()
    W.setVariant(4, 1)                                           # an outfit mod made for Chic
    G.settle()
    check('an outfit mod made for Chic applies as before', mesh().startswith('/Game/Characters/ZWOUTFITA/')
          and tex() == TEX_OUTFIT, (mesh(), tex()))
    # PC session 7: Body Test picked AFTER another outfit mod; both change the same body texture
    W.setVariant(1, 1)
    G.settle()
    check('a later outfit mod that doesn\'t fit gives way: the earlier outfit keeps its own texture',
          mesh().startswith('/Game/Characters/ZWOUTFITA/') and tex() == TEX_OUTFIT, (mesh(), tex()))
    check('  pieces are counted per mod: Body Test 0 on screen, the outfit all of them',
          W.slotShown('L/Body').shown == 0 and W.slotState(1) == 'unused'
          and W.slotShown('O/main').shown == W.slotShown('O/main').total, (W.slotShown('L/Body').shown, W.slotState(1)))
    ov = list(W.overlaps(4).values())
    check('  and the overlap note says the outfit is the one that shows', len(ov) == 1 and ov[0].wins, [o.wins for o in ov])
    W.setWear('L/Body', True)
    G.settle()
    check('  Wear Body Test: its mesh and its texture', mesh().startswith('/Game/Characters/ZWLIGHT/') and tex() == TEX_MOD,
          (mesh(), tex()))
    W.setWear('L/Body', False)
    G.settle()
    check('  Unwear: the outfit with its own texture again', mesh().startswith('/Game/Characters/ZWOUTFITA/')
          and tex() == TEX_OUTFIT, (mesh(), tex()))
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open


    # ---- PC session 9: a barefoot variant left boot parts on a freshly spawned skin
    tmp, mod, L, G, W, mesh, tex = run('auto_wear = false\n')
    slot0 = L.eval('function(b) local m = b:GetMaterial(0); return (m._p.Parent and m._p.Parent._path) or m._path end')
    body = L.eval('function() return ACTORS[1].Body end')()
    # like the game: the fresh skin's slot shows the game's own instance of the vanilla material
    L.eval('function(b) b:CreateDynamicMaterialInstance(0, get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"), FName("None")) end')(body)
    W.setVariant(3, 1)                                           # barefoot, on the game's fresh Chic skin
    G.settle()
    check('a fresh skin: the variant mesh\'s own material wins over the variant\'s remap of the old one '
          '(Hide_Material on the boots\' slot, not the outfit material)',
          mesh().startswith('/Game/Characters/ZWBARE/') and slot0(body) == '/Game/Materials/Hide_Material.Hide_Material',
          (mesh(), slot0(body)))
    W.setVariant(4, 1)                                           # an outfit with that slot visible
    G.settle()
    check('  switching to a variant that shows the slot: its material comes back',
          mesh().startswith('/Game/Characters/ZWOUTFITA/') and slot0(body).startswith('/Game/Characters/ZWOUTFITA/'),
          (mesh(), slot0(body)))
    W.setVariant(3, 1)
    G.settle()
    check('  and back to barefoot: hidden again', slot0(body) == '/Game/Materials/Hide_Material.Hide_Material', slot0(body))
    W.setVariant(3, 0)
    W.setVariant(4, 0)
    G.settle()
    check('  both off: the game\'s own mesh and material', mesh().startswith('/Game/Characters/Lune/')
          and slot0(body).startswith('/Game/Characters/Lune/Chic/MI_Chic'), (mesh(), slot0(body)))
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # ---- Auto Wear on (default)
    tmp, mod, L, G, W, mesh, tex = run('')
    W.setVariant(4, 1)
    G.settle()
    check('Auto Wear: not used when the mod\'s mesh already shows', not W.isWear('O/main')
          and mesh().startswith('/Game/Characters/ZWOUTFITA/'), mesh())
    W.setVariant(4, 0)
    G.settle()
    W.setVariant(1, 1)
    G.settle()
    check('Auto Wear: a mod made for another outfit is worn in place of Chic by itself',
          W.isWear('L/Body') and W.autoWorn('L/Body') and mesh().startswith('/Game/Characters/ZWLIGHT/'), mesh())
    check('  with its textures, on screen', tex() == TEX_MOD and W.slotState(1) == 'on', (tex(), W.slotState(1)))
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('  the live log says so; saved in settings.txt', "Auto Wear: Lune Body Test: Body doesn't fit" in live
          and 'wear = L/Body' in open(os.path.join(mod, 'settings.txt'), encoding='utf-8').read(), live[-400:])
    W.setWear('L/Body', False)
    G.settle()
    G.tickGT(40)
    check('the player\'s own Unwear sticks (Auto Wear doesn\'t put it back)', not W.isWear('L/Body') and mesh() == CHIC
          and tex() == TEX_VANILLA, (mesh(), tex()))
    check('  and the autoWorn mark is gone', not W.autoWorn('L/Body'))
    # Fix look: ApplyCurrentCharacterSkin(Character Name) gets the name the game used for the owner
    W.fixLook()
    G.settle()
    check('Fix look without a known character name: not called, and said so', G.FIXARG == 'none'
          and '1 without a known character name' in G.getlog(), G.getlog()[-300:])
    G.assignHook('Lune')
    W.fixLook()
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('Fix look passes the name the game gave the character when it assigned the skin; the game re-dresses',
          G.FIXARG == 'Lune' and W.lastFix().n == 1 and 're-dressed 1 of 1 character(s) (Lune)' in G.getlog()
          and 'ApplyCurrentCharacterSkin(NameProperty Character Name) - calling it with each character\'s name' in live,
          (G.FIXARG, G.getlog()[-300:]))
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # ---- a costume with a mesh per character becomes one slot per character (PC: switching it for
    # one character switched it for all; before that, nothing changed and no Auto Wear)
    tmp, mod, L, G, W, mesh, tex = run('wear = K/main\n')
    sl = list(W.slots().values())
    ids = [x.id for x in sl]
    check('a costume for Lune and Maelle is split into one slot per character, the old one is gone',
          'K/main@Lune' in ids and 'K/main@Maelle' in ids and 'K/main' not in ids, ids)
    ls = next(x for x in sl if x.id == 'K/main@Lune')
    keys = list(ls.variants[1].map.keys())
    check('  Lune\'s slot holds only Lune\'s assets', ls.character == 'Lune' and keys == ['/Game/Characters/Lune/Body/SK_Lune_Placeholder'], keys)
    check('  a Wear flag saved under the old slot is carried over to both',
          W.isWear('K/main@Lune') and W.isWear('K/main@Maelle') and not W.isWear('K/main'))
    W.setWear('K/main@Lune', False)
    W.setWear('K/main@Maelle', False)
    li = ids.index('K/main@Lune') + 1
    W.setVariant(li, 1)                                          # Lune wears Chic
    G.settle()
    G.tickGT(40)
    check('  Auto Wear puts the costume on Lune', W.isWear('K/main@Lune') and mesh().startswith('/Game/Characters/ZWLIGHT/'),
          (W.isWear('K/main@Lune'), mesh()))
    check('  and leaves Maelle\'s slot alone', not W.isWear('K/main@Maelle') and W.variantIndex(sl[ids.index('K/main@Maelle')]) == 0)
    W.setVariant(li, 0)
    G.settle()
    check('  switching Lune\'s slot off: back to Chic', mesh() == CHIC, mesh())
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # ---- a mod material with an empty texture slot gets what the body showed before
    tmp, mod, L, G, W, mesh, tex = run('')
    gi = [x.id for x in W.slots().values()].index('G/main') + 1
    W.setVariant(gi, 1)                                          # Lune wears Chic: Auto Wear puts it on
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('an empty base colour in a mod\'s material (an invalid object in UE4SS) gets the mod\'s own unused texture '
          'named like the old one (T_Chic_D -> T_Chic_D-mod), not grey',
          mesh().startswith('/Game/Characters/ZWGREY/') and tex() == '/Game/Characters/ZWGREY/Chic/T_Chic_D-mod.T_Chic_D-mod'
          and "(the mod's own texture for it)" in live, (mesh(), tex(), [l for l in live.splitlines() if 'empty' in l][:2]))
    grey = [l for l in live.splitlines() if 'on screen: Grey: Lune outfit' in l]
    check('  the texture put into the empty link counts as on screen in that same pass (2/2, not "not used")',
          grey and ': 2/2 asset(s)' in grey[-1] and 'not used' not in grey[-1], grey[-1:])
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # ---- the same, but the mod's texture has another name (PC: Sciel's Cheeki body, body_high_BaseColor-<suffix>)
    tmp, mod, L, G, W, mesh, tex = run('')
    gi = [x.id for x in W.slots().values()].index('G2/main') + 1
    W.setVariant(gi, 1)
    G.settle()
    G.tickGT(40)
    check('  a texture of the mod named for the kind of parameter (BaseColor -> body_high_BaseColor), not underwear',
          mesh().startswith('/Game/Characters/ZWGREY2/') and tex() == '/Game/Characters/ZWGREY2/Body/body_high_BaseColor-mod.body_high_BaseColor-mod',
          (mesh(), tex()))
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # ---- a mod mesh with empty material slots (PC report 2026-10-11: Cheeki's Sciel, grey body)
    tmp, mod, L, G, W, mesh, tex = run('')
    gi = [x.id for x in W.slots().values()].index('G3/main') + 1
    W.setVariant(gi, 1)                                          # Lune wears Chic: Auto Wear puts it on
    G.settle()
    G.tickGT(40)
    slot = L.eval('''function(b, i)
        local m = b:GetMaterial(i)
        if not m then return "nil" end
        local base = (m._p.Parent and m._p.Parent._path) or m._path
        local tex
        local ok, arr = pcall(function() return m.TextureParameterValues end)
        if ok and arr then arr:ForEach(function(_, e) tex = e:get().ParameterValue._path end) end
        return base .. " | " .. tostring(tex) end''')
    body = L.eval('function() return ACTORS[1].Body end')()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    s0, s1, s2 = slot(body, 0), slot(body, 1), slot(body, 2)
    check('an empty slot of a worn mod mesh gets the body\'s material from the slot of the same name, not grey',
          mesh().startswith('/Game/Characters/ZWGREY3/') and s1.startswith('/Game/Characters/Lune/Chic/MI_Chic'), (mesh(), s1))
    check('  with the mod\'s own texture named like the one it showed (T_Chic_D -> T_Chic_D-alt)',
          s1.endswith('/Game/Characters/ZWGREY3/Chic/T_Chic_D-alt.T_Chic_D-alt'), s1)
    check('  a slot with no match gets the skin material; the mod\'s own material stays',
          s2.startswith('/Game/Characters/Lune/Chic/MI_Chic') and s0.startswith('/Game/Characters/ZWGREY3/Body/MI_Bikini_Mod'), (s0, s2))
    check('  the live log says what filled each slot', "mat1 empty (the mod's mesh has no material for slot body)" in live
          and "(the body's skin material)" in live, [x for x in live.splitlines() if 'empty' in x][:3])
    W.setWear('G3/main', False)
    G.settle()
    check('  Wear off: Chic with its own texture again', mesh() == CHIC and tex() == TEX_VANILLA, (mesh(), tex()))
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # PC 17 Oct: the body's skin material belonged to another character (Sciel's Chic is a Lune
    # mesh), none of the mod's textures fit it, and the body showed the wrong skin tone
    tmp, mod, L, G, W, mesh, tex = run('')
    gi = [x.id for x in W.slots().values()].index('G6/main') + 1
    W.setVariant(gi, 1)
    G.settle()
    G.tickGT(40)
    body = L.eval('function() return ACTORS[1].Body end')()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    s1 = L.eval('''function(b, i)
        local m = b:GetMaterial(i)
        if not m then return "nil" end
        local base = (m._p.Parent and m._p.Parent._path) or m._path
        local tex
        local ok, arr = pcall(function() return m.TextureParameterValues end)
        if ok and arr then arr:ForEach(function(_, e) tex = e:get().ParameterValue._path end) end
        return base .. " | " .. tostring(tex) end''')(body, 1)
    check('an empty slot gets the skin material of the game\'s own mesh when the mod\'s textures fit it '
          '(not the body\'s, which none fit)',
          mesh().startswith('/Game/Characters/ZWGREY6/') and s1.startswith('/Game/Characters/Lune/Body/MI_Body_Other')
          and s1.endswith('/Game/Characters/ZWGREY6/Body/body_other_D-alt.body_other_D-alt')
          and "(the skin material of the game's own SK_Lune_Bikini_G_Skin)" in live,
          (mesh(), s1, [x for x in live.splitlines() if 'empty' in x][:2]))
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- rules chosen in the app (fixes.json): they win over the menu's own guesses
    tmp, mod, L, G, W, mesh, tex = run('')
    ids = [x.id for x in W.slots().values()]
    W.setVariant(ids.index('G4/main') + 1, 1)
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a texture rule fills the empty link with the chosen texture, not the menu\'s guess (T_Chic_D-mod)',
          mesh().startswith('/Game/Characters/ZWGREY4/') and tex() == '/Game/Characters/ZWGREY4/Body/T_Picked.T_Picked'
          and '(your choice)' in live, (mesh(), tex()))
    check('  the fill line names the variant, the material\'s original path and the parameter for the app',
          '{fix:tex|G4/a|/game/characters/lune/bikini/mi_body_mod4|BaseColor}' in live,
          [x for x in live.splitlines() if 'fix:tex' in x][:2])
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    tmp, mod, L, G, W, mesh, tex = run('')
    ids = [x.id for x in W.slots().values()]
    W.setVariant(ids.index('G5/main') + 1, 1)
    G.settle()
    G.tickGT(40)
    body = L.eval('function() return ACTORS[1].Body end')()
    slot = L.eval('function(b, i) local m = b:GetMaterial(i); if not m then return "nil" end; return (m._p.Parent and m._p.Parent._path) or m._path end')
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a material rule "hide" puts Hide_Material in that empty slot; a rule naming a texture is ignored and that slot gets the skin',
          slot(body, 1) == '/Game/Materials/Hide_Material.Hide_Material' and slot(body, 2).startswith('/Game/Characters/Lune/Chic/MI_Chic'),
          (slot(body, 1), slot(body, 2)))
    check('  the slot lines carry the variant, the mesh\'s original path, slot index and name',
          '{fix:mat|G5/a|/game/characters/lune/customization/skin/sk_lune_bikini_f_skin|1|body}' in live
          and '{fix:mat|G5/a|/game/characters/lune/customization/skin/sk_lune_bikini_f_skin|2|extra}' in live,
          [x for x in live.splitlines() if 'fix:mat' in x][:3])
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # ---- an outfit built on someone else's skin textures, plus a skin mod (a base body with the
    # body's textures and nothing else). Nexus comment, Nov 2026: "either the skin texture or the
    # outfit". PC 17 Oct: the skin mod showed 0 of 3 pieces under an outfit, then Auto Wear put its
    # bare body on in place of the outfit.
    tmp, mod, L, G, W, mesh, tex = run('')                       # Auto Wear on, as players have it
    sl = list(W.slots().values())
    ids = [x.id for x in sl]
    xi, yi = ids.index('X/main') + 1, ids.index('Y/main') + 1
    W.setVariant(xi, 1)                                          # the outfit, made for Chic
    G.settle()
    G.tickGT(40)
    check('(an outfit without a body texture of its own shows the game\'s)',
          mesh().startswith('/Game/Characters/ZWCOMP/') and tex() == BODY_GAME, (mesh(), tex()))
    W.setVariant(yi, 1)                                          # the skin mod
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a skin mod picked with a mod outfit gives the outfit its skin texture',
          mesh().startswith('/Game/Characters/ZWCOMP/') and tex() == BODY_SKIN, (mesh(), tex()))
    check('  Auto Wear leaves the outfit on (the skin mod is in use under it), and the log says so',
          not W.isWear('Y/main') and 'skin under outfit: Skin Light: Lune shows under what Lune wears' in live
          and "Auto Wear: Skin Light: Lune doesn't fit" not in live, [x for x in live.splitlines() if 'Wear' in x][-3:])
    check('  the menu: on, shown as the skin under the outfit, its own mesh not shown (Wear stays possible)',
          W.slotState(yi) == 'on' and W.asSkin(sl[yi - 1]) is True and W.meshShown(sl[yi - 1]) is False
          and W.meshShown(sl[xi - 1]) is True and not W.asSkin(sl[xi - 1]),
          (W.slotState(yi), W.asSkin(sl[yi - 1]), W.meshShown(sl[yi - 1]), W.meshShown(sl[xi - 1])))
    W.setWear('Y/main', True)
    G.settle()
    check('  Wear still puts the skin mod\'s own body on in place of the outfit',
          mesh().startswith('/Game/Characters/ZWSKIN/') and tex() == BODY_SKIN and not W.asSkin(sl[yi - 1]), (mesh(), tex()))
    W.setWear('Y/main', False)
    G.settle()
    check('  Unwear: the outfit again, still with the skin mod\'s texture',
          mesh().startswith('/Game/Characters/ZWCOMP/') and tex() == BODY_SKIN, (mesh(), tex()))
    W.setVariant(xi, 0)                                          # the outfit off: Lune wears the game's Chic
    G.settle()
    G.tickGT(40)
    check('  the outfit off: the game\'s Chic again, and the skin mod is not worn over it by itself',
          mesh() == CHIC and tex() == TEX_VANILLA and not W.isWear('Y/main') and not W.asSkin(sl[yi - 1]), (mesh(), tex()))
    shutil.rmtree(tmp, ignore_errors=True)
    # the other order, and an outfit that brings its own body texture (PC session 7): it keeps it,
    # the skin mod lends nothing, so Auto Wear puts the skin mod's body on as before
    tmp, mod, L, G, W, mesh, tex = run('')
    sl = list(W.slots().values())
    ids = [x.id for x in sl]
    xi, yi, wi = (ids.index(k) + 1 for k in ('X/main', 'Y/main', 'W/main'))
    W.setVariant(yi, 1)                                          # the skin mod first: Lune wears Chic
    G.settle()
    G.tickGT(40)
    check('a skin mod picked while the game\'s outfit is worn: Auto Wear puts its body on, as before',
          W.isWear('Y/main') and mesh().startswith('/Game/Characters/ZWSKIN/'), mesh())
    W.setWear('Y/main', False)
    G.settle()
    W.setVariant(xi, 1)                                          # then the outfit
    G.settle()
    G.tickGT(40)
    check('  Unwear, then the mod outfit picked: the outfit with the skin mod\'s texture, nothing worn over it',
          mesh().startswith('/Game/Characters/ZWCOMP/') and tex() == BODY_SKIN and not W.isWear('Y/main')
          and not W.isWear('X/main'), (mesh(), tex()))
    W.setVariant(xi, 0)
    W.setVariant(yi, 0)
    G.settle()
    W.setVariant(wi, 1)                                          # an outfit with its own body texture
    G.settle()
    own = (mesh(), tex())
    W.setVariant(yi, 1)
    G.settle()
    G.tickGT(40)
    check('an outfit that brings its own body texture keeps it, and the skin mod, lending nothing, is worn instead',
          own[0].startswith('/Game/Characters/ZWCOMP/') and own[1] == BODY_OWN and W.isWear('Y/main')
          and not W.asSkin(sl[yi - 1]) and mesh().startswith('/Game/Characters/ZWSKIN/'),
          (own, W.isWear('Y/main'), mesh(), tex()))
    shutil.rmtree(tmp, ignore_errors=True)
    # a costume built on the base body (PC library: one brings Lune_Belt_* next to Lune_Body_*) is an
    # outfit, not a skin mod: its body texture stays off the outfit worn, and Auto Wear puts it on
    tmp, mod, L, G, W, mesh, tex = run('')
    sl = list(W.slots().values())
    ids = [x.id for x in sl]
    xi, ci = ids.index('X/main') + 1, ids.index('C2/main') + 1
    W.setVariant(xi, 1)
    G.settle()
    G.tickGT(40)
    W.setVariant(ci, 1)
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a costume for the base body that also brings other textures is worn in place of the outfit, as before',
          W.isWear('C2/main') and mesh().startswith('/Game/Characters/ZWLIGHT/') and 'skin under outfit' not in live
          and "Auto Wear: Cat: Lune costume doesn't fit" in live, (W.isWear('C2/main'), mesh()))
    shutil.rmtree(tmp, ignore_errors=True)
    # the game's own outfits take a skin mod's textures too ("skin_under", on by default: what the
    # skin mod does when installed as a replacer); an outfit made for another outfit lends nothing
    BODY_MAT = 'function() ACTORS[1].Body:SetMaterial(0, get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune")) end'
    tmp, mod, L, G, W, mesh, tex = run('')
    sl = list(W.slots().values())
    ids = [x.id for x in sl]
    xi, yi, si = (ids.index(k) + 1 for k in ('X/main', 'Y/main', 'S/main'))
    W.setVariant(xi, 1)
    G.settle()
    W.setVariant(si, 1)                                          # an outfit made for the Bikini outfit
    G.settle()
    W.setWear('S/main', False)                                   # (Auto Wear put it on: take it off again)
    G.settle()
    check('an outfit made for another outfit lends nothing to the outfit worn (only a skin mod does)',
          mesh().startswith('/Game/Characters/ZWCOMP/') and tex() == BODY_GAME and W.slotState(si) == 'unused',
          (mesh(), tex(), W.slotState(si)))
    W.setVariant(si, 0)
    W.setVariant(xi, 0)
    G.settle()
    L.eval(BODY_MAT)()                                           # the game's Chic, showing the body's skin material
    W.setVariant(yi, 1)                                          # the skin mod
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a skin mod picked while the game\'s own outfit is worn: its texture goes under that outfit',
          mesh() == CHIC and tex() == BODY_SKIN and W.slotState(yi) == 'on', (mesh(), tex(), W.slotState(yi)))
    check('  Auto Wear leaves the outfit on; Wear stays possible',
          not W.isWear('Y/main') and W.asSkin(sl[yi - 1]) is True and W.meshShown(sl[yi - 1]) is False
          and 'skin under outfit: Skin Light: Lune shows under what Lune wears' in live,
          (W.isWear('Y/main'), W.asSkin(sl[yi - 1]), W.meshShown(sl[yi - 1])))
    W.setWear('Y/main', True)
    G.settle()
    check('  Wear: the skin mod\'s own body in place of the game\'s outfit', mesh().startswith('/Game/Characters/ZWSKIN/')
          and not W.asSkin(sl[yi - 1]), mesh())
    W.setWear('Y/main', False)
    G.settle()
    W.setVariant(yi, 0)
    G.settle()
    check('  the skin mod off: the game\'s body texture again', mesh() == CHIC and tex() == BODY_GAME, (mesh(), tex()))
    shutil.rmtree(tmp, ignore_errors=True)
    # a skin mod whose own mesh is the outfit worn (the game's base body): it shows as itself, and
    # is not called "the skin under the outfit"
    tmp, mod, L, G, W, mesh, tex = run('')
    sl = list(W.slots().values())
    yi = [x.id for x in sl].index('Y/main') + 1
    L.execute('ACTORS[1].Body._mesh = get("/Game/Characters/Lune/Body/SK_Lune_Placeholder.SK_Lune_Placeholder")')
    W.setVariant(yi, 1)
    G.settle()
    G.tickGT(40)
    check('a skin mod made for the outfit worn (the base body): its own body shows, not "skin under outfit"',
          mesh().startswith('/Game/Characters/ZWSKIN/') and W.meshShown(sl[yi - 1]) is True
          and not W.asSkin(sl[yi - 1]) and not W.isWear('Y/main'),
          (mesh(), W.meshShown(sl[yi - 1]), W.asSkin(sl[yi - 1]), W.isWear('Y/main')))
    shutil.rmtree(tmp, ignore_errors=True)
    # skin_under = false (settings.txt, or Settings > Skin mods): as 1.3.1, a skin mod gives nothing to
    # any outfit and Auto Wear puts its own body on
    tmp, mod, L, G, W, mesh, tex = run('skin_under = false\nauto_wear = false\n')
    sl = list(W.slots().values())
    ids = [x.id for x in sl]
    xi, yi = ids.index('X/main') + 1, ids.index('Y/main') + 1
    W.setVariant(xi, 1)
    G.settle()
    W.setVariant(yi, 1)
    G.settle()
    check('skin_under off: a skin mod gives nothing to the mod outfit worn',
          mesh().startswith('/Game/Characters/ZWCOMP/') and tex() == BODY_GAME and W.slotState(yi) == 'unused'
          and not W.asSkin(sl[yi - 1]), (mesh(), tex(), W.slotState(yi)))
    W.setVariant(xi, 0)
    G.settle()
    L.eval(BODY_MAT)()
    G.settle()
    W.setVariant(yi, 0)
    W.setVariant(yi, 1)
    G.settle()
    check('  nor to the game\'s own outfit', mesh() == CHIC and tex() == BODY_GAME and W.slotState(yi) == 'unused',
          (mesh(), tex(), W.slotState(yi)))
    shutil.rmtree(tmp, ignore_errors=True)
    tmp, mod, L, G, W, mesh, tex = run('skin_under = false\n')   # Auto Wear on
    ids = [x.id for x in W.slots().values()]
    W.setVariant(ids.index('X/main') + 1, 1)
    G.settle()
    G.tickGT(40)
    W.setVariant(ids.index('Y/main') + 1, 1)
    G.settle()
    G.tickGT(40)
    check('  and Auto Wear puts the skin mod\'s own body on in place of the outfit, as 1.3.1 did',
          W.isWear('Y/main') and mesh().startswith('/Game/Characters/ZWSKIN/'), (W.isWear('Y/main'), mesh()))
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- PC 17 Nov: "after a modded outfit was removed the default outfit didn't look correct, and
    # Fix look and All off didn't fix it". Fix look had dropped every body's Wear record (what the
    # game had on it under the worn mesh), also of characters the game did not re-dress.
    SLOT0 = 'function() local m = ACTORS[1].Body:GetMaterial(0); return (m._p.Parent and m._p.Parent._path) or m._path end'
    tmp, mod, L, G, W, mesh, tex = run('')
    li = [x.id for x in W.slots().values()].index('L/Body') + 1
    L.eval(BODY_MAT)()                                           # what the game has on the body: its skin material
    W.setVariant(li, 1)                                          # worn in place of Chic (Auto Wear)
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('Wear notes what the game had on each slot of the body (for the log)',
          mesh().startswith('/Game/Characters/ZWLIGHT/')
          and 'under it: SK_Lune_Chic, 1 slot(s) (* = a dynamic instance): 0 body=MI_Body_Lune' in live
          and 'wears: Lune SK_Lune_Placeholder (worn over SK_Lune_Chic)' in live,
          [x for x in live.splitlines() if 'under it' in x or 'wears:' in x][-2:])
    G.assignHook('Lune')
    W.fixLook()
    G.settle()
    W.setWear('L/Body', False)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('Fix look keeps the Wear records: Unwear after it still goes back to the outfit and what the game had on it',
          mesh() == CHIC and L.eval(SLOT0)() == '/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune'
          and 'Fix look: 1 Wear record(s) kept' in live and '1 material(s) the game had on it are back' in live
          and 'now: SK_Lune_Chic, 1 slot(s) (* = a dynamic instance): 0 body=MI_Body_Lune' in live,
          (mesh(), L.eval(SLOT0)(), [x for x in live.splitlines() if 'Wear record' in x or 'now:' in x]))
    shutil.rmtree(tmp, ignore_errors=True)

    # one body component, two characters (the walking character): each has its own record
    tmp, mod, L, G, W, mesh, tex = run('auto_wear = false\n')
    ids = [x.id for x in W.slots().values()]
    li, zi = ids.index('L/Body') + 1, ids.index('Z/main') + 1
    G.PARTY()
    W.setVariant(li, 1)
    W.setWear('L/Body', True)                                    # Lune leads: a costume over Chic
    G.settle()
    G.LEAD(G.SCIEL, '/Game/Characters/Sciel/Base/SK_Sciel_Base.SK_Sciel_Base')
    W.setVariant(zi, 1)
    W.setWear('Z/main', True)                                    # Sciel leads: an outfit over her own
    G.settle()
    worn_s = mesh()
    G.LEAD(G.LUNE, '/Game/Characters/ZWLIGHT/Body/SK_Lune_Placeholder.SK_Lune_Placeholder')   # as the mod left it
    W.applyAll('test')
    G.settle()
    W.setWear('L/Body', False)
    G.settle()
    check('a body shared by the party: Lune\'s Unwear goes back to Lune\'s outfit, not to the last leader\'s',
          worn_s.startswith('/Game/Characters/ZWZ/') and mesh() == CHIC, (worn_s, mesh()))
    G.LEAD(G.SCIEL, '/Game/Characters/ZWZ/Skin/SK_Sciel_Worn.SK_Sciel_Worn')
    W.applyAll('test')
    G.settle()
    W.setWear('Z/main', False)
    G.settle()
    check('  and Sciel\'s to Sciel\'s', mesh() == '/Game/Characters/Sciel/Base/SK_Sciel_Base.SK_Sciel_Base', mesh())
    shutil.rmtree(tmp, ignore_errors=True)

    # Unwear with the record intact: a slot the game ships without a material is empty again
    BASE_SLOTS = ('/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune | '
                  '/Game/Characters/Lune/Base/MI_Base_Coat.MI_Base_Coat | empty')
    tmp, mod, L, G, W, mesh, tex = run('')
    gi = [x.id for x in W.slots().values()].index('G3/main') + 1
    G.BASE_OUTFIT()
    W.setVariant(gi, 1)                                          # worn; its two empty slots get the skin material
    G.settle()
    G.tickGT(40)
    worn3 = G.SLOTS3()
    W.setWear('G3/main', False)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('Unwear: the game\'s materials are back and its empty slot is empty again (not what the worn mesh had there)',
          worn3.count('instance of /Game/Characters/Lune/Body/MI_Body_Lune') == 2 and G.SLOTS3() == BASE_SLOTS
          and mesh().endswith('SK_Lune_Base.SK_Lune_Base'), (worn3, G.SLOTS3()))
    check('  nothing is "filled" on the game\'s own mesh (its empty slots are how the game ships it)',
          "the mod's mesh has no material for slot lambert1" not in live, [x for x in live.splitlines() if 'lambert1' in x])
    # ... and with the record gone (here: the component was renamed, as on a reused address): the
    # outfit's own mesh from its Blueprint, and its own materials, not the worn mesh's leftovers
    W.setWear('G3/main', True)
    G.settle()
    L.execute('ACTORS[1].Body._path = "/Game/Map.Actor.Body_renamed"')
    W.setWear('G3/main', False)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('Unwear without a record: back to the outfit\'s own mesh with its own materials',
          mesh().endswith('SK_Lune_Base.SK_Lune_Base') and G.SLOTS3() == BASE_SLOTS
          and "back to this outfit's own mesh (a worn mesh was left on it)" in live
          and "materials: the outfit's own again (3 slot(s); 0 set by its Blueprint, 0 the game's own instances)" in live,
          (mesh(), G.SLOTS3(), [x for x in live.splitlines() if 'own again' in x]))
    W.dump()
    G.settle()
    dtxt = open(os.path.join(mod, 'dump.txt'), encoding='utf-8').read()
    check('  dump.txt names the outfit\'s own body from its Blueprint, the component and its Wear record',
          "outfit's own body (its Blueprint): mesh=/Game/Characters/Lune/Base/SK_Lune_Base; materials it sets: none" in dtxt
          and 'component=/Game/Map.Actor.Body_renamed' in dtxt and 'Wear record: none' in dtxt,
          [x for x in dtxt.splitlines() if 'own body' in x or 'Wear record' in x or 'component=' in x][:4])
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- PC 17 Nov: "some outfits still say missing pieces". A piece nothing on its character uses
    # can't show: it is left out of the count (here: a costume's body and belt textures; the body
    # shows neither). Another character using the belt texture doesn't make it Lune's.
    tmp, mod, L, G, W, mesh, tex = run('')
    ci = [x.id for x in W.slots().values()].index('C2/main') + 1
    G.ADD_SCIEL_BELTED()
    L.execute(r'''
      -- an NPC (no character) whose body uses the body texture the costume also brings
      asset("SkeletalMesh", "/Game/Characters/NPCs/SK_NPC_Woman", "SK_NPC_Woman",
        { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune") } }) })
      local b = meshComp("Body", get("/Game/Characters/NPCs/SK_NPC_Woman.SK_NPC_Woman"))
      b._path = "/Game/Map.PersistentLevel.Bp_Cine_NPC_C_2.Body"
      local npc = new("Bp_Cine_NPC_C", "/Game/Map.PersistentLevel.Bp_Cine_NPC_C_2", {},
        { K2_GetComponentsByClass = function() return TArray({ b }) end })
      npc._class = new("BlueprintGeneratedClass", "/Game/Characters/NPCs/Bp_Cine_NPC.Bp_Cine_NPC_C")
      npc._class._super = { GetFName = function() return { ToString = function() return "BP_CineCharacter_Main_C" end } end,
                            IsValid = function() return true end, GetSuperStruct = function() return nil end }
      npc._skin = "BP_CineCharacter_Main_C"
      table.insert(ACTORS, npc)
    ''')
    W.setVariant(ci, 1)                                          # worn in place of Chic (Auto Wear)
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    ln = [x for x in live.splitlines() if 'on screen: Cat: Lune costume' in x]
    sh = W.slotShown('C2/main')
    check('pieces nothing on the character uses are not counted as missing: 1/1, not 1/3 (also when another '
          'character, or an NPC, uses one of them)',
          mesh().startswith('/Game/Characters/ZWLIGHT/') and sh.shown == 1 and sh.total == 1
          and ln and ': 1/1 asset(s); 2 not used by anything on screen, not counted (' in ln[-1]
          and 'not shown:' not in ln[-1], (sh.shown, sh.total, ln[-1:]))
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- PC 17 Nov (game running): the game moves the walking character's Body between the party
    # pawn and the outfit actors, so the component's full path changes with its owner. That is the
    # same object: its Wear record stays (it was dropped as "address reused").
    tmp, mod, L, G, W, mesh, tex = run('')
    li = [x.id for x in W.slots().values()].index('L/Body') + 1
    L.eval(BODY_MAT)()
    W.setVariant(li, 1)                                          # worn in place of Chic (Auto Wear)
    G.settle()
    G.tickGT(40)
    L.execute('ACTORS[1].Body._path = "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_7.Body"')
    W.applyAll('test')
    G.settle()
    L.execute('ACTORS[1].Body._path = "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_1.Body"')
    W.setWear('L/Body', False)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a body moved to another owner and back keeps its Wear record: Unwear restores what the game had on it',
          mesh() == CHIC and L.eval(SLOT0)() == '/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune'
          and '1 material(s) the game had on it are back' in live and "back to this outfit's own mesh" not in live,
          (mesh(), L.eval(SLOT0)(), [x for x in live.splitlines() if 'back' in x][-3:]))
    shutil.rmtree(tmp, ignore_errors=True)

    # an NPC whose body shows an NPC mesh is no party member, even if it carries a party member's
    # weapon (PC 17 Nov: cutscene expeditioners with Gustave's weapon were listed as Gustave)
    tmp, mod, L, G, W, mesh, tex = run('')
    L.execute(r"""
      asset("SkeletalMesh", "/Game/Characters/NPCs/SK_NPC_Male_A", "SK_NPC_Male_A",
        { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })
      asset("StaticMesh", "/Game/Characters/Gustave/Weapons/SM_Gustave_Weapon_Handle", "SM_Gustave_Weapon_Handle", {})
      local b = meshComp("Body", get("/Game/Characters/NPCs/SK_NPC_Male_A.SK_NPC_Male_A"))
      b._path = "/Game/Map.PersistentLevel.Bp_Cine_NPC_C_1.Body"
      local w = new("StaticMeshComponent", "/Game/Map.PersistentLevel.Bp_Cine_NPC_C_1.Weapon_R_SM_Handle",
        { StaticMesh = get("/Game/Characters/Gustave/Weapons/SM_Gustave_Weapon_Handle.SM_Gustave_Weapon_Handle") })
      local npc = new("Bp_Cine_NPC_C", "/Game/Map.PersistentLevel.Bp_Cine_NPC_C_1", {},
        { K2_GetComponentsByClass = function() return TArray({ b, w }) end })
      npc._class = new("BlueprintGeneratedClass", "/Game/Characters/NPCs/Bp_Cine_NPC.Bp_Cine_NPC_C")
      npc._class._super = { GetFName = function() return { ToString = function() return "BP_CineCharacter_Main_C" end } end,
                            IsValid = function() return true end, GetSuperStruct = function() return nil end }
      npc._skin = "BP_CineCharacter_Main_C"
      table.insert(ACTORS, npc)
    """)
    W.applyAll('test')
    G.settle()
    chars = list(W.loadedChars().values())
    check('an NPC with a party member\'s weapon is not taken for that member', 'Gustave' not in chars
          and 'Lune' in chars, chars)
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- PC 17 Nov evening, with "game dresses (B)" on: the game spawned the variant's own
    # relocated Blueprint, whose own mesh is the mod's mesh. With the pick off, the mod "changed"
    # the mesh to the same mesh and reset the materials, and would on every pass.
    tmp, mod, L, G, W, mesh, tex = run('')
    L.execute(r"""
      local c = new("BlueprintGeneratedClass", "/Game/Characters/ZWB/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C")
      c._super = ACTORS[1]._class._super
      ACTORS[1]._class = c
      local t = meshComp("Body_GEN_VARIABLE", get("/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      t._p.OverrideMaterials = TArray({})
      REGSET("/Game/Characters/ZWB/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C:Body_GEN_VARIABLE", t)
      ACTORS[1].Body._mesh = get("/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic")
    """)
    W.applyAll('test')
    G.settle()
    W.applyAll('again')
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    again = [x for x in live.splitlines() if 'pass (again)' in x]
    check('an outfit actor that is the variant\'s own Blueprint, pick off: no "back to its own mesh" with the same '
          'mesh; the game\'s version of the mesh shows, and the next pass changes nothing',
          "back to this outfit's own mesh" not in live and mesh() == CHIC
          and "(variant off: the game's own)" in live and again and ': 0 change(s)' in again[0],
          (mesh(), [x for x in live.splitlines() if 'mesh /' in x][:3], again))
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- PC 17 Nov evening (all-options run): on a hidden outfit actor the game freed its own
    # material instances while a mesh was worn over them, and Unwear put the plain materials back
    # ("0 material(s) the game had on it are back"). The instance is rebuilt from the record.
    tmp, mod, L, G, W, mesh, tex = run('')
    li = [x.id for x in W.slots().values()].index('L/Body') + 1
    L.execute('GAMEMID = ACTORS[1].Body:CreateDynamicMaterialInstance(0, '
              'get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune"), FName("None"))')
    W.setVariant(li, 1)                                          # worn in place of Chic (Auto Wear)
    G.settle()
    G.tickGT(40)
    L.execute('GAMEMID._path = GAMEMID._path .. "_freed"')       # another object at that address now
    W.setWear('L/Body', False)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    m0 = L.eval('function() local m = ACTORS[1].Body:GetMaterial(0); '
                'return m ~= GAMEMID and m._p.Parent ~= nil and m._p.Parent._path end')()
    check('a game instance freed while a mesh was worn: Unwear rebuilds it (same parent), not the plain material',
          mesh() == CHIC and m0 == '/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune'
          and '0 material(s) the game had on it are back, 1 rebuilt (the game had freed them)' in live,
          (mesh(), m0, [x for x in live.splitlines() if 'are back' in x][-1:]))
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- PC 17 Nov, all-options run: an option that brings the outfit's own Blueprint, whose Body
    # uses another of the game's meshes and sets the option's own material. On: the option's
    # material was replaced by the new mesh's default. Off: the mesh stayed.
    tmp, mod, L, G, W, mesh, tex = run('')
    L.execute(r"""
      asset("BlueprintGeneratedClass", "/Game/Characters/ZWBPFIX/BP_Lune_Skin_Chic", "BP_Lune_Skin_Chic_C", {})
      asset("MaterialInstanceConstant", "/Game/Characters/ZWBPFIX/MI_Base_Coat", "MI_Base_Coat", { TextureParameterValues = TArray({}) })
      local own = meshComp("Body_GEN_VARIABLE", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      own._p.OverrideMaterials = TArray({})
      REGSET("/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C:Body_GEN_VARIABLE", own)
      local fix = meshComp("Body_GEN_VARIABLE", get("/Game/Characters/Lune/Base/SK_Lune_Base.SK_Lune_Base"))
      fix._p.OverrideMaterials = TArray({ get("/Game/Characters/ZWBPFIX/MI_Base_Coat.MI_Base_Coat") })
      REGSET("/Game/Characters/ZWBPFIX/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C:Body_GEN_VARIABLE", fix)
    """)
    pi = [x.id for x in W.slots().values()].index('P/main') + 1
    S0 = 'function() local m = ACTORS[1].Body:GetMaterial(0); return (m._p.Parent and m._p.Parent._path) or m._path end'
    W.setVariant(pi, 1)
    G.settle()
    on = (mesh(), L.eval(S0)())
    W.setVariant(pi, 0)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('an option\'s outfit Blueprint: its body mesh, with the material its Blueprint sets (not the mesh\'s default)',
          on == ('/Game/Characters/Lune/Base/SK_Lune_Base.SK_Lune_Base',
                 '/Game/Characters/ZWBPFIX/MI_Base_Coat.MI_Base_Coat'), on)
    check('  switched off: the outfit\'s own body and material again',
          mesh() == CHIC and L.eval(S0)() == '/Game/Characters/Lune/Chic/MI_Chic.MI_Chic'
          and "the option's outfit Blueprint is off: back to this outfit's own part" in live,
          (mesh(), L.eval(S0)(), [x for x in live.splitlines() if 'Blueprint' in x][-2:]))
    W.applyAll('again')
    G.settle()
    again = [x for x in open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read().splitlines() if 'pass (again)' in x]
    check('  and the next pass changes nothing', again and ': 0 change(s)' in again[0], again)
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- all-options run, 17 Nov: a mod mesh with empty slots, made for the outfit worn; the mod
    # fills its empty slots. Switched off, the game's mesh came back but kept the fill on a slot the
    # game ships empty (Sciel's own outfit kept a skin material on slot 8).
    tmp, mod, L, G, W, mesh, tex = run('auto_wear = false\n')
    L.execute(r"""
      asset("SkeletalMesh", "/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_D_Skin", "SK_Lune_Bikini_D_Skin",
        { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"), MaterialSlotName = FName("Bikini") },
                               { MaterialInterface = get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune"), MaterialSlotName = FName("Body") },
                               { MaterialSlotName = FName("Extra") } }) })
      ACTORS[1].Body._mesh = get("/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_D_Skin.SK_Lune_Bikini_D_Skin")
    """)
    gi = [x.id for x in W.slots().values()].index('G3/main') + 1
    S2 = 'function() return ACTORS[1].Body:GetMaterial(2) ~= nil end'
    W.setVariant(gi, 1)
    G.settle()
    on = (mesh(), L.eval(S2)())
    W.setVariant(gi, 0)
    G.settle()
    check('a mod mesh\'s filled empty slot is cleared when the game\'s mesh (with that slot empty) comes back',
          on == ('/Game/Characters/ZWGREY3/Body/SK_Lune_Bikini_D_Skin.SK_Lune_Bikini_D_Skin', True)
          and mesh() == '/Game/Characters/Lune/Customization/Skin/SK_Lune_Bikini_D_Skin.SK_Lune_Bikini_D_Skin'
          and L.eval(S2)() is False, (on, mesh(), L.eval(S2)()))
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- all-options run, 17 Nov: an outfit worn over Chic (Wear), then a skin mod picked that
    # replaces the same game mesh (the base body). The skin mod's mesh took the worn one's place,
    # the Wear record was lost, and with everything off Lune stood in the game's base body.
    tmp, mod, L, G, W, mesh, tex = run('auto_wear = false\nwear = L/Body\n')
    ids = [x.id for x in W.slots().values()]
    li, yi = ids.index('L/Body') + 1, ids.index('Y/main') + 1
    L.eval(BODY_MAT)()
    W.setVariant(li, 1)                                          # worn in place of Chic (its Wear flag)
    G.settle()
    G.tickGT(40)
    W.setVariant(yi, 1)                                          # the skin mod: also a base body, not worn
    G.settle()
    G.tickGT(40)
    worn = mesh()
    W.setVariant(li, 0)
    G.settle()
    W.setVariant(yi, 0)
    G.settle()
    check('a worn mesh stays when another pick replaces the same game mesh, and all off gives the outfit back',
          worn.startswith('/Game/Characters/ZWLIGHT/') and mesh() == CHIC, (worn, mesh()))
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- rerun, 17 Nov (a skin mod for Sciel picked with Wear off, then off): the mod's version of the
    # game's mesh has a material on a slot the game ships empty, and the game made its own instance
    # of it there. With the game's mesh back that slot kept it; Fix look and all off didn't help.
    tmp, mod, L, G, W, mesh, tex = run('auto_wear = false\n')
    ei = [x.id for x in W.slots().values()].index('E/main') + 1
    G.BASE_OUTFIT()
    W.setVariant(ei, 1)
    G.settle()
    on = mesh()
    L.execute('ACTORS[1].Body:CreateDynamicMaterialInstance(2, get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"), FName("None"))')
    worn = G.SLOTS3()
    W.setVariant(ei, 0)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a mod\'s mesh off: a slot the game\'s mesh ships empty is empty again (the game had made an instance there)',
          on.startswith('/Game/Characters/ZWEMPTY/') and worn.endswith('| instance of /Game/Characters/Lune/Chic/MI_Chic.MI_Chic')
          and mesh().endswith('/Lune/Base/SK_Lune_Base.SK_Lune_Base') and G.SLOTS3() == BASE_SLOTS
          and "mat2 /Game/Characters/Lune/Chic/MI_Chic -> empty (the game's mesh has no material for this slot)" in live,
          (on, worn, mesh(), G.SLOTS3(), [x for x in live.splitlines() if '-> empty' in x][-2:]))
    shutil.rmtree(tmp, ignore_errors=True)
    tmp, mod, L, G, W, mesh, tex = run('auto_wear = false\n')
    ei = [x.id for x in W.slots().values()].index('E/main') + 1
    G.BASE_OUTFIT()
    L.execute('ACTORS[1].Body:SetMaterial(2, get("/Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune"))')
    W.setVariant(ei, 1)
    G.settle()
    W.setVariant(ei, 0)
    G.settle()
    check('  a material the game itself put on that slot (not the mod\'s mesh\'s) stays',
          mesh().endswith('/Lune/Base/SK_Lune_Base.SK_Lune_Base')
          and G.SLOTS3().endswith('| /Game/Characters/Lune/Body/MI_Body_Lune.MI_Body_Lune'), (mesh(), G.SLOTS3()))
    shutil.rmtree(tmp, ignore_errors=True)
    # a leftover like that from an older build (or from anywhere): a pass leaves it, Fix look clears
    # it. A material the outfit's Blueprint sets on such a slot stays.
    tmp, mod, L, G, W, mesh, tex = run('')
    G.BASE_OUTFIT()
    L.execute('ACTORS[1].Body:SetMaterial(2, get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"))')
    W.applyAll('test')
    G.settle()
    kept = G.SLOTS3()
    # a cutscene NPC (no party character) on its own mesh, with a material on its empty slot
    L.execute(r'''
      asset("SkeletalMesh", "/Game/Characters/NPCs/SK_NPC_Two", "SK_NPC_Two",
        { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") },
                               { MaterialSlotName = FName("lambert1") } }) })
      local b = meshComp("Body", get("/Game/Characters/NPCs/SK_NPC_Two.SK_NPC_Two"))
      b._path = "/Game/Map.PersistentLevel.Bp_Cine_NPC_C_3.Body"
      b:SetMaterial(1, get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"))
      NPCBODY = b
      local npc = new("Bp_Cine_NPC_C", "/Game/Map.PersistentLevel.Bp_Cine_NPC_C_3", {},
        { K2_GetComponentsByClass = function() return TArray({ b }) end })
      npc._class = new("BlueprintGeneratedClass", "/Game/Characters/NPCs/Bp_Cine_NPC.Bp_Cine_NPC_C")
      npc._class._super = { GetFName = function() return { ToString = function() return "BP_CineCharacter_Main_C" end } end,
                            IsValid = function() return true end, GetSuperStruct = function() return nil end }
      npc._skin = "BP_CineCharacter_Main_C"
      table.insert(ACTORS, npc)
      -- and Lune's outfit actor gets a second part (its template is not needed by Fix look)
      asset("SkeletalMesh", "/Game/Characters/Lune/Hair/SK_Lune_Hair_A", "SK_Lune_Hair_A",
        { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })
      local lune = ACTORS[1]
      local hair = meshComp("Hair", get("/Game/Characters/Lune/Hair/SK_Lune_Hair_A.SK_Lune_Hair_A"))
      hair._path = lune._path .. ".Hair"
      lune._f.K2_GetComponentsByClass = function() return TArray({ lune.Body, hair }) end
      local sfo = StaticFindObject
      FINDS = {}
      StaticFindObject = function(p, ...) FINDS[#FINDS + 1] = tostring(p); return sfo(p, ...) end
    ''')
    G.assignHook('Lune')
    W.fixLook()
    G.settle()
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('Fix look: a leftover material on a slot the game\'s mesh ships empty comes off (a plain pass leaves it)',
          kept.endswith('| /Game/Characters/Lune/Chic/MI_Chic.MI_Chic') and G.SLOTS3() == BASE_SLOTS
          and 'pass (after Fix look)' in live
          and "-> empty (the game's mesh has no material for this slot; Fix look)" in live,
          (kept, G.SLOTS3(), [x for x in live.splitlines() if 'Fix look' in x][-3:]))
    finds = list(L.eval('function() local t = {}; for _, f in ipairs(FINDS) do t[#t + 1] = f end; return t end')().values())
    npc_finds = [f for f in finds if 'Bp_Cine_NPC_C:' in f]
    check('  a cutscene NPC is left alone: its slot keeps its material, and none of its class\'s parts is looked up '
          '(PC: 13 NPCs made the pass 458 ms)',
          L.eval('function() return NPCBODY:GetMaterial(1) ~= nil end')() is True and not npc_finds, npc_finds[:3])
    check('  and of Lune\'s outfit Blueprint only the Body is looked up, not her other parts',
          not [f for f in finds if 'BP_Lune_Skin_Chic_C:Hair' in f], [f for f in finds if ':' in f][:4])
    shutil.rmtree(tmp, ignore_errors=True)
    tmp, mod, L, G, W, mesh, tex = run('')
    G.BASE_OUTFIT()
    L.execute(r'''
      local t = meshComp("Body_GEN_VARIABLE", get("/Game/Characters/Lune/Base/SK_Lune_Base.SK_Lune_Base"))
      t._p.OverrideMaterials = TArray({ NULLOBJ(), NULLOBJ(), get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") })
      REGSET("/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C:Body_GEN_VARIABLE", t)
      ACTORS[1].Body:SetMaterial(2, get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"))
    ''')
    G.assignHook('Lune')
    W.fixLook()
    G.settle()
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('  a material the outfit\'s Blueprint sets on that slot stays',
          G.SLOTS3().endswith('| /Game/Characters/Lune/Chic/MI_Chic.MI_Chic') and 'pass (after Fix look)' in live,
          G.SLOTS3())
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- rerun, 17 Nov: an outfit option for the base body worn over Chic (Auto Wear), then a skin
    # mod (also a base body) picked: its texture goes under the worn outfit and its own body is left
    # off on purpose. It read "5/6, not shown: SK_Lune_Placeholder", as if a piece were missing.
    tmp, mod, L, G, W, mesh, tex = run('')
    ids = [x.id for x in W.slots().values()]
    qi, yi = ids.index('Q/main') + 1, ids.index('Y/main') + 1
    W.setVariant(qi, 1)
    G.settle()
    G.tickGT(40)
    W.setVariant(yi, 1)
    G.settle()
    G.tickGT(40)
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    ln = [x for x in live.splitlines() if 'on screen: Skin Light: Lune' in x]
    sh = W.slotShown('Y/main')
    check('a skin mod under a worn outfit for the same base body: its texture counts, its own body (left off) does not',
          W.isWear('Q/main') and not W.isWear('Y/main') and mesh().startswith('/Game/Characters/ZWOPT/')
          and tex() == BODY_SKIN and sh and sh.shown == 1 and sh.total == 1
          and ln and 'its own body left off (skin under the outfit), not counted' in ln[-1] and 'not shown' not in ln[-1],
          (W.isWear('Q/main'), W.isWear('Y/main'), mesh(), tex(), sh and (sh.shown, sh.total), ln[-1:]))
    shutil.rmtree(tmp, ignore_errors=True)
    # skin_under off: its body is not "left off on purpose" (Auto Wear would wear it; taken off by
    # hand here), so it counts as not shown. Its texture still shows: the outfit is made for the
    # same base body, as in 1.3.1.
    tmp, mod, L, G, W, mesh, tex = run('skin_under = false\n')
    ids = [x.id for x in W.slots().values()]
    W.setVariant(ids.index('Q/main') + 1, 1)
    G.settle()
    G.tickGT(40)
    W.setVariant(ids.index('Y/main') + 1, 1)
    G.settle()
    G.tickGT(40)
    W.setWear('Y/main', False)                                   # (Auto Wear put it on: take it off again)
    G.settle()
    live = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    ln = [x for x in live.splitlines() if 'on screen: Skin Light: Lune' in x]
    sh = W.slotShown('Y/main')
    check('  with skin_under off its body, taken off by hand, counts as not shown',
          mesh().startswith('/Game/Characters/ZWOPT/') and sh and sh.shown == 1 and sh.total == 2
          and ln and 'not shown: SK_Lune_Placeholder' in ln[-1] and 'left off' not in ln[-1],
          (mesh(), tex(), sh and (sh.shown, sh.total), ln[-1:]))
    shutil.rmtree(tmp, ignore_errors=True)

    # an old pick saved under the unsplit slot is carried over too
    tmp, mod, L, G, W, mesh, tex = run('', selection='K/main\tK/a\n')
    sel = open(os.path.join(mod, 'selection.txt'), encoding='utf-8').read()
    check('a pick saved under the old slot moves to each character\'s slot',
          'K/main@Lune\tK/a@Lune' in sel and 'K/main@Maelle\tK/a@Maelle' in sel and 'K/main\tK/a\n' not in sel, sel)
    base.av_check(check, RUNTIMES)
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
