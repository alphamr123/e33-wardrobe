-- Sciel skin copy showing SK_Sciel_Placeholder, Wear on for Sciel (forced relocated SK_Sciel_Chic_skin),
-- plus a cutscene Esquie pawn. Sizes are assumptions: Body 8 slots, MID -> MIC -> MIC -> Material,
-- 3 + 6 + 10 texture parameters per level, 30 scalars, 10 vectors.
local NTEX = { 3, 6, 10 }
local function tex(path) return new("Texture2D", "Texture2D", path .. "." .. path:match("[^/]+$")) end
local function texParams(prefix, n, dir)
  local items = {}
  for k = 1, n do
    local name = prefix .. "_P" .. k
    items[k] = struct("FTextureParameterValue", {
      ParameterInfo = struct("FMaterialParameterInfo", { Name = FNameQuiet(name), Association = 2, Index = -1 }),
      ParameterValue = tex(dir .. "/T_" .. name) })
  end
  return items
end
local function scalars(n)
  local items = {}
  for k = 1, n do items[k] = struct("FScalarParameterValue", { ParameterInfo = struct("FMaterialParameterInfo", { Name = FNameQuiet("S" .. k) }), ParameterValue = 0.5 }) end
  return items
end
local function vectors(n)
  local items = {}
  for k = 1, n do items[k] = struct("FVectorParameterValue", { ParameterInfo = struct("FMaterialParameterInfo", { Name = FNameQuiet("V" .. k) }), ParameterValue = { R = 1, G = 1, B = 1, A = 1 } }) end
  return items
end
MASTER = new("Material", "Material", "/Game/Materials/M_SkinMaster.M_SkinMaster")
local function mic(path, ntex, parent, texdir)
  local o = new("MaterialInstanceConstant", "MaterialInstanceConstant", path .. "." .. path:match("[^/]+$"), {
    TextureParameterValues = TArray("TextureParameterValues", texParams(path:match("[^/]+$"), ntex, texdir)),
    ScalarParameterValues = TArray("ScalarParameterValues", scalars(30)),
    VectorParameterValues = TArray("VectorParameterValues", vectors(10)),
    Parent = parent })
  REG[o._path] = o
  return o
end
local MIDN = 0
function makeMid(owner, parent)
  MIDN = MIDN + 1
  local texItems = parent and texParams("MID" .. MIDN, NTEX[1], "/Game/Characters/Heros/Sciel/Textures") or {}
  local m
  m = new("MaterialInstanceDynamic", "MaterialInstanceDynamic", owner .. ".MaterialInstanceDynamic_" .. MIDN, {
    TextureParameterValues = TArray("TextureParameterValues", texItems),
    ScalarParameterValues = TArray("ScalarParameterValues", scalars(30)),
    VectorParameterValues = TArray("VectorParameterValues", vectors(10)),
    Parent = parent }, {
    SetTextureParameterValue = function() end, SetTextureParameterValueByInfo = function() end,
    SetScalarParameterValue = function() end, SetVectorParameterValue = function() end })
  return m
end
local function skelMesh(full, mats, names)
  local items = {}
  for i = 1, #names do items[i] = struct("FSkeletalMaterial", { MaterialInterface = mats[i], MaterialSlotName = FNameQuiet(names[i]) }) end
  local sk = new("Skeleton", "Skeleton", "/Game/Characters/Heros/Sciel/SK_Sciel_Skeleton.SK_Sciel_Skeleton")
  return new("SkeletalMesh", "SkeletalMesh", full, { Materials = TArray("Materials", items), Skeleton = sk })
end
local SLOTN = { "body", "skin_legs", "top", "skirt", "shoes", "gloves", "belt", "jewels" }
-- vanilla placeholder body: 8 slots of vanilla MICs
local vmats = {}
for i = 1, 8 do
  local base = mic("/Game/Characters/Heros/Sciel/Materials/MI_Sciel_Base" .. i, NTEX[3], MASTER, "/Game/Characters/Heros/Sciel/Textures")
  vmats[i] = mic("/Game/Characters/Heros/Sciel/Materials/MI_Sciel_" .. i, NTEX[2], base, "/Game/Characters/Heros/Sciel/Textures")
end
PLACEHOLDER = skelMesh("/Game/Characters/Heros/Sciel/SK_Sciel_Placeholder.SK_Sciel_Placeholder", vmats, SLOTN)
REG[PLACEHOLDER._path] = PLACEHOLDER
-- the relocated mod mesh: 6 mod MICs, 2 empty slots
local modmats = {}
for i = 1, 8 do
  if i ~= 2 and i ~= 3 then
    modmats[i] = mic("/Game/Characters/Heros/ZWAB12/Materials/MI_Chic_" .. i, 8, MASTER, "/Game/Characters/Heros/ZWAB12/Textures")
  end
end
LOADABLE["/Game/Characters/Heros/ZWAB12/Customization/Skin/SK_Sciel_Chic_skin.SK_Sciel_Chic_skin"] = function()
  return skelMesh("/Game/Characters/Heros/ZWAB12/Customization/Skin/SK_Sciel_Chic_skin.SK_Sciel_Chic_skin", modmats, SLOTN)
end
ANIMCLS = new("AnimBlueprintGeneratedClass", "AnimBlueprintGeneratedClass", "/Game/Characters/Heros/Sciel/ABP_Sciel.ABP_Sciel_C")

function skelComp(owner, name, mesh, midSlots)
  local over = {}
  local c
  c = new("SkeletalMeshComponent", "SkeletalMeshComponent", owner .. "." .. name, { AnimClass = ANIMCLS }, {
    GetSkeletalMeshAsset = function(self) return self._mesh end,
    SetSkeletalMeshAsset = function(self, m) self._mesh = m end,
    SetSkinnedAssetAndUpdate = function(self, m) self._mesh = m end,
    GetNumMaterials = function(self) return #self._mesh._p.Materials._items end,
    GetMaterial = function(self, i)
      if over[i] then return over[i] end
      local e = self._mesh._p.Materials._items[i + 1]
      return e and rawget(e, "_raw").MaterialInterface or nil
    end,
    SetMaterial = function(self, i, m) over[i] = m or false end,
    CreateDynamicMaterialInstance = function(self, i, parent) local m = makeMid(owner .. "." .. name, parent) over[i] = m return m end,
    GetOwner = function() return OWNERS[c] end })
  c._mesh = mesh
  if midSlots then for i = 0, midSlots - 1 do over[i] = makeMid(owner .. "." .. name, mesh._p.Materials._items[i + 1] and vmats[i + 1]) end end
  c._over = over
  return c
end
OWNERS = {}
local PROPTYPE = {}
local function propDef(name, ty)
  PROPTYPE[ty] = PROPTYPE[ty] or new("Class", "Class", "/Script/CoreUObject." .. ty)
  local pr = new("Property", ty, "/Script/X.Prop:" .. name)
  pr._class = PROPTYPE[ty]
  return pr
end
local function cls(path, super, props)
  local c = new("BlueprintGeneratedClass", "BlueprintGeneratedClass", path)
  c._super = super
  c._plist = {}
  for _, p in ipairs(props or {}) do c._plist[#c._plist + 1] = propDef(p[1], p[2]) end
  return c
end
local actorCls = cls("/Script/Engine.Actor", nil)
local pawnCls = cls("/Script/Engine.Pawn", actorCls)
local charCls = cls("/Script/Engine.Character", pawnCls)
local skinBase = cls("/Game/Characters/BP_CharacterSkinBase.BP_CharacterSkinBase_C", actorCls)
SCIEL_CLS = cls("/Game/Characters/Heros/Sciel/Customization/Skin/BP_CharacterSkinBase_Sciel.BP_CharacterSkinBase_Sciel_C", skinBase,
  { { "Body", "ObjectProperty" }, { "bHidden", "BoolProperty" } })
local cineBase = cls("/Game/Cinematics/BP_CineCharacter_Main.BP_CineCharacter_Main_C", charCls)
ESQ_CLS = cls("/Game/Cinematics/Esquie/BP_Cine_Esquie.BP_Cine_Esquie_C", cineBase,
  { { "BP_CinematicCharacterSkinComponent", "ObjectProperty" }, { "Mesh", "ObjectProperty" }, { "BloodLevel", "FloatProperty" } })
local ownerCls = cls("/Game/Characters/BP_jRPG_Character_Dialog.BP_jRPG_Character_Dialog_C", charCls,
  { { "BP_CharacterSkinComponent", "ObjectProperty" }, { "AllMeshMaterials", "ArrayProperty" } })
COMPANION_CLS = cls("/Game/Characters/BP_jRPG_Character_World.BP_jRPG_Character_World_C", charCls,
  { { "CharacterMesh0", "ObjectProperty" }, { "CharacterName", "NameProperty" } })

function makeSciel(n)
  local path = "/Game/Maps/WorldMap.WorldMap:PersistentLevel.BP_CharacterSkinBase_Sciel_C_" .. n
  local body = skelComp(path, "Body", PLACEHOLDER, 8)
  local accm = skelMesh("/Game/Characters/Heros/Sciel/SK_Sciel_Acc.SK_Sciel_Acc", { vmats[7], vmats[8] }, { "a", "b" })
  local acc1 = skelComp(path, "Acc_Bag", accm, 0)
  local accm2 = skelMesh("/Game/Characters/Heros/Sciel/SK_Sciel_Hat.SK_Sciel_Hat", { vmats[6] }, { "hat" })
  local acc2 = skelComp(path, "Acc_Hat", accm2, 0)
  local opath = "/Game/Maps/WorldMap.WorldMap:PersistentLevel.BP_jRPG_Character_Dialog_C_" .. n
  local skinComp = new("BP_CharacterSkinComponent_C", "BP_CharacterSkinComponent_C", opath .. ".BP_CharacterSkinComponent", {
    CurrentCharacterSkinMaterialInstances = TArray("CurrentCharacterSkinMaterialInstances", {}) })
  local owner = new("Character", "BP_jRPG_Character_Dialog_C", opath, { BP_CharacterSkinComponent = skinComp,
    AllMeshMaterials = TArray("AllMeshMaterials", {}) }, { GetOwner = function() return nil end })
  owner._class = ownerCls
  local a
  a = new("Actor", "BP_CharacterSkinBase_Sciel_C", path, { Body = body }, {
    K2_GetComponentsByClass = function() return PARAMS("K2_GetComponentsByClass", { body, acc1, acc2 }) end,
    GetOwner = function() return owner end, GetAttachParentActor = function() return nil end })
  a._class = SCIEL_CLS
  a._find = { BP_CharacterSkinBase_C = true }
  for _, c in ipairs({ body, acc1, acc2 }) do OWNERS[c] = a ALLSKMC[#ALLSKMC + 1] = c end
  skinComp._p.SpawnedCharacterSkin = a
  return a, body, owner
end

function makeEsquie(n)
  local path = "/Game/Maps/Cine_Lumiere.Cine_Lumiere:PersistentLevel.BP_Cine_Esquie_C_" .. n
  local em = {}
  for i = 1, 4 do em[i] = mic("/Game/Characters/Esquie/MI_Esquie_" .. i, 10, MASTER, "/Game/Characters/Esquie/Textures") end
  local mesh = skelMesh("/Game/Characters/Esquie/SK_Esquie.SK_Esquie", em, { "a", "b", "c", "d" })
  local cm = skelComp(path, "CharacterMesh0", mesh, 4)
  local sc = new("BP_CinematicCharacterSkinComponent_C", "BP_CinematicCharacterSkinComponent_C", path .. ".BP_CinematicCharacterSkinComponent",
    { CharacterHardcodedName = FNameQuiet("Esquie") })
  local a = new("Actor", "BP_Cine_Esquie_C", path, { BP_CinematicCharacterSkinComponent = sc, Mesh = cm }, {
    K2_GetComponentsByClass = function() return PARAMS("K2_GetComponentsByClass", { cm }) end,
    GetOwner = function() return nil end, GetAttachParentActor = function() return nil end })
  a._class = ESQ_CLS
  a._find = { BP_CineCharacter_Main_C = true }
  OWNERS[cm] = a
  ALLSKMC[#ALLSKMC + 1] = cm
  return a
end

ALLSKMC = {}
-- unrelated skeletal mesh components in the world (NPCs etc.), for forEachMappedMeshOwner
function addNPCs(n)
  for i = 1, n do
    local m = skelMesh("/Game/Characters/NPC/SK_NPC_" .. i .. ".SK_NPC_" .. i, {}, {})
    local c = skelComp("/Game/Maps/WorldMap.WorldMap:PersistentLevel.NPC_" .. i, "Mesh", m, 0)
    ALLSKMC[#ALLSKMC + 1] = c
  end
end

-- an AI companion pawn (not a skin actor) showing Sciel's base body: found by the pass through
-- FindAllOf("SkeletalMeshComponent"), then watched every 2 s (SPAWN.watch)
function makeCompanion(n)
  local path = "/Game/Maps/WorldMap.WorldMap:PersistentLevel.BP_jRPG_Character_World_C_" .. n
  local cm = skelComp(path, "CharacterMesh0", PLACEHOLDER, 8)
  local a = new("Character", "BP_jRPG_Character_World_C", path, { CharacterMesh0 = cm, CharacterName = FNameQuiet("Sciel") }, {
    K2_GetComponentsByClass = function() return PARAMS("K2_GetComponentsByClass", { cm }) end,
    GetOwner = function() return nil end, GetAttachParentActor = function() return nil end })
  a._class = COMPANION_CLS
  a._find = { BP_jRPG_Character_World_C = true }
  OWNERS[cm] = a
  ALLSKMC[#ALLSKMC + 1] = cm
  return a, cm
end
