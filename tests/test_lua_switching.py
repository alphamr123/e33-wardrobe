"""Live-switching material regressions (needs lupa). Scenarios from the final audit:
  * outfit A -> B -> off with the game's own dynamic material instance on the slot, where the
    variants' meshes bring MOD-ONLY materials (original paths served by <Mod>_Shared_P)
  * an outfit whose mesh uses a material from the mod's common pak (mod-only, unrelocated)
  * character scoping: a Sciel-only slot never touches Lune; a character-scoped slot does not
    apply to an actor whose character can't be told
"""
import os
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
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
