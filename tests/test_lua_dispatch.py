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


def load(no_gt_loop=False, settings='', preload='', variants=None, ue4ss_log=None, files=None):
    """files: {name: text} written next to the mod (the folder of live_log.txt) before it starts."""
    tmp = tempfile.mkdtemp(prefix='e33disp_')
    if ue4ss_log is not None:                   # the mod reads ../../UE4SS.log: <tmp>/UE4SS.log
        tmp = os.path.join(tmp, 'Mods')
        os.makedirs(tmp)
        open(os.path.join(tmp, '..', 'UE4SS.log'), 'w', encoding='utf-8').write(ue4ss_log)
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(variants or base.VARIANTS)
    if settings:
        open(os.path.join(tmp, 'E33Wardrobe', 'settings.txt'), 'w').write(settings)
    for name, text in (files or {}).items():
        open(os.path.join(tmp, 'E33Wardrobe', name), 'w', encoding='utf-8').write(text)
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
    # (the Wear and Fix look requests just before the map load wait for it: one pass, both reasons)
    check('  the map-load pass ran on the loop', any(' pass (' in x and 'after map load' in x for x in lv.splitlines()),
          [x for x in lv.splitlines() if ' pass (' in x][-3:])
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
    # book ch 19: the times were rounded down by 1 ms, so the last step always read "-1 ms"
    steps = [x for x in stall.splitlines() if x.split(' ', 2)[-1].lstrip().startswith('step ')]
    check('  the last step is at 0 ms (where it stopped), not -1 ms',
          steps and ' 0 ms: ' in steps[-1] and not any(' -1 ms: ' in x for x in steps), steps[-2:])
    check('  the pass line says how long it took', ' actor(s) in ' in lv and ' ms' in lv)
    shutil.rmtree(tmp, ignore_errors=True)

    # book ch 19: the stats line's BeginPlay time belongs to its own minute, also when the tick that
    # writes the line follows the frame the calls were in (one long frame's 777 ms in 23,749 calls
    # went into the next, quiet minute)
    tmp, L, body = load()
    G = L.globals()
    lvf = os.path.join(tmp, 'E33Wardrobe', 'live_log.txt')
    stats = lambda: [x for x in open(lvf, encoding='utf-8').read().splitlines() if ' stats (' in x]  # noqa: E731
    for _ in range(1300):
        G.tickGT(1)
        if stats():
            break
    G.tickGT(1199)                                              # the tick before the next stats line
    L.execute('''
      for i = 1, 5 do
        local x = new("BP_Thing_C", "/Game/Map.PersistentLevel.BP_Minute_C_" .. i, {}, {})
        IN_GT = true; BEGINPLAY({ get = function() return x end }); IN_GT = false
      end''')
    n0 = len(stats())
    G.tickGT(1)
    st = stats()
    check('stats line: BeginPlay calls just before the tick that writes it count in its own minute',
          len(st) == n0 + 1 and 'in 5 call(s)' in st[-1], st[-1:])
    # book ch 19: report.txt bundled files read raw and wrote them in text mode ("\r\r\n");
    # dump.txt had no date, and reports carried a dump days old
    G.KEYS['C+F9']()
    G.tickGT(2)
    rep = open(os.path.join(tmp, 'E33Wardrobe', 'report.txt'), 'rb').read()
    dmp = open(os.path.join(tmp, 'E33Wardrobe', 'dump.txt'), encoding='utf-8').readline()
    check('report.txt has no doubled line ends ("\\r\\r\\n")', b'\r\r\n' not in rep and len(rep) > 1000, rep.count(b'\r\r\n'))
    check('dump.txt starts with its date and the session it belongs to',
          ' dump 20' in dmp and '(session started 20' in dmp, dmp)
    shutil.rmtree(tmp, ignore_errors=True)

    # book ch 19: the "errors" section listed UE4SS's offset table (FArchiveState::ArIsError), and
    # "last 80 lines" held 81
    ue = ['[Lua] filler line %d' % i for i in range(100)]
    ue[5] = 'FArchiveState::ArIsError = 0x29'
    ue[6] = '[Lua] [E33Wardrobe] started'
    ue[7] = '[Lua] error: something broke'
    tmp, L, body = load(ue4ss_log='\n'.join(ue) + '\n')
    G = L.globals()
    G.tickGT(20)
    G.KEYS['C+F9']()
    G.tickGT(2)
    rep = open(os.path.join(tmp, 'E33Wardrobe', 'report.txt'), encoding='utf-8').read()
    parts = {p.split('\n', 1)[0]: p.split('\n', 1)[1] for p in rep.split('\n==================== ')[1:]}
    errs = parts.get('UE4SS.log: wardrobe lines and errors', '').split('\n')
    tail = [x for x in parts.get('UE4SS.log: last 80 lines', '').split('\n') if x]
    check('report.txt: UE4SS errors section keeps "error" words and wardrobe lines, not ArIsError',
          errs[:2] == [ue[6], ue[7]] and not any('ArIsError' in x for x in errs), errs[:3])
    check('report.txt: "last 80 lines" holds 80 lines, ending at the last', len(tail) == 80 and tail[-1] == ue[-1],
          (len(tail), tail[-1:]))
    shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)

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

    # a long pass is spread over loop ticks (PC, 17-18 Oct: the camp's map-load pass took 244-283 ms
    # in one frame). Here every actor's look costs game time (5 ms per mesh read), so 7 actors don't
    # fit one tick's 12 ms.
    slow = '''
      local baseClock = os.clock
      EXTRA_S, SLOW = 0, false
      os.clock = function() return baseClock() + EXTRA_S end
      for k = 2, 7 do
        local b = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
        b._path = "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_" .. k .. ".Body"
        local a = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_" .. k, { Body = b },
          { K2_GetComponentsByClass = function() return TArray({ b }) end })
        a._class = ACTORS[1]._class; a._skin = "BP_CharacterSkinBase_C"
        table.insert(ACTORS, a)
      end
      for _, a in ipairs(ACTORS) do
        local b = a._p.Body; local g = b._f.GetSkeletalMeshAsset
        b._f.GetSkeletalMeshAsset = function(self) if SLOW then EXTRA_S = EXTRA_S + 0.005 end; return g(self) end
      end
      function DRESSED()
        local n = 0
        for _, a in ipairs(ACTORS) do if a._p.Body._mesh._path:find("/ZWOUTFITA/", 1, true) then n = n + 1 end end
        return n
      end
    '''
    tmp, L, body = load(preload=slow)
    G = L.globals()
    W = G.API_OUT
    lvf = os.path.join(tmp, 'E33Wardrobe', 'live_log.txt')
    plines = lambda: [x for x in open(lvf, encoding='utf-8').read().splitlines() if ' pass (' in x]  # noqa: E731
    G.tickGT(20)
    p0 = len(plines())
    G.SLOW = True
    W.setVariant(1, 1)
    seen, at_line = [], None
    for t in range(40):
        G.tickGT(1)
        seen.append(G.DRESSED())
        if at_line is None and len(plines()) > p0:
            at_line = t
    first = next((i for i, n in enumerate(seen) if n > 0), None)
    check('a pass over 7 slow actors is spread over several loop ticks', first is not None
          and seen[first] < 7 and 7 in seen and seen.index(7) > first, seen[:20])
    check('  every actor is dressed in the end, and the pass line is written once, after the last one',
          at_line is not None and seen[-1] == 7 and len(plines()) == p0 + 1 and at_line == seen.index(7)
          and '7 actor(s)' in plines()[-1], (at_line, seen[:20], plines()[p0:]))

    # an actor that dies or is replaced while the pass waits for its turn is skipped; a pick made
    # during the pass waits for it to finish
    L.execute('SLOW = false')
    W.setVariant(1, 2)                                          # back to Sleeveless (ZWOUTFITB)
    G.tickGT(20)
    p0 = len(plines())
    G.SLOW = True
    W.setVariant(1, 1)
    for _ in range(40):
        G.tickGT(1)
        if G.DRESSED() > 0:
            break
    d1 = G.DRESSED()
    L.execute('''
      ACTORS[7]._f.HasAnyFlags = function() return true end                       -- being destroyed
      ACTORS[6]._path = "/Game/Map.PersistentLevel.BP_Other_C_9"                  -- address reused
    ''')
    W.setVariant(2, 1)                                          # Lune color = red, during the pass
    for _ in range(40):                                         # to the end of the first pass
        G.tickGT(1)
        if len(plines()) > p0:
            break
    m6 = L.eval('ACTORS[6]._p.Body._mesh._path')
    m7 = L.eval('ACTORS[7]._p.Body._mesh._path')
    dressed = G.DRESSED()
    G.tickGT(80)
    pl = plines()[p0:]
    check('  (the first tick dressed some actors but not actors 6 and 7)', 0 < d1 < 6, d1)
    check('  a dead actor and a reused address are skipped when their turn comes',
          '/ZWOUTFITB/' in m6 and '/ZWOUTFITB/' in m7 and dressed == 5 and pl and '5 actor(s)' in pl[0],
          (m6, m7, dressed, pl))
    check('  a pick made during the pass gets its own pass after it',
          len(pl) == 2 and 'pass (Lune outfit = Sleeves + boots)' in pl[0] and 'pass (Lune color = red)' in pl[1], pl)
    shutil.rmtree(tmp, ignore_errors=True)

    # a map that loads while the previous map's pass is still waiting (book ch 16; PC 17 Oct 14:52:
    # camp 11 s after the world map, the crash pass started 1 s after the camp loaded). Neither the
    # old map's timer (camp 40 ticks after) nor its due pass (62 ticks after) may run before the
    # camp's own 6 s wait (120 ticks + 4 debounce)
    for gap in (40, 62):
        tmp, L, body = load()
        G = L.globals()
        G.API_OUT.setVariant(1, 1)
        G.tickGT(700)
        lvf = os.path.join(tmp, 'E33Wardrobe', 'live_log.txt')
        world = lambda n: L.eval('{ get = function() return { IsValid = function() return true end, '  # noqa: E731
                                 'GetFName = function() return FName("%s") end } end }' % n)
        G.LOADMAP_POST(None, world('Level_WorldMap_Main_V2'))
        G.tickGT(gap)
        G.MOCK_TICKS = G.MOCK_TICKS + 100                       # the camp's load: 5 s, no loop tick
        n0 = open(lvf, encoding='utf-8').read().count('pass (after map load)')
        G.LOADMAP_POST(None, world('Level_Camp_Main'))
        runs = []
        for t in range(1, 201):
            G.tickGT(1)
            if open(lvf, encoding='utf-8').read().count('pass (after map load)') > n0 + len(runs):
                runs.append(t)
        check(f'a map {gap} ticks after the previous one: no pass of the old map before the new map\'s wait',
              len(runs) == 1 and runs[0] >= 120, runs)
        shutil.rmtree(tmp, ignore_errors=True)

    # the log-only probe on the skin component's OnSkinAssignCompleted (21 Oct): registered once its
    # Blueprint class is loaded (RegisterHook fails before), the hook only keeps the parameters and
    # the next loop tick writes "component hook: <character> <- <skin>, <face> (known/new skin)"
    comp_fn = ('/Game/Gameplay/CharacterCustomization/Blueprints/BP_CharacterSkinComponent'
               '.BP_CharacterSkinComponent_C:OnSkinAssignCompleted')
    tmp, L, body = load(preload='''
      local baseRH = RegisterHook
      COMP_LOADED = false
      function RegisterHook(name, pre, post)
        if name == "%s" and not COMP_LOADED then error("no UFunction with the specified name was found") end
        return baseRH(name, pre, post)
      end''' % comp_fn)
    G = L.globals()
    G.API_OUT.setVariant(1, 1)
    G.tickGT(80)
    lvf = os.path.join(tmp, 'E33Wardrobe', 'live_log.txt')
    lv = open(lvf, encoding='utf-8').read()
    check('component hook probe: not registered while its class is not loaded, and says so once',
          lv.count('component hook: not yet') == 1 and G.PREHOOKS[comp_fn] is None, lv.count('component hook: not yet'))
    G.COMP_LOADED = True
    G.LOADMAP_POST(None, L.eval('{ get = function() return { IsValid = function() return true end, '
                                'GetFName = function() return FName("Level_WorldMap_Main_V2") end } end }'))
    G.tickGT(2)
    lv = open(lvf, encoding='utf-8').read()
    check('  registered after the next map load (the class is loaded then)',
          'component hook: ready (OnSkinAssignCompleted)' in lv and G.PREHOOKS[comp_fn] is not None)
    G.tickGT(200)
    L.execute('''
      PAWN = new("BP_jRPG_Character_World_C", "/Game/Map.PersistentLevel.BP_jRPG_Character_World_C_7")
      COMPO = new("BP_CharacterSkinComponent_C", PAWN._path .. ".BP_CharacterSkinComponent", {},
                  { GetOwner = function() return PAWN end })
      NEWSKIN = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_9")
      FACE = new("BP_CharacterFace_Lune_C", "/Game/Map.PersistentLevel.BP_CharacterFace_Lune_C_9")
      function W(o) return { get = function() return o end } end
    ''')
    mesh = L.eval('function(b) return b._mesh._path end')
    dressed = mesh(body)
    # PC 22 Oct: party leader switched back to Lune: the game shows her pooled skin actor again
    # (no spawn, no BeginPlay) with the game's own outfit on it
    L.execute('ACTORS[1]._p.Body._mesh = get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic")')
    n0 = open(lvf, encoding='utf-8').read().count('component hook: ')
    hook = G.PREHOOKS[comp_fn]
    L.eval('function(h) local o = IN_GT; IN_GT = true; h(W(COMPO), W(ACTORS[1]), W(FACE)); IN_GT = o end')(hook)
    L.eval('function(h) local o = IN_GT; IN_GT = true; h(W(COMPO), W(NEWSKIN), W(FACE)); IN_GT = o end')(hook)
    L.eval('function(h) h(W(COMPO), W(NEWSKIN), W(NEWSKIN)) end')(hook)       # not on the game thread
    early = open(lvf, encoding='utf-8').read().count('component hook: ') - n0
    G.tickGT(2)
    lines = [x for x in open(lvf, encoding='utf-8').read().splitlines() if 'component hook: BP_' in x]
    check('  the hook itself writes nothing; the next tick names the character, the skin and the face',
          early == 0 and len(lines) == 2
          and 'component hook: BP_jRPG_Character_World_C_7 <- BP_Lune_Skin_Chic_C_1, BP_CharacterFace_Lune_C_9 (shown again)' in lines[0]
          and 'component hook: BP_jRPG_Character_World_C_7 <- BP_Lune_Skin_Chic_C_9, BP_CharacterFace_Lune_C_9 (new skin)' in lines[1],
          (early, lines))
    G.tickGT(80)                                                # ~1 s re-check of a skin shown again
    check('  a skin actor the game shows again (pooled, no BeginPlay) is dressed again',
          dressed.startswith('/Game/Characters/ZWOUTFITA/') and mesh(body) == dressed, (dressed, mesh(body)))
    shutil.rmtree(tmp, ignore_errors=True)

    # a map load drops the pass of the old map
    tmp, L, body = load(preload=slow)
    G = L.globals()
    lvf = os.path.join(tmp, 'E33Wardrobe', 'live_log.txt')
    G.tickGT(20)
    p0 = len(plines())
    G.SLOW = True
    G.API_OUT.setVariant(1, 1)
    for _ in range(40):
        G.tickGT(1)
        if G.DRESSED() > 0:
            break
    d1 = G.DRESSED()
    G.LOADMAP_POST(None, None)
    G.SLOW = False
    G.tickGT(2)
    check('a map load drops the old map\'s unfinished pass', 0 < d1 < 7 and G.DRESSED() == d1, (d1, G.DRESSED()))
    G.tickGT(200)
    pl = plines()[p0:]
    check('  only the new map\'s pass is written', len(pl) == 1 and 'pass (after map load' in pl[0]
          and G.DRESSED() == 7, (pl, G.DRESSED()))
    shutil.rmtree(tmp, ignore_errors=True)

    # the "on screen" count leaves out another character's assets that don't show (PC, 18 Oct: a Lune
    # option counted Sciel's body_high_* textures as "not shown", 7/10)
    sciel = ('["/Game/Characters/Heros/Sciel/T_Sciel_Body_D"] = { "/Game/Characters/ZWOUTFITA/Sciel/T_Sciel_Body_D", '
             '"T_Sciel_Body_D", "Texture2D" },\n        ["/Game/Characters/Lune/Chic/MI_Chic"]')
    tmp, L, body = load(variants=base.VARIANTS.replace('["/Game/Characters/Lune/Chic/MI_Chic"]', sciel, 1))
    G = L.globals()
    G.tickGT(20)
    G.API_OUT.setVariant(1, 1)
    G.tickGT(20)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    ln = [x for x in lv.splitlines() if 'on screen: Lune outfit = ' in x]
    check('on screen: another character\'s texture in a Lune option is not counted as missing',
          ln and ': 2/2 asset(s)' in ln[-1] and 'T_Sciel_Body_D' not in ln[-1]
          and "1 of another character's not counted" in ln[-1], ln[-1:])
    shutil.rmtree(tmp, ignore_errors=True)

    # Auto Wear judged a pick by the pass BEFORE it: a look at a new character between the pick and
    # its pass (here: 2 ticks after the pick, 2 before the pass) found the pick's mesh "not shown"
    # and wore it over the very outfit it was made for (audit, Nov 2026).
    tmp, L, body = load(preload='''
      asset("SkeletalMesh", "/Game/Characters/Lune/Other/SK_Lune_Other", "SK_Lune_Other",
        { Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })
      function SPAWN_OTHER()                      -- a second Lune skin actor showing another outfit
        local b = meshComp("Body", get("/Game/Characters/Lune/Other/SK_Lune_Other.SK_Lune_Other"))
        b._path = "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_9.Body"
        local a = new("BP_Lune_Skin_Chic_C", "/Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_9", { Body = b },
          { K2_GetComponentsByClass = function() return TArray({ b }) end })
        a._class = ACTORS[1]._class; a._skin = "BP_CharacterSkinBase_C"
        table.insert(ACTORS, a)
        BEGINPLAY({ get = function() return a end })
      end
    ''')
    G = L.globals()
    W = G.API_OUT
    lvf = os.path.join(tmp, 'E33Wardrobe', 'live_log.txt')
    G.tickGT(20)
    W.setVariant(2, 1)                                          # Lune color = red: new skins are watched
    G.tickGT(20)
    G.SPAWN_OTHER()                                             # looked at 20 ticks from now
    G.tickGT(18)
    W.setVariant(1, 1)                                          # an outfit made for Chic, which Lune wears
    G.tickGT(60)
    lv = open(lvf, encoding='utf-8').read().splitlines()
    at = lambda s: next((i for i, x in enumerate(lv) if s in x), None)  # noqa: E731
    look, the_pass = at('re-check after spawn'), at('pass (Lune outfit = Sleeves + boots)')
    check('(the look at the new character came between the pick and its pass)',
          look is not None and the_pass is not None and look < the_pass, (look, the_pass))
    check('Auto Wear waits for the pick\'s own pass: an outfit that fits is not worn over itself',
          not W.isWear('CC/Lune outfit') and not any("Auto Wear: Lune outfit doesn't fit" in x for x in lv)
          and L.eval('function(b) return b._mesh._path end')(body).startswith('/Game/Characters/ZWOUTFITA/'),
          [x for x in lv if 'Auto Wear' in x])
    check('  and no "on screen" count is written from the pass before the pick',
          look is not None and not any('on screen: Lune outfit' in x for x in lv[look:the_pass]), lv[look:the_pass])
    shutil.rmtree(tmp, ignore_errors=True)

    # while a pass is under way (several ticks) the menu reads "pending", not half a pass: a pick
    # read "not visible" with a Wear button, and "<character> wears" emptied, until the last actor
    tmp, L, body = load(preload=slow + '''
      function ADD_MAELLE()                       -- first in the pass: a skin actor of another character
        local b = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
        b._path = "/Game/Map.PersistentLevel.BP_Maelle_Skin_C_1.Body"
        local a = new("BP_Maelle_Skin_C", "/Game/Map.PersistentLevel.BP_Maelle_Skin_C_1", { Body = b },
          { K2_GetComponentsByClass = function() return TArray({ b }) end })
        a._class = new("BlueprintGeneratedClass", "/Game/Characters/Maelle/BP_Maelle_Skin.BP_Maelle_Skin_C")
        a._class._super = ACTORS[1]._class._super
        a._skin = "BP_CharacterSkinBase_C"
        local g = b._f.GetSkeletalMeshAsset           -- over the tick's 12 ms by itself: a tick of its own
        b._f.GetSkeletalMeshAsset = function(self)
          if SLOW then EXTRA_S = EXTRA_S + 0.02; MAELLE_LOOKED = true end
          return g(self)
        end
        table.insert(ACTORS, 1, a)
      end
    ''')
    G = L.globals()
    W = G.API_OUT
    G.ADD_MAELLE()
    G.tickGT(20)
    W.setVariant(1, 2)
    G.tickGT(30)
    check('(before the pass: the pick is on, Lune and Maelle are loaded)', W.slotState(1) == 'on'
          and W.wornBy('Lune') is not None and list(W.loadedChars().values()) == ['Lune', 'Maelle'],
          (W.slotState(1), list(W.loadedChars().values())))
    G.SLOW = True
    W.setVariant(1, 1)
    mid = None
    for _ in range(12):                                         # to the tick that looked at Maelle's actor only
        G.tickGT(1)
        if G.MAELLE_LOOKED:
            mid = (G.DRESSED(), W.slotState(1), W.applyPending(), W.wornBy('Lune') is not None,
                   list(W.loadedChars().values()))
            break
    check('during a pass: the slot reads "pending", an apply is pending, and characters the pass hasn\'t '
          'reached yet still read as loaded',
          mid is not None and mid[0] == 0 and mid[1] == 'pending' and mid[2] is True and mid[3]
          and mid[4] == ['Lune', 'Maelle'], mid)
    G.tickGT(60)
    check('  after it: "on", nothing pending', G.DRESSED() == 7 and W.slotState(1) == 'on' and not W.applyPending(),
          (G.DRESSED(), W.slotState(1), W.applyPending()))
    shutil.rmtree(tmp, ignore_errors=True)

    # the same mistake at the end of a pass: a pick made while the pass was on its last actor (another
    # character's) was judged by that pass, which had not dressed anyone with it
    tmp, L, body = load(preload=slow + '''
      function ADD_MAELLE_LAST()
        local b = meshComp("Body", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
        b._path = "/Game/Map.PersistentLevel.BP_Maelle_Skin_C_1.Body"
        local a = new("BP_Maelle_Skin_C", "/Game/Map.PersistentLevel.BP_Maelle_Skin_C_1", { Body = b },
          { K2_GetComponentsByClass = function() return TArray({ b }) end })
        a._class = new("BlueprintGeneratedClass", "/Game/Characters/Maelle/BP_Maelle_Skin.BP_Maelle_Skin_C")
        a._class._super = ACTORS[1]._class._super
        a._skin = "BP_CharacterSkinBase_C"
        table.insert(ACTORS, a)
        for _, x in ipairs(ACTORS) do             -- every look over the tick's 12 ms: one actor per tick
          local xb = x._p.Body; local g = xb._f.GetSkeletalMeshAsset
          xb._f.GetSkeletalMeshAsset = function(self) if SLOW then EXTRA_S = EXTRA_S + 0.015 end; return g(self) end
        end
      end
    ''')
    G = L.globals()
    W = G.API_OUT
    lvf = os.path.join(tmp, 'E33Wardrobe', 'live_log.txt')
    G.ADD_MAELLE_LAST()
    G.tickGT(20)
    G.SLOW = True
    W.setVariant(2, 1)                                          # Lune color = red: a pass over 8 slow actors
    for _ in range(60):                                         # until Lune's last actor has been looked at
        G.tickGT(1)
        if 'BP_Lune_Skin_Chic_C_7 [Lune]' in open(lvf, encoding='utf-8').read():
            break
    running = W.applyPending() and not any(' pass (Lune color = red)' in x
                                           for x in open(lvf, encoding='utf-8').read().splitlines())
    W.setVariant(1, 1)                                          # an outfit made for Chic, which Lune wears
    G.tickGT(80)
    lv = open(lvf, encoding='utf-8').read().splitlines()
    check('(the pick was made while the pass was still running)', running, [x for x in lv if ' pass (' in x])
    check('a pick made during a pass is judged by its own pass: an outfit that fits is not worn over itself',
          not W.isWear('CC/Lune outfit') and not any("Auto Wear: Lune outfit doesn't fit" in x for x in lv)
          and G.DRESSED() == 7, ([x for x in lv if 'Auto Wear' in x], G.DRESSED()))
    shutil.rmtree(tmp, ignore_errors=True)

    # the "new skin" line's body, and dump.txt's skin component, come from the actor's component
    # list. Reading a part by property is only for outfit actors (1.3.1, the camp crashes); the line
    # still read Body / CharacterMesh0 by property on battle, companion and camp pawns.
    tmp, L, body = load(preload='''
      PROPREADS = {}
      function ADD_PAWN()
        local cm = meshComp("CharacterMesh0", get("/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic"))
        cm._path = "/Game/Map.PersistentLevel.BP_Pawn_AICompanion_Lune_C_1.CharacterMesh0"
        local props = setmetatable({}, { __index = function(_, k) PROPREADS[k] = (PROPREADS[k] or 0) + 1 end })
        local pawn = new("BP_Pawn_AICompanion_Lune_C", "/Game/Map.PersistentLevel.BP_Pawn_AICompanion_Lune_C_1", props,
          { K2_GetComponentsByClass = function() return TArray({ cm }) end })
        pawn._class = new("BlueprintGeneratedClass", "/Game/Characters/Lune/BP_Pawn_AICompanion_Lune.BP_Pawn_AICompanion_Lune_C")
        BEGINPLAY({ get = function() return pawn end })
      end
      function TRAP_SKIN()                        -- property reads of the skin actor that find nothing
        setmetatable(ACTORS[1]._p, { __index = function(_, k) PROPREADS[k] = (PROPREADS[k] or 0) + 1 end })
        -- and a skin component in its component list (the skin actor has no owner, as in game)
        local scCls = new("BlueprintGeneratedClass",
          "/Game/Gameplay/CharacterCustomization/Blueprints/BP_CharacterSkinComponent.BP_CharacterSkinComponent_C")
        REGSET(scCls._path, scCls)
        local a = ACTORS[1]
        local sc = new("BP_CharacterSkinComponent_C", a._path .. ".BP_CharacterSkinComponent", {})
        sc._class = scCls
        local k2 = a._f.K2_GetComponentsByClass
        a._f.K2_GetComponentsByClass = function(self, c) if c == scCls then return TArray({ sc }) end return k2(self, c) end
      end
    ''')
    G = L.globals()
    W = G.API_OUT
    G.tickGT(20)
    W.setVariant(2, 1)
    G.tickGT(20)
    G.ADD_PAWN()
    G.tickGT(40)
    lv = open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read()
    ln = [x for x in lv.splitlines() if 'new skin BP_Pawn_AICompanion_Lune_C_1:' in x]
    reads = dict(G.PROPREADS.items())
    check('a new companion pawn: the "new skin" line names its body from the component list',
          ln and 'shows CharacterMesh0 SK_Lune_Chic' in ln[0], ln)
    check('  and none of its parts is read by property', 'Body' not in reads and 'CharacterMesh0' not in reads
          and 'bHidden' in reads, reads)
    G.TRAP_SKIN()
    W.dump()
    G.tickGT(5)
    reads = dict(G.PROPREADS.items())
    dp = os.path.join(tmp, 'E33Wardrobe', 'dump.txt')
    dtxt = open(dp, encoding='utf-8').read() if os.path.exists(dp) else ''
    check('dump.txt lists the skin component of an actor without an owner (it never did: the list '
          '{ owner, actor } started with nil)',
          '  skin component: BP_CharacterSkinComponent_C /Game/Map.PersistentLevel.BP_Lune_Skin_Chic_C_1.'
          'BP_CharacterSkinComponent' in dtxt, [x for x in dtxt.splitlines() if 'skin' in x.lower()][:4])
    check('  found in its component list, not through the actor\'s Blueprint property',
          'BP_CharacterSkinComponent' not in reads, reads)
    shutil.rmtree(tmp, ignore_errors=True)

    # live_log.txt held open by another program (Windows): it can't be renamed at start, and opening
    # it for writing empties it. The last session is copied to live_log_previous.txt first.
    tmp, L, body = load(preload='os.rename = function() return nil, "Permission denied" end',
                        files={'live_log.txt': '21:00:00 #1 session start THE LAST SESSION\n'})
    prev = os.path.join(tmp, 'E33Wardrobe', 'live_log_previous.txt')
    check('a live log that can\'t be renamed is copied to live_log_previous.txt before the new one starts',
          os.path.exists(prev) and 'THE LAST SESSION' in open(prev, encoding='utf-8').read()
          and 'THE LAST SESSION' not in open(os.path.join(tmp, 'E33Wardrobe', 'live_log.txt'), encoding='utf-8').read(),
          os.path.exists(prev))
    shutil.rmtree(tmp, ignore_errors=True)

    # a variant with several meshes: which one Wear puts on (and the menu names) must not depend on
    # pairs() order, which differs from one game session to the next
    many = '''return { { mod = "Many", slots = { { id = "M/main", label = "Many: Lune outfit", character = "Lune", variants = {
      { id = "M/a", label = "A", map = {
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_D_Skin"] = { "/Game/Characters/ZWM/SK_Lune_D_Skin", "SK_Lune_D_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_B_Skin"] = { "/Game/Characters/ZWM/SK_Lune_B_Skin", "SK_Lune_B_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_E_Skin"] = { "/Game/Characters/ZWM/SK_Lune_E_Skin", "SK_Lune_E_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_A_Skin"] = { "/Game/Characters/ZWM/SK_Lune_A_Skin", "SK_Lune_A_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Customization/Skin/SK_Lune_C_Skin"] = { "/Game/Characters/ZWM/SK_Lune_C_Skin", "SK_Lune_C_Skin", "SkeletalMesh" },
        ["/Game/Characters/Lune/Other/SK_Lune_0_Other"] = { "/Game/Characters/ZWM/SK_Lune_0_Other", "SK_Lune_0_Other", "SkeletalMesh" } } } } } } } }'''
    got = []
    for _ in range(4):
        tmp, L, body = load(variants=many)
        W = L.globals().API_OUT
        got.append(W.targetOutfit(W.slots()[1]))
        shutil.rmtree(tmp, ignore_errors=True)
    check('of a variant\'s meshes, the outfit mesh first in a-z order is the one worn, in every session',
          got == ['/Game/Characters/Lune/Customization/Skin/SK_Lune_A_Skin'] * 4, got)

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
