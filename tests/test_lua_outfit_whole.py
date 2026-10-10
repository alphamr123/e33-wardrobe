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
}
'''

CHIC = '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic'
TEX_VANILLA = '/Game/Characters/Lune/Chic/T_Chic_D.T_Chic_D'
TEX_MOD = '/Game/Characters/ZWCOLOR01/Chic/T_Chic_D.T_Chic_D'
TEX_OUTFIT = '/Game/Characters/ZWOUTTEX/Chic/T_Chic_D.T_Chic_D'


def run(settings):
    tmp = tempfile.mkdtemp(prefix='e33whole_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(VARIANTS)
    open(os.path.join(mod, 'settings.txt'), 'w').write(settings)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
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
    shutil.rmtree(tmp)


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
    shutil.rmtree(tmp)

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
    shutil.rmtree(tmp)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
