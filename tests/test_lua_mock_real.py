"""Stricter variant of test_lua_mock.py: the mock follows RE-UE4SS source behaviour:

R1  A UFunction that returns a TArray gives a plain Lua table whose elements are RemoteUnrealParam
    (need :get()), not a TArray userdata with ForEach (LuaUObject.cpp call_ufunction_from_lua ->
    push_arrayproperty GetNonTrivialLocal, create_new_if_get_non_trivial_local defaults to true).
R2  Indexing a UClass/BlueprintGeneratedClass object looks the name up in the class's *instance*
    layout (prepare_to_handle: Cast<UStruct>(object) -> FindProperty), so bpClass.InheritableComponentHandler
    returns an invalid UObject; calling a member on it raises "UObject instance is nullptr".
R3  Component templates of a cooked BP are subobjects "<Class path>:<Var>_GEN_VARIABLE" (seen in cooked
    E33 BP_Dialog_FacelessBoy_OrangeForest exports), so StaticFindObject can reach them.
Also counts FindAllOf calls (each = one full GUObjectArray pass) and engine calls made off the game thread.

usage: python test_lua_mock_real.py [path/to/main.lua]
"""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lua_mock as base
from lupa import lua54

MAIN = sys.argv[1] if len(sys.argv) > 1 else base.MAIN

REAL = r'''
THREAD = "load"; OFFTHREAD = {}
local function eng(name) if THREAD ~= "game" and THREAD ~= "load" then table.insert(OFFTHREAD, THREAD .. ":" .. name) end end
INVALID = setmetatable({}, { __index = function(_, k)
    if k == "IsValid" then return function() return false end end
    return INVALID end,
  __call = function() error("Tried calling a member function but the UObject instance is nullptr") end })
-- R1: UFunction TArray return value = plain table of params
function PARAMS(items)
  local t = {}
  for i, v in ipairs(items) do t[i] = setmetatable({}, { __index = function(_, k)
    if k == "get" or k == "Get" then return function() return v end end end }) end
  return t
end
-- R2: class objects only expose UObject methods; any reflected name resolves to an invalid object
local oldIndex = getmetatable(new("X", "/x")).__index
getmetatable(new("X", "/x")).__index = function(t, k)
  if rawget(t, "_isclass") then local m = rawget(Obj or {}, k); if m ~= nil then return m end end
  if rawget(t, "_isclass") then
    local v = oldIndex(t, k)
    if type(v) == "function" then return v end
    return INVALID
  end
  return oldIndex(t, k)
end
-- R3: class assets register their component templates as subobjects
local oldAsset = asset
function asset(kind, pkg, obj, props, fns)
  if kind ~= "BlueprintGeneratedClass" then return oldAsset(kind, pkg, obj, props, fns) end
  local full = pkg .. "." .. obj
  LOADABLE[full] = function()
    local c = new(kind, full, props, fns); c._isclass = true
    for _, rec in ipairs(props.InheritableComponentHandler.Records._items) do
      REGSET(full .. ":" .. rec.ComponentKey.SCSVariableName:ToString() .. "_GEN_VARIABLE", rec.ComponentTemplate)
    end
    return c
  end
end
FINDALL = 0
local oldFindAllOf = FindAllOf
function FindAllOf(n) eng("FindAllOf"); FINDALL = FINDALL + 1; return oldFindAllOf(n) end
local oldSFO = StaticFindObject
function StaticFindObject(p) eng("StaticFindObject"); return oldSFO(p) end
function ExecuteInGameThread(f) local o = THREAD; THREAD = "game"; f(); THREAD = o end
ASYNCRUNS = 0
function ExecuteWithDelay(ms, f) table.insert(DELAYED, function() ASYNCRUNS = ASYNCRUNS + 1; local o = THREAD; THREAD = "async"; f(); THREAD = o end) end
function ExecuteInGameThreadWithDelay(ms, f) table.insert(DELAYED, function() local o = THREAD; THREAD = "game"; f(); THREAD = o end) end
'''

# StaticFindObject in the base mock reads a local REG; expose a setter by patching the mock source.
MOCK = base.MOCK.replace('local REG, ADDR = {}, 0', 'local REG, ADDR = {}, 0\nfunction REGSET(k, v) REG[k] = v end')

SCENARIO = base.SCENARIO.replace(
    'local actor = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_1", { Body = body }, {\n  K2_GetComponentsByClass = function() return TArray({ body }) end })',
    '''mi("/Game/Characters/Lune/Chic/MI_Acc", "MI_Acc", "/Game/Characters/Lune/Chic/T_Chic_D", "T_Chic_D")
asset("SkeletalMesh", "/Game/Characters/Lune/Chic/SK_Acc", "SK_Acc", { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Acc.MI_Acc") } }) })
ACC = meshComp("Acc", get("/Game/Characters/Lune/Chic/SK_Acc.SK_Acc"))
local actor = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_1", { Body = body }, {
  K2_GetComponentsByClass = function() return PARAMS({ body, ACC }) end })''')
assert 'ACC = meshComp' in SCENARIO
SCENARIO = SCENARIO.replace('local skinClass = new("BlueprintGeneratedClass"', 'local skinClass = new("BlueprintGeneratedClass"')


def main():
    tmp = tempfile.mkdtemp(prefix='e33lua_real_')
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    shutil.copy(MAIN, os.path.join(scripts, 'main.lua'))
    shutil.copy(os.path.join(os.path.dirname(MAIN), 'menu.lua'), scripts)
    open(os.path.join(scripts, 'variants.lua'), 'w').write(base.VARIANTS)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.execute('do local o = new("X","/x"); local mt = getmetatable(o); Obj = mt end')
    L.execute(REAL)
    body, actor = L.execute(SCENARIO)
    chunk = L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')
    chunk(open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    cmd, t = G.CMDS['wardrobe'], L.table_from
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    tex_of = L.eval('''function(c)
        local m = c:GetMaterial(0); local tex
        local ok, arr = pcall(function() return m.TextureParameterValues end)
        if ok and arr and arr.ForEach then arr:ForEach(function(_, e) tex = e:get().ParameterValue._path end) end
        if not tex and m._p.Parent then m._p.Parent._p.TextureParameterValues:ForEach(function(_, e) tex = e:get().ParameterValue._path end) end
        return tex end''')
    mesh_path = L.eval('function(b) return b._mesh._path end')

    cmd(None, t(['2', '1']))                                   # Lune color = red
    check('color variant retextures Body (named component)', tex_of(body).startswith('/Game/Characters/ZWCOLOR01/'), tex_of(body))
    check('color variant retextures extra component found via K2_GetComponentsByClass',
          tex_of(G.ACC).startswith('/Game/Characters/ZWCOLOR01/'), tex_of(G.ACC))
    cmd(None, t(['2', 'off']))

    cmd(None, t(['4', '1']))                                   # skin Blueprint override
    check('skin-blueprint override applies template mesh (real UClass indexing)',
          mesh_path(body) == '/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh_path(body))
    cmd(None, t(['4', 'off']))

    cmd(None, t(['1', '1']))
    L.execute('runDelayed()')        # let earlier actions' debounced auto dump run first: measure only the spawn
    L.execute('FINDALL = 0; ASYNCRUNS = 0')
    L.execute('''
      local body2 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a2 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_2", { Body = body2 }, { K2_GetComponentsByClass = function() return PARAMS({ body2 }) end })
      a2._class = ACTORS[1]._class; a2._skin = "BP_CharacterSkinBase_C"; table.insert(ACTORS, a2); NEWBODY = body2
      THREAD = "game"; BEGINPLAY({ get = function() return a2 end }); THREAD = "load"
      runDelayed()
    ''')
    check('new actor gets selection on spawn', L.eval('NEWBODY._mesh._path').startswith('/Game/Characters/ZWOUTFITA/'), L.eval('NEWBODY._mesh._path'))
    n = G.FINDALL
    print(f'INFO full object-array scans (FindAllOf) for one skin spawn: {n}')
    check('no FindAllOf scan on the spawn path', n == 0, n)
    off = list(G.OFFTHREAD.values())
    check('no engine call off the game thread', not off, off)
    check('delayed work scheduled on the game thread (no Lua on the async thread)', G.ASYNCRUNS == 0, f'{G.ASYNCRUNS} async callbacks')
    shutil.rmtree(tmp)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
