"""Run E33Wardrobe/Scripts/main.lua against a mock UE4SS API (needs: pip install lupa).

The mock models just enough of UE: assets addressed by path, skin actors with mesh
components, materials, material-instance texture parameters and Blueprint templates.
"""
import os
import shutil
import sys
import tempfile

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, '..', 'lua', 'E33Wardrobe', 'Scripts', 'main.lua')

MOCK = r'''
local REG, ADDR = {}, 0
function REGSET(k, v) REG[k] = v end
local LOG = {}
function print(s) table.insert(LOG, s) end
function getlog() return table.concat(LOG) end

-- Like UE4SS: a missing property, an empty object link or a UFunction that returns null reads
-- as an "invalid" UObject. Only IsValid and GetAddress are safe on it: any other method call or
-- property read dereferences null inside UE4SS, an access violation pcall can't catch (PC: the
-- game froze on GetClass() of a missing attach parent). The mock counts them in AV, by call site.
AV, AVSITES = 0, {}
function AVHIT(k)
  AV = AV + 1
  local where = {}                              -- the innermost two lines of main.lua / menu.lua
  for lvl = 3, 60 do
    local info = debug.getinfo(lvl, "Sl")
    if not info or #where == 2 then break end
    local file = (info.source or ""):match("([%w_]+%.lua)$")
    local here = file and (file .. ":" .. tostring(info.currentline))
    if (file == "main.lua" or file == "menu.lua") and here ~= where[#where] then where[#where + 1] = here end
  end
  local site = (#where > 0 and table.concat(where, "<-") or "?") .. " " .. tostring(k)
  AVSITES[site] = (AVSITES[site] or 0) + 1
end
function AVREPORT()
  local out = {}
  for site, n in pairs(AVSITES) do out[#out + 1] = site .. " (x" .. n .. ")" end
  table.sort(out)
  return table.concat(out, "; ")
end
local NULLMT = {}
NULLMT.__index = function(_, k)
  if k == "IsValid" then return function() return false end end
  if k == "GetAddress" then return function() return 0 end end
  if type(k) == "string" and k:sub(1, 1) == "_" then return nil end   -- the mock's own fields
  AVHIT(k)
  return NULLOBJ()
end
NULLMT.__newindex = function(_, k) AVHIT(k) end
NULLMT.__call = function() error("Tried calling a member function but the UObject instance is nullptr") end
function NULLOBJ() return setmetatable({}, NULLMT) end
-- UFunctions that return an object: null when there is none (no owner, no attach parent)
local NULLFN = { GetOwner = true, GetAttachParentActor = true, GetOuter = true }

local Obj = {}
Obj.__index = function(t, k)
  local m = rawget(Obj, k); if m then return m end
  local props = rawget(t, "_p"); if props and props[k] ~= nil then return props[k] end
  local fns = rawget(t, "_f"); if fns and fns[k] then return fns[k] end
  if type(k) ~= "string" or k:sub(1, 1) == "_" then return nil end   -- the mock's own fields
  if NULLFN[k] then return function() return NULLOBJ() end end
  return NULLOBJ()                                                  -- no such property: invalid
end
function Obj.IsValid(o) return true end
function Obj.GetFullName(o) return o._cls .. " " .. o._path end
function Obj.GetFName(o) local n = o._path:match("[%.:]([^%.:]+)$") or o._path; return { ToString = function() return n end } end
function Obj.GetAddress(o) return o._addr end
function Obj.GetClass(o) return o._class end
function Obj.IsA(o, c)
  local k = o._kind
  while k do if c and c._name == k then return true end; k = KINDS[k] end
  return false
end
function Obj.GetSuperStruct(o) return o._super end
KINDS = { SkeletalMeshComponent = "MeshComponent", StaticMeshComponent = "MeshComponent",
          MaterialInstanceDynamic = "MaterialInstance", MaterialInstanceConstant = "MaterialInstance",
          MaterialInstance = "MaterialInterface", Material = "MaterialInterface",
          Texture2D = "Texture", TextureRenderTarget2D = "TextureRenderTarget", TextureRenderTarget = "Texture" }

function new(kind, path, props, fns)
  ADDR = ADDR + 1
  local o = setmetatable({ _kind = kind, _cls = kind, _path = path, _p = props or {}, _f = fns or {}, _addr = ADDR }, Obj)
  return o
end
local function classObj(name) return { _name = name, IsValid = function() return true end } end
local CLASSES = {}
for _, n in ipairs({ "MeshComponent", "SkeletalMeshComponent", "StaticMeshComponent", "MaterialInstanceDynamic",
                     "MaterialInterface", "Texture", "TextureRenderTarget2D" }) do
  CLASSES["/Script/Engine." .. n] = classObj(n)
end

function TArray(items)
  return { ForEach = function(self, fn) for i, v in ipairs(items) do fn(i, { get = function() return v end }) end end, _items = items }
end

LOADABLE = {}   -- full object path -> factory()
LOADCOUNT = 0
function StaticFindObject(p) return CLASSES[p] or REG[p] or NULLOBJ() end
function FindFirstOf(n) return NULLOBJ() end
-- Like UE4SS: LoadAsset only finds assets listed in the game's AssetRegistry (not relocated "/ZW" ones)
function LoadAsset(p) if REG[p] == nil and LOADABLE[p] and not p:find("/ZW") then REG[p] = LOADABLE[p](); LOADCOUNT = LOADCOUNT + 1 end end
local function realLoad(p) if REG[p] == nil and LOADABLE[p] then REG[p] = LOADABLE[p]() end end
CLASSES["/Script/AssetRegistry.Default__AssetRegistryHelpers"] = { IsValid = function() return true end,
  GetAsset = function(self, ad) local full = ad.PackageName:ToString() .. "." .. ad.AssetName:ToString(); realLoad(full); return REG[full] end }
function asset(kind, pkg, obj, props, fns)
  local full = pkg .. "." .. obj
  LOADABLE[full] = function() return new(kind, full, props, fns) end
end
function get(full) realLoad(full); return REG[full] end

ACTORS = {}
function FindAllOf(name) local out = {}; for _, a in ipairs(ACTORS) do if a._skin == name then table.insert(out, a) end end; return #out > 0 and out or nil end
IN_GT = false
function ExecuteInGameThread(f) local o = IN_GT; IN_GT = true; f(); IN_GT = o end
function IsInGameThread() return IN_GT or THREAD == "game" end
-- UE4SS's game-thread loop: tickGT(n) runs every registered loop n times on the "game thread"
GTLOOPS = {}
function LoopInGameThreadWithDelay(ms, f) table.insert(GTLOOPS, f); return #GTLOOPS end
-- game time: os.clock() (wall time on Windows) advances 50 ms per loop tick, not with the CPU
-- time the test itself spends between ticks
MOCK_TICKS = 0
os.clock = function() return MOCK_TICKS * 0.05 end
function tickGT(n)
  for _ = 1, n or 1 do
    MOCK_TICKS = MOCK_TICKS + 1
    for _, f in ipairs(GTLOOPS) do
      local o, ot = IN_GT, THREAD; IN_GT = true; if THREAD ~= nil then THREAD = "game" end
      f(); IN_GT = o; THREAD = ot
    end
  end
end
function settle() tickGT(16) end               -- ~0.8 s of game time: debounced passes, timers
DELAYED = {}
function ExecuteWithDelay(ms, f) table.insert(DELAYED, f) end
function runDelayed() local d = DELAYED; DELAYED = {}; for _, f in ipairs(d) do f() end; settle() end
function LoopAsync() end
KEYS, CMDS = {}, {}
Key = setmetatable({}, { __index = function(_, k) return k end })
ModifierKey = { CONTROL = "C", SHIFT = "S", ALT = "A" }
function RegisterKeyBind(k, mods, fn) local id = k; for _, m in ipairs(mods) do id = m .. "+" .. id end; KEYS[id] = function() fn(); settle() end end
function RegisterConsoleCommandHandler(n, fn)    -- console commands run on the game thread; time passes after
  CMDS[n] = function(...) local o = IN_GT; IN_GT = true; local r = fn(...); IN_GT = o; settle(); return r end
end
BEGINPLAY = nil
function RegisterBeginPlayPostHook(fn) BEGINPLAY = fn end
function FName(s) return { ToString = function() return s end } end

-- a material component helper
function meshComp(name, mesh, mats)
  local c
  local over = {}
  c = new("SkeletalMeshComponent", "/Game/Map.Actor." .. name, { }, {
    GetSkeletalMeshAsset = function(self) return self._mesh or NULLOBJ() end,
    SetSkeletalMeshAsset = function(self, m) self._mesh = m end,
    GetNumMaterials = function(self) local n = 0; for i, _ in pairs(self._mesh._p.Materials._items) do n = i end; return n end,
    GetMaterial = function(self, i) return over[i] or self._mesh._p.Materials._items[i + 1].MaterialInterface end,
    SetMaterial = function(self, i, m) over[i] = m end,
    CreateDynamicMaterialInstance = function(self, i, parent, n)
      local tex = {}
      local mid = new("MaterialInstanceDynamic", "/Game/Maps/Lumiere.Lumiere:PersistentLevel.BP_Lune_Skin_Chic_C_1.Body.MID_" .. i, { Parent = parent, ScalarParameterValues = TArray({}), VectorParameterValues = TArray({}) }, {
        SetTextureParameterValue = function(m, fname, t) tex[fname:ToString()] = t end,
        SetScalarParameterValue = function() end, SetVectorParameterValue = function() end })
      mid._p.TextureParameterValues = setmetatable({}, { __index = function(_, k)
        if k == "ForEach" then return function(_, fn) local i = 0; for nm, t in pairs(tex) do i = i + 1; fn(i, { get = function() return { ParameterInfo = { Name = FName(nm) }, ParameterValue = t } end }) end end end end })
      over[i] = mid
      return mid
    end })
  c._mesh = mesh
  return c
end
'''

SCENARIO = r'''
-- assets: vanilla + two relocated outfit variants + one relocated color variant
local function mi(pkg, obj, texpath, texobj)
  asset("MaterialInstanceConstant", pkg, obj, { TextureParameterValues = TArray({ { ParameterInfo = { Name = FName("BaseColor") }, ParameterValue = get(texpath .. "." .. texobj) } }), Parent = nil })
end
asset("Texture2D", "/Game/Characters/Lune/Chic/T_Chic_D", "T_Chic_D")
asset("Texture2D", "/Game/Characters/ZWCOLOR01/Chic/T_Chic_D", "T_Chic_D")
mi("/Game/Characters/Lune/Chic/MI_Chic", "MI_Chic", "/Game/Characters/Lune/Chic/T_Chic_D", "T_Chic_D")
mi("/Game/Characters/ZWOUTFITA/Chic/MI_Chic", "MI_Chic", "/Game/Characters/Lune/Chic/T_Chic_D", "T_Chic_D")
local function skel(pkg, obj, mipkg)
  asset("SkeletalMesh", pkg, obj, { Materials = TArray({ { MaterialInterface = get(mipkg .. ".MI_Chic") } }) })
end
skel("/Game/Characters/Lune/Chic/SK_Lune_Chic", "SK_Lune_Chic", "/Game/Characters/Lune/Chic/MI_Chic")
skel("/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic", "SK_Lune_Chic", "/Game/Characters/ZWOUTFITA/Chic/MI_Chic")
skel("/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic", "SK_Lune_Chic", "/Game/Characters/Lune/Chic/MI_Chic")

local skinClass = new("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C")
skinClass._super = { GetFName = function() return { ToString = function() return "BP_CharacterSkinBase_C" end } end, IsValid = function() return true end, GetSuperStruct = function() return nil end }
local body = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
local actor = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_1", { Body = body }, {
  K2_GetComponentsByClass = function() return TArray({ body }) end })
actor._class = skinClass
actor._skin = "BP_CharacterSkinBase_C"
table.insert(ACTORS, actor)
local tmpl = meshComp("Body_GEN_VARIABLE", get("/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic.SK_Lune_Chic"))
asset("BlueprintGeneratedClass", "/Game/Characters/ZWCLASS01/BP_Lune_Skin_Chic", "BP_Lune_Skin_Chic_C",
  { InheritableComponentHandler = { Records = TArray({ { ComponentKey = { SCSVariableName = FName("Body") }, ComponentTemplate = tmpl } }) } })
-- cooked component templates are subobjects "<class path>:<Var>_GEN_VARIABLE" (found via StaticFindObject)
REGSET("/Game/Characters/ZWCLASS01/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C:Body_GEN_VARIABLE", tmpl)
return body, actor
'''

VARIANTS = r'''return {
  { mod = "Some Outfit V2", slots = {
    { id = "CC/Lune outfit", label = "Lune outfit", variants = {
      { id = "CC/A", label = "Sleeves + boots", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" },
        ["/Game/Characters/Lune/Chic/MI_Chic"] = { "/Game/Characters/ZWOUTFITA/Chic/MI_Chic", "MI_Chic", "MaterialInstanceConstant" } } },
      { id = "CC/B", label = "Sleeveless", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" } } },
    } },
    { id = "CC/Lune color", label = "Lune color", variants = {
      { id = "CC/red", label = "red", map = {
        ["/Game/Characters/Lune/Chic/T_Chic_D"] = { "/Game/Characters/ZWCOLOR01/Chic/T_Chic_D", "T_Chic_D", "Texture2D" } } },
    } },
    { id = "CC/Sciel outfit", label = "Sciel outfit", character = "Sciel", variants = {
      { id = "CC/S", label = "Sciel sleeveless", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" } } },
    } },
    { id = "CC/Lune skin", label = "Lune skin blueprint", variants = {
      { id = "CC/bp", label = "BP override", map = {
        ["/Game/Characters/Lune/BP_Lune_Skin_Chic"] = { "/Game/Characters/ZWCLASS01/BP_Lune_Skin_Chic", "BP_Lune_Skin_Chic_C", "BlueprintGeneratedClass" } } },
    } },
  } },
}
'''


def av_check(check, runtimes):
    """The last check of every Lua suite: main.lua / menu.lua never touched an invalid object."""
    n = sum(L.eval('AV') for L in runtimes)
    sites = '; '.join(s for s in (L.eval('AVREPORT()') for L in runtimes) if s)
    check('no method call or property read on an invalid UE4SS object (an access violation in game)', n == 0,
          f'{n} at: {sites}')


def main():
    tmp = tempfile.mkdtemp(prefix='e33lua_')
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    shutil.copy(MAIN, scripts)
    shutil.copy(os.path.join(os.path.dirname(MAIN), 'menu.lua'), scripts)
    open(os.path.join(scripts, 'variants.lua'), 'w').write(VARIANTS)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    body, actor = L.execute(SCENARIO)
    chunk = L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')
    src = open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read()
    chunk(src, '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    fails = 0

    def mesh_path():
        return L.eval('function(b) return b._mesh._path end')(body)

    def mat_info(i=0):
        return L.eval('''function(b, i)
            local m = b:GetMaterial(i); local tex
            local ok, arr = pcall(function() return m.TextureParameterValues end)
            if ok and arr then arr:ForEach(function(_, e) tex = e:get().ParameterValue._path end) end
            if not tex and m._p.Parent then
              m._p.Parent._p.TextureParameterValues:ForEach(function(_, e) tex = e:get().ParameterValue._path end)
            end
            return m._path, tex end''')(body, i)

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    cmd = G.CMDS['wardrobe']
    t = L.table_from
    check('loads 4 slots', 'loaded 4 slot(s)' in G.getlog(), G.getlog())
    check('vanilla at start', mesh_path() == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path())

    cmd(None, t(['1', '1']))                                      # Lune outfit = A
    check('outfit A swaps mesh', mesh_path() == '/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path())
    m, tex = mat_info()
    check('outfit A uses its relocated material', m == '/Game/Characters/ZWOUTFITA/Chic/MI_Chic.MI_Chic', m)

    cmd(None, t(['2', '1']))                                      # Lune color = red
    m, tex = mat_info()
    check('color variant retextures via dynamic instance', tex == '/Game/Characters/ZWCOLOR01/Chic/T_Chic_D.T_Chic_D', (m, tex))
    check('  outfit kept while color applied', mesh_path().startswith('/Game/Characters/ZWOUTFITA/'), mesh_path())

    cmd(None, t(['1', '2']))                                      # Lune outfit = B (no own material)
    check('outfit B swaps mesh', mesh_path() == '/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path())
    m, tex = mat_info()
    check('  color still applied after outfit change', tex == '/Game/Characters/ZWCOLOR01/Chic/T_Chic_D.T_Chic_D', (m, tex))

    cmd(None, t(['1', 'off'])); cmd(None, t(['2', 'off']))
    check('off restores vanilla mesh', mesh_path() == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path())
    m, tex = mat_info()
    check('off restores vanilla texture', tex == '/Game/Characters/Lune/Chic/T_Chic_D.T_Chic_D', (m, tex))

    sel = os.path.join(tmp, 'E33Wardrobe', 'selection.txt')
    cmd(None, t(['1', '1']))
    check('selection persisted to selection.txt', 'CC/Lune outfit\tCC/A' in open(sel, encoding='utf-8').read(), open(sel, encoding='utf-8').read())

    # a freshly spawned skin actor gets the current selection via the BeginPlay hook
    L.execute('''
      local body2 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a2 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_2", { Body = body2 }, { K2_GetComponentsByClass = function() return TArray({ body2 }) end })
      a2._class = ACTORS[1]._class; a2._skin = "BP_CharacterSkinBase_C"; table.insert(ACTORS, a2); NEWBODY = body2
      BEGINPLAY({ get = function() return a2 end })
      runDelayed(); tickGT(20)   -- new skins are looked at ~1 s after they appear
    ''')
    check('new actor gets selection on spawn', L.eval('NEWBODY._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'), L.eval('NEWBODY._mesh._path'))

    # PC: "change None [Maelle].Body" a second after a battle: a queued actor whose address now
    # holds another object (its name changed) is not touched again
    L.execute('''
      local b4 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a4 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_4", { Body = b4 }, { K2_GetComponentsByClass = function() return TArray({ b4 }) end })
      a4._class = ACTORS[1]._class; a4._skin = "BP_CharacterSkinBase_C"; BODY4 = b4
      BEGINPLAY({ get = function() return a4 end })
      a4._path = "/Game/Map.PersistentLevel.None"
      runDelayed(); tickGT(160)
    ''')
    check('an actor whose address was reused (name now None) is left alone',
          L.eval('BODY4._mesh._path') == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', L.eval('BODY4._mesh._path'))

    # PC: the game froze while the mod handled BP_Cine_Esquie: a cutscene actor of no party
    # character is left alone when no slot tied to no character is picked
    L.execute('''
      local cc = new("BlueprintGeneratedClass", "/Game/Characters/Esquie/BP_Cine_Esquie.BP_Cine_Esquie_C")
      cc._super = { GetFName = function() return { ToString = function() return "BP_CineCharacter_Main_C" end } end, IsValid = function() return true end, GetSuperStruct = function() return nil end }
      local b5 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a5 = new("BP_Cine_Esquie_C", "/Game/Map.PersistentLevel.BP_Cine_Esquie_C_5", { Body = b5 }, { K2_GetComponentsByClass = function() return TArray({ b5 }) end })
      a5._class = cc; BODY5 = b5
      BEGINPLAY({ get = function() return a5 end })
      runDelayed(); tickGT(160)
    ''')
    check('a cutscene actor of no party character is not touched',
          L.eval('BODY5._mesh._path') == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', L.eval('BODY5._mesh._path'))

    # UE4SS's IsValid doesn't look at these flags: an actor being destroyed (RF_BeginDestroyed) is
    # not touched, and a mesh still loading (RF_NeedLoad) is left for a later look
    L.execute('''
      local b8 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a8 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_8", { Body = b8 }, {
        K2_GetComponentsByClass = function() return TArray({ b8 }) end,
        HasAnyFlags = function(self, f) return (f & 0x8000) ~= 0 end })      -- RF_BeginDestroyed
      a8._class = ACTORS[1]._class; a8._skin = "BP_CharacterSkinBase_C"; BODY8 = b8
      BEGINPLAY({ get = function() return a8 end })
      runDelayed(); tickGT(80)
    ''')
    check('an actor being destroyed (RF_BeginDestroyed) is not touched',
          L.eval('BODY8._mesh._path') == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', L.eval('BODY8._mesh._path'))
    L.execute('''
      local m = get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic")
      LOADING = true
      local mesh9 = setmetatable({}, { __index = function(_, k)
        if k == "HasAnyFlags" then return function(self, f) return LOADING and (f & 0x400) ~= 0 end end
        local v = m[k]; if type(v) == "function" then return function(self, ...) return v(m, ...) end end; return v end })
      local b9 = meshComp("Body", mesh9)
      local a9 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_9", { Body = b9 }, { K2_GetComponentsByClass = function() return TArray({ b9 }) end })
      a9._class = ACTORS[1]._class; a9._skin = "BP_CharacterSkinBase_C"; BODY9 = b9
      BEGINPLAY({ get = function() return a9 end })
      runDelayed(); tickGT(30)
    ''')
    check('a mesh still loading (RF_NeedLoad) is not read at the first look',
          L.eval('BODY9._mesh._path') == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', L.eval('BODY9._mesh._path'))
    L.execute('LOADING = false; tickGT(50)')
    check('  and gets the pick once it has loaded', L.eval('BODY9._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'),
          L.eval('BODY9._mesh._path'))

    # a burst of new actors (a map or a cutscene being set up): new skins wait for calm
    L.execute('''
      local b10 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a10 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_10", { Body = b10 }, { K2_GetComponentsByClass = function() return TArray({ b10 }) end })
      a10._class = ACTORS[1]._class; a10._skin = "BP_CharacterSkinBase_C"; BODY10 = b10
      BEGINPLAY({ get = function() return a10 end })
      local junk = new("BP_Rock_C", "/Game/Map.PersistentLevel.BP_Rock_C_1", {}, {})
      for t = 1, 40 do                              -- 2 s of bursts: 6 new actors every tick
        for _ = 1, 6 do BEGINPLAY({ get = function() return junk end }) end
        tickGT(1)
      end
      BURST_MESH = BODY10._mesh._path
      tickGT(40)
    ''')
    check('during a burst of new actors a new skin is not touched yet',
          L.eval('BURST_MESH') == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', L.eval('BURST_MESH'))
    check('  and gets the pick once things are calm', L.eval('BODY10._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'),
          L.eval('BODY10._mesh._path'))

    # PC (dump of the 3rd freeze): GetClass() on a missing attach parent read address 0x10 inside
    # UE4SS, an access violation pcall can't catch. Invalid objects get IsValid() only, nothing else.
    L.execute('''
      local b11 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a11 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_11", { Body = b11 }, {
        K2_GetComponentsByClass = function() return TArray({ b11 }) end,
        GetOwner = function() return NULLOBJ() end,
        GetAttachParentActor = function() return NULLOBJ() end })
      a11._class = ACTORS[1]._class; a11._skin = "BP_CharacterSkinBase_C"; BODY11 = b11
      BEGINPLAY({ get = function() return a11 end })
      runDelayed(); tickGT(80)
    ''')
    check('no method is called on an invalid object (no owner, no attach parent): AV-safe',
          L.eval('AV') == 0 and L.eval('BODY11._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'),
          (L.eval('AVREPORT()'), L.eval('BODY11._mesh._path')))

    # PC dump: a character's "Face" was a weak/soft reference; UE4SS 1125 reads those as a plain pointer
    # and crashes. Property types come from the class: only plain object pointers are read by name.
    L.execute('''
      local function pr(cls, name) return { GetClass = function() return { GetFName = function() return FName(cls) end } end,
                                           GetFName = function() return FName(name) end } end
      local typed = new("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Lune_Skin_Typed.BP_Lune_Skin_Typed_C")
      typed._super = ACTORS[1]._class._super
      typed._f.ForEachProperty = function(self, cb) cb(pr("ObjectProperty", "Body")); cb(pr("WeakObjectProperty", "Face")) end
      local b13 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a13 = new("BP_Lune_Skin_Typed_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Typed_C_13", {}, {
        K2_GetComponentsByClass = function() return TArray({ b13 }) end })
      rawset(a13, "_p", setmetatable({ Body = b13 }, { __index = function(_, k)
        if k == "Face" then AVHIT("read of a weak reference (Face)") end end }))
      a13._class = typed; a13._skin = "BP_CharacterSkinBase_C"; BODY13 = b13
      AV13 = AV
      BEGINPLAY({ get = function() return a13 end })
      runDelayed(); tickGT(80)
    ''')
    check('a property the class lists as a weak/soft reference is never read (UE4SS 1125 crashes on it)',
          L.eval('AV') == L.eval('AV13'), L.eval('AVREPORT()'))
    check('  and the plain object properties of that class still are (Body gets the pick)',
          L.eval('BODY13._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'), L.eval('BODY13._mesh._path'))

    # PC 17 Oct crash: UE4SS AV in FField::GetFName under UStruct::FindProperty, reading a camp
    # actor's property by name 3 s after the camp loaded. A class still loading is not read.
    L.execute('''
      local function pr(cls, name) return { GetClass = function() return { GetFName = function() return FName(cls) end } end,
                                           GetFName = function() return FName(name) end } end
      local loading = new("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Lune_Skin_Loading.BP_Lune_Skin_Loading_C")
      loading._super = ACTORS[1]._class._super
      loading._f.ForEachProperty = function(self, cb) cb(pr("ObjectProperty", "Body")) end
      CLASS_LOADING = true
      loading._f.HasAnyInternalFlags = function(self, m) return CLASS_LOADING and (m & 0x8000000) ~= 0 end
      local b16 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a16 = new("BP_Lune_Skin_Loading_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Loading_C_16", {}, {
        K2_GetComponentsByClass = function() return TArray({ b16 }) end })
      READS16 = 0
      rawset(a16, "_p", setmetatable({}, { __index = function(_, k) if k == "Body" then READS16 = READS16 + 1; return b16 end end }))
      a16._class = loading; a16._skin = "BP_CharacterSkinBase_C"; BODY16 = b16
      table.insert(ACTORS, a16)
      BEGINPLAY({ get = function() return a16 end })
      runDelayed(); tickGT(80)
      READS_LOADING = READS16
    ''')
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('a skin whose class is still loading: its Body property is not read by name',
          L.eval('READS_LOADING') == 0, (L.eval('READS_LOADING'), [x for x in lv.splitlines() if 'skipped reading' in x][:2]))
    L.execute('CLASS_LOADING = false')
    cmd(None, t(['1', 'off'])); cmd(None, t(['1', '1']))
    check('  once the class has loaded, the next pass reads it and it gets the pick',
          L.eval('READS16') > 0 and L.eval('BODY16._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'),
          (L.eval('READS16'), L.eval('BODY16._mesh._path')))
    L.execute('table.remove(ACTORS)')

    # PC: outfits back to the game's in battle: battle skins get their mesh seconds after the
    # actor spawns (async), so new actors are checked again later, not only after 0.7 s
    L.execute('''
      local b6 = meshComp("Body", nil)
      local a6 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_6", { Body = b6 }, { K2_GetComponentsByClass = function() return TArray({ b6 }) end })
      a6._class = ACTORS[1]._class; a6._skin = "BP_CharacterSkinBase_C"; BODY6 = b6
      BEGINPLAY({ get = function() return a6 end })
      runDelayed(); tickGT(30)                 -- 1.5 s: past the first look, the mesh isn't there yet
      b6._mesh = get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic")
      tickGT(40)
    ''')
    check('a skin whose mesh arrives late (battle) still gets the pick',
          L.eval('BODY6._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'), L.eval('BODY6._mesh._path'))

    cmd(None, t(['1', 'off'])); cmd(None, t(['4', '1']))
    check('skin-blueprint override applies template mesh', mesh_path() == '/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path())
    cmd(None, t(['4', 'off']))
    check('  and reverts when switched off', mesh_path() == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path())

    cmd(None, t(['3', '1']))                                      # Sciel-only slot, actor is Lune
    check('Sciel-only slot leaves Lune alone (shared Chic mesh)', mesh_path() == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path())
    cmd(None, t(['3', 'off']))

    G.KEYS['C+F9']()
    dump = os.path.join(tmp, 'E33Wardrobe', 'dump.txt')
    check('dump writes component report', os.path.isfile(dump) and 'SK_Lune_Chic' in open(dump, encoding='utf-8').read())
    L.execute('''
      local b3 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a3 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_3", { Body = b3 }, { K2_GetComponentsByClass = function() return TArray({ b3 }) end })
      a3._skin = "BP_CharacterSkinBase_C"; table.insert(ACTORS, 1, a3)   -- no class: GetClass() is nil
      b3._f.GetMaterial = function() error("the component died") end      -- fails mid-listing
    ''')
    G.KEYS['C+F9']()
    dt = open(dump, encoding='utf-8').read()
    check('  a character that fails mid-listing is noted, the rest of dump.txt is still written',
          '(listing stopped:' in dt and 'SK_Lune_Chic' in dt.split('(listing stopped:')[1] and 'WARDROBE CHECK' in dt, dt[:400])
    L.execute('table.remove(ACTORS, 1)')
    # PC 17 Oct: the cutscene Sciel from the swapped Blueprint had no AnimClass; what animates a body
    # is the component's AnimScriptInstance and AnimationMode (read only where the class lists them)
    L.execute('''
      local function pr(cls, name) return { GetClass = function() return { GetFName = function() return FName(cls) end } end,
                                           GetFName = function() return FName(name) end } end
      local smc = new("Class", "/Script/Engine.SkeletalMeshComponent")
      smc._f.ForEachProperty = function(self, cb) cb(pr("ObjectProperty", "AnimScriptInstance")); cb(pr("ByteProperty", "AnimationMode")) end
      local inst = new("AnimSingleNodeInstance", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_14.Body.AnimSingleNodeInstance_0")
      inst._class = new("Class", "/Script/Engine.AnimSingleNodeInstance")
      local b14 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      b14._class = smc; b14._p.AnimScriptInstance = inst; b14._p.AnimationMode = 1
      local hat = new("StaticMeshComponent", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_14.Hat14",
                      { StaticMesh = new("StaticMesh", "/Game/Props/SM_Hat.SM_Hat") })
      local a14 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_14", { Body = b14 }, { K2_GetComponentsByClass = function() return TArray({ b14, hat }) end })
      a14._class = ACTORS[1]._class; a14._skin = "BP_CharacterSkinBase_C"; table.insert(ACTORS, 1, a14)
      -- a class that lists AnimScriptInstance as a weak reference (UE4SS 1125 crashed reading those)
      local weak = new("Class", "/Script/Engine.SkeletalMeshComponent")
      weak._f.ForEachProperty = function(self, cb) cb(pr("WeakObjectProperty", "AnimScriptInstance")); cb(pr("ByteProperty", "AnimationMode"))
                                                   cb(pr("WeakObjectProperty", "LeaderPoseComponent")) end
      local b15 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      b15._class = weak
      -- LeaderPoseComponent is a weak pointer in UE 5.4 (17 Oct audit: the dump read it directly)
      rawset(b15, "_p", setmetatable({ AnimationMode = 0 }, { __index = function(_, k)
        if k == "AnimScriptInstance" or k == "LeaderPoseComponent" then AVHIT("read of a weak reference (" .. k .. ")") end end }))
      local a15 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_15", { Body = b15 }, { K2_GetComponentsByClass = function() return TArray({ b15 }) end })
      a15._class = ACTORS[1]._class; a15._skin = "BP_CharacterSkinBase_C"; table.insert(ACTORS, 1, a15)
      AV14 = AV
    ''')
    G.KEYS['C+F9']()
    dt = open(dump, encoding='utf-8').read()
    check('dump: a skeletal body says what animates it (instance class and animation mode)',
          'instance=/Script/Engine.AnimSingleNodeInstance  mode=AnimationSingleNode' in dt, [x for x in dt.splitlines() if 'instance=' in x][:3])
    check('  a body whose class can\'t list them says nil, without reading them (AV-safe)',
          'instance=nil  mode=nil' in dt and L.eval('AV') == L.eval('AV14'), (L.eval('AVREPORT()'), [x for x in dt.splitlines() if 'instance=' in x][:3]))
    a15 = dt[dt.find('BP_Lune_Skin_Chic_C_15'):]
    check('  a class that lists AnimScriptInstance as a weak reference: not read, mode still given',
          'instance=nil  mode=AnimationBlueprint' in a15[:a15.find('ACTOR ', 10)] and L.eval('AV') == L.eval('AV14'),
          (L.eval('AVREPORT()'), a15[:400]))
    hat = dt[dt.find('[Hat14]'):]
    check('  a static mesh component gets no animation line', '[Hat14]' in dt
          and 'instance=' not in hat[:hat.find('[', 2) if hat.find('[', 2) > 0 else len(hat)].split('ACTOR ')[0], hat[:300])
    L.execute('table.remove(ACTORS, 1); table.remove(ACTORS, 1)')
    errors = [l for l in G.getlog().split('\n') if 'failed' in l or 'could not' in l or ' error: ' in l]
    check('no apply errors logged', not errors, errors)
    av_check(check, [L])
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
