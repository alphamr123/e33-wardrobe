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

local Obj = {}
Obj.__index = function(t, k)
  local m = rawget(Obj, k); if m then return m end
  local props = rawget(t, "_p"); if props and props[k] ~= nil then return props[k] end
  local fns = rawget(t, "_f"); if fns and fns[k] then return fns[k] end
  return nil
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
function StaticFindObject(p) return CLASSES[p] or REG[p] or setmetatable({}, { __index = function(_, k) if k == "IsValid" then return function() return false end end end }) end
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
function tickGT(n)
  for _ = 1, n or 1 do
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
    GetSkeletalMeshAsset = function(self) return self._mesh end,
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
      runDelayed()
    ''')
    check('new actor gets selection on spawn', L.eval('NEWBODY._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'), L.eval('NEWBODY._mesh._path'))

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
    ''')
    G.KEYS['C+F9']()
    dt = open(dump, encoding='utf-8').read()
    check('  a character that fails mid-listing is noted, the rest of dump.txt is still written',
          '(listing stopped:' in dt and 'SK_Lune_Chic' in dt.split('(listing stopped:')[1] and 'WARDROBE CHECK' in dt, dt[:400])
    L.execute('table.remove(ACTORS, 1)')
    errors = [l for l in G.getlog().split('\n') if 'failed' in l or 'could not' in l]
    check('no apply errors logged', not errors, errors)
    shutil.rmtree(tmp)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
