"""Threading model (needs lupa): after start-up nothing is queued to the game thread from anywhere.

An audit of the tested UE4SS build (RE-UE4SS 527a483b) found that ExecuteInGameThread /
LoopAsync / ExecuteWithDelay called from a thread other than the game thread race with the
game thread on the mod's shared Lua stack ("Ref was not function" in UE4SS.log). The mod now:
  * hops to the game thread once at start-up (registers hooks, first load, starts ONE
    LoopInGameThreadWithDelay loop);
  * key binds only post to an inbox; the loop runs them, the mod's timers, the menu and the
    debounced apply pass;
  * the watchdog's async loop only reads a number and writes the log.
Checks:
  * exactly one ExecuteInGameThread (the start hop), one game-thread loop; none afterwards for
    picks, keys, Wear, Fix look, auto report, spawns, policy assigns, map loads
  * key callbacks do no engine work on the key thread
  * picks close together -> one pass with all reasons; delayed work runs on the loop
  * watchdog reports a stalled loop with the mod state, and never calls UE4SS
  * a build without LoopInGameThreadWithDelay stays off with a message (no unsafe fallback)
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

COUNTERS = r'''
CLOCK = 100000
local realTime = os.time
os.time = function(t) if t then return realTime(t) end return CLOCK end
EIGT, EIGTD, EWD = 0, 0, 0
local baseEIGT = ExecuteInGameThread
function ExecuteInGameThread(f, m) EIGT = EIGT + 1; return baseEIGT(f) end
function ExecuteInGameThreadWithDelay(ms, f) EIGTD = EIGTD + 1; table.insert(DELAYED, f) end
local baseEWD = ExecuteWithDelay
function ExecuteWithDelay(ms, f) EWD = EWD + 1; return baseEWD(ms, f) end
ASYNC_LOOPS, LOOP_MS = {}, {}
function LoopAsync(ms, f) table.insert(ASYNC_LOOPS, f) end
function asyncTick() for _, f in ipairs(ASYNC_LOOPS) do f() end end
local baseLoop = LoopInGameThreadWithDelay
function LoopInGameThreadWithDelay(ms, f) table.insert(LOOP_MS, ms); return baseLoop(ms, f) end
-- engine work while a key callback runs (the key thread)
ON_KEY_THREAD, KEY_THREAD_ENGINE = false, 0
local baseFind = FindAllOf
function FindAllOf(n) if ON_KEY_THREAD then KEY_THREAD_ENGINE = KEY_THREAD_ENGINE + 1 end; return baseFind(n) end
local baseRKB = RegisterKeyBind
RAWKEYS = {}                                   -- the callback alone, as UE4SS's key thread runs it
function RegisterKeyBind(k, mods, fn)
  local w = function() ON_KEY_THREAD = true; fn(); ON_KEY_THREAD = false end
  local id = k; for _, m in ipairs(mods) do id = m .. "+" .. id end
  RAWKEYS[id] = w
  baseRKB(k, mods, w)
end
HOOKS = {}
PREHOOKS = {}
function RegisterHook(name, pre, post) HOOKS[name] = post; PREHOOKS[name] = pre; return 1, 2 end
function RegisterLoadMapPostHook(fn) LOADMAP_POST = fn end
function RegisterInitGameStatePostHook(fn) INITGS = fn end
'''


RUNTIMES = []                   # every Lua state made, for the access-violation check at the end


def load(no_gt_loop=False, settings='', preload=''):
    tmp = tempfile.mkdtemp(prefix='e33disp_')
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(base.VARIANTS)
    if settings:
        open(os.path.join(tmp, 'E33Wardrobe', 'settings.txt'), 'w').write(settings)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    RUNTIMES.append(L)
    L.execute(base.MOCK)
    L.execute(COUNTERS)
    if no_gt_loop:
        L.execute('LoopInGameThreadWithDelay = nil')
    body, _a = L.execute(base.SCENARIO)
    if preload:
        L.execute(preload)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    return tmp, L, body


def main():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    tmp, L, body = load(settings='auto_report = true\n')
    G = L.globals()
    W = G.API_OUT
    mesh = L.eval('function(b) return b._mesh._path end')
    live = lambda: open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()  # noqa: E731
    check('start-up: one hop to the game thread, one game-thread loop every 50 ms',
          G.EIGT == 1 and list(G.LOOP_MS.values()) == [50], (G.EIGT, list(G.LOOP_MS.values())))
    G.tickGT(10)                                                # first pass after the debounce
    G.EIGT, G.EIGTD, G.EWD = 0, 0, 0

    # picks close together: one pass
    passes = lambda: live().count(' pass (')  # noqa: E731
    p0 = passes()
    W.setVariant(1, 1)
    W.setVariant(2, 1)
    G.tickGT(2)
    check('picks are not applied at once (debounce)', mesh(body).startswith('/Game/Characters/Lune/'), mesh(body))
    G.tickGT(4)
    check('two picks within ~200 ms -> one pass', passes() == p0 + 1, passes() - p0)
    check('  the pass applies both and names both reasons', mesh(body).startswith('/Game/Characters/ZWOUTFITA/')
          and 'pass (Lune outfit = Sleeves + boots + Lune color = red)' in live(),
          [l for l in live().splitlines() if 'pass (' in l][-1:])

    # keys: they only post; the work runs in the loop
    n0 = live().count('wardrobe: ')
    G.RAWKEYS['C+F8']()                                         # reload, on the key thread only
    check('a key callback itself does nothing but post (Ctrl+F8 reload has not run yet)',
          live().count('wardrobe: ') == n0)
    G.tickGT(1)
    check('  the next game-thread tick runs it', live().count('wardrobe: ') == n0 + 1)
    for k in ('C+F7', 'C+F8', 'C+F9'):
        G.KEYS[k]()
    check('key callbacks do no engine work on the key thread', G.KEY_THREAD_ENGINE == 0, G.KEY_THREAD_ENGINE)
    check('  but the work runs on the next loop tick (dump.txt written by Ctrl+F9)',
          os.path.isfile(os.path.join(tmp, 'E33Wardrobe', 'dump.txt')))

    # timers, Wear, Fix look, spawns, policy assigns, map loads: all on the loop
    W.setWear('CC/Lune outfit', True)
    W.fixLook()
    G.BEGINPLAY(L.eval('function(a) return { get = function() return a end } end')(G.ACTORS[1]))
    post = G.HOOKS['/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkin']
    post(None, L.eval('function(a) return { get = function() return a end } end')(G.ACTORS[1]), None)
    G.LOADMAP_POST(None, None)
    G.tickGT(200)                                               # 10 s: map-load pass at 3 s, its auto report 4 s later
    check('after start-up nothing is queued to the game thread from anywhere '
          '(no ExecuteInGameThread / ...WithDelay / ExecuteWithDelay)',
          G.EIGT == 0 and G.EIGTD == 0 and G.EWD == 0, (G.EIGT, G.EIGTD, G.EWD))
    lv = live()
    check('  the 4 s auto report ran on the loop', 'dump.txt and report.txt refreshed' in lv)
    check('  the map-load pass ran on the loop', 'pass (after map load)' in lv)
    check('  Fix look re-applied on the loop', 'after Fix look' in lv)

    # watchdog: reads a number, writes a line, never calls UE4SS
    G.asyncTick()
    G.CLOCK = G.CLOCK + 8                                       # the loop stops ticking for 8 s
    G.asyncTick()
    check('watchdog: a stalled game-thread loop is reported with the mod state', 'WATCHDOG: the game thread has not run '
          'for 8 s; mod state: idle' in live(), live()[-300:])
    G.CLOCK = G.CLOCK + 1
    G.asyncTick()
    check('  once per stall (not every second)', live().count('WATCHDOG: the game thread') == 1)
    check('  and it never queued anything', G.EIGT == 0 and G.EWD == 0)
    G.tickGT(1)
    check('  when the loop runs again, a line says so (PC: battle loads stall 5-6 s and go on; not a freeze)',
          'WATCHDOG: the game thread ran again after 9 s' in live(), live()[-300:])
    G.tickGT(5)
    check('    once', live().count('the game thread ran again') == 1)
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # settings.txt "scene_copies = false": actors the game dressed as "Default" (its dialogue and
    # battle copies) are left alone; a test switch for the PC report of dialogue not appearing
    for setting, touched in (('scene_copies = false\n', False), ('', True)):
        tmp, L, body = load(settings=setting)
        G = L.globals()
        mesh = L.eval('function(b) return b._mesh._path end')
        L.eval('''function(p, a)
            IN_GT = true
            p(nil, { get = function() return a end }, { get = function() return FName("Default") end })
            IN_GT = false
        end''')(G.HOOKS['/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkin'], G.ACTORS[1])
        G.API_OUT.setVariant(1, 1)
        G.tickGT(20)
        changed = mesh(body).startswith('/Game/Characters/ZWOUTFITA/')
        check(f'scene_copies {"on (default)" if touched else "off"}: a "Default" copy is '
              f'{"changed" if touched else "left alone"}', changed == touched, mesh(body))
        shutil.rmtree(tmp, ignore_errors=True)

    # PC: both freezes happened in the mod's first look at a skin the game had just spawned: new
    # skins are not touched on the tick they appear, only ~1 s later
    tmp, L, body = load()
    G = L.globals()
    mesh = L.eval('function(b) return b._mesh._path end')
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    L.execute('''
      local b7 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a7 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_7", { Body = b7 }, { K2_GetComponentsByClass = function() return TArray({ b7 }) end })
      a7._class = ACTORS[1]._class; a7._skin = "BP_CharacterSkinBase_C"; BODY7 = b7
      IN_GT = true; BEGINPLAY({ get = function() return a7 end }); IN_GT = false
    ''')
    G.tickGT(2)
    check('a new skin is not touched on the tick it appears', mesh(G.BODY7).startswith('/Game/Characters/Lune/'), mesh(G.BODY7))
    G.tickGT(20)
    check('  but about 1 s later', mesh(G.BODY7).startswith('/Game/Characters/ZWOUTFITA/'), mesh(G.BODY7))

    # PC: the game put its own mesh back on its scene copies 5-8 times and the mod re-dressed them
    # every time (stutter). After 3 quick resets in a row the component is left alone.
    G.API_OUT.setWear('CC/Lune outfit', True)
    G.tickGT(20)
    L.execute('''asset("SkeletalMesh", "/Game/Characters/Heros/Lune/SK_Lune_Placeholder", "SK_Lune_Placeholder",
        { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })''')
    sets = 0
    for _ in range(5):          # the game puts the bare base body back; 4 = the pick + 3 re-dresses
        if mesh(body).startswith('/Game/Characters/ZWOUTFITA/'):
            sets += 1
        L.eval('function(b) b._mesh = get("/Game/Characters/Heros/Lune/SK_Lune_Placeholder.SK_Lune_Placeholder") end')(body)
        G.API_OUT.applyAll('test')
        G.tickGT(10)
    live = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('Wear: after 3 quick resets by the game, the component is left alone',
          mesh(body).endswith('SK_Lune_Placeholder') and sets == 4 and 'keeps putting its own mesh back; left alone' in live,
          (mesh(body), sets))
    G.CLOCK = G.CLOCK + 60
    G.API_OUT.applyAll('test later')
    G.tickGT(10)
    check('  and dressed again after a while (an outfit change later starts the count again)',
          mesh(body).startswith('/Game/Characters/ZWOUTFITA/'), mesh(body))
    shutil.rmtree(tmp, ignore_errors=True)

    # PC dump (battle start): reading owner.BP_CharacterSkinComponent.SpawnedCharacterSkin 50 ms after
    # the game's assign hook crashed inside UE4SS (the reference pointed to a freed object). A re-
    # assign now re-checks the skins already seen for that owner, without reading its properties.
    tmp, L, body = load()
    G = L.globals()
    mesh = L.eval('function(b) return b._mesh._path end')
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    L.execute('''
      FREED = setmetatable({}, { __index = function(_, k) AVHIT("freed " .. tostring(k)); return NULLOBJ() end })
      OWNER12 = new("BP_Lune_Battle_C", "/Game/Map.PersistentLevel.BP_Lune_Battle_C_12", {}, {})
      rawset(OWNER12, "_p", setmetatable({}, { __index = function(_, k)
        if k == "BP_CharacterSkinComponent" or k == "BP_CinematicCharacterSkinComponent" then return FREED end end }))
      local b12 = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
      local a12 = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_12", { Body = b12 }, {
        K2_GetComponentsByClass = function() return TArray({ b12 }) end, GetOwner = function() return OWNER12 end })
      a12._class = ACTORS[1]._class; a12._skin = "BP_CharacterSkinBase_C"; BODY12 = b12
      IN_GT = true; BEGINPLAY({ get = function() return a12 end }); IN_GT = false
    ''')
    G.tickGT(30)
    first = mesh(G.BODY12)
    L.execute('BODY12._mesh = get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic")')   # the game re-dresses it
    L.eval('''function(p)
        IN_GT = true
        p(nil, { get = function() return OWNER12 end }, { get = function() return FName("Lune") end })
        IN_GT = false
    end''')(G.HOOKS['/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkin'])
    G.tickGT(40)
    check('a skin re-assigned by the game (no BeginPlay) gets the pick again',
          first.startswith('/Game/Characters/ZWOUTFITA/') and mesh(G.BODY12).startswith('/Game/Characters/ZWOUTFITA/'),
          (first, mesh(G.BODY12)))
    check('  without reading the owner\'s skin component (a freed object at battle start)', G.AV == 0, L.eval('AVREPORT()'))
    shutil.rmtree(tmp, ignore_errors=True)

    # PC: four party-menu characters, 95-309 ms each, all in one frame. New skins now get about
    # 8 ms per frame; the rest wait for the next frames.
    tmp, L, body = load()
    G = L.globals()
    mesh = L.eval('function(b) return b._mesh._path end')
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    L.execute('''
      SLOW = {}
      for i = 1, 3 do
        local b = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
        local orig = b._f.GetNumMaterials
        b._f.GetNumMaterials = function(self) EXTRA_MS = (EXTRA_MS or 0) + 6; return orig(self) end   -- a slow look
        local a = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_S" .. i, { Body = b }, {
          K2_GetComponentsByClass = function() return TArray({ b }) end })
        a._class = ACTORS[1]._class; a._skin = "BP_CharacterSkinBase_C"; SLOW[i] = b
        IN_GT = true; BEGINPLAY({ get = function() return a end }); IN_GT = false
      end
      local c = os.clock
      os.clock = function() return c() + (EXTRA_MS or 0) / 1000 end
    ''')
    done = lambda: sum(1 for i in (1, 2, 3) if mesh(L.eval(f'SLOW[{i}]')).startswith('/Game/Characters/ZWOUTFITA/'))  # noqa: E731
    G.tickGT(21)                                                    # the first look (~1 s)
    first = done()
    G.tickGT(10)
    check('slow looks at new skins are spread over frames (~8 ms per frame), and all get done',
          first < 3 and done() == 3, (first, done()))
    shutil.rmtree(tmp, ignore_errors=True)

    # UE4SS-settings.ini HookLoadMap = 0 (a crash came from inside the engine's LoadMap, called through
    # UE4SS's LoadMap hook): InitGameState still tells the mod about a new map, and when both fire
    # the map is handled once
    tmp, L, body = load()
    G = L.globals()
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    gs = G.INITGS
    check('the mod registers an InitGameState hook', gs is not None)
    if gs is not None:
        L.eval('''function(f)
            local gm = { IsValid = function() return true end,
                         GetWorld = function() return { IsValid = function() return true end,
                           GetFName = function() return FName("Level_Camp_Main") end } end }
            IN_GT = true; f({ get = function() return gm end }); IN_GT = false
        end''')(gs)
        G.LOADMAP_POST(None, L.eval('{ get = function() return { IsValid = function() return true end, GetFName = function() return FName("Level_Camp_Main") end } end }'))
        G.tickGT(80)
        lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
        check('  a map seen only through InitGameState is handled (the pass after a map load runs), once',
              'map loaded: Level_Camp_Main (game state)' in lv and lv.count('map loaded:') == 1
              and lv.count('pass (after map load)') == 1, [x for x in lv.splitlines() if 'map loaded' in x or 'after map load' in x])
    shutil.rmtree(tmp, ignore_errors=True)

    # the redesign probe: parameter types of the game's skin functions (read from the function, never
    # a value) and how many calls could be changed before they run
    tmp, L, body = load(preload='''
      local function prop(cls, name) return { GetClass = function() return { GetFName = function() return FName(cls) end } end,
                                             GetFName = function() return FName(name) end } end
      REGSET("/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkin", { IsValid = function() return true end,
        ForEachProperty = function(self, cb) cb(prop("ObjectProperty", "Owner")); cb(prop("NameProperty", "CharacterName"));
                                             cb(prop("SoftClassProperty", "SkinClass")) end })
    ''')
    G = L.globals()
    for _ in range(3):
        G.PREHOOKS['/Script/SandFall.CharacterSkinAssignPolicy:AssignBodySkin']()
    G.tickGT(1250)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('probe: the skin function\'s parameter types are logged',
          'probe: AssignBodySkin(ObjectProperty Owner, NameProperty CharacterName, SoftClassProperty SkinClass)' in lv,
          [x for x in lv.splitlines() if 'probe' in x][:3])
    check('  and the calls seen before they run are counted per minute',
          'probe: calls seen before they run: AssignBodySkin 3' in lv, [x for x in lv.splitlines() if 'probe: calls' in x])
    shutil.rmtree(tmp, ignore_errors=True)

    # a hang inside an engine call: the watchdog writes the mod's last steps, the last one names the
    # call that never returned (PC: a 16 GB memory dump can't be sent; this can)
    tmp, L, body = load()
    G = L.globals()
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    G.asyncTick()
    L.execute('''
      local orig = ACTORS[1]._p.Body._f.GetMaterial
      ACTORS[1]._p.Body._f.GetMaterial = function(self, i)
        if STALL then STALL = false; CLOCK = CLOCK + 8; asyncTick() end
        return orig(self, i)
      end
      STALL = true
    ''')
    G.API_OUT.applyAll('test')
    G.tickGT(10)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    stall = lv[lv.find('WATCHDOG: the game thread'):]
    check('a hang inside an engine call: the watchdog names the mod\'s last step (the call that hangs)',
          'WATCHDOG: last mod step: slot 0: GetMaterial' in stall or 'WATCHDOG: last mod step: Wear: materials' in stall,
          stall[:600])
    check('  with the steps before it, oldest first', stall.count('  step ') >= 5 and 'component Body' in stall, stall[:900])
    check('  the pass line says how long it took', ' actor(s) in ' in lv and ' ms' in lv)
    shutil.rmtree(tmp, ignore_errors=True)

    # PC: a burst of new actors filled all 40 breadcrumbs with "skin class check"; a step repeated
    # in a row is one line with a count, so the history before it stays
    tmp, L, body = load()
    G = L.globals()
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    G.asyncTick()
    L.execute('''
      for i = 1, 5 do
        local x = new("BP_Thing_C", "/Game/Map.PersistentLevel.BP_Thing_C_" .. i, {}, {})
        IN_GT = true; BEGINPLAY({ get = function() return x end }); IN_GT = false
      end
      CLOCK = CLOCK + 8; asyncTick()
    ''')
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    steps = [x.split(' ms: ', 1)[1] for x in lv[lv.find('WATCHDOG: the game thread'):].splitlines()
             if '  step ' in x and ' ms: ' in x]
    check('5 skin class checks in a row are one breadcrumb "(x5)"',
          steps[-1:] == ['skin class check (x5)'] and not steps[-2].startswith('skin class check'), steps[-6:])
    check('  the steps before them are still there', len(steps) >= 5, steps)
    shutil.rmtree(tmp, ignore_errors=True)

    # stutter numbers: a frame that took long is logged as a hitch with the mod's work before it
    tmp, L, body = load()
    G = L.globals()
    G.tickGT(5)
    L.execute('local c = os.clock; local extra = 0; os.clock = function() return c() + extra end; '
              'function slowFrame(ms) extra = extra + ms / 1000 end')
    G.slowFrame(400)
    G.tickGT(2)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('a slow frame (400 ms) is logged as a hitch with the mod\'s work in the tick before',
          'hitch: a frame took 4' in lv and 'mod work in the tick before' in lv, lv[-400:])
    shutil.rmtree(tmp, ignore_errors=True)

    # a slow look: the mod's own long frame is a hitch too, and the line says where the time went
    # (PC: 150-310 ms looks; the logged loads and mesh sets explained ~20 ms of them; and the hitch
    # lines only measured the gap between the loop's ticks, so they never showed the mod's own work)
    tmp, L, body = load()
    G = L.globals()
    G.tickGT(5)
    L.execute('''
      local c = os.clock; local extra = 0; os.clock = function() return c() + extra end
      local orig = ACTORS[1]._p.Body._f.GetMaterial
      ACTORS[1]._p.Body._f.GetMaterial = function(self, i)
        if SLOW then SLOW = false; extra = extra + 0.4 end
        return orig(self, i)
      end
      SLOW = true
    ''')
    G.API_OUT.setVariant(1, 1)
    G.tickGT(40)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    slow = [x for x in lv.splitlines() if 'slow look:' in x]
    check('a look that took 400 ms writes a "slow look" line naming the step that took the time',
          len(slow) == 1 and re.search(r'most time in: [^,]+ (39\d|40\d) ms, ', slow[0]) is not None, slow or lv[-600:])
    check('  and the frame it made is logged as a hitch of the mod\'s own work',
          "hitch: the mod's own work took 4" in lv, [x for x in lv.splitlines() if 'hitch' in x])
    check('  a fast look writes no such line', len(slow) == 1)
    shutil.rmtree(tmp, ignore_errors=True)

    # fix14: assets are asked of GetAsset (finds or loads); StaticFindObject, whose misses cost 13-27 ms
    # each on PC, is not asked first. "loading" is named once per asset per map.
    tmp, L, G, live = None, None, None, None
    tmp, L, body = load()
    G = L.globals()
    L.execute('''SFO = {}
      local base = StaticFindObject
      function StaticFindObject(p) SFO[#SFO + 1] = p; return base(p) end''')
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    sfo = list(L.eval('SFO').values())
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('a pick: the variant\'s assets are not looked up with StaticFindObject (GetAsset is asked)',
          not any('/ZWOUTFITA/' in x for x in sfo) and '/ZWOUTFITA/Chic/SK_Lune_Chic' in lv and 'change ' in lv,
          [x for x in sfo if '/ZW' in x][:5])
    n1 = lv.count('    loading /Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic')
    G.API_OUT.setVariant(1, 2)                                  # another variant and back: asked for again
    G.tickGT(20)
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('  "loading" is named once per asset in a map (not on every look)',
          n1 == 1 and lv.count('    loading /Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic') == 1,
          (n1, lv.count('    loading /Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic')))
    G.LOADMAP_POST(None, L.eval('{ get = function() return { IsValid = function() return true end, GetFName = function() return FName("Level_Camp_Main") end } end }'))
    G.tickGT(120)
    G.API_OUT.setVariant(1, 2)
    G.tickGT(20)
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('  and again when needed after a map load', lv.count('    loading /Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic') == 2,
          lv.count('    loading /Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic.SK_Lune_Chic'))
    G.tickGT(200)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('17 Oct audit: no speed test for players (B test off, the default): ~70 ms of lookups for nothing',
          'speed test:' not in lv, [x for x in lv.splitlines() if 'speed test:' in x])
    shutil.rmtree(tmp, ignore_errors=True)
    tmp, L, body = load(settings='b_swap = param\n')
    G = L.globals()
    G.tickGT(5)
    G.API_OUT.setVariant(1, 1)                                  # a pick: the passes below need one
    G.tickGT(20)
    for wname in ('Level_Camp_Main', 'Level_WorldMap_Main_V2'):
        G.LOADMAP_POST(None, L.eval('{ get = function() return { IsValid = function() return true end, GetFName = '
                                    'function() return FName("' + wname + '") end } end }'))
        G.tickGT(250)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    sp = [x for x in lv.splitlines() if 'speed test:' in x]
    check('in a test session (b_swap = param) the speed test runs 9 s after a map that isn\'t the title screen',
          len(sp) >= 1 and 'StaticFindObject, not found:' in sp[0] and 'GetAsset of an asset in memory:' in sp[0], sp)
    check('  only once per session', len(sp) == 1, len(sp))
    # PC 17 Oct crash: world map, then camp 11 s later; the map-load pass ran 3 s after the camp and
    # crashed inside UE4SS reading a camp actor's property. A map soon after another waits 6 s.
    def world(name):
        return L.eval('{ get = function() return { IsValid = function() return true end, GetFName = function() return FName("%s") end } end }' % name)

    def passes():
        return open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read().count('pass (after map load)')
    G.tickGT(700)                                               # 35 s: the last map is long ago
    p0 = passes()
    G.LOADMAP_POST(None, world('Level_A'))
    G.tickGT(80)                                                # 4 s
    p1 = passes()
    G.tickGT(120)                                               # 10 s after Level_A
    G.LOADMAP_POST(None, world('Level_Camp_Main'))
    G.tickGT(80)                                                # 4 s after the camp
    p2 = passes()
    G.tickGT(60)                                                # 7 s after the camp
    p3 = passes()
    check('a map long after the last one: its pass runs after 3 s; one 10 s after another waits 6 s',
          p1 == p0 + 1 and p2 == p1 and p3 == p1 + 1, (p0, p1, p2, p3))
    # the BeginPlay hook's own time: counted, shown with long frames and per minute
    L.execute('''local c = os.clock; local extra = 0; os.clock = function() return c() + extra end
      local x = new("BP_Thing_C", "/Game/Map.PersistentLevel.BP_Thing_C_77", {}, {})
      -- each read of the hook's parameter (inside the hook's work) takes 0.4 ms
      for i = 1, 500 do IN_GT = true; BEGINPLAY({ get = function() extra = extra + 0.0004; return x end }); IN_GT = false end''')
    G.tickGT(2)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    hl = [x for x in lv.splitlines() if 'BeginPlay hook meanwhile' in x and 'in 500 call(s)' in x]
    check('a long frame full of BeginPlay calls: the hitch line gives the hook\'s time and call count',
          len(hl) == 1 and int(re.search(r'meanwhile: (\d+) ms', hl[0]).group(1)) >= 200, hl or lv[-400:])
    G.tickGT(1250)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('  and the minute\'s stats line its total', any(re.search(r'BeginPlay hook (\d{3,}) ms in 50\d call', x) for x in lv.splitlines() if 'stats (' in x),
          [x[-60:] for x in lv.splitlines() if 'stats (' in x][-3:])
    shutil.rmtree(tmp, ignore_errors=True)

    # commands.txt: a script or developer drives the mod while the game runs (read about once a second)
    tmp, L, body = load()
    G = L.globals()
    mesh = L.eval('function(b) return b._mesh._path end')
    G.tickGT(20)
    cf = os.path.join(tmp, 'E33Wardrobe', 'commands.txt')
    eigt0, ewd0 = G.EIGT, G.EWD
    with open(cf, 'w', encoding='utf-8') as f:
        f.write('pick CC/Lune outfit | CC/B\nset recheck_ms 900\nset no_such 1\n# a comment\nwear CC/Lune outfit | on\ndump\n')
    G.tickGT(30)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    st = open(os.path.join(tmp, 'E33Wardrobe', 'settings.txt'), encoding='utf-8').read()
    check('commands.txt: a pick by slot and variant id (ids with spaces) is applied',
          mesh(body).startswith('/Game/Characters/ZWOUTFITB/') and 'command: pick CC/Lune outfit | CC/B' in lv, mesh(body))
    check('  a setting is set and saved; an unknown one is named', 'recheck_ms = 900' in st and 'no setting no_such' in G.getlog(),
          [x for x in st.splitlines() if 'recheck' in x])
    check('  Wear by slot id, console words (dump), comments skipped',
          'wear = CC/Lune outfit' in st and os.path.isfile(os.path.join(tmp, 'E33Wardrobe', 'dump.txt'))
          and 'command: # a comment' not in lv, [x for x in st.splitlines() if x.startswith('wear')])
    check('  the file is removed once read, each line logged once', not os.path.exists(cf)
          and lv.count('command: pick CC/Lune outfit | CC/B') == 1, os.path.exists(cf))
    G.tickGT(60)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    check('  and not run again', lv.count('command: pick CC/Lune outfit | CC/B') == 1)
    check('  no game-thread work queued from other threads for it', G.EIGT == eigt0 and G.EWD == ewd0,
          (G.EIGT - eigt0, G.EWD - ewd0))
    shutil.rmtree(tmp, ignore_errors=True)

    # a UE4SS build without LoopInGameThreadWithDelay
    tmp, L, body = load(no_gt_loop=True)
    G = L.globals()
    mesh = L.eval('function(b) return b._mesh._path end')
    check('a UE4SS build without LoopInGameThreadWithDelay: the mod stays off and says why, instead of '
          'queueing from other threads (which can crash those builds)',
          G.EIGT == 0 and len(list(G.ASYNC_LOOPS.values())) == 0 and 'too old for E33Wardrobe' in G.getlog()
          and G.CMDS['wardrobe'] is None, (G.EIGT, len(list(G.ASYNC_LOOPS.values())), G.CMDS['wardrobe']))
    base.av_check(check, RUNTIMES)
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
