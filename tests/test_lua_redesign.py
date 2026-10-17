"""The redesign-B probe in main.lua: reading the outfit the game asks for, coverage of new skins,
the variants' own Blueprints, and the two swap tests (run: python tests/test_lua_redesign.py).

Soft references are modelled as UE4SS 1176 gives them to Lua (GetObjectID():GetAssetPathName(),
KismetSystemLibrary conversions); every read of one is counted, so the 1125 case can prove none
happens there (UE4SS #1433 crashes on them).
"""
import os
import shutil
import sys
import tempfile

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_lua_mock as base  # noqa: E402
import test_lua_dispatch as disp  # noqa: E402

RUNTIMES = []
SHA_1125, SHA_1176 = '527a483b', '1ba38db4'
VANILLA = '/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C'
RELOC = '/Game/Characters/ZWCLASS01/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C'
FACE = '/Game/Characters/Lune/BP_Lune_Face.BP_Lune_Face_C'
BASE = '/Game/Characters/Heros/BP_CharacterSkinBase_Lune.BP_CharacterSkinBase_Lune_C'     # what the PC game asked for
# a Lune outfit that brings its mesh and its own Blueprint (like Cheekier Chic's Sciel outfit)
WEAR_SLOT = '''    { id = "W/Lune outfit", label = "Lune outfit", character = "Lune", variants = {
      { id = "W/bp", label = "Lace with Blueprint", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" },
        ["/Game/Characters/Lune/BP_Lune_Skin_Chic"] = { "/Game/Characters/ZWCLASS01/BP_Lune_Skin_Chic", "BP_Lune_Skin_Chic_C", "BlueprintGeneratedClass" } } },
    } },
'''
WEAR_VARIANTS = base.VARIANTS.replace("    { id = \"CC/Lune skin\"", WEAR_SLOT + "    { id = \"CC/Lune skin\"", 1)

SOFT = r'''
SOFT_READS, SETS, BUILT = 0, 0, 0
ENGINE_SAYS = nil
function softRef(path)
  return { _soft = path, GetObjectID = function(self)
    return { GetAssetPathName = function() SOFT_READS = SOFT_READS + 1; return FName(self._soft) end } end }
end
function param(v)
  return { _v = v, get = function(self) return self._v end, set = function(self, x) SETS = SETS + 1; self._v = x end }
end
REGSET("/Script/Engine.Default__KismetSystemLibrary", { IsValid = function() return true end,
  Conv_SoftClassReferenceToString = function(self, s)
    SOFT_READS = SOFT_READS + 1; ENGINE_READS = (ENGINE_READS or 0) + 1
    return { ToString = function() return ENGINE_SAYS or s._soft end } end,
  Conv_ClassToSoftClassReference = function(self, cls) BUILT = BUILT + 1; return softRef(cls._path) end })
CALLED = {}
POLICY = new("CSAP_SwapAssign", "/Game/Map.PersistentLevel.CSAP_SwapAssign_1", {}, {
  AssignBodySkin = function(self, owner, n, cls)
    table.insert(CALLED, n:ToString() .. " " .. cls._path)
    -- the game's hooks fire for the mod's own call too
    callAssign("AssignBodySkin", n:ToString(), cls, nil, true)
  end })
OWNER = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_1", {}, {})
OWNER._class = new("BlueprintGeneratedClass", "/Game/jRPG/BP_jRPG_Character_World.BP_jRPG_Character_World_C")
-- one call of the game's skin function, pre-hook then post-hook, on the game thread
function callAssign(fn, char, body, face, hard)
  local name = "/Script/SandFall.CharacterSkinAssignPolicy:" .. fn
  local b = body and param(hard and body or softRef(body)) or nil
  local f = face and param(hard and face or softRef(face)) or nil
  local o = IN_GT; IN_GT = true
  PREHOOKS[name](param(POLICY), param(OWNER), param(FName(char)), b, f)
  HOOKS[name](param(POLICY), param(OWNER), param(FName(char)))
  IN_GT = o
  return b
end
function bodyPath(b) return b._v._soft end
-- a skin of class `full` begins play
function spawn(full, n)
  local cls = get(full) or new("BlueprintGeneratedClass", full)
  cls._super = ACTORS[1]._class._super
  local body = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
  local a = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_" .. n, { Body = body },
                { K2_GetComponentsByClass = function() return TArray({ body }) end })
  a._class = cls; a._skin = "BP_CharacterSkinBase_C"
  local o = IN_GT; IN_GT = true; BEGINPLAY({ get = function() return a end }); IN_GT = o
  return a
end
asset("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Lune_Skin_Chic", "BP_Lune_Skin_Chic_C")
'''


def load(sha=SHA_1176, settings='', pick=True, selection='CC/Lune skin\tCC/bp\n', variants=None):
    tmp = tempfile.mkdtemp(prefix='e33b_')
    mod = os.path.join(tmp, 'ue4ss', 'Mods', 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    if sha:
        with open(os.path.join(tmp, 'ue4ss', 'UE4SS.log'), 'w', encoding='utf-8') as f:
            f.write(f'[2026-10-14 21:51:25.6863246] Console created\n'
                    f'[2026-10-14 21:51:25.6925905] UE4SS - v3.0.1 Beta #0 - Git SHA #{sha}\n')
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(variants or base.VARIANTS)
    if pick:
        open(os.path.join(mod, 'selection.txt'), 'w').write(selection)
    if settings:
        open(os.path.join(mod, 'settings.txt'), 'w').write(settings)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    RUNTIMES.append(L)
    L.execute(base.MOCK)
    L.execute(disp.COUNTERS)
    L.execute(base.SCENARIO)
    L.execute(SOFT)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    G.tickGT(5)

    def live():
        return open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    return tmp, L, G, live


def blines(text):
    return [x.split(' ', 2)[2] for x in text.splitlines() if ' B: ' in x]


def main():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    # ------------------------------------------------------------------ UE4SS 1125: no soft reads
    tmp, L, G, live = load(sha=SHA_1125)
    check('the selection picks the variant with its own Blueprint (the fixture works)',
          'CC/bp' in live() or 'BP override' in live(), live()[-500:])
    check('1125: the start line says soft references are not read, and why',
          'B: UE4SS build 527a483b (b_soft = auto): soft references are not read (this build may crash on them, '
          'UE4SS #1433)' in live(), blines(live()))
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('1125: a soft call is not read at all (no soft reference touched)', G.SOFT_READS == 0, G.SOFT_READS)
    check('  and not logged', 'B: call AssignBodyAndFaceSkinAsync' not in live(), blines(live()))
    G.callAssign('AssignBodySkin', 'Lune', G.get(VANILLA), None, True)
    check('1125: a call with a plain class (AssignBodySkin) is read and logged',
          f'B: call AssignBodySkin for Lune (owner BP_jRPG_Character_World_C): body {VANILLA}' in live(), blines(live()))
    check('  still without soft reads', G.SOFT_READS == 0, G.SOFT_READS)
    check('the start line counts the variants that bring their own Blueprint class',
          'B: variants: 1 of 5 bring their own Blueprint class (BP_Lune_Skin_Chic_C); per mod: Some Outfit V2 1/5'
          in live(), blines(live()))
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ settings override the build check
    tmp, L, G, live = load(sha=SHA_1125, settings='b_soft = on\n')
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('b_soft = on reads them on 1125 too', G.SOFT_READS > 0 and 'B: call AssignBodyAndFaceSkinAsync' in live(),
          blines(live()))
    shutil.rmtree(tmp, ignore_errors=True)
    tmp, L, G, live = load(sha=SHA_1176, settings='b_soft = off\n')
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('b_soft = off never reads them, even on 1176', G.SOFT_READS == 0, G.SOFT_READS)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp, L, G, live = load(sha=None)
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('no UE4SS.log (build unknown): not read', G.SOFT_READS == 0 and 'B: UE4SS build unknown' in live(),
          blines(live()))
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ 1176: reading and coverage
    tmp, L, G, live = load()
    check('1176: soft references are read', 'B: UE4SS build 1ba38db4 (b_soft = auto): soft references are read'
          in live(), blines(live()))
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('1176: the call is logged with the body and face classes it asks for',
          f'B: call AssignBodyAndFaceSkinAsync for Lune (owner BP_jRPG_Character_World_C): body {VANILLA}, face {FACE}' in live(), blines(live()))
    check('  b_swap off (default): the call is not changed', G.SETS == 0 and G.bodyPath(b) == VANILLA, G.SETS)
    G.ENGINE_SAYS = '/Game/Other/BP_Other.BP_Other_C'
    G.callAssign('AssignBodySkinAsync', 'Lune', VANILLA)
    check('the two readings are compared: a difference is logged',
          '(the engine reads /Game/Other/BP_Other.BP_Other_C)' in live(), blines(live()))
    G.ENGINE_SAYS = None
    for _ in range(4):
        G.callAssign('AssignBodySkinAsync', 'Sciel', VANILLA)
    check('the same call is logged twice, then only counted',
          sum('B: call AssignBodySkinAsync for Sciel' in x for x in blines(live())) == 2, blines(live()))
    # coverage: a new skin whose class a call asked for, and one no call asked for
    G.tickGT(30)
    G.spawn(VANILLA, 21)
    G.spawn('/Game/Characters/Lune/BP_Unasked.BP_Unasked_C', 22)
    G.tickGT(1250)
    summ = [x for x in blines(live()) if x.startswith('B: ') and 'call(s);' in x]
    check('the minute line: calls, new skins after a call for their class, and those without (named)',
          len(summ) >= 1 and ' 2 new skin(s): 1 after a call for that class, 1 without (BP_Unasked_C)' in summ[0],
          summ)
    check('  asked-for skins with no new one are counted, named as skins (bodies and faces), not calls',
          len(summ) >= 1 and 'asked-for skin(s) (bodies and faces) with no new one within 15 s' in summ[0], summ)
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ swap test: param
    tmp, L, G, live = load(settings='b_swap = param\n')
    G.tickGT(5)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('param: the call\'s body class is replaced by the picked variant\'s own Blueprint',
          G.SETS == 1 and G.bodyPath(b) == RELOC, (G.SETS, b and G.bodyPath(b)))
    check('  the soft reference was made by the engine function from the loaded class', G.BUILT == 1, G.BUILT)
    check('  logged, with the value read back from the call',
          f'B: swap (param, replaces) AssignBodyAndFaceSkinAsync body for Lune: {VANILLA} -> {RELOC}: written; '
          f'the call now asks for {RELOC}' in live(), blines(live()))
    G.tickGT(30)
    G.spawn(RELOC, 31)
    check('  the game spawning the variant\'s class: "swap took"',
          f'B: swap took: the game spawned {RELOC} for Lune (it had asked for {VANILLA})' in live(), blines(live()))
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('  the second call reuses the soft reference (one engine conversion)', G.BUILT == 1, G.BUILT)
    G.tickGT(30)
    G.spawn(VANILLA, 32)
    check('  the game spawning its own class anyway: "did not take"',
          f'B: swap did not take: the game spawned its own {VANILLA} for Lune' in live(), blines(live()))
    G.callAssign('AssignBodySkin', 'Lune', G.get(VANILLA), None, True)
    check('  a call with a plain class is never written (only soft ones in this mode)', G.SETS == 2, G.SETS)
    shutil.rmtree(tmp, ignore_errors=True)

    # PC 15 Oct: two swaps to the same class in one go (menu Sciel twice) gave one "took": each counts
    tmp, L, G, live = load(settings='b_swap = param\n')
    G.tickGT(10)
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Default', VANILLA, FACE)
    G.tickGT(30)
    G.spawn(RELOC, 81)
    G.spawn(RELOC, 82)
    G.tickGT(1250)
    summ = [x for x in blines(live()) if 'call(s);' in x]
    check('two swaps to one class and two spawns of it: both took', live().count('B: swap took') == 2
          and any('swaps 2: took 2, did not take 0' in x for x in summ), (live().count('B: swap took'), summ[-1:]))
    shutil.rmtree(tmp, ignore_errors=True)

    tmp, L, G, live = load(settings='b_swap = param\n', pick=False)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('param, but no variant with its own Blueprint picked: nothing is written',
          G.SETS == 0 and G.bodyPath(b) == VANILLA and 'swap (param)' not in live(), blines(live()))
    shutil.rmtree(tmp, ignore_errors=True)

    tmp, L, G, live = load(sha=SHA_1125, settings='b_swap = param\n')
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('param on 1125: nothing read, nothing written', G.SETS == 0 and G.SOFT_READS == 0, (G.SETS, G.SOFT_READS))
    shutil.rmtree(tmp, ignore_errors=True)

    # a package a variant replaces with something that isn't a class is never written into a call
    tmp, L, G, live = load(settings='b_swap = param\n', selection='CC/Lune outfit\tCC/A\n')
    G.tickGT(20)
    check('  (the mesh variant is picked)', 'Sleeves + boots' in live() or 'CC/A' in live(), live()[-400:])
    b = G.callAssign('AssignBodySkinAsync', 'Lune', '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic')
    check('param: a variant entry that is a mesh, not a class, is never written into a skin call',
          G.SETS == 0 and G.bodyPath(b).endswith('/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic'), (G.SETS, blines(live())))
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ call mode is gone
    # PC 15 Oct: b_swap = call (the mod calling the policy's AssignBodySkin) left Sciel without a body and
    # the characters' animations frozen until the game restarted
    tmp, L, G, live = load(settings='b_swap = call\nwear = W/Lune outfit\n', selection='W/Lune outfit\tW/bp\n',
                           variants=WEAR_VARIANTS)
    G.tickGT(10)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', BASE, FACE)
    G.tickGT(60)
    check('b_swap = call from an old settings.txt: off, with a line saying why; nothing called or written',
          'B: b_swap = call is no longer offered (it broke bodies and animation in game): off' in live()
          and len(list(G.CALLED.values())) == 0 and G.SETS == 0, (blines(live())[:4], G.SETS))
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ once per session after the first map
    prep = r'''
      local function prop(cls, name) return { GetClass = function() return { GetFName = function() return FName(cls) end } end,
                                               GetFName = function() return FName(name) end } end
      REGSET("/Script/Engine.KismetSystemLibrary:Conv_ClassToSoftClassReference", { IsValid = function() return true end,
        ForEachProperty = function(self, cb) cb(prop("ClassProperty", "Class")); cb(prop("SoftClassProperty", "ReturnValue")) end })
      local ccls = new("BlueprintGeneratedClass", "/Game/Gameplay/BP_CharacterSkinComponent.BP_CharacterSkinComponent_C")
      local comp = new("BP_CharacterSkinComponent_C", "/Game/Map.PersistentLevel.Lune_1.BP_CharacterSkinComponent",
        { CurrentCharacterCustomization = { CharacterSkinBase = softRef("/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C") } },
        { GetOwner = function() return OWNER end })
      comp._class = ccls; comp._skin = "BP_CharacterSkinComponent_C"
      table.insert(ACTORS, comp)
    '''
    # the first map is often the title screen: no characters, nothing to prepare yet
    tmp, L, G, live = load()
    G.LOADMAP_POST(None, None)
    G.tickGT(250)
    check('a map without characters (title screen): nothing prepared, no line', 'B: function' not in live(),
          blines(live()))
    L.execute(prep)
    G.LOADMAP_POST(None, None)
    G.tickGT(250)
    check('  the next map with characters prepares it',
          'Conv_ClassToSoftClassReference(ClassProperty Class' in live(), blines(live()))
    shutil.rmtree(tmp, ignore_errors=True)

    # 17 Oct audit: the build test loads Blueprints on the game thread; only in test sessions
    tmp, L, G, live = load(sha=SHA_1176)
    L.execute(prep)
    G.LOADMAP_POST(None, None)
    G.tickGT(250)
    check('1176 with the B test off (the default): functions listed, but no build test (no Blueprint loads)',
          'Conv_ClassToSoftClassReference(' in live() and 'B: built' not in live() and 'B: Blueprint' not in live(),
          blines(live()))
    shutil.rmtree(tmp, ignore_errors=True)

    for sha in (SHA_1176, SHA_1125):
        tmp, L, G, live = load(sha=sha, settings='b_swap = param\n')
        L.execute(prep)
        G.LOADMAP_POST(None, None)
        G.tickGT(40)
        check(f'{sha}: nothing prepared within 2 s of a map load', 'B: function' not in live(), blines(live()))
        G.tickGT(200)
        lv = live()
        check(f'{sha}: the engine functions a redesign would use are listed with their types, or "not found"',
              'B: function KismetSystemLibrary:Conv_ClassToSoftClassReference(ClassProperty Class, SoftClassProperty '
              'ReturnValue)' in lv and 'B: function /Script/Engine.KismetSystemLibrary:Conv_SoftClassReferenceToString '
              'not found' in lv, blines(lv))
        check(f'{sha}:   and the skin component\'s functions',
              'B: function /Game/Gameplay/BP_CharacterSkinComponent.BP_CharacterSkinComponent_C:OverrideCharacterSkin '
              'not found' in lv, blines(lv))
        if sha == SHA_1176:
            check('1176: the build test: a soft reference to the picked variant\'s class reads back the same',
                  f'B: built a soft reference to {RELOC}: reads back the same' in lv, blines(lv))
            check('  and what the game will copy from it: its Body template next to the game\'s own class',
                  'B: Blueprint BP_Lune_Skin_Chic_C: Body mesh /Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic, 0 material '
                  'override(s); the game\'s own /Game/Characters/Lune/BP_Lune_Skin_Chic: Body no Body template' in lv,
                  [x for x in blines(lv) if 'Blueprint' in x])
        else:
            check('1125: no build test (soft references)', 'B: built' not in lv and G.SOFT_READS == 0, blines(lv))
        G.LOADMAP_POST(None, None)
        G.tickGT(250)
        check(f'{sha}: only once per session', live().count('Conv_ClassToSoftClassReference(') == 1, blines(live()))
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ review findings
    tmp, L, G, live = load()
    G.ENGINE_READS = 0
    for _ in range(6):
        G.callAssign('AssignBodySkinAsync', 'Maelle', VANILLA)
    check('the engine\'s second reading is made only for the calls that are logged (2 of 6)', G.ENGINE_READS == 2,
          G.ENGINE_READS)
    L.execute('BADPARAM = param(NULLOBJ())')
    L.execute('local o = IN_GT; IN_GT = true; PREHOOKS["/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkinAsync"]'
              '(param(POLICY), param(OWNER), param(FName("Lune")), BADPARAM); IN_GT = o')
    check('a call whose outfit is an invalid object: logged as nil, no method called on it (AV counter below)',
          'B: call AssignBodySkinAsync for Lune (owner BP_jRPG_Character_World_C): body nil' in live(), blines(live())[-3:])
    shutil.rmtree(tmp, ignore_errors=True)

    # param mode: the class is prepared after a pick, never loaded inside the game's call
    tmp, L, G, live = load(settings='b_swap = param\n')      # load() runs 0.25 s: before the 0.5 s preparation
    L.execute('REGSET("' + RELOC + '", nil)')   # the class isn't in memory
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('param: right after the pick the class isn\'t ready: the call is left alone and the line says so',
          G.SETS == 0 and 'is not ready yet (prepared after a pick)' in live(), blines(live())[-3:])
    G.tickGT(20)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    check('  prepared outside the call, the next call is swapped', G.SETS == 1 and G.bodyPath(b) == RELOC,
          (G.SETS, blines(live())[-3:]))
    shutil.rmtree(tmp, ignore_errors=True)

    # param mode with "Apply to new skins" off: the swap's skin is still checked
    tmp, L, G, live = load(settings='b_swap = param\nauto_apply = false\n')
    G.tickGT(10)
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    G.spawn(RELOC, 41)
    check('param with auto apply off: "swap took" is still seen', 'B: swap took' in live(), blines(live())[-3:])
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ Wear: swap whatever the game asks for
    assert 'W/Lune outfit' in WEAR_VARIANTS
    wsel = 'W/Lune outfit\tW/bp\n'
    tmp, L, G, live = load(settings='b_swap = param\nwear = W/Lune outfit\n', selection=wsel, variants=WEAR_VARIANTS)
    G.tickGT(10)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', BASE, FACE)
    check('Wear on: the base skin the game asks for is swapped for the worn variant\'s own Blueprint',
          G.SETS == 1 and G.bodyPath(b) == RELOC and f'B: swap (param, Wear) AssignBodyAndFaceSkinAsync body for Lune: '
          f'{BASE} -> {RELOC}: written' in live(), (G.SETS, blines(live())[-2:]))
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Default', BASE, FACE)
    check('  a "Default" copy of Lune (character from the class path) too', G.SETS == 2 and G.bodyPath(b) == RELOC,
          (G.SETS, blines(live())[-2:]))
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Sciel', BASE.replace('Lune', 'Sciel'), FACE)
    check('  another character is left alone', G.SETS == 2, G.SETS)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', RELOC, FACE)
    check('  a call already asking for the variant\'s class is not written again', G.SETS == 2, G.SETS)
    G.tickGT(30)
    G.spawn(RELOC, 51)
    check('  the spawn of the variant\'s class: "swap took"', 'B: swap took: the game spawned ' + RELOC in live(),
          blines(live())[-2:])
    shutil.rmtree(tmp, ignore_errors=True)

    tmp, L, G, live = load(settings='b_swap = param\n', selection=wsel, variants=WEAR_VARIANTS)
    G.tickGT(10)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', BASE, FACE)
    check('Wear off for that slot: the base skin is left alone', G.SETS == 0 and G.bodyPath(b) == BASE, G.SETS)
    shutil.rmtree(tmp, ignore_errors=True)

    mixed = WEAR_SLOT.replace('character = "Lune", ', '').replace('W/Lune outfit', 'W/mixed').replace(
        '["/Game/Characters/Lune/BP_Lune_Skin_Chic"] = { "/Game/Characters/ZWCLASS01/BP_Lune_Skin_Chic"',
        '["/Game/Characters/Sciel/BP_Sciel_Skin_Chic"] = { "/Game/Characters/ZWCLASS01/BP_Lune_Skin_Chic"')
    assert 'Sciel/BP_Sciel_Skin_Chic' in mixed and 'character =' not in mixed
    tmp, L, G, live = load(settings='b_swap = param\nwear = W/mixed\n', selection='W/mixed\tW/bp\n',
                           variants=base.VARIANTS.replace("    { id = \"CC/Lune skin\"", mixed + "    { id = \"CC/Lune skin\"", 1))
    G.tickGT(10)
    b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', BASE, FACE)
    check('Wear in a slot for several characters: Lune never gets the Blueprint of Sciel\'s outfit', G.SETS == 0,
          (G.SETS, blines(live())[-2:]))
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ new skins the re-check drops: the reason
    tmp, L, G, live = load(selection=wsel, variants=WEAR_VARIANTS)
    G.tickGT(80)
    G.spawn('/Game/Characters/Other/BP_SkinNoName.BP_SkinNoName_C', 61)
    a = G.spawn('/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C', 62)
    L.eval('function(a) a.IsValid = function() return false end end')(a)
    G.tickGT(40)
    lv = live()
    check('a new skin of no known character (only character slots picked): not looked at, and the line says why',
          'new skin BP_Lune_Skin_Chic_C_61 not looked at (round 1): no party character found for it' in lv,
          [x for x in lv.splitlines() if 'not looked' in x])
    check('  a skin gone before the look: the line says so',
          'new skin BP_Lune_Skin_Chic_C_62 not looked at (round 1): gone (invalid object) before the look' in lv,
          [x for x in lv.splitlines() if 'not looked' in x])
    shutil.rmtree(tmp, ignore_errors=True)

    tmp, L, G, live = load(selection=wsel, variants=WEAR_VARIANTS)
    G.tickGT(80)
    a = G.spawn('/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C', 71)
    L.eval('function(a) a._f.HasAnyInternalFlags = function(self, m) return (m & 0x4000000) ~= 0 end end')(a)
    r = G.spawn('/Game/Characters/Lune/BP_Lune_Skin_Chic.BP_Lune_Skin_Chic_C', 72)
    L.eval('function(a) a._path = "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_99" end')(r)
    G.tickGT(40)
    lv = live()
    check('a skin skipped for its flags: the line names the flag (PC: battle skins, visible, all skipped)',
          'new skin BP_Lune_Skin_Chic_C_71 not looked at (round 1): skipped by its flags: Async (internal)' in lv,
          [x for x in lv.splitlines() if 'not looked' in x])
    check('  a skin renamed before the look: the line gives the new name',
          'new skin BP_Lune_Skin_Chic_C_72 not looked at (round 1): renamed before the look: now BP_Lune_Skin_Chic_C_99'
          in lv, [x for x in lv.splitlines() if 'not looked' in x])
    shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ fix15: the body after a swap
    # PC 16 Oct: the cutscene Sciel's Body had no mesh after the game used the swapped Blueprint
    for body_mesh, broken in ((None, True), ('/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', False)):
        tmp, L, G, live = load(settings='b_swap = param\n')
        G.tickGT(10)
        # the pawn's Body component, as the game lists it (the body check reads no property by name)
        L.eval('''function(p) OWNER._p.Body = meshComp("Body", p and get(p) or nil)
                  local b = OWNER._p.Body
                  OWNER._f.K2_GetComponentsByClass = function() return TArray({ b }) end end''')(body_mesh)
        G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
        G.tickGT(20)
        G.spawn(RELOC, 91)
        G.tickGT(10)
        early = 'B: swap broke the body' in live() or 'B: after the swap' in live()
        G.tickGT(40)
        lv = live()
        if broken:
            check('a swap that leaves the dressed character\'s Body without a mesh: logged ~2 s later (not at once)',
                  not early and 'B: swap broke the body: BP_jRPG_Character_World_C_1 (Lune).Body has no mesh after the game '
                  'used ' + RELOC in lv, blines(lv)[-3:])
            sets = G.SETS
            b = G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
            check('  and that class is not swapped in again this session', G.SETS == sets and G.bodyPath(b) == VANILLA,
                  (G.SETS, sets))
        else:
            check('a swap whose character shows a mesh afterwards: logged, and swaps go on',
                  'B: after the swap BP_jRPG_Character_World_C_1 (Lune).Body shows /Game/Characters/Lune/Chic/SK_Lune_Chic' in lv
                  and 'broke' not in lv, blines(lv)[-3:])
            sets = G.SETS
            G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
            check('  (the next call is swapped as usual)', G.SETS == sets + 1, (G.SETS, sets))
        shutil.rmtree(tmp, ignore_errors=True)
    # PC 17 Oct: the world pawn's body is a component named at run time (SkeletalMeshComponent_<n>):
    # the check said only "has no Body or CharacterMesh0"; now it lists what its skeletal meshes show
    tmp, L, G, live = load(settings='b_swap = param\n')
    G.tickGT(10)
    L.execute('''
      OWNER._p.Body = nil
      local rt = meshComp("SkeletalMeshComponent_2147474781", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local hat = new("StaticMeshComponent", "/Game/Map.Actor.StaticMeshComponent_2147474790",
                      { StaticMesh = new("StaticMesh", "/Game/Props/SM_Hat.SM_Hat") })
      OWNER._f.K2_GetComponentsByClass = function() return TArray({ hat, rt }) end
      AV_RT = AV
    ''')
    G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
    G.tickGT(20)
    G.spawn(RELOC, 92)
    G.tickGT(50)
    lv = live()
    check('a swap on a pawn without Body/CharacterMesh0: the check lists its run-time named skeletal meshes',
          'has no Body or CharacterMesh0 to check; its skeletal meshes: SkeletalMeshComponent_2147474781 '
          '/Game/Characters/Lune/Chic/SK_Lune_Chic' in lv and 'broke' not in lv and L.eval('AV') == L.eval('AV_RT')
          and 'SM_Hat' not in lv and 'StaticMeshComponent_2147474790' not in lv,
          (blines(lv)[-3:], L.eval('AVREPORT()')))
    shutil.rmtree(tmp, ignore_errors=True)
    # PC 17 Oct: the body found by its own name. Battle and companion pawns: CharacterMesh0 (the
    # Character's Mesh property); world pawns: a component named Body with no Body property, next to
    # an empty "SkeletalMesh" component that is not the body
    LUNE_SK = '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic'
    for comp, mesh, extra, want in (
            ('CharacterMesh0', LUNE_SK, False, '.CharacterMesh0 shows /Game/Characters/Lune/Chic/SK_Lune_Chic'),
            ('CharacterMesh0', None, False, 'B: swap broke the body: BP_jRPG_Character_World_C_1 (Lune).CharacterMesh0 '
                                            'has no mesh after the game used ' + RELOC),
            ('Body', LUNE_SK, True, '.Body shows /Game/Characters/Lune/Chic/SK_Lune_Chic')):
        tmp, L, G, live = load(settings='b_swap = param\n')
        G.tickGT(10)
        L.eval('''function(name, p, extra)
          OWNER._p.Body = nil
          local body = meshComp(name, p and get(p) or nil)
          local list = { body }
          if extra then table.insert(list, 1, meshComp("SkeletalMesh", nil)) end
          OWNER._f.K2_GetComponentsByClass = function() return TArray(list) end
        end''')(comp, mesh, extra)
        G.callAssign('AssignBodyAndFaceSkinAsync', 'Lune', VANILLA, FACE)
        G.tickGT(20)
        G.spawn(RELOC, 93)
        G.tickGT(50)
        lv = live()
        check(f'the body by its own name ({comp}{", next to an empty SkeletalMesh" if extra else ""}, '
              f'{"mesh" if mesh else "no mesh"}): judged, not just listed',
              want in lv and 'has no Body or CharacterMesh0' not in lv
              and (('broke' in lv) == (mesh is None)), blines(lv)[-3:])
        shutil.rmtree(tmp, ignore_errors=True)

    # PC 14-15 Oct: the 2 s companion watch ran FindAllOf for every learned class in one frame
    # (up to 757 ms). Now classes are taken in turn within the 8 ms budget
    tmp, L, G, live = load()
    G.tickGT(80)
    L.execute('''
      for i, cn in ipairs({ "BP_Lune_Battle_C", "BP_Maelle_Battle_C", "BP_Pawn_AICompanion_Sciel_C" }) do
        local cls = new("BlueprintGeneratedClass", "/Game/Battle/" .. cn:sub(1, -3) .. "." .. cn)
        cls._super = { GetFName = function() return FName("Character") end, IsValid = function() return true end,
                       GetSuperStruct = function() return nil end }
        local a = new(cn, "/Game/Map.PersistentLevel." .. cn .. "_" .. (500 + i))
        a._class = cls
        local o = IN_GT; IN_GT = true; BEGINPLAY({ get = function() return a end }); IN_GT = o
      end
      WATCHED = {}
      local realFind, realClock, extra = FindAllOf, os.clock, 0
      os.clock = function() return realClock() + extra end      -- the mock's clock moves per tick
      FindAllOf = function(name)
        if type(name) == "string" and (name:find("_Battle_C$") or name:find("^BP_Pawn_")) then
          table.insert(WATCHED, name)
          extra = extra + 0.010                                  -- a slow full object scan
          return {}
        end
        return realFind(name)
      end
    ''')
    rounds = []
    for _ in range(3):
        L.execute('WATCHED = {}')
        G.tickGT(40)
        rounds.append(list(L.eval('WATCHED').values()))
    check('the companion watch: one slow class scan per round, the next round goes on with the next class',
          all(len(r) == 1 for r in rounds) and len({r[0] for r in rounds}) == 3, rounds)
    shutil.rmtree(tmp, ignore_errors=True)

    # PC 17 Oct: ~6000 BeginPlays a minute in battle, nearly all of classes the mod never dresses
    # (projectiles, effects): their class name is checked once per class, not once per actor
    tmp, L, G, live = load(settings='b_swap = param\n')
    G.tickGT(80)
    n_names = L.execute('''
      local base = { GetFName = function() return FName("Actor") end, IsValid = function() return true end,
                     GetSuperStruct = function() return nil end }
      local names = 0
      local cls = new("BlueprintGeneratedClass", "/Game/FX/BP_FreeAimProjectile_Battle.BP_FreeAimProjectile_Battle_C", {},
                      { GetFName = function() names = names + 1; return FName("BP_FreeAimProjectile_Battle_C") end })
      cls._super = base
      for i = 1, 40 do
        local a = new("BP_FreeAimProjectile_Battle_C", "/Game/Map.PersistentLevel.BP_FreeAimProjectile_Battle_C_" .. i)
        a._class = cls
        local o = IN_GT; IN_GT = true; BEGINPLAY({ get = function() return a end }); IN_GT = o
      end
      return names
    ''')
    check('40 BeginPlays of a class the mod never dresses: its name is read about once per actor, not more',
          n_names <= 45, n_names)
    shutil.rmtree(tmp, ignore_errors=True)

    # fix15: battle and companion characters are known by their class names (passes don't run when a
    # battle starts; PC: no battle character was looked at with Cheeki worn over Chic)
    tmp, L, G, live = load()
    G.tickGT(80)
    L.execute('''
      local function pawn(cls, n)
        local c = new("BlueprintGeneratedClass", cls)
        local body = meshComp("CharacterMesh0", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
        local a = new(c._path:match("%.(.+)$"), "/Game/Map.PersistentLevel." .. c._path:match("%.(.+)$") .. "_" .. n,
                      { CharacterMesh0 = body }, { K2_GetComponentsByClass = function() return TArray({ body }) end })
        a._class = c
        IN_GT = true; BEGINPLAY({ get = function() return a end }); IN_GT = false
      end
      pawn("/Game/Characters/Battle/BP_Sciel_Battle.BP_Sciel_Battle_C", 1)
      pawn("/Game/Characters/Battle/BP_Verso_Battle2.BP_Verso_Battle2_C", 2)
      pawn("/Game/Characters/AI/BP_Pawn_AICompanion_Lune.BP_Pawn_AICompanion_Lune_C", 3)
      pawn("/Game/Enemies/BP_EnemyBattle_Chalier_Sword.BP_EnemyBattle_Chalier_Sword_C", 4)
      pawn("/Game/Characters/BP_CharacterBattle_Dummy.BP_CharacterBattle_Dummy_C", 5)
    ''')
    G.tickGT(40)
    lv = live()
    check('battle and companion characters are looked at when they appear, by their class name',
          all(f'game spawned {n}' in lv for n in ('BP_Sciel_Battle_C_1', 'BP_Verso_Battle2_C_2', 'BP_Pawn_AICompanion_Lune_C_3')),
          [x for x in lv.splitlines() if 'game spawned' in x][-5:])
    check('  enemies and the battle dummy are not', 'BP_EnemyBattle_Chalier_Sword_C_4' not in lv
          and 'BP_CharacterBattle_Dummy_C_5' not in lv, [x for x in lv.splitlines() if 'game spawned' in x][-5:])
    check('  the "new skin" line says what the character shows',
          any(x.endswith('shows CharacterMesh0 SK_Lune_Chic') for x in lv.splitlines() if 'new skin BP_Sciel_Battle_C_1' in x),
          [x for x in lv.splitlines() if 'new skin BP_Sciel_Battle' in x])
    shutil.rmtree(tmp, ignore_errors=True)

    base.av_check(check, RUNTIMES)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
