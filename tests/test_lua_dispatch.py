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
function RegisterHook(name, pre, post) HOOKS[name] = post; return 1, 2 end
function RegisterLoadMapPostHook(fn) LOADMAP_POST = fn end
'''


def load(no_gt_loop=False, settings=''):
    tmp = tempfile.mkdtemp(prefix='e33disp_')
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    shutil.copy(base.MAIN, scripts)
    open(os.path.join(scripts, 'menu.lua'), 'w').write('return { init = function(api) API_OUT = api end }\n')
    open(os.path.join(scripts, 'variants.lua'), 'w').write(base.VARIANTS)
    if settings:
        open(os.path.join(tmp, 'E33Wardrobe', 'settings.txt'), 'w').write(settings)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(COUNTERS)
    if no_gt_loop:
        L.execute('LoopInGameThreadWithDelay = nil')
    body, _a = L.execute(base.SCENARIO)
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
    check('  once per stall (not every second)', live().count('WATCHDOG') == 1)
    check('  and it never queued anything', G.EIGT == 0 and G.EWD == 0)
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open

    # a UE4SS build without LoopInGameThreadWithDelay
    tmp, L, body = load(no_gt_loop=True)
    G = L.globals()
    mesh = L.eval('function(b) return b._mesh._path end')
    check('a UE4SS build without LoopInGameThreadWithDelay: the mod stays off and says why, instead of '
          'queueing from other threads (which can crash those builds)',
          G.EIGT == 0 and len(list(G.ASYNC_LOOPS.values())) == 0 and 'too old for E33Wardrobe' in G.getlog()
          and G.CMDS['wardrobe'] is None, (G.EIGT, len(list(G.ASYNC_LOOPS.values())), G.CMDS['wardrobe']))
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
