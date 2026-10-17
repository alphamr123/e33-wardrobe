"""Clean: blood and dirt off the characters (needs lupa).

Studied from three Nexus pak mods (#143 Dirt And Blood Remover, #115 Clean Characters and Bloody
Effects Remover, #151 Dirt and Blood Reducer): they only replace the BTLS mask textures under
/Game/MetaHumans/BTLS_Textures/, #143 and #115 with all-zero masks. The characters' materials take
the masks as texture parameters (BTLS_Map on faces, BTLS_Map_Tiling on bodies; PC dump).
Checks:
  * Clean on: every texture parameter showing a BTLS mask (not a normal map) gets an all-zero
    render target (RGBA8, alpha 0, owned by the game instance, made once); also a mask that is
    only set on the parent material, and one on a plain material (the slot gets an instance;
    PC: 6-18 such masks were left); normals and colours are left
  * cutscene blood / dirt / dust levels to 0, sweat and tears stay; kept at 0 every second
  * saved in settings.txt; Clean off puts the game's own masks back; on again reuses the texture
  * a pass that re-dresses a character blanks its masks again
  * console "wardrobe clean" / "wardrobe clean off"; the dump lists scalar values
  * main.lua keeps headroom under Lua's 200-locals limit
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
local function params(vals, kind)            -- UE4SS-like TArray of F<kind>ParameterValue, read live
  return setmetatable({}, { __index = function(_, k)
    if k == "ForEach" then return function(_, fn)
      local i = 0
      for nm, v in pairs(vals) do i = i + 1; fn(i, { get = function() return { ParameterInfo = { Name = FName(nm) }, ParameterValue = v } end }) end
    end end end })
end
local function tex(path) local leaf = path:match("[^/]+$"); return new("Texture2D", path .. "." .. leaf) end
MASK_BODY = tex("/Game/MetaHumans/BTLS_Textures/Main_Characters/Lune_Body_BTLS")
NORMAL_BODY = tex("/Game/MetaHumans/BTLS_Textures/Main_Characters/Lune_Body_Normal_BTLS")
COLOR_BODY = tex("/Game/Characters/Heros/Lune/Textures_V2/Lune_Body_BaseColor")
MASK_FACE = tex("/Game/MetaHumans/BTLS_Textures/Main_Characters/Lune_Face_BTLS_4")
BODYTEX = { BTLS_Map_Tiling = MASK_BODY, BTLS_Normal_Tiling = NORMAL_BODY, Color_MAIN = COLOR_BODY }
BODYSC = { Wetness = 0.3 }
local bodyParent = new("MaterialInstanceConstant", "/Game/Characters/Heros/Lune/Outfit/MI_Body_Lune.MI_Body_Lune",
  { ScalarParameterValues = params({}), TextureParameterValues = params({}) })
BODYMID = new("MaterialInstanceDynamic", "/Game/Map.PersistentLevel.Pawn.Body.MID_MI_Body_Lune_1",
  { Parent = bodyParent, ScalarParameterValues = params(BODYSC), TextureParameterValues = params(BODYTEX) },
  { SetTextureParameterValue = function(self, name, t) BODYTEX[name:ToString()] = t end })
-- the face's mask is only set on its parent material
local faceParent = new("MaterialInstanceConstant", "/Game/MetaHumans/Lune/MI_HeadSynthesized_Baked_Lune.MI_HeadSynthesized_Baked_Lune",
  { ScalarParameterValues = params({}), TextureParameterValues = params({ BTLS_Map = MASK_FACE }) })
FACETEX = {}
FACEMID = new("MaterialInstanceDynamic", "/Game/Map.PersistentLevel.Face.head_shader_shader",
  { Parent = faceParent, ScalarParameterValues = params({}), TextureParameterValues = params(FACETEX) },
  { SetTextureParameterValue = function(self, name, t) FACETEX[name:ToString()] = t end })
-- a material without a dynamic instance
MICTEX = { BTLS_Map = MASK_FACE }
local mic = new("MaterialInstanceConstant", "/Game/MetaHumans/Lune/MI_Other.MI_Other",
  { ScalarParameterValues = params({}), TextureParameterValues = params(MICTEX) })
local mesh = new("SkeletalMesh", "/Game/Characters/Heros/Lune/SK_Lune_Chic_Skin.SK_Lune_Chic_Skin", { Materials = TArray({}) })
local function comp(path, mats)
  return new("SkeletalMeshComponent", path, {}, {
    GetSkeletalMeshAsset = function() return mesh end,
    GetNumMaterials = function() return #mats end,
    GetMaterial = function(self, i) return mats[i + 1] end,
    CreateDynamicMaterialInstance = function(self, i, parent)
      NEWTEX = {}
      local mid = new("MaterialInstanceDynamic", path .. ".MID_" .. i,
        { Parent = parent, ScalarParameterValues = params({}), TextureParameterValues = params(NEWTEX) },
        { SetTextureParameterValue = function(_, name, t) NEWTEX[name:ToString()] = t end })
      mats[i + 1] = mid
      return mid
    end })
end
BODY = comp("/Game/Map.PersistentLevel.Skin.Body", { BODYMID, mic })
FACE = comp("/Game/Map.PersistentLevel.Skin.Face", { FACEMID })
local skin = new("BP_CharacterSkin_LuneOutfit_Chic_C", "/Game/Map.PersistentLevel.BP_CharacterSkin_LuneOutfit_Chic_C_1",
  { Body = BODY, Face = FACE }, { K2_GetComponentsByClass = function() return TArray({ BODY, FACE }) end })
skin._skin = "BP_CharacterSkinBase_C"
skin._class = new("BlueprintGeneratedClass", "/Game/Characters/Heros/Lune/Customization/Skin/BP_CharacterSkin_LuneOutfit_Chic.BP_CharacterSkin_LuneOutfit_Chic_C")
table.insert(ACTORS, skin)
CINE = new("BP_CineCharacter_Main_C", "/Game/Map.PersistentLevel.BP_CineCharacter_Main_C_1",
  { BloodLevel = 0.8, DirtLevel = 0.5, DustingLevel = 0.2, SweatLevel = 0.6, TearsLevel = 0.4 },
  { K2_GetComponentsByClass = function() return TArray({}) end })
CINE._skin = "BP_CineCharacter_Main_C"
CINE._class = new("BlueprintGeneratedClass", "/Game/Characters/BP_CineCharacter_Main.BP_CineCharacter_Main_C")
table.insert(ACTORS, CINE)
function cine(k) return CINE[k] end         -- written values live on the object, like UE4SS properties
function RegisterLoadMapPreHook(fn) MAP_PRE = fn end
-- the render target library and the game instance
GI = new("GameInstance", "/Engine/Transient.BP_GameInstance_C_0")
function FindFirstOf(n) if n == "GameInstance" then return GI end; return NULLOBJ() end
RT_MADE, RT_ARGS, RT_CLEARED = 0, nil, 0
local baseSFO = StaticFindObject
function StaticFindObject(p)
  if p == "/Script/Engine.Default__KismetRenderingLibrary" then
    return new("KismetRenderingLibrary", "/Script/Engine.Default__KismetRenderingLibrary", {}, {
      CreateRenderTarget2D = function(self, owner, w, h, fmt, color, mips, uav)
        RT_MADE = RT_MADE + 1
        RT_ARGS = { owner = owner, w = w, h = h, fmt = fmt, a = color.A, r = color.R }
        RT = new("TextureRenderTarget2D", "/Engine/Transient.BP_GameInstance_C_0:TextureRenderTarget2D_" .. RT_MADE)
        return RT
      end,
      ClearRenderTarget2D = function() RT_CLEARED = RT_CLEARED + 1 end })
  end
  return baseSFO(p)
end
'''

VARIANTS = 'return { }\n'


def main():
    tmp = tempfile.mkdtemp(prefix='e33clean_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(VARIANTS)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(SCEN)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    G.settle()
    W = G.API_OUT
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    live = lambda: open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()  # noqa: E731
    settings = lambda: open(os.path.join(mod, 'settings.txt'), encoding='utf-8').read()  # noqa: E731
    same = L.eval('function(a, b) return a ~= nil and b ~= nil and a:GetAddress() == b:GetAddress() end')
    on_gt = L.eval('function(f, x) local r; ExecuteInGameThread(function() r = f(x) end); return r end')   # the menu's thread
    r = on_gt(W.setClean, True)
    BT, FT = G.BODYTEX, G.FACETEX
    check('Clean on: the body mask (BTLS_Map_Tiling) shows an all-zero texture', same(BT.BTLS_Map_Tiling, G.RT), BT.BTLS_Map_Tiling)
    check('  the face mask set only on the parent material: set on the instance', same(FT.BTLS_Map, G.RT), FT.BTLS_Map)
    check('  normal map and colour left alone', same(BT.BTLS_Normal_Tiling, G.NORMAL_BODY) and same(BT.Color_MAIN, G.COLOR_BODY))
    check('  a plain material showing a mask: the slot gets an instance, blanked; the material asset is untouched',
          same(G.NEWTEX.BTLS_Map, G.RT) and same(G.MICTEX.BTLS_Map, G.MASK_FACE)
          and 'without a dynamic instance' not in live(), (G.NEWTEX.BTLS_Map, live()[-300:]))
    a = G.RT_ARGS
    check('  the texture: a 4x4 RGBA8 render target cleared to 0 (alpha 0 too), owned by the game instance',
          G.RT_MADE == 1 and a.w == 4 and a.fmt == 2 and a.a == 0 and a.r == 0 and same(a.owner, G.GI) and G.RT_CLEARED == 1,
          (G.RT_MADE, a.w, a.fmt, a.a))
    check('cutscene pawn: blood, dirt and dust levels to 0; sweat and tears stay',
          G.cine('BloodLevel') == 0 and G.cine('DirtLevel') == 0 and G.cine('DustingLevel') == 0
          and G.cine('SweatLevel') == 0.6 and G.cine('TearsLevel') == 0.4,
          [G.cine(k) for k in ('BloodLevel', 'DirtLevel', 'DustingLevel', 'SweatLevel', 'TearsLevel')])
    check('the result for the menu and the log', r.set == 3 and r.cine == 3
          and list(r.names.values()) == ['BTLS_Map', 'BTLS_Map_Tiling']
          and 'clean (switched on): 3 mask(s) blanked' in live() and 'clean = true' in settings(),
          (r.set, r.cine, list(r.names.values())))
    G.CINE.BloodLevel = 0.5                                   # a cutscene animates it again
    G.tickGT(25)
    check('while on: cutscene levels back to 0 every second', G.cine('BloodLevel') == 0, G.cine('BloodLevel'))
    BT.BTLS_Map_Tiling = G.MASK_BODY                          # the character was re-dressed
    W.applyAll()
    G.settle()
    check('a pass over a re-dressed character blanks its mask again', same(BT.BTLS_Map_Tiling, G.RT), BT.BTLS_Map_Tiling)
    n = on_gt(W.setClean, False)
    check('Clean off: the game\'s own masks back', same(BT.BTLS_Map_Tiling, G.MASK_BODY) and same(FT.BTLS_Map, G.MASK_FACE)
          and same(G.NEWTEX.BTLS_Map, G.MASK_FACE) and n == 3 and 'clean = false' in settings(), (n, BT.BTLS_Map_Tiling))
    on_gt(W.setClean, True)
    check('on again: the same texture is used (made once)', G.RT_MADE == 1 and same(BT.BTLS_Map_Tiling, G.RT))
    G.CMDS['wardrobe'](None, L.table_from(['clean', 'off']))
    check('console "wardrobe clean off" / "wardrobe clean"', same(BT.BTLS_Map_Tiling, G.MASK_BODY))
    G.CMDS['wardrobe'](None, L.table_from(['clean']))
    check('  ', same(BT.BTLS_Map_Tiling, G.RT) and 'clean (console)' in live())
    # the engine frees objects nothing references; a freed address can hold another object later
    G.RT._path = '/Engine/Transient.SomethingElse_7'           # same address, another object now
    on_gt(W.setClean, False)
    on_gt(W.setClean, True)
    check('a texture whose address now holds another object is not reused: a new one is made',
          G.RT_MADE == 2 and same(BT.BTLS_Map_Tiling, G.RT) and G.RT._path.endswith('TextureRenderTarget2D_2'),
          (G.RT_MADE, G.RT._path))
    G.FACEMID._path = '/Game/Map.PersistentLevel.Other.MID_Replaced'   # the game rebuilt it; address reused
    FT.BTLS_Map = G.RT
    n = on_gt(W.setClean, False)
    check('restore skips an instance the game replaced in the same level (its address now holds another one)',
          n == 2 and same(FT.BTLS_Map, G.RT) and same(BT.BTLS_Map_Tiling, G.MASK_BODY), (n, FT.BTLS_Map))
    G.FACEMID._path = '/Game/Map.PersistentLevel.Face.head_shader_shader'
    on_gt(W.setClean, True)
    G.MAP_PRE()                                               # level change: everything of the old world goes
    G.BODYMID._path = '/Game/Map.PersistentLevel.Other.MID_Someone_Else'    # its address reused
    n = on_gt(W.setClean, False)
    check('after a level change nothing old is touched on restore (the instance there now is another one)',
          n == 0 and same(BT.BTLS_Map_Tiling, G.RT), (n, BT.BTLS_Map_Tiling))
    G.BODYMID._path = '/Game/Map.PersistentLevel.Pawn.Body.MID_MI_Body_Lune_1'
    BT.BTLS_Map_Tiling = G.MASK_BODY
    G.KEYS['C+F9']()
    dump = open(os.path.join(mod, 'dump.txt'), encoding='utf-8').read()
    check('the dump lists scalar values', 'scalar Wetness = 0.3' in dump, dump[:600])
    src = open(base.MAIN, encoding='utf-8').read()
    n = 0
    for line in src.split('\n'):
        m = re.match(r'^local (function )?([A-Za-z_][\w, ]*)', line)
        if m:
            n += 1 if m.group(1) else len([x for x in m.group(2).split('=')[0].split(',') if x.strip()])
    check(f'main.lua: {n} top-level locals, under 197 (Lua\'s limit is 200 per function)', n < 197, n)
    base.av_check(check, [L])
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
