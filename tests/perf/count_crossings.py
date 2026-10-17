"""Count the mod's calls into UE4SS ("crossings") per scenario, to measure what a change costs.

    python -I tests/perf/count_crossings.py lua/E33Wardrobe/Scripts/main.lua [clean] [--verbose|--sites|--funcs|--trace X]

Run it on the old and the new main.lua and compare. Counts, not milliseconds: in game a crossing
costs roughly microseconds, property reads by name the most.

Scenarios (one Lua state, in order):
  a  first look at a new Sciel skin copy, Wear on (mesh swap to the relocated Chic mesh)
  b  second look (round 2, 2 s later), nothing changed
  c  the game re-dressed the copy (policy hook) -> first re-check round
  d  map load: 20 new copies + a companion pawn spawn in the quiet period, then the map-load pass
     (+ 300 other skeletal mesh components in the world)
  e  the 2 s companion watch, nothing changed
  f  Clean switched on (console "wardrobe clean") over everything loaded
"""
import collections
import os
import re
import sys

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = sys.argv[1]
CLEAN = 'clean' in sys.argv[2:]
TRACE_NAME = sys.argv[sys.argv.index('--trace') + 1] if '--trace' in sys.argv else None

L = lua54.LuaRuntime(unpack_returned_tuples=True)
L.execute(open(os.path.join(HERE, 'count_mock.lua'), encoding='utf-8').read())
L.execute(open(os.path.join(HERE, 'count_scenario.lua'), encoding='utf-8').read())
VARIANTS = r'''return { { mod = "Sciel Chic", slots = { { id = "S/sciel", label = "Sciel outfit", character = "Sciel", variants = {
 { id = "S/chic", label = "Chic skin", map = {
  ["/Game/Characters/Heros/Sciel/Customization/Skin/SK_Sciel_Chic_skin"] = { "/Game/Characters/Heros/ZWAB12/Customization/Skin/SK_Sciel_Chic_skin", "SK_Sciel_Chic_skin", "SkeletalMesh" },
  ["/Game/Characters/Heros/Sciel/Materials/MI_Chic_1"] = { "/Game/Characters/Heros/ZWAB12/Materials/MI_Chic_1", "MI_Chic_1", "MaterialInstanceConstant", false },
  ["/Game/Characters/Heros/Sciel/Textures/T_Chic_Body_BaseColor"] = { "/Game/Characters/Heros/ZWAB12/Textures/T_Chic_Body_BaseColor", "T_Chic_Body_BaseColor", "Texture2D", false },
  ["/Game/Characters/Heros/Sciel/Textures/T_Chic_Body_Normal"] = { "/Game/Characters/Heros/ZWAB12/Textures/T_Chic_Body_Normal", "T_Chic_Body_Normal", "Texture2D", false },
 } } } } } } }
'''
G = L.globals()
fs = G.FILESTORE
fs['/fake/Mods/E33Wardrobe/Scripts/variants.lua'] = VARIANTS
fs['/fake/Mods/E33Wardrobe/selection.txt'] = 'S/sciel\tS/chic\n'
fs['/fake/Mods/E33Wardrobe/settings.txt'] = 'wear = S/sciel\nauto_report = false\nclean = %s\n' % ('true' if CLEAN else 'false')
src = open(MAIN, encoding='utf-8').read()
chunk = L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')
chunk(src, '@/fake/Mods/E33Wardrobe/Scripts/main.lua')()
G.addNPCs(300)
G.tickGT(10)

ROWS = []


def summary(title, key):
    tr = [G.TRACE[i] for i in range(1, len(G.TRACE) + 1)]
    ops = [t for t in tr if not t.startswith(('LIVE', 'SYNCLOAD'))]
    kinds = collections.Counter(t.split(' ', 1)[0] for t in ops)
    full = sum(1 for t in ops if t.startswith('call ') and t.endswith(':GetFullName'))
    byname = kinds['prop'] + kinds['MISS']
    struct = kinds['struct'] + kinds['MISS.struct']
    loads = sum(1 for t in tr if t.startswith('SYNCLOAD')) + kinds['LoadAsset']
    changes = sum(1 for t in tr if t.startswith('LIVE') and ' change ' in t)
    row = dict(key=key, title=title, total=len(ops), getfullname=full, byname=byname, struct=struct,
               findallof=kinds['FindAllOf'], loads=loads, changes=changes, tick=G.TICKMAX)
    ROWS.append(row)
    if TRACE_NAME == key:
        with open(os.path.join(os.getcwd(), 'trace_%s.txt' % key), 'w', encoding='utf-8') as f:   # written where you run it
            f.write('\n'.join(tr))
    if '--verbose' in sys.argv:
        simp = collections.Counter()
        for t in ops:
            k = t.split(' ', 1)[1] if ' ' in t else t
            k = re.sub(r'MaterialInstanceDynamic_\d+', 'MID', k)
            k = re.sub(r'_\d+\b', '_N', k)
            simp[t.split(' ', 1)[0] + ' ' + k] += 1
        print('--', key, title)
        for k, n in simp.most_common(25):
            print('   %6d %s' % (n, k))


def run_hook(name, owner, cname):
    L.eval('function(h, o, n) ExecuteInGameThread(function() h(nil, o, n) end) end')(
        G.HOOKS['/Script/SandFall.CharacterSkinAssignPolicy:' + name], owner, G.FName(cname))


if '--sites' in sys.argv:
    G.SITES = L.table()
if '--funcs' in sys.argv:
    G.FUNCS = L.table()
# a) a new Sciel copy: BeginPlay, first look 1 s later (round 1)
G.TRACING = True
G.resetTrace()
a, body, owner = G.makeSciel(1)
G.ACTORS[len(G.ACTORS) + 1] = a
G.BEGINPLAY(a)
G.tickGT(25)
summary('first look at a new skin copy, Wear mesh swap', 'a')
# b) round 2, nothing changed
G.resetTrace()
G.tickGT(45)
summary('second look (round 2), nothing changed', 'b')
# c) the game puts its own body back; policy hook -> re-check round 1
L.execute('local b = ...; b._mesh = PLACEHOLDER; for k in pairs(b._over) do b._over[k] = nil end', body)
G.resetTrace()
run_hook('AssignBodySkin', owner, 'Default')
G.tickGT(25)
summary('re-dress after the game reset the mesh (round 1)', 'c')
G.TRACING = False
G.tickGT(45)
# a cutscene pawn of no party character (left alone), as in the older script
e = G.makeEsquie(1)
G.ACTORS[len(G.ACTORS) + 1] = e
G.BEGINPLAY(e)
G.tickGT(70)
# d) map load
G.TRACING = True
G.resetTrace()
G.MAP_POST(None, None)
for i in range(20):
    a2, b2, o2 = G.makeSciel(100 + i)
    G.ACTORS[len(G.ACTORS) + 1] = a2
    G.BEGINPLAY(a2)
comp, cm = G.makeCompanion(1)
G.ACTORS[len(G.ACTORS) + 1] = comp
G.tickGT(75)
summary('map load: 20 new copies + companion + 360 SKMCs, map-load pass', 'd')
G.TRACING = False
G.tickGT(80)                      # first watch applies the companion (not seen yet), rechecks settle
# e) the 2 s companion watch, nothing changed
G.TRACING = True
G.resetTrace()
G.tickGT(40)
summary('2 s companion watch, nothing changed', 'e')
# f) Clean switched on
G.resetTrace()
G.CMD(None, L.table_from(['clean']))
G.tickGT(2)
summary('Clean switched on (console), everything loaded', 'f')
G.TRACING = False

if '--sites' in sys.argv:
    items = sorted(((v, k) for k, v in G.SITES.items()), reverse=True)[:40]
    for v, k in items:
        print('   site %6d %s' % (v, k))
if '--funcs' in sys.argv:
    srcl = open(MAIN, encoding='utf-8').read().split('\n')
    items = sorted(((v, k) for k, v in G.FUNCS.items()), reverse=True)[:45]
    for v, k in items:
        print('   func %7d %5d %s' % (v, k, srcl[k - 1].strip()[:90] if k > 0 else '?'))
print('%-3s %-62s %8s %8s %8s %8s %6s %6s %7s %8s' % ('', 'scenario', 'total', 'GetFull', 'byName', 'struct',
                                                 'FindAll', 'loads', 'changes', 'maxTick'))
for r in ROWS:
    print('%-3s %-62s %8d %8d %8d %8d %6d %6d %7d %8d' % (r['key'], r['title'][:62], r['total'], r['getfullname'],
                                                     r['byname'], r['struct'], r['findallof'], r['loads'], r['changes'], r['tick']))
log = G.getlog()
print('passes:', re.findall(r'applied to [^\n]*', log))
print('AV-ish errors:', len(re.findall(r'error', log)))
