"""Live-switching material regressions (needs lupa). Scenarios from the final audit:
  * outfit A -> B -> off with the game's own dynamic material instance on the slot, where the
    variants' meshes bring MOD-ONLY materials (original paths served by <Mod>_Shared_P)
  * an outfit whose mesh uses a material from the mod's common pak (mod-only, unrelocated)
  * character scoping: a Sciel-only slot never touches Lune; a character-scoped slot does not
    apply to an actor whose character can't be told
  * engine reads kept within one game-thread call (TRACE.memo, for less stutter) change nothing:
    the same session with the memo switched off ends in the same looks, change lines and states;
    a texture set during the call, the game's own changes between calls, a material whose parent
    is an instance, a character named by the game mid-call and a load in the middle are all seen
"""
import os
import re
import shutil
import sys
import tempfile

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_lua_mock as base  # noqa: E402

SCEN = r'''
asset("Texture2D", "/Game/Characters/Lune/Chic/T_Chic_D", "T_Chic_D")
local function mi(pkg, obj)
  asset("MaterialInstanceConstant", pkg, obj, { TextureParameterValues = TArray({}) })
end
mi("/Game/Characters/Lune/Chic/MI_Chic", "MI_Chic")            -- vanilla
mi("/Game/Mods/Chic/MI_Lace", "MI_Lace")                        -- mod-only original (shared pak)
mi("/Game/ZWAAAAA/Chic/MI_Lace", "MI_Lace")                     -- variant A's relocated copy
mi("/Game/Mods/Chic/MI_Net", "MI_Net")
mi("/Game/ZWBBBBB/Chic/MI_Net", "MI_Net")                       -- variant B's relocated copy
mi("/Game/ModCommon/MI_Common", "MI_Common")                    -- common pak material (mod-only, shared pak)
local function skel(pkg, matfull)
  asset("SkeletalMesh", pkg, "SK_Lune_Chic", { Materials = TArray({ { MaterialInterface = get(matfull) } }) })
end
skel("/Game/Characters/Lune/Chic/SK_Lune_Chic", "/Game/Characters/Lune/Chic/MI_Chic.MI_Chic")
skel("/Game/ZWAAAAAAAAA/Lune/Chic/SK_Lune_Chic", "/Game/ZWAAAAA/Chic/MI_Lace.MI_Lace")
skel("/Game/ZWBBBBBBBBB/Lune/Chic/SK_Lune_Chic", "/Game/ZWBBBBB/Chic/MI_Net.MI_Net")
skel("/Game/ZWCCCCCCCCC/Lune/Chic/SK_Lune_Chic", "/Game/ModCommon/MI_Common.MI_Common")

local function skinActor(classPath, name)
  local cls = new("BlueprintGeneratedClass", classPath)
  cls._super = { GetFName = function() return { ToString = function() return "BP_CharacterSkinBase_C" end } end,
                 IsValid = function() return true end, GetSuperStruct = function() return nil end }
  local body = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
  local a = new(name, "/Game/Map.PersistentLevel." .. name .. "_1", { Body = body },
                { K2_GetComponentsByClass = function() return TArray({ body }) end })
  a._class = cls; a._skin = "BP_CharacterSkinBase_C"; table.insert(ACTORS, a)
  -- the pawn that owns the skin: it has no AllMeshMaterials (an invalid object when read)
  local pawn = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_" .. name)
  a._f.GetOwner = function() return pawn end
  body:CreateDynamicMaterialInstance(0, get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic"), FName("None"))  -- the game's MID
  return body
end
LUNE = skinActor("/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C", "BP_Lune_Skin_Chic_C")
NOBODY = skinActor("/Game/Characters/Skins/BP_Skin_Chic.BP_Skin_Chic_C", "BP_Skin_Chic_C")
'''

VARIANTS = r'''return { { mod = "CC", slots = {
  { id = "CC/Lune outfit", label = "Lune outfit", character = "Lune", variants = {
    { id = "CC/A", label = "A", map = {
      ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/ZWAAAAAAAAA/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh", true },
      ["/Game/Mods/Chic/MI_Lace"] = { "/Game/ZWAAAAA/Chic/MI_Lace", "MI_Lace", "MaterialInstanceConstant", false } } },
    { id = "CC/B", label = "B", map = {
      ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/ZWBBBBBBBBB/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh", true },
      ["/Game/Mods/Chic/MI_Net"] = { "/Game/ZWBBBBB/Chic/MI_Net", "MI_Net", "MaterialInstanceConstant", false } } },
    { id = "CC/C", label = "C (common material)", map = {
      ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/ZWCCCCCCCCC/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh", true } } },
  } },
  { id = "CC/Sciel outfit", label = "Sciel outfit", character = "Sciel", variants = {
    { id = "CC/S", label = "S", map = {
      ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/ZWBBBBBBBBB/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh", true } } } } },
} } }
'''


# --------------------------------------------------------------------------- memo (less stutter)
# main.lua keeps engine reads for the rest of one game-thread call (TRACE.memo): texture parameters
# per material with their parents, class keys, characters, mesh slot lists. The same session runs
# twice, with the memo and with it switched off (main.lua patched), and must end the same.
MEMO_ON = 'if TRACE.memo or gtDepth > 0 then TRACE.memo = { tp = {} } end'

MEMO_SCEN = r"""
local function live(list)                     -- UE4SS-like TArray of FTextureParameterValue, read live
  return setmetatable({}, { __index = function(_, k)
    if k == "ForEach" then return function(_, fn)
      for i, e in ipairs(list) do fn(i, { get = function() return { ParameterInfo = { Name = FName(e[1]) }, ParameterValue = e[2] } end }) end
    end end end })
end
local function setIn(list, name, t)
  for _, e in ipairs(list) do if e[1] == name then e[2] = t return end end
  list[#list + 1] = { name, t }
end
TEX = {}
local function tex(path) local leaf = path:match("[^/]+$"); asset("Texture2D", path, leaf); TEX[path] = get(path .. "." .. leaf); return TEX[path] end
tex("/Game/Characters/Lune/Body/T_Body_D"); tex("/Game/Characters/Lune/Body/T_Body_N")
tex("/Game/Characters/Lune/Body/T_Top_D"); tex("/Game/MetaHumans/BTLS_Textures/Main_Characters/Lune_Body_BTLS")
tex("/Game/ZWRED0001/Lune/Body/T_Body_D"); tex("/Game/ZWBLUE001/Lune/Body/T_Body_D")
tex("/Game/ZWDIRT001/MetaHumans/BTLS_Textures/Main_Characters/Lune_Body_BTLS")
tex("/Game/ZWOUT0001/Lune/Body/T_Body_D-nude")
asset("Texture2D", "/Game/ZWBLUE001/Lune/Body/T_Body_D-x", "T_Body_D-x")      -- loaded only by a test below
local MASK = "/Game/MetaHumans/BTLS_Textures/Main_Characters/Lune_Body_BTLS"
local function mat(kind, pkg, obj, list, parent)
  local m = new(kind, pkg .. "." .. obj, { TextureParameterValues = live(list), Parent = parent,
    ScalarParameterValues = TArray({}), VectorParameterValues = TArray({}) })
  m._list = list
  REGSET(pkg .. "." .. obj, m)
  return m
end
local M_SKIN = new("Material", "/Game/Materials/M_Skin.M_Skin", {})        -- a base material: no parameters, no parent
REGSET("/Game/Materials/M_Skin.M_Skin", M_SKIN)
MIC_BODY = mat("MaterialInstanceConstant", "/Game/Characters/Lune/Body/MI_Lune_Body", "MI_Lune_Body",
  { { "Color_MAIN", TEX["/Game/Characters/Lune/Body/T_Body_D"] }, { "Normal_MAIN", TEX["/Game/Characters/Lune/Body/T_Body_N"] },
    { "BTLS_Map_Tiling", TEX[MASK] } }, M_SKIN)
MIC_TOP = mat("MaterialInstanceConstant", "/Game/Characters/Lune/Chic/MI_Lune_Top", "MI_Lune_Top",
  { { "Top_D", TEX["/Game/Characters/Lune/Body/T_Top_D"] } }, MIC_BODY)
-- the mod's own material: its base colour points at a texture nobody shipped (an empty link)
MI_MOD = mat("MaterialInstanceConstant", "/Game/Mods/Out/MI_Mod", "MI_Mod", { { "Color_MAIN", NULLOBJ() } }, M_SKIN)
local function skel(pkg, obj, slots)
  local items = {}
  for i, sl in ipairs(slots) do items[i] = { MaterialInterface = sl[2], MaterialSlotName = FName(sl[1]) } end
  local m = new("SkeletalMesh", pkg .. "." .. obj, { Materials = TArray(items) })
  REGSET(pkg .. "." .. obj, m)
  return m
end
CHIC = skel("/Game/Characters/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", { { "body", MIC_BODY }, { "top", MIC_TOP }, { "hair", MIC_BODY } })
skel("/Game/ZWOUT0001/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic",
  { { "body", MIC_BODY }, { "top", MIC_TOP }, { "extra", MI_MOD }, { "body2", nil } })   -- slot 3 empty
MIDN = 0
function comp(owner, name, mesh)
  local over = {}
  local c
  c = new("SkeletalMeshComponent", owner .. "." .. name, {}, {
    GetSkeletalMeshAsset = function(self) return self._mesh end,
    SetSkeletalMeshAsset = function(self, m) self._mesh = m end,
    GetNumMaterials = function(self) return #self._mesh._p.Materials._items end,
    GetMaterial = function(self, i)
      if over[i] then return over[i] end
      local e = self._mesh._p.Materials._items[i + 1]
      return e and e.MaterialInterface or NULLOBJ()
    end,
    SetMaterial = function(self, i, m) over[i] = m end,
    CreateDynamicMaterialInstance = function(self, i, parent)
      MIDN = MIDN + 1
      local list = {}
      local mid = new("MaterialInstanceDynamic", owner .. "." .. name .. ".MaterialInstanceDynamic_" .. MIDN,
        { Parent = parent, TextureParameterValues = live(list), ScalarParameterValues = TArray({}), VectorParameterValues = TArray({}) },
        { SetTextureParameterValue = function(m, fname, t) setIn(list, fname:ToString(), t) end,
          SetScalarParameterValue = function() end, SetVectorParameterValue = function() end })
      mid._list = list
      over[i] = mid
      return mid
    end })
  c._mesh = mesh
  c._over = over
  return c
end
local skinCls = new("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C")
skinCls._super = { GetFName = function() return { ToString = function() return "BP_CharacterSkinBase_C" end } end,
                   IsValid = function() return true end, GetSuperStruct = function() return nil end }
BODIES = {}
function skin(n, mids)
  local path = "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_" .. n
  local body = comp(path, "Body", CHIC)
  local a = new("BP_Lune_Skin_Chic_C", path, { Body = body }, { K2_GetComponentsByClass = function() return TArray({ body }) end })
  a._class = skinCls; a._skin = "BP_CharacterSkinBase_C"
  table.insert(ACTORS, a)
  BODIES[#BODIES + 1] = body
  if mids then
    -- the game's own instances: slot 0 on the body material, slot 1 an instance whose PARENT is
    -- slot 0's instance (a chain through an instance)
    local x = body:CreateDynamicMaterialInstance(0, MIC_BODY)
    body:CreateDynamicMaterialInstance(1, x)
  end
  return a, body
end
A1, BODY1 = skin(1, true)
A2, BODY2 = skin(2, false)
-- what a component shows: mesh, and per slot the material (and parent) and the texture the
-- material chain gives each parameter (child values win), sorted by parameter
function snapshot()
  local out = {}
  for bi, b in ipairs(BODIES) do
    out[#out + 1] = "body" .. bi .. " " .. b._mesh._path
    for i = 0, #b._mesh._p.Materials._items - 1 do
      local m = b:GetMaterial(i)
      if not m:IsValid() then out[#out + 1] = "  mat" .. i .. " empty"
      else
        local seen, names, m2 = {}, {}, m
        local desc = m._kind .. (m._kind == "MaterialInstanceDynamic" and "" or (" " .. m._path))
        local p = m._p.Parent
        if m._kind == "MaterialInstanceDynamic" then
          desc = desc .. " of " .. ((p and p._kind == "MaterialInstanceDynamic") and "an instance" or (p and p._path or "?"))
        end
        while m2 and rawget(m2, "_list") do
          for _, e in ipairs(m2._list) do
            if seen[e[1]] == nil then seen[e[1]] = e[2]:IsValid() and (e[2]._path or "?") or "empty"; names[#names + 1] = e[1] end
          end
          m2 = m2._p.Parent
        end
        table.sort(names)
        local parts = {}
        for _, nm in ipairs(names) do parts[#parts + 1] = nm .. "=" .. seen[nm] end
        out[#out + 1] = "  mat" .. i .. " " .. desc .. " | " .. table.concat(parts, " ")
      end
    end
  end
  return table.concat(out, "\n")
end
function gameResets()                         -- the game puts its own texture back on its instance
  local x = BODY1._over[0]
  for _, e in ipairs(x._list) do if e[1] == "Color_MAIN" then e[2] = TEX["/Game/Characters/Lune/Body/T_Body_D"] end end
end
CROSSINGS = 0                                 -- method calls and property reads on engine objects (counted)
local Obj = getmetatable(BODY1)
local oldIndex = Obj.__index
Obj.__index = function(t, k) CROSSINGS = CROSSINGS + 1 return oldIndex(t, k) end
"""

MEMO_VARIANTS = r"""return { { mod = "Perf", slots = {
  { id = "P/outfit", label = "Perf: Lune outfit", character = "Lune", variants = {
    { id = "P/out", label = "out", map = {
      ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/ZWOUT0001/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" },
      ["/Game/Mods/Out/MI_Mod"] = { "/Game/Mods/Out/MI_Mod", "MI_Mod", "MaterialInstanceConstant", false },
      ["/Game/Characters/Lune/Body/T_Body_D-nude"] = { "/Game/ZWOUT0001/Lune/Body/T_Body_D-nude", "T_Body_D-nude", "Texture2D" } } } } },
  { id = "P/color", label = "Perf: Lune color", character = "Lune", variants = {
    { id = "P/red", label = "red", map = {
      ["/Game/Characters/Lune/Body/T_Body_D"] = { "/Game/ZWRED0001/Lune/Body/T_Body_D", "T_Body_D", "Texture2D" } } },
    { id = "P/blue", label = "blue", map = {
      ["/Game/Characters/Lune/Body/T_Body_D"] = { "/Game/ZWBLUE001/Lune/Body/T_Body_D", "T_Body_D", "Texture2D" } } } } },
  { id = "P/dirt", label = "Perf: less dirt", character = "Lune", variants = {
    { id = "P/less", label = "less", map = {
      ["/Game/MetaHumans/BTLS_Textures/Main_Characters/Lune_Body_BTLS"] = { "/Game/ZWDIRT001/MetaHumans/BTLS_Textures/Main_Characters/Lune_Body_BTLS", "Lune_Body_BTLS", "Texture2D" } } } } },
} } }
"""


def memo_session(memo, sabotage=None):
    """One scripted session; returns (looks after each step, sorted change lines, states, engine reads, AV)."""
    tmp = tempfile.mkdtemp(prefix='e33memo_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    src = open(base.MAIN, encoding='utf-8').read()
    if not memo:
        assert MEMO_ON in src, 'main.lua changed: update MEMO_ON in this test'
        src = src.replace(MEMO_ON, 'TRACE.memo = nil')
    for old, new in (sabotage or []):
        assert old in src, old
        src = src.replace(old, new)
    open(os.path.join(scripts, 'main.lua'), 'w', encoding='utf-8').write(src)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(MEMO_VARIANTS)
    open(os.path.join(mod, 'settings.txt'), 'w').write('clean = true\nauto_wear = false\n')
    open(os.path.join(mod, 'selection.txt'), 'w').write('P/outfit\tP/out\nP/color\tP/red\nP/dirt\tP/less\n')
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(MEMO_SCEN)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        src, '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    W = G.API_OUT
    on_gt = L.eval('function(f, x) ExecuteInGameThread(function() f(x) end) end')
    G.settle()
    snaps = [G.snapshot()]
    G.gameResets()                               # between calls: the game's own texture is back
    W.applyAll('test')
    G.settle()
    snaps.append(G.snapshot())
    W.setVariant(2, 2)                           # red -> blue
    G.settle()
    snaps.append(G.snapshot())
    on_gt(W.setClean, False)                     # Clean off: the masks it kept go back
    G.settle()
    snaps.append(G.snapshot())
    on_gt(W.setClean, True)
    G.settle()
    snaps.append(G.snapshot())
    L.execute('local a = skin(3, true); BEGINPLAY({ get = function() return a end }); tickGT(80)')
    snaps.append(G.snapshot())
    W.setVariant(2, 0)
    W.setVariant(1, 0)
    G.settle()
    snaps.append(G.snapshot())
    lv = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    changes = sorted(re.sub(r'^\S+ #\d+ ', '', x) for x in lv.splitlines() if ' change ' in x)
    worn = W.wornBy('Lune')
    states = [str(W.slotState(i)) for i in (1, 2, 3)] + [str(worn and worn.path)]
    out = (snaps, changes, states, G.CROSSINGS, L.eval('AV'))
    shutil.rmtree(tmp, ignore_errors=True)
    return out


UPVAL = r"""
-- a local of main.lua by name, through the upvalues of the functions main.lua handed out
function UPVAL(name)
  local seen = {}
  local function walk(f, depth)
    if type(f) ~= "function" or seen[f] or depth > 12 then return nil end
    seen[f] = true
    for i = 1, 255 do
      local n, v = debug.getupvalue(f, i)
      if not n then break end
      if n == name then return v end
      if type(v) == "function" then local r = walk(v, depth + 1); if r ~= nil then return r end end
      if type(v) == "table" and not seen[v] then
        seen[v] = true
        for _, x in pairs(v) do local r = walk(x, depth + 1); if r ~= nil then return r end end
      end
    end
  end
  for _, f in pairs(API_OUT) do local r = walk(f, 0); if r ~= nil then return r end end
  for _, f in pairs(HOOKS or {}) do local r = walk(f, 0); if r ~= nil then return r end end
  return walk(BEGINPLAY, 0)
end
"""


def memo_white_box(check):
    """Kept reads are dropped where they could be wrong (main.lua's locals, reached through upvalues)."""
    tmp = tempfile.mkdtemp(prefix='e33memo_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(MEMO_VARIANTS)
    open(os.path.join(mod, 'settings.txt'), 'w').write('auto_wear = false\n')
    open(os.path.join(mod, 'selection.txt'), 'w').write('P/outfit\tP/out\n')
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(MEMO_SCEN)
    L.execute('function RegisterHook(name, pre, post) HOOKS = HOOKS or {}; HOOKS[name] = post; return 1, 2 end')
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(base.MAIN, encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    G.settle()
    L.execute(UPVAL)
    L.execute('TRACE_T = UPVAL("TRACE"); ON_ASSIGNED = UPVAL("onAssigned"); KNOWN = UPVAL("KNOWN_SKINS")')
    gt = G.API_OUT.gt
    # outside game-thread calls nothing is kept; inside, it goes when the call ends
    gt(L.eval('function() INSIDE = TRACE_T.memo ~= nil end'))
    check('memo: kept reads exist only during a game-thread call (none between calls)',
          G.INSIDE is True and L.eval('TRACE_T.memo') is None, (G.INSIDE, L.eval('TRACE_T.memo')))
    # a load in the middle of a call runs engine code: nothing read before it is kept
    gt(L.eval('''function()
        local textureParams, loadObj = UPVAL("textureParams"), UPVAL("loadObj")
        -- a real load takes time (PC: 1 ms or more); finding an asset in memory doesn't (0 ms)
        local arh = StaticFindObject("/Script/AssetRegistry.Default__AssetRegistryHelpers")
        local g = arh.GetAsset
        arh.GetAsset = function(self, ad)
          if SLOW_LOAD then MOCK_TICKS = MOCK_TICKS + 1 end
          return g(self, ad)
        end
        textureParams(MIC_TOP)
        BEFORE_LOAD = next(TRACE_T.memo.tp) ~= nil
        SLOW_LOAD = true
        loadObj("/Game/ZWBLUE001/Lune/Body/T_Body_D-x", "T_Body_D-x")
        AFTER_LOAD = next(TRACE_T.memo.tp) ~= nil
        SLOW_LOAD = false
        textureParams(MIC_TOP)
        loadObj("/Game/ZWBLUE001/Lune/Body/T_Body_D-x", "T_Body_D-x")      -- in memory now: 0 ms
        AFTER_FIND = next(TRACE_T.memo.tp) ~= nil
        arh.GetAsset = g
      end'''))
    check('memo: a load in the middle of a call drops what was kept before it',
          G.BEFORE_LOAD is True and G.AFTER_LOAD is False, (G.BEFORE_LOAD, G.AFTER_LOAD))
    check('  an asset found in memory (0 ms) keeps them (fix14: the mod\'s own assets are asked of GetAsset)',
          G.AFTER_FIND is True, G.AFTER_FIND)
    # fix14 review: a game asset may be streaming in; GetAsset would load it synchronously on the game
    # thread. It is found first and, still loading, left for later; only the mod's relocated copies
    # (never streamed by the game) go straight to GetAsset.
    gt(L.eval('''function()
        local loadObj = UPVAL("loadObj")
        local arh = StaticFindObject("/Script/AssetRegistry.Default__AssetRegistryHelpers")
        local g, sfo = arh.GetAsset, StaticFindObject
        GA, SF = 0, {}
        arh.GetAsset = function(self, ad) GA = GA + 1; return g(self, ad) end
        StaticFindObject = function(p) SF[#SF + 1] = p; return sfo(p) end
        MIC_TOP._f.HasAnyInternalFlags = function(self, m) return (m & 0x8000000) ~= 0 end   -- AsyncLoading
        STREAMING = loadObj("/Game/Characters/Lune/Chic/MI_Lune_Top", "MI_Lune_Top")
        GA_STREAMING = GA
        MIC_TOP._f.HasAnyInternalFlags = nil
        OWN = loadObj("/Game/ZWBLUE001/Lune/Body/T_Body_D", "T_Body_D")      -- a variant's relocated texture
        OWN_SFO = 0
        for _, p in ipairs(SF) do if p:find("ZWBLUE001") then OWN_SFO = OWN_SFO + 1 end end
        arh.GetAsset, StaticFindObject = g, sfo
      end'''))
    check('a game asset that is still loading: not handed to GetAsset (no synchronous load), left for later',
          G.STREAMING is None and G.GA_STREAMING == 0, (G.STREAMING, G.GA_STREAMING))
    check('  the mod\'s own relocated asset: GetAsset straight away, no StaticFindObject',
          G.OWN is not None and G.OWN_SFO == 0, (G.OWN, G.OWN_SFO))
    # the game names a skin's character mid-call (policy hook -> onAssigned): asked again in the
    # same call, the skin has that character, not the "unknown" kept a moment before
    L.execute(r"""
      NOCLS = new("BlueprintGeneratedClass", "/Game/Characters/Skins/BP_Skin_Any.BP_Skin_Any_C")
      NOCLS._super = { GetFName = function() return { ToString = function() return "BP_CharacterSkinBase_C" end } end,
                       IsValid = function() return true end, GetSuperStruct = function() return nil end }
      OWN = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_7")
      ANY = new("BP_Skin_Any_C", "/Game/Map.PersistentLevel.BP_Skin_Any_C_7", {}, { GetOwner = function() return OWN end })
      ANY._class = NOCLS
      OWN_NAME = OWN:GetFullName():match("^%S+%s+(.+)$")
      KNOWN[ANY:GetAddress()] = { a = ANY, name = ANY:GetFullName(), owner = OWN_NAME }
    """)
    gt(L.eval('''function()
        local characterOf = UPVAL("characterOf")
        CHAR_BEFORE = characterOf(ANY)
        ON_ASSIGNED(OWN_NAME, "Sciel")
        CHAR_AFTER = characterOf(ANY)
      end'''))
    check('memo: a character the game names mid-call is used at once (not the one kept before)',
          G.CHAR_BEFORE is None and G.CHAR_AFTER == 'Sciel', (G.CHAR_BEFORE, G.CHAR_AFTER))
    # audit 17 Oct: skins made while a map loads are left to the map-load pass, and only the
    # re-check noted them, so the game re-showing one later (no BeginPlay) went unseen
    gt(L.eval('''function()
        for k in pairs(KNOWN) do KNOWN[k] = nil end
        local nSkins = 0
        UPVAL("forEachSkin")(function() nSkins = nSkins + 1 end)
        UPVAL("runApply")()
        local n = 0
        for _, k in pairs(KNOWN) do if k.name and k.a then n = n + 1 end end
        PASS_SKINS, PASS_KNOWN = nSkins, n
      end'''))
    check('the map-load pass notes the skins it dresses (for re-dressing them when the game shows them again)',
          G.PASS_SKINS and G.PASS_SKINS > 0 and G.PASS_KNOWN == G.PASS_SKINS, (G.PASS_SKINS, G.PASS_KNOWN))
    # PC 17 Oct, two camp crashes inside UE4SS's property cache while reading "Face" of a camp
    # character: a character that isn't an outfit actor is never read by property; its components
    # come from K2_GetComponentsByClass under their own names (Body first, as NAMED orders them)
    gt(L.eval(r'''function()
        local function pr(cls, name) return { GetClass = function() return { GetFName = function() return FName(cls) end } end,
                                             GetFName = function() return FName(name) end } end
        local campCls = new("BlueprintGeneratedClass", "/Game/Camp/BP_Character_Camp_Lune.BP_Character_Camp_Lune_C")
        campCls._super = { GetFName = function() return FName("Character") end, IsValid = function() return true end,
                           GetSuperStruct = function() return nil end }
        campCls._f.ForEachProperty = function(self, cb) cb(pr("ObjectProperty", "Body")); cb(pr("ObjectProperty", "Face")) end
        local face = comp("/Game/Map.PersistentLevel.BP_Character_Camp_Lune_C_9", "Face", CHIC)
        local body = comp("/Game/Map.PersistentLevel.BP_Character_Camp_Lune_C_9", "Body", CHIC)
        CAMP_READS = {}
        -- JMAP at camp, 17 Oct: camp Lune also holds her skin component in a Blueprint property
        local skinCompCls = new("BlueprintGeneratedClass",
          "/Game/Gameplay/CharacterCustomization/Blueprints/BP_CharacterSkinComponent.BP_CharacterSkinComponent_C")
        REGSET(skinCompCls._path, skinCompCls)                                   -- found by StaticFindObject
        local cineCls = new("BlueprintGeneratedClass",
          "/Game/Gameplay/CharacterCustomization/Blueprints/BP_CinematicCharacterSkinComponent.BP_CinematicCharacterSkinComponent_C")
        cineCls._f.ForEachProperty = function(self, cb) cb(pr("NameProperty", "CharacterHardcodedName")) end
        local sc = new("BP_CinematicCharacterSkinComponent_C", "/Game/Map.PersistentLevel.BP_Character_Camp_Lune_C_9.BP_CinematicCharacterSkinComponent",
                       { CharacterHardcodedName = FName("Sciel") })   -- not the class path's Lune: proves the component was read
        sc._class = cineCls
        campCls._f.ForEachProperty = function(self, cb)
          cb(pr("ObjectProperty", "Body")); cb(pr("ObjectProperty", "Face")); cb(pr("ObjectProperty", "BP_CinematicCharacterSkinComponent")) end
        local camp = new("BP_Character_Camp_Lune_C", "/Game/Map.PersistentLevel.BP_Character_Camp_Lune_C_9", {}, {
          K2_GetComponentsByClass = function(self, c)
            if c == skinCompCls then return TArray({ sc }) end
            return TArray({ face, body }) end })
        rawset(camp, "_p", setmetatable({}, { __index = function(_, k)                  -- its Blueprint properties
          if k == "Body" or k == "Face" or k == "BP_CinematicCharacterSkinComponent" then CAMP_READS[#CAMP_READS + 1] = k end end }))
        camp._class = campCls
        local names = {}
        for _, e in ipairs(UPVAL("meshComponents")(camp)) do names[#names + 1] = e.name end
        CAMP_NAMES = table.concat(names, ",")
        CAMP_CHAR = UPVAL("characterOf")(camp)
      end'''))
    check('a camp character: components by their own names (Body first), not one property read by name',
          G.CAMP_NAMES == 'Body,Face' and len(L.eval('CAMP_READS')) == 0,
          (G.CAMP_NAMES, list(L.eval('CAMP_READS').values())))
    check('  and its character comes from its skin component found by class, not from its property',
          G.CAMP_CHAR == 'Sciel' and len(L.eval('CAMP_READS')) == 0, (G.CAMP_CHAR, list(L.eval('CAMP_READS').values())))
    # a material chain deeper than the 8 levels read: a parent's kept result (levels 5-10) must not
    # make a child's walk (levels 1-8) read past level 8
    gt(L.eval('''function()
        local textureParams = UPVAL("textureParams")
        local chain, parent = {}, nil
        for k = 10, 1, -1 do
          local list = { { "P" .. k, TEX["/Game/Characters/Lune/Body/T_Top_D"] } }
          parent = new("MaterialInstanceConstant", "/Game/Deep/MI_Deep" .. k .. ".MI_Deep" .. k, {
            TextureParameterValues = setmetatable({}, { __index = function(_, key)
              if key == "ForEach" then return function(_, fn)
                for i, e in ipairs(list) do fn(i, { get = function() return { ParameterInfo = { Name = FName(e[1]) }, ParameterValue = e[2] } end }) end
              end end end }), Parent = parent })
          chain[k] = parent
        end
        local n5, n1 = 0, 0
        for _ in pairs(textureParams(chain[5])) do n5 = n5 + 1 end
        for _ in pairs(textureParams(chain[1])) do n1 = n1 + 1 end
        DEEP = { n5, n1 }
      end'''))
    # an engine class that can't be found is never noted as checked (IsA with it would read null)
    gt(L.eval('''function()
        local isA = UPVAL("isA")
        NOCLASS = { isA(BODY1, "/Script/Engine.NoSuchClass"), isA(BODY1, "/Script/Engine.NoSuchClass") }
        NOCLASS_NOTED = (TRACE_T.memo.cls or {})["/Script/Engine.NoSuchClass"] == true
        SKCLASS_NOTED = (TRACE_T.memo.cls or {})["/Script/Engine.SkeletalMeshComponent"] == true
        SKCLASS = isA(BODY1, "/Script/Engine.SkeletalMeshComponent")
        SKCLASS_NOTED = (TRACE_T.memo.cls or {})["/Script/Engine.SkeletalMeshComponent"] == true
      end'''))
    check('memo: an engine class that isn\'t there is never noted as checked; one that is, is',
          list(L.eval('NOCLASS').values()) == [False, False] and G.NOCLASS_NOTED is False
          and G.SKCLASS is True and G.SKCLASS_NOTED is True,
          (list(L.eval('NOCLASS').values()), G.NOCLASS_NOTED, G.SKCLASS, G.SKCLASS_NOTED))
    # a skin whose class lists its properties: Body and Face (object properties) point at components
    # the actor doesn't own (the swap policy shares the pawn's); the other component names are
    # skipped without reading them, Hair (a weak reference: UE4SS 1125 crashes reading it) included
    L.execute(r"""
      local function pr(cls, name) return { GetClass = function() return { GetFName = function() return FName(cls) end } end,
                                           GetFName = function() return FName(name) end } end
      local typed = new("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Lune_Skin_Typed.BP_Lune_Skin_Typed_C")
      typed._super = { GetFName = function() return { ToString = function() return "BP_CharacterSkinBase_C" end } end,
                       IsValid = function() return true end, GetSuperStruct = function() return nil end }
      typed._f.ForEachProperty = function(self, cb)
        cb(pr("ObjectProperty", "Body")); cb(pr("ObjectProperty", "Face")); cb(pr("WeakObjectProperty", "Hair")) end
      TYPEDBODY = comp("/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_4", "Body", CHIC)
      TYPEDFACE = comp("/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_4", "Face", CHIC)
      NAMEREADS = {}
      local a = new("BP_Lune_Skin_Typed_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Typed_C_4", {}, {
        K2_GetComponentsByClass = function() return TArray({}) end })
      rawset(a, "_p", setmetatable({ Body = TYPEDBODY, Face = TYPEDFACE }, { __index = function(_, k)
        if k == "Hair" or k == "Eyebrows" or k == "Beard" or k == "Haircut_StaticMesh" then NAMEREADS[#NAMEREADS + 1] = k end end }))
      a._class = typed; a._skin = "BP_CharacterSkinBase_C"
      table.insert(ACTORS, a)
    """)
    G.API_OUT.applyAll('test')
    G.settle()
    check('memo: properties the class lists as objects (Body, Face: another actor\'s components) are read; '
          'names it lacks or lists as weak references are skipped without a read',
          L.eval('TYPEDBODY._mesh._path').startswith('/Game/ZWOUT0001/')
          and L.eval('TYPEDFACE._mesh._path').startswith('/Game/ZWOUT0001/') and len(L.eval('NAMEREADS')) == 0,
          (L.eval('TYPEDBODY._mesh._path'), L.eval('TYPEDFACE._mesh._path'), list(L.eval('NAMEREADS').values())))
    check('memo: a deep material chain is read to 8 levels, also when a parent\'s result is kept',
          list(L.eval('DEEP').values()) == [6, 8], list(L.eval('DEEP').values()))
    shutil.rmtree(tmp, ignore_errors=True)


STALE_SCEN = r"""
-- PC 17 Oct: Cheekier Chic's swapped Sciel Blueprint brings the outfit's relocated material, whose
-- textures are mod-only originals from the shared pak (Thank_you_Sciel_*). Unpicked colour variants
-- own those textures. Every look said "textures back to ...'s own (variant off)" and rebuilt the
-- game's instance, though going back to the parent changed nothing (4-6 times per character).
local function live(list)                     -- UE4SS-like TArray of FTextureParameterValue, read live
  return setmetatable({}, { __index = function(_, k)
    if k == "ForEach" then return function(_, fn)
      for i, e in ipairs(list) do fn(i, { get = function() return { ParameterInfo = { Name = FName(e[1]) }, ParameterValue = e[2] } end }) end
    end end end })
end
TEX = {}
local function tex(path) local leaf = path:match("[^/]+$"); asset("Texture2D", path, leaf); TEX[path] = get(path .. "." .. leaf) end
tex("/Game/Mods/Sh/T_Lace_D"); tex("/Game/ZWCOL0001/Sh/T_Lace_D")
local M_SKIN = new("Material", "/Game/Materials/M_Skin.M_Skin", {})
REGSET("/Game/Materials/M_Skin.M_Skin", M_SKIN)
local shareList = { { "Color", TEX["/Game/Mods/Sh/T_Lace_D"] } }
MI_SHARE = new("MaterialInstanceConstant", "/Game/ZWOUT0002/Sh/MI_Share.MI_Share", { TextureParameterValues = live(shareList),
  Parent = M_SKIN, ScalarParameterValues = TArray({}), VectorParameterValues = TArray({}) })
MI_SHARE._list = shareList
REGSET("/Game/ZWOUT0002/Sh/MI_Share.MI_Share", MI_SHARE)
SHMESH = new("SkeletalMesh", "/Game/ZWOUT0002/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic",
  { Materials = TArray({ { MaterialInterface = MI_SHARE, MaterialSlotName = FName("body") } }) })
REGSET("/Game/ZWOUT0002/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic", SHMESH)
local function comp(owner, name, mesh)
  local over, c = {}, nil
  c = new("SkeletalMeshComponent", owner .. "." .. name, {}, {
    GetSkeletalMeshAsset = function(self) return self._mesh end,
    SetSkeletalMeshAsset = function(self, m) self._mesh = m end,
    GetNumMaterials = function(self) return #self._mesh._p.Materials._items end,
    GetMaterial = function(self, i)
      if over[i] then return over[i] end
      local e = self._mesh._p.Materials._items[i + 1]
      return e and e.MaterialInterface or NULLOBJ()
    end,
    SetMaterial = function(self, i, m) over[i] = m end,
    CreateDynamicMaterialInstance = function(self, i, parent)
      MIDS_MADE = (MIDS_MADE or 0) + 1
      local list = {}
      local mid = new("MaterialInstanceDynamic", owner .. "." .. name .. ".MaterialInstanceDynamic_" .. MIDS_MADE,
        { Parent = parent, TextureParameterValues = live(list), ScalarParameterValues = TArray({}), VectorParameterValues = TArray({}) },
        { SetTextureParameterValue = function(m, fname, t)
            for _, e in ipairs(list) do if e[1] == fname:ToString() then e[2] = t return end end
            list[#list + 1] = { fname:ToString(), t } end,
          SetScalarParameterValue = function() end, SetVectorParameterValue = function() end })
      mid._list = list
      over[i] = mid
      return mid
    end })
  c._mesh = mesh
  return c
end
local cls = new("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Lune_Skin_Share.BP_Lune_Skin_Share_C")
cls._super = { GetFName = function() return { ToString = function() return "BP_CharacterSkinBase_C" end } end,
               IsValid = function() return true end, GetSuperStruct = function() return nil end }
function shareSkin(n, override)
  local path = "/Game/Map.PersistentLevel.BP_Lune_Skin_Share_C_" .. n
  local body = comp(path, "Body", SHMESH)
  local a = new("BP_Lune_Skin_Share_C", path, { Body = body }, { K2_GetComponentsByClass = function() return TArray({ body }) end })
  a._class = cls; a._skin = "BP_CharacterSkinBase_C"
  table.insert(ACTORS, a)
  local mid = body:CreateDynamicMaterialInstance(0, MI_SHARE)          -- the game's own instance
  if override then mid._list[1] = { "Color", TEX[override] } end
  return body
end
PLAIN = shareSkin(1, nil)                                  -- nothing of its own: the parent's texture
LEFT = shareSkin(2, "/Game/ZWCOL0001/Sh/T_Lace_D")        -- a colour left from when it was picked
function colorOf(b)
  local m = b:GetMaterial(0)
  for _, e in ipairs(m._list or {}) do if e[1] == "Color" then return e[2]._path end end
  local p = m._p.Parent
  for _, e in ipairs(p and p._list or {}) do if e[1] == "Color" then return e[2]._path end end
end
"""

STALE_VARIANTS = r"""return { { mod = "Sh", slots = {
  { id = "S/outfit", label = "Sh: Lune outfit", character = "Lune", variants = {
    { id = "S/o", label = "o", map = {
      ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/ZWOUT0002/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh", true },
      ["/Game/Mods/Sh/MI_Share"] = { "/Game/ZWOUT0002/Sh/MI_Share", "MI_Share", "MaterialInstanceConstant", false } } } } },
  { id = "S/color", label = "Sh: Lune color", character = "Lune", variants = {
    { id = "S/red", label = "red", map = {
      ["/Game/Mods/Sh/T_Lace_D"] = { "/Game/ZWCOL0001/Sh/T_Lace_D", "T_Lace_D", "Texture2D", false } } } } },
} } }
"""


def stale_checks(check):
    """A texture the parent already shows is never 'back to the parent's own' (no rebuild loop)."""
    tmp = tempfile.mkdtemp(prefix='e33stale_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(STALE_VARIANTS)
    open(os.path.join(mod, 'settings.txt'), 'w').write('auto_wear = false\n')
    open(os.path.join(mod, 'selection.txt'), 'w').write('S/outfit\tS/o\n')        # no colour picked
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(STALE_SCEN)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(base.MAIN, encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    W = G.API_OUT
    G.settle()
    L.execute('PLAIN_MID = PLAIN:GetMaterial(0)')
    for _ in range(3):
        W.applyAll('test')
        G.settle()
    lv = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    back = [x for x in lv.splitlines() if 'textures back to' in x]
    plain_back = [x for x in back if 'BP_Lune_Skin_Share_C_1' in x]
    left_back = [x for x in back if 'BP_Lune_Skin_Share_C_2' in x]
    check('stale: the game\'s instance showing its parent\'s mod-only texture (unpicked colour) is left alone',
          not plain_back and L.eval('PLAIN:GetMaterial(0) == PLAIN_MID') is True
          and G.colorOf(G.PLAIN) == '/Game/Mods/Sh/T_Lace_D.T_Lace_D', (plain_back[:2], G.colorOf(G.PLAIN)))
    check('  a colour the instance kept from an unpicked variant still goes back to the parent\'s texture, once',
          len(left_back) == 1 and G.colorOf(G.LEFT) == '/Game/Mods/Sh/T_Lace_D.T_Lace_D', (left_back, G.colorOf(G.LEFT)))
    check('  no access violations', L.eval('AV') == 0, L.eval('AVREPORT()'))
    shutil.rmtree(tmp, ignore_errors=True)


def memo_checks():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    on = memo_session(True)
    off = memo_session(False)
    differ = [k for k, (a, b) in enumerate(zip(on[0], off[0])) if a != b]
    check('memo: every look (meshes, materials, textures of 3 copies after 7 steps) is the same without kept reads',
          len(on[0]) == 7 and not differ and on[0][0] != on[0][-1],
          differ and f'step {differ[0]}:\n{on[0][differ[0]]}\n--- without:\n{off[0][differ[0]]}')
    check('  so are the change lines in the live log', on[1] == off[1] and len(on[1]) > 10,
          [x for x in on[1] if x not in off[1]][:5] + ['---'] + [x for x in off[1] if x not in on[1]][:5])
    check('  and the slot states and what Lune wears', on[2] == off[2], (on[2], off[2]))
    check('  Clean puts back the variant\'s mask set in the same pass, and blue replaced red',
          '/Game/ZWDIRT001/' in on[0][3] and '/Game/ZWBLUE001/' in on[0][3] and '/Game/ZWRED0001/' not in on[0][3], on[0][3])
    check('  kept reads cut the reads from engine objects by at least a quarter', on[3] * 4 <= off[3] * 3, (on[3], off[3]))
    check('  no access violations either way', on[4] == 0 and off[4] == 0, (on[4], off[4]))
    memo_white_box(check)
    stale_checks(check)
    return fails


def main():
    tmp = tempfile.mkdtemp(prefix='e33switch_')
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    shutil.copy(os.path.join(os.path.dirname(base.MAIN), 'menu.lua'), scripts)
    open(os.path.join(scripts, 'variants.lua'), 'w').write(VARIANTS)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(SCEN)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    cmd, t = G.CMDS['wardrobe'], L.table_from
    state = L.eval('''function(b) local m = b:GetMaterial(0)
        return b._mesh._path, (m._p.Parent and m._p.Parent._path) or m._path end''')
    fails = 0

    def check(name, body, mesh, mat):
        nonlocal fails
        got = state(body)
        ok = got[0] == mesh + '.SK_Lune_Chic' and got[1] == mat
        print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'   -> mesh={got[0]} mat={got[1]}'))
        fails += (not ok)

    LUNE, NOBODY = G.LUNE, G.NOBODY
    V_MESH, V_MAT = '/Game/Characters/Lune/Chic/SK_Lune_Chic', '/Game/Characters/Lune/Chic/MI_Chic.MI_Chic'
    check('start: vanilla', LUNE, V_MESH, V_MAT)
    cmd(None, t(['1', '1']))
    check('A: A mesh with A\'s lace material', LUNE, '/Game/ZWAAAAAAAAA/Lune/Chic/SK_Lune_Chic', '/Game/ZWAAAAA/Chic/MI_Lace.MI_Lace')
    cmd(None, t(['1', '2']))
    check('A -> B: B mesh with B\'s material, not A\'s lace', LUNE, '/Game/ZWBBBBBBBBB/Lune/Chic/SK_Lune_Chic', '/Game/ZWBBBBB/Chic/MI_Net.MI_Net')
    cmd(None, t(['1', '3']))
    check('B -> C: C mesh with the common-pak material', LUNE, '/Game/ZWCCCCCCCCC/Lune/Chic/SK_Lune_Chic', '/Game/ModCommon/MI_Common.MI_Common')
    cmd(None, t(['1', 'off']))
    check('C -> off: vanilla mesh and vanilla material', LUNE, V_MESH, V_MAT)
    cmd(None, t(['1', '1'])); cmd(None, t(['1', 'off']))
    check('A -> off: vanilla material back (no mod-only leftovers)', LUNE, V_MESH, V_MAT)
    check('unknown-character actor untouched by Lune-only slot', NOBODY, V_MESH, V_MAT)
    cmd(None, t(['2', '1']))
    check('Sciel-only slot leaves Lune alone', LUNE, V_MESH, V_MAT)
    check('Sciel-only slot leaves unknown-character actor alone', NOBODY, V_MESH, V_MAT)
    errors = [l for l in G.getlog().split('\n') if 'failed' in l]
    print(('PASS' if not errors else 'FAIL') + ' no apply errors' + ('' if not errors else f' -> {errors}'))
    fails += bool(errors)

    def avcheck(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)
    base.av_check(avcheck, [L])
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    fails += memo_checks()
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
