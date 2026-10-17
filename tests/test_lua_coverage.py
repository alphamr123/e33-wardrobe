"""Which actors get swapped, for which character, and which pick wins (needs lupa).

Real-PC run 3 showed base-body mods ("Lune Body Test", "ScielBodyLight") replace
SK_<Character>_Placeholder, a mesh shown by pawns that aren't outfit skin actors, and mods with
one option had no character. Scenarios:
  * a world pawn (not a skin class) showing SK_Lune_Placeholder gets the "Body" variant; its
    class is learned so a new pawn of that class is swapped on BeginPlay
  * slot characters guessed from the mod name ("Lune Body Test", "ScielBodyLight" CamelCase,
    "Maelle - Claudia Set"), Sciel's slot leaves the Lune pawn alone
  * two slots replacing the same mesh: the later pick wins, re-picking brings the other back
  * slot states: "on" when applied, "unused" when nothing loaded shows it; dump check section
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
local function mi(pkg, obj) asset("MaterialInstanceConstant", pkg, obj, { TextureParameterValues = TArray({}) }) end
mi("/Game/Characters/Heros/Lune/MI_Body", "MI_Body")
mi("/Game/Materials/Hide_Material", "Hide_Material")
mi("/Game/Characters/Heros/Lune/MI_Pot", "MI_Pot")
mi("/Game/ZWPOTA0001/Heros/Lune/MI_Pot", "MI_Pot")
local function skel(pkg, obj)
  asset("SkeletalMesh", pkg, obj, { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Heros/Lune/MI_Body.MI_Body") } }) })
end
skel("/Game/Characters/Heros/Lune/SK_Lune_Placeholder", "SK_Lune_Placeholder")
skel("/Game/ZWBODY0001/Heros/Lune/SK_Lune_Placeholder", "SK_Lune_Placeholder")
skel("/Game/ZWBODY0002/Heros/Lune/SK_Lune_Placeholder", "SK_Lune_Placeholder")
skel("/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin", "SK_Lune_Chic_Skin")
skel("/Game/ZWOUTA0001/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin", "SK_Lune_Chic_Skin")
skel("/Game/ZWOUTB0001/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin", "SK_Lune_Chic_Skin")
skel("/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Potato_Skin", "SK_Lune_Potato_Skin")
skel("/Game/ZWPOTA0001/Heros/Lune/Customization/Skin/SK_Lune_Potato_Skin", "SK_Lune_Potato_Skin")
skel("/Game/Characters/Heros/Maelle/SK_Maelle_Placeholder", "SK_Maelle_Placeholder")
SFOS = {}
local baseSFO = StaticFindObject
function StaticFindObject(p) SFOS[p] = (SFOS[p] or 0) + 1; return baseSFO(p) end
GTDEPTH, NESTED, EIGT_CALLS = 0, 0, 0
function ExecuteInGameThread(f)
  EIGT_CALLS = EIGT_CALLS + 1
  if GTDEPTH > 0 then NESTED = NESTED + 1 end
  GTDEPTH = GTDEPTH + 1; local o = IN_GT; IN_GT = true; f(); IN_GT = o; GTDEPTH = GTDEPTH - 1
end

COMPS = {}
local function pawn(classPath, name, meshFull, skinBase)
  local cls = new("BlueprintGeneratedClass", classPath)
  cls._super = { GetFName = function() return { ToString = function() return skinBase or "Character" end } end,
                 IsValid = function() return true end, GetSuperStruct = function() return nil end }
  local body = meshComp("Body", get(meshFull))
  local a = new(name, "/Game/Map.PersistentLevel." .. name, { Body = body },
                { K2_GetComponentsByClass = function() return TArray({ body }) end })
  a._class = cls
  a._skin = skinBase
  body._f.GetOwner = function() return a end
  table.insert(COMPS, body)
  table.insert(ACTORS, a)
  return a, body, cls
end
-- generic world pawn: class path names no character, not a skin class
PAWN, PAWNBODY, PAWNCLS = pawn("/Game/Characters/BP_jRPG_Character_World.BP_jRPG_Character_World_C",
  "BP_jRPG_Character_World_C_1", "/Game/Characters/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder", nil)
-- Lune's outfit skin actor
SKIN, SKINBODY = pawn("/Game/Characters/Heros/Lune/Customization/Skin/BP_CharacterSkin_LuneOutfit_Chic.BP_CharacterSkin_LuneOutfit_Chic_C",
  "BP_CharacterSkin_LuneOutfit_Chic_C_1", "/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin.SK_Lune_Chic_Skin",
  "BP_CharacterSkinBase_C")
-- the game's swap policy: the world pawn renders the skin through the SAME Body component
SHARED = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_9", { Body = SKINBODY },
             { K2_GetComponentsByClass = function() return TArray({ SKINBODY }) end })
SHARED._class = PAWNCLS
SKINBODY._f.GetOwner = function() return SHARED end   -- the component belongs to the pawn
NMAT = 0
local gnm = SKINBODY._f.GetNumMaterials
SKINBODY._f.GetNumMaterials = function(self) NMAT = NMAT + 1; return gnm(self) end
TMPL = meshComp("Body_GEN_VARIABLE", get("/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin.SK_Lune_Chic_Skin"))
TMPL._path = "/Game/Characters/Heros/Lune/Customization/Skin/BP_CharacterSkin_LuneOutfit_Chic.BP_CharacterSkin_LuneOutfit_Chic_C:Body_GEN_VARIABLE"
REGSET("/Game/Characters/Heros/Lune/Customization/Skin/BP_CharacterSkin_LuneOutfit_Chic.BP_CharacterSkin_LuneOutfit_Chic_C:Body_GEN_VARIABLE", TMPL)
REDRESSED = 0
SKINCOMP = new("BP_CharacterSkinComponent_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_9.BP_CharacterSkinComponent", {},
  { ApplyCurrentCharacterSkin = function() REDRESSED = REDRESSED + 1 end })
local baseFAO = FindAllOf
function FindAllOf(n)
  if n == "SkeletalMeshComponent" then return COMPS end
  if n == "BP_CharacterSkinComponent_C" then return { SKINCOMP } end
  return baseFAO(n)
end
-- PC: the walking character (BP_jRPG_Character_World_C) has only run-time named mesh components, and
-- they show meshes of more than one character, so its character can't be told
function mixedActor()
  local cls = new("BlueprintGeneratedClass", "/Game/jRPG/BP_jRPG_Character_World2.BP_jRPG_Character_World2_C")
  cls._super = { GetFName = function() return { ToString = function() return "Character" end } end,
                 IsValid = function() return true end, GetSuperStruct = function() return nil end }
  local c1 = meshComp("SkeletalMeshComponent_2147406712", get("/Game/ZWPOTA0001/Heros/Lune/Customization/Skin/SK_Lune_Potato_Skin.SK_Lune_Potato_Skin"))
  local c2 = meshComp("SkeletalMeshComponent_2147406713", get("/Game/Characters/Heros/Maelle/SK_Maelle_Placeholder.SK_Maelle_Placeholder"))
  c1._path = "/Game/Map.PersistentLevel.BP_jRPG_Character_World2_C_5.SkeletalMeshComponent_2147406712"
  c2._path = "/Game/Map.PersistentLevel.BP_jRPG_Character_World2_C_5.SkeletalMeshComponent_2147406713"
  local a = new("BP_jRPG_Character_World2_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World2_C_5", {},
                { K2_GetComponentsByClass = function() return TArray({ c1, c2 }) end })
  a._class = cls
  c1._f.GetOwner = function() return a end
  c2._f.GetOwner = function() return a end
  table.insert(COMPS, c1); table.insert(COMPS, c2)
  return a, c1
end
function newPawn()   -- a second pawn of the learned class, spawned later
  local body = meshComp("Body", get("/Game/Characters/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder"))
  local a = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_2", { Body = body },
                { K2_GetComponentsByClass = function() return TArray({ body }) end })
  a._class = PAWNCLS
  body._f.GetOwner = function() return a end
  table.insert(COMPS, body)
  return a, body
end
'''

E = lambda o, n: f'{{ "{n}", "{o.rsplit("/", 1)[1]}", "SkeletalMesh", true }}'
PH = '/Game/Characters/Heros/Lune/SK_Lune_Placeholder'
CHIC = '/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin'
VARIANTS = f'''return {{
  {{ mod = "Lune Body Test", slots = {{
    {{ id = "LLT/Body", label = "Lune Body Test: Body", variants = {{
      {{ id = "LLT/Body/Clean", label = "Clean", map = {{ ["{PH}"] = {E(PH, "/Game/ZWBODY0001/Heros/Lune/SK_Lune_Placeholder")} }} }},
      {{ id = "LLT/Body/PH", label = "PH", map = {{ ["{PH}"] = {E(PH, "/Game/ZWBODY0002/Heros/Lune/SK_Lune_Placeholder")} }} }} }} }} }} }},
  {{ mod = "Outfits A", slots = {{
    {{ id = "A/Main", label = "Outfits A: Main", variants = {{
      {{ id = "A/", label = "", map = {{ ["{CHIC}"] = {E(CHIC, "/Game/ZWOUTA0001/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin")} }} }} }} }} }} }},
  {{ mod = "Lune Outfits B", slots = {{
    {{ id = "B/Main", label = "Lune Outfits B: Main", variants = {{
      {{ id = "B/", label = "", map = {{ ["{CHIC}"] = {E(CHIC, "/Game/ZWOUTB0001/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin")} }} }} }} }} }} }},
  {{ mod = "ScielBodyLight", slots = {{
    {{ id = "S/Main", label = "ScielBodyLight: Main", variants = {{
      {{ id = "S/", label = "", map = {{ ["{PH}"] = {E(PH, "/Game/ZWBODY0001/Heros/Lune/SK_Lune_Placeholder")} }} }} }} }} }} }},
  {{ mod = "Infernal", slots = {{
    {{ id = "I/Main", label = "Infernal: Main", character = "Lune", variants = {{
      {{ id = "I/", label = "on", map = {{ ["/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Potato_Skin"] = {{ "/Game/ZWPOTA0001/Heros/Lune/Customization/Skin/SK_Lune_Potato_Skin", "SK_Lune_Potato_Skin", "SkeletalMesh", true }},
        ["/Game/Characters/Heros/Lune/MI_Pot"] = {{ "/Game/ZWPOTA0001/Heros/Lune/MI_Pot", "MI_Pot", "MaterialInstanceConstant", true }} }} }} }} }} }} }},
  {{ mod = "Grp", slots = {{
    {{ id = "G/outfit", label = "Grp: Lune outfit", character = "Lune", variants = {{
      {{ id = "G/o/lace", label = "Lace dress: Lace lune-sleeves-boots", map = {{ ["/Game/Grp/T_o1"] = {{ "/Game/ZWGRP00001/T_o1", "T_o1", "Texture2D", true }} }} }},
      {{ id = "G/o/chic", label = "Non-Lace dress: chic lune-sleeves-boots", map = {{ ["/Game/Grp/T_o2"] = {{ "/Game/ZWGRP00001/T_o2", "T_o2", "Texture2D", true }} }} }} }} }},
    {{ id = "G/color", label = "Grp: Lune color", character = "Lune", variants = {{
      {{ id = "G/c/lblack", label = "Lace dress: Lune Lace-chic black", map = {{ ["/Game/Grp/T_c1"] = {{ "/Game/ZWGRP00001/T_c1", "T_c1", "Texture2D", true }} }} }},
      {{ id = "G/c/lred", label = "Lace dress: Lune Lace-chic red", map = {{ ["/Game/Grp/T_c2"] = {{ "/Game/ZWGRP00001/T_c2", "T_c2", "Texture2D", true }} }} }},
      {{ id = "G/c/black", label = "Non-Lace dress: Lune chic black", map = {{ ["/Game/Grp/T_c3"] = {{ "/Game/ZWGRP00001/T_c3", "T_c3", "Texture2D", true }} }} }},
      {{ id = "G/c/red", label = "Non-Lace dress: Lune chic red", map = {{ ["/Game/Grp/T_c4"] = {{ "/Game/ZWGRP00001/T_c4", "T_c4", "Texture2D", true }} }} }} }} }} }} }},
  {{ mod = "Grp", slots = {{
    {{ id = "G/fix", label = "Grp: _only Lune mod_fix_P", character = "Lune", variants = {{
      {{ id = "G/f/lace", label = "Lace dress: only Lune mod fix", map = {{ ["/Game/Grp/BP_Fix"] = {{ "/Game/ZWGRP00002/BP_Fix", "BP_Fix_C", "BlueprintGeneratedClass", true }} }} }},
      {{ id = "G/f/chic", label = "Non-Lace dress: only Lune mod fix", map = {{ ["/Game/Grp/BP_Fix"] = {{ "/Game/ZWGRP00003/BP_Fix", "BP_Fix_C", "BlueprintGeneratedClass", true }} }} }} }} }} }} }},
  {{ mod = "Maelle - Claudia Set", slots = {{
    {{ id = "M/Main", label = "Maelle - Claudia Set: Main", variants = {{
      {{ id = "M/", label = "", map = {{ ["/Game/Characters/Heros/Maelle/SK_Maelle_Placeholder"] = {{ "/Game/ZWMAEL0001/Heros/Maelle/SK_Maelle_Placeholder", "SK_Maelle_Placeholder", "SkeletalMesh", true }} }} }} }} }} }} }},
}}
'''


def main():
    tmp = tempfile.mkdtemp(prefix='e33cov_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    for f in ('main.lua', 'menu.lua'):
        shutil.copy(os.path.join(os.path.dirname(base.MAIN), f), scripts)
    open(os.path.join(scripts, 'variants.lua'), 'w').write(VARIANTS)
    open(os.path.join(mod, 'settings.txt'), 'w').write('auto_wear = false\n')   # Wear by hand here (see test_lua_outfit_whole)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute('API_OUT = nil')
    L.execute(SCEN)
    # capture the API main.lua hands to menu.lua
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    W = G.API_OUT
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    mesh = L.eval('function(b) return b._mesh._path end')
    slots = {s.id: (i, s) for i, s in W.slots().items()}
    ch = {k: v[1].character for k, v in slots.items()}
    check('character from the mod name: "Lune Body Test" -> Lune', ch['LLT/Body'] == 'Lune', ch)
    check('  CamelCase "ScielBodyLight" -> Sciel', ch['S/Main'] == 'Sciel', ch)
    check('  "Maelle - Claudia Set" -> Maelle', ch['M/Main'] == 'Maelle', ch)
    check('  no name: from the assets it replaces ("Outfits A" -> Lune)', ch['A/Main'] == 'Lune', ch)
    check('empty variant label shown as "on"', slots['A/Main'][1].variants[1].label == 'on')

    cmd = G.CMDS['wardrobe']
    t = L.table_from
    idx = {k: v[0] for k, v in slots.items()}
    check('before any pass: no state yet', W.slotState(idx['LLT/Body']) is None)
    cmd(None, t([str(idx['LLT/Body']), '1']))
    check('a non-skin pawn showing SK_Lune_Placeholder gets the body-mod body', mesh(G.PAWNBODY).startswith('/Game/ZWBODY0001/'),
          mesh(G.PAWNBODY))
    check('  its character is read from its own meshes (class path names none)', 'other(s) showing a replaced mesh' in G.getlog())
    check('  slot state "on"', W.slotState(idx['LLT/Body']) == 'on', W.slotState(idx['LLT/Body']))
    a2, b2 = L.eval('newPawn')()
    G.BEGINPLAY(L.eval('function(a) return { get = function() return a end } end')(a2))
    G.runDelayed(); G.tickGT(20)                               # new skins are looked at ~1 s after they appear
    check('a new pawn of that learned class is swapped on BeginPlay', mesh(b2).startswith('/Game/ZWBODY0001/'), mesh(b2))
    # PC: the party members walking behind the leader are re-created after battles, mostly without a
    # BeginPlay the mod sees; they kept the game's outfit until Fix look. The learned classes are
    # looked up every 2 s.
    b3 = L.execute('''
      local body = meshComp("Body", get("/Game/Characters/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder"))
      local a = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_3", { Body = body },
                    { K2_GetComponentsByClass = function() return TArray({ body }) end })
      a._class = PAWNCLS; a._skin = "BP_jRPG_Character_World_C"   -- FindAllOf(class name) finds it
      body._f.GetOwner = function() return a end
      table.insert(COMPS, body); table.insert(ACTORS, a)
      return body
    ''')
    G.tickGT(10)
    early = mesh(b3)
    G.tickGT(50)
    check('a pawn of a learned class re-created without BeginPlay (companion after a battle) is dressed within ~3 s',
          early.startswith(PH) and mesh(b3).startswith('/Game/ZWBODY0001/'), (early, mesh(b3)))
    # and the 2 s look-up costs nothing while nothing changes: in a later, quiet minute no pawn is
    # looked at again (the 'stats' line counts every look)
    G.tickGT(2500)                                              # two stats lines: the last minute is quiet
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    st = [x for x in lv.splitlines() if ' stats (' in x]
    import re as _re
    looks = int(_re.search(r'(\d+) actor look', st[-1]).group(1)) if st else -1
    check('  the 2 s look-up re-dresses nothing that is already dressed (stats: actor looks in the last minute)',
          len(st) >= 2 and looks == 0, st[-2:] if st else 'no stats line')
    cmd(None, t([str(idx['LLT/Body']), 'off']))
    check('switching it off restores the game body', mesh(G.PAWNBODY) == PH + '.SK_Lune_Placeholder', mesh(G.PAWNBODY))

    cmd(None, t([str(idx['S/Main']), '1']))
    check('Sciel\'s body slot (same mesh path) leaves the Lune pawn alone', mesh(G.PAWNBODY) == PH + '.SK_Lune_Placeholder',
          mesh(G.PAWNBODY))
    check('  and is "unused" (no Sciel loaded)', W.slotState(idx['S/Main']) == 'unused', W.slotState(idx['S/Main']))
    cmd(None, t([str(idx['S/Main']), 'off']))
    cmd(None, t([str(idx['M/Main']), '1']))
    check('Maelle mod with no Maelle loaded: "unused"', W.slotState(idx['M/Main']) == 'unused')

    # last pick wins where two slots replace the same mesh
    cmd(None, t([str(idx['A/Main']), '1']))
    cmd(None, t([str(idx['B/Main']), '1']))
    check('two slots replace the same outfit: the later pick (B) shows', mesh(G.SKINBODY).startswith('/Game/ZWOUTB0001/'),
          mesh(G.SKINBODY))
    ov = W.overlaps(idx['A/Main'])
    check('  overlaps() reports A as covered by B', len(ov) == 1 and ov[1].idx == idx['B/Main'] and not ov[1].wins,
          [(o.idx, o.wins) for o in ov.values()])
    cmd(None, t([str(idx['A/Main']), '1']))
    check('  picking A again brings A on top', mesh(G.SKINBODY).startswith('/Game/ZWOUTA0001/'), mesh(G.SKINBODY))
    sel = open(os.path.join(mod, 'selection.txt'), encoding='utf-8').read().splitlines()
    check('  selection.txt keeps pick order (A last)', sel and sel[-1].startswith('A/Main'), sel)
    G.KEYS['C+F8']()                                                # reload from disk
    check('  order survives a reload', mesh(G.SKINBODY).startswith('/Game/ZWOUTA0001/'), mesh(G.SKINBODY))

    # one pass handles a component shared by a skin actor and its pawn once
    G.NMAT = 0
    W.applyAll()
    G.settle()
    check('a Body shared by the skin actor and the pawn is handled once per pass', G.NMAT == 1, G.NMAT)

    # Lace / Non-Lace pieces of one mod stay in the same group
    def selmap():
        return dict(l.split('\t') for l in open(os.path.join(mod, 'selection.txt'), encoding='utf-8').read().splitlines() if '\t' in l)
    W.setVariant(idx['G/color'], 3)                                   # Non-Lace black
    changed = W.setVariant(idx['G/outfit'], 1)                        # Lace outfit
    check('picking a Lace outfit switches a Non-Lace color to the matching Lace color',
          selmap().get('G/color') == 'G/c/lblack' and len(changed) == 1, (selmap(), list(changed.values())))
    W.setVariant(idx['G/color'], 4)                                   # Non-Lace red
    check('  and picking a Non-Lace color switches the outfit back to Non-Lace',
          selmap().get('G/outfit') == 'G/o/chic', selmap())
    W.setVariant(idx['G/color'], 0)
    G.settle()
    W.setVariant(idx['G/outfit'], 1)
    G.settle()
    check('  a vanilla color is left alone', 'G/color' not in selmap(), selmap())
    W.settings.match_groups = False
    W.setVariant(idx['G/color'], 3)
    G.settle()
    check('  matching can be switched off (Settings)', selmap().get('G/outfit') == 'G/o/lace'
          and selmap().get('G/color') == 'G/c/black', selmap())
    W.settings.match_groups = True
    W.setVariant(idx['G/color'], 3)                                   # Non-Lace black
    W.setVariant(idx['G/fix'], 1)                                     # a Blueprint-only fix pak, "Lace"
    check('a Blueprint-only fix pak does not flip the colour group (PC: clicking it changed Lune color)',
          selmap().get('G/color') == 'G/c/black', selmap())
    check('  and Wear is only offered for slots with a mesh', W.canWear(slots['G/outfit'][1]) is False
          and W.canWear(slots['I/Main'][1]) is True)
    W.setVariant(idx['G/fix'], 0)
    G.settle()
    W.setVariant(idx['G/color'], 0)
    G.settle()
    W.setVariant(idx['G/outfit'], 0)
    G.settle()

    # "Wear": an outfit replacer (Potato bag) put over the outfit Lune wears now (Chic)
    cmd(None, t([str(idx['A/Main']), 'off']))
    cmd(None, t([str(idx['B/Main']), 'off']))
    cmd(None, t([str(idx['I/Main']), '1']))
    check('a replacer for another outfit does nothing on Chic and is "unused"',
          mesh(G.SKINBODY) == CHIC + '.SK_Lune_Chic_Skin' and W.slotState(idx['I/Main']) == 'unused',
          (mesh(G.SKINBODY), W.slotState(idx['I/Main'])))
    hide = L.eval('function(b) return b:CreateDynamicMaterialInstance(0, get("/Game/Materials/Hide_Material.Hide_Material"), FName("None")) end')(G.SKINBODY)
    slot0 = L.eval('function(b) local m = b:GetMaterial(0); return (m._p.Parent and m._p.Parent._path) or m._path end')
    W.setWear('I/Main', True)
    G.settle()
    check('Wear on: the Potato mesh is put over Chic, state "on"',
          mesh(G.SKINBODY).startswith('/Game/ZWPOTA0001/') and W.slotState(idx['I/Main']) == 'on',
          (mesh(G.SKINBODY), W.slotState(idx['I/Main'])))
    check('  the old outfit\'s game-set material (hidden slot) is not kept on the new mesh',
          slot0(G.SKINBODY) == '/Game/Characters/Heros/Lune/MI_Body.MI_Body', slot0(G.SKINBODY))
    check('  only on the character\'s body (Lune), saved in settings.txt',
          'wear = I/Main' in open(os.path.join(mod, 'settings.txt'), encoding='utf-8').read())
    cmd(None, t([str(idx['A/Main']), '1']))
    check('  a later outfit pick does not undo the worn mesh', mesh(G.SKINBODY).startswith('/Game/ZWPOTA0001/'),
          mesh(G.SKINBODY))
    W.setWear('I/Main', False)
    G.settle()
    check('Wear off: back to what the game shows, through the active variants (Outfits A)',
          mesh(G.SKINBODY).startswith('/Game/ZWOUTA0001/'), mesh(G.SKINBODY))
    check('  and the game\'s own material setup comes back (the hidden slot)',
          L.eval('function(b, h) return b:GetMaterial(0) == h end')(G.SKINBODY, hide), slot0(G.SKINBODY))
    cmd(None, t([str(idx['I/Main']), 'off']))
    # the menu calls setVariant from its game-thread tick (ExecuteInGameThread + W.gt)
    G.ExecuteInGameThread(lambda: W.gt(lambda: W.setVariant(idx['G/outfit'], 1)))
    G.settle()
    G.ExecuteInGameThread(lambda: W.gt(lambda: W.setVariant(idx['G/outfit'], 0)))
    G.settle()
    check('no game-thread work queued from inside a game-thread callback (menu path)', G.NESTED == 0, G.NESTED)
    check('ExecuteInGameThread is called once (the start-up hop) and never again: keys, clicks, timers '
          'and passes all run in the game-thread loop', G.EIGT_CALLS == 3, G.EIGT_CALLS)   # +2 calls this test made

    # ---- PC session 2: Wear on a body mod, switch its variants, switch it off -> the outfit comes back
    cmd(None, t([str(idx['A/Main']), 'off']))
    W.setWear('LLT/Body', True)
    G.settle()
    cmd(None, t([str(idx['LLT/Body']), '1']))                         # Clean, worn over Chic
    check('Wear + Body Clean: the body-mod body is worn', mesh(G.SKINBODY).startswith('/Game/ZWBODY0001/'), mesh(G.SKINBODY))
    cmd(None, t([str(idx['LLT/Body']), '2']))                         # PH
    cmd(None, t([str(idx['LLT/Body']), '1']))                         # Clean again
    cmd(None, t([str(idx['LLT/Body']), '2']))                         # PH
    check('  switching between worn variants', mesh(G.SKINBODY).startswith('/Game/ZWBODY0002/'), mesh(G.SKINBODY))
    cmd(None, t([str(idx['LLT/Body']), 'off']))
    check('  Body off: back to the outfit Lune wore (Chic), not to a previous body-mod mesh (the PC bug)',
          mesh(G.SKINBODY) == CHIC + '.SK_Lune_Chic_Skin', mesh(G.SKINBODY))
    cmd(None, t([str(idx['A/Main']), '1']))
    check('  and an outfit mod works again afterwards', mesh(G.SKINBODY).startswith('/Game/ZWOUTA0001/'), mesh(G.SKINBODY))
    cmd(None, t([str(idx['LLT/Body']), '1']))
    W.setWear('LLT/Body', False)
    G.settle()
    check('Wear off with the variant still picked: back to the outfit (A)', mesh(G.SKINBODY).startswith('/Game/ZWOUTA0001/'),
          mesh(G.SKINBODY))
    cmd(None, t([str(idx['LLT/Body']), 'off']))
    cmd(None, t([str(idx['A/Main']), 'off']))

    # ---- self-heal: a worn mesh left on the skin's body without bookkeeping (e.g. after a mod reload)
    L.eval('function(b) b._mesh = get("/Game/ZWBODY0002/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder") end')(G.SKINBODY)
    W.applyAll()
    G.settle()
    check('a leftover worn mesh on a skin actor goes back to the outfit\'s own mesh',
          mesh(G.SKINBODY) == CHIC + '.SK_Lune_Chic_Skin', mesh(G.SKINBODY))

    # ---- Fix look: the game re-dresses everyone, then the picks are applied again
    W.fixLook()
    G.settle()
    G.runDelayed()
    check('Fix look asks the game to re-dress (ApplyCurrentCharacterSkin) and re-applies', G.REDRESSED == 1
          and 'Fix look: the game re-dressed 1 of 1 character(s)' in G.getlog() and 'after Fix look' in
          open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read(), G.REDRESSED)
    # PC: ApplyCurrentCharacterSkin failed on every skin component ("0 of 13") in every session
    L.execute('SKINCOMP._f.ApplyCurrentCharacterSkin = function() error("Function not found") end')
    cmd(None, t([str(idx['I/Main']), '1']))
    W.setWear('I/Main', True)
    G.settle()
    worn = mesh(G.SKINBODY).startswith('/Game/ZWPOTA0001/') and mesh(G.PAWNBODY).startswith('/Game/ZWPOTA0001/')
    W.fixLook()
    G.settle()
    G.runDelayed()
    lv = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('a Fix look the game ignores logs the error and the component\'s functions',
          'ApplyCurrentCharacterSkin failed' in lv and 'Function not found' in lv and 'skin component functions:' in lv
          and W.lastFix().n == 0, lv[-500:])
    still = mesh(G.SKINBODY).startswith('/Game/ZWPOTA0001/')
    W.setWear('I/Main', False)
    G.settle()
    check('  the worn mod stays on, and Unwear still brings Chic back (bookkeeping kept)',
          worn and still and mesh(G.SKINBODY) == CHIC + '.SK_Lune_Chic_Skin', (worn, still, mesh(G.SKINBODY)))
    check('  also on a pawn that is not a skin actor (no self-heal there: the AI companion, menu pawns)',
          mesh(G.PAWNBODY) == PH + '.SK_Lune_Placeholder', mesh(G.PAWNBODY))
    cmd(None, t([str(idx['I/Main']), 'off']))
    cmd(None, t([str(idx['A/Main']), '1']))                          # state the dump checks below expect

    # fix14 rule: an actor whose character can't be told (PC: "[no character]" on the walking character):
    # the character its mesh is made for decides, so a Lune-only pick isn't undone there (PC: undone,
    # then put back by Lune's skin 2 s later, every pass)
    cmd(None, t([str(idx['I/Main']), '1']))                         # Lune-only Potato replacer
    G.settle()
    ma, mc = L.eval('mixedActor')()
    L.eval('function(c) c:SetMaterial(0, get("/Game/ZWPOTA0001/Heros/Lune/MI_Pot.MI_Pot")) end')(mc)
    W.applyAll()
    G.settle()
    check('an actor of no known character keeps a Lune-only variant on a Lune mesh (not undone)',
          mesh(mc).startswith('/Game/ZWPOTA0001/'), mesh(mc))
    lv = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    mat0 = L.eval('function(c) return c:GetMaterial(0)._path end')
    check('  and its material from the same pick stays too (the whole component counts as Lune\'s)',
          mat0(mc) == '/Game/ZWPOTA0001/Heros/Lune/MI_Pot.MI_Pot', mat0(mc))
    check('  and the pass says nothing about it ("variant off" for that component)',
          'SkeletalMeshComponent_2147406712: mesh /Game/ZWPOTA0001' not in lv, [x for x in lv.splitlines() if '2147406712' in x][:3])
    cmd(None, t([str(idx['I/Main']), 'off']))
    G.settle()
    check('  with the pick off it goes back to the game\'s own mesh',
          mesh(mc) == '/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Potato_Skin.SK_Lune_Potato_Skin', mesh(mc))
    # a skin actor with a run-time named component and a worn mesh left on its body: its own templates
    # are looked up (self-heal), but never for the run-time name
    L.execute('''
      local cls = SKIN._class
      local body = meshComp("Body", get("/Game/ZWBODY0002/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder"))
      local extra = meshComp("GroomComponent_2147317866", get("/Game/Characters/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder"))
      local a = new("BP_CharacterSkin_LuneOutfit_Chic_C", "/Game/Map.PersistentLevel.BP_CharacterSkin_LuneOutfit_Chic_C_7",
                    { Body = body }, { K2_GetComponentsByClass = function() return TArray({ body, extra }) end })
      a._class = cls; a._skin = "BP_CharacterSkinBase_C"
      body._f.GetOwner = function() return a end; extra._f.GetOwner = function() return a end
      table.insert(COMPS, body); table.insert(ACTORS, a); RTBODY = body
    ''')
    W.applyAll()
    G.settle()
    check('  (the run-time named actor was looked at: its leftover worn mesh went back to Chic, as Outfits A)',
          mesh(G.RTBODY).startswith('/Game/ZWOUTA0001/'), mesh(G.RTBODY))
    L.execute('table.remove(COMPS); table.remove(ACTORS)')
    sf = dict(L.eval('SFOS').items())
    check('fix14: components named at run time are never looked up as templates (each miss cost 13-27 ms on PC)',
          not any('_2147406712_GEN_VARIABLE' in k or '_2147406713_GEN_VARIABLE' in k or 'GroomComponent_2147317866' in k
                  for k in sf),
          [k for k in sf if '_GEN_VARIABLE' in k][:4])
    tk = '/Game/Characters/Heros/Lune/Customization/Skin/BP_CharacterSkin_LuneOutfit_Chic.BP_CharacterSkin_LuneOutfit_Chic_C:Body_GEN_VARIABLE'
    check('  and a class\'s template is looked up once, not on every look', sf.get(tk, 0) == 1, sf.get(tk))
    # a kept template whose address now holds another object (the class was unloaded): looked up again
    L.execute('TMPL._path = "/Game/Other/Thing.Thing"')
    L.eval('function(b) b._mesh = get("/Game/ZWBODY0002/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder") end')(G.SKINBODY)
    W.applyAll()
    G.settle()
    sf = dict(L.eval('SFOS').items())
    check('  a kept template that is now another object (same address, other name) is looked up again',
          sf.get(tk, 0) == 2, sf.get(tk))
    L.execute('TMPL._path = "/Game/Characters/Heros/Lune/Customization/Skin/BP_CharacterSkin_LuneOutfit_Chic.BP_CharacterSkin_LuneOutfit_Chic_C:Body_GEN_VARIABLE"')
    L.execute('table.remove(COMPS); table.remove(COMPS)')        # the dump checks below expect no Maelle loaded
    # ... but only for the mod's relocated meshes: the game's own can be shared (Lune's Chic is Sciel's too)
    cmd(None, t([str(idx['A/Main']), '1']))                         # a Lune pick for Chic
    G.settle()
    ma2, mc2 = L.eval('mixedActor')()
    L.eval('function(c) c._mesh = get("/Game/Characters/Heros/Lune/Customization/Skin/SK_Lune_Chic_Skin.SK_Lune_Chic_Skin") end')(mc2)
    W.applyAll()
    G.settle()
    check('an actor of no known character showing the game\'s own (shared) Chic mesh is left alone',
          mesh(mc2) == CHIC + '.SK_Lune_Chic_Skin', mesh(mc2))
    L.execute('table.remove(COMPS); table.remove(COMPS)')

    G.KEYS['C+F9']()
    dump = open(os.path.join(mod, 'dump.txt'), encoding='utf-8').read()
    check('dump visits the non-skin pawn and says why', 'BP_jRPG_Character_World_C_1' in dump
          and 'not a skin actor' in dump, dump[:300])
    check('dump check section: shown vs absent per selected variant', 'WARDROBE CHECK' in dump
          and 'SHOWN  ' + CHIC in dump and 'absent /Game/Characters/Heros/Maelle/SK_Maelle_Placeholder' in dump,
          dump[dump.find('WARDROBE CHECK'):][:600])
    # ---- session recorder
    livef = os.path.join(mod, 'live_log.txt')
    lv = open(livef, encoding='utf-8').read()
    check('live log: session header and the wardrobe with characters', 'session start' in lv
          and 'wardrobe: 9 slot(s)' in lv and 'Lune Body Test: Body [Lune, guessed]' in lv, lv[:600])
    check('live log: console commands and keys', 'console: wardrobe' in lv and 'key CONTROL+F8' in lv)
    check('live log: each pass says why and what it changed',
          'pass (Lune Body Test: Body = Clean): ' in lv
          and 'change BP_jRPG_Character_World_C_1 [Lune].Body: mesh ' + PH + ' -> /Game/ZWBODY0001/' in lv
          and '(selected variant)' in lv, [l for l in lv.splitlines() if 'change' in l][:4])
    check('live log: Wear and its restore are named', '(Wear: over the outfit worn now)' in lv
          and '(Wear off: back to the outfit)' in lv)
    check('live log: what is on screen after a pass, with overlaps', 'on screen: Outfits A: Main = on: 1/1 asset(s)' in lv
          and 'on screen: Maelle - Claudia Set: Main = on: 0/1 asset(s); not shown: SK_Maelle_Placeholder' in lv
          and 'overlaps Lune Outfits B: Main' in lv, [l for l in lv.splitlines() if 'on screen' in l][:6])
    check('live log: a pass that changed nothing says so', 'nothing loaded needed changing' in lv)
    check('live log: spawns and the group matching', 'game spawned BP_jRPG_Character_World_C' in lv
          and 'matched: Grp: Lune color -> Lace dress: Lune Lace-chic black' in lv)
    check('live log: settings changes', 'setting wear = I/Main' in lv)
    check('live log: every real asset load is named before it happens (a hang shows what was loading)',
          '    loading /Game/ZWPOTA0001/Heros/Lune/Customization/Skin/SK_Lune_Potato_Skin.SK_Lune_Potato_Skin' in lv)
    check('live log: the start says how game-thread work is dispatched', 'game-thread work runs in one game-thread loop every 50 ms (LoopInGameThreadWithDelay)' in lv)
    for f in ('dump.txt', 'report.txt'):
        if os.path.exists(os.path.join(mod, f)):
            os.remove(os.path.join(mod, f))
    cmd(None, t([str(idx['A/Main']), 'off']))
    G.runDelayed()
    check('auto report is off by default: no dump after a change', not os.path.isfile(os.path.join(mod, 'dump.txt')))
    W.settings.auto_report = True
    with open(os.path.join(mod, 'live_log_previous.txt'), 'a') as lf:
        lf.write('loaded C:\\Users\\Some Name\\AppData\\x.pak and D:/users/other/y\n')
        lf.write("python: C:\\\\Users\\\\pyuser\\\\x and E:\\jdoe\\mods, UserWidget jdoeX\n")
    os.environ['USERNAME'] = 'jdoe'                                  # read when the report is written
    cmd(None, t([str(idx['A/Main']), '1']))
    G.tickGT(100)                                                   # 5 s of game-thread loop
    rep_ = os.path.join(mod, 'report.txt')
    rt = open(rep_, encoding='utf-8').read() if os.path.isfile(rep_) else ''
    check('4 s after a change dump.txt and report.txt are written by themselves',
          os.path.isfile(os.path.join(mod, 'dump.txt')) and 'refreshed' in open(livef, encoding='utf-8').read(), open(livef, encoding='utf-8').read()[-300:])
    check('report.txt holds settings, selection, live log, dump, UE4SS.log and relocator sections',
          all(x in rt for x in ('== settings.txt', '== selection.txt', '== live_log.txt', '== live_log_previous.txt', '== dump.txt',
                                '== UE4SS.log', '== relocate_console.txt')) and 'WARDROBE CHECK' in rt, rt[:300])
    check('  user names in paths are replaced by <user>', 'C:\\Users\\<user>\\AppData' in rt and 'D:/users/<user>/y' in rt
          and 'Some Name' not in rt, [l for l in rt.splitlines() if 'AppData' in l][:2])
    check('  also in Python-style paths (\\\\), and the Windows user name where it is a folder name, not inside words',
          'Users\\\\<user>\\\\x' in rt and 'pyuser' not in rt and 'E:\\<user>\\mods' in rt and 'jdoeX' in rt,
          [l for l in rt.splitlines() if 'python:' in l][:2])
    os.environ.pop('USERNAME', None)
    W.setRecord(False)
    size = os.path.getsize(livef)
    cmd(None, t([str(idx['A/Main']), '1']))
    check('recording off: nothing more is written', os.path.getsize(livef) == size
          and 'record = false' in open(os.path.join(mod, 'settings.txt'), encoding='utf-8').read())
    pp = os.path.join(mod, 'live_log_previous.txt')
    prev = open(pp, encoding='utf-8').read() if os.path.isfile(pp) else None
    W.setRecord(True)
    cmd(None, t([str(idx['A/Main']), 'off']))
    lv = open(livef, encoding='utf-8').read()
    check('  on again: the same file goes on (appended), and the previous session\'s log is not replaced',
          'recording switched on' in lv and 'session start' in lv and 'pass (' in lv.split('recording switched on')[1]
          and (open(pp, encoding='utf-8').read() if os.path.isfile(pp) else None) == prev, lv[-300:])

    errors = [l for l in G.getlog().split('\n') if 'failed' in l or 'error' in l]
    check('no apply errors', not errors, errors)
    base.av_check(check, [L])
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
