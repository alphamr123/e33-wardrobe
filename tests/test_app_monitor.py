"""Tests for the app's live game-log watcher, app/backend/monitor.py (run: python tests/test_app_monitor.py).

Small synthetic logs in the formats the game writes (UE4SS.log lines "[YYYY-MM-DD HH:MM:SS.fffffff] ...",
live_log.txt lines "HH:MM:SS #N ..."), appended between poll_once() calls.
"""
import datetime as dt
import importlib.util
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location('e33_monitor', os.path.join(ROOT, 'app', 'backend', 'monitor.py'))
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'  -> {extra}'))
    fails += (not cond)


# The timeline: at(400) is about now, so the "60 s after UE4SS started" check can be driven by the
# log's own times.
T0 = dt.datetime.now().replace(microsecond=0) - dt.timedelta(seconds=400)


def at(s):
    return T0 + dt.timedelta(seconds=s)


def hms(s):
    return at(s).strftime('%H:%M:%S')


class Game:
    """A fake game folder; writes the two logs the way UE4SS and the menu do."""

    def __init__(self, root):
        self.root = root
        self.ue4ss = os.path.join(root, 'Sandfall', 'Binaries', 'Win64', 'ue4ss')
        self.menu = os.path.join(self.ue4ss, 'Mods', 'E33Wardrobe')
        self.crashes = os.path.join(root, 'Crashes')
        for d in (self.menu, self.crashes):
            os.makedirs(d, exist_ok=True)
        self.live_path = os.path.join(self.menu, 'live_log.txt')
        self.ue_path = os.path.join(self.ue4ss, 'UE4SS.log')
        self.seq = 0

    def paths(self):
        return {'game_root': self.root, 'paks': None, 'ue4ss_dir': self.ue4ss, 'menu_dir': self.menu}

    def raw(self, path, data, mode='ab'):
        with open(path, mode) as f:
            f.write(data.encode('utf-8') if isinstance(data, str) else data)

    def live(self, s, msg, mode='ab'):
        self.seq += 1
        self.raw(self.live_path, f'{hms(s)} #{self.seq} {msg}\r\n', mode)

    def new_live_session(self, s):
        if os.path.exists(self.live_path):
            os.replace(self.live_path, os.path.join(self.menu, 'live_log_previous.txt'))
        self.seq = 0
        self.live(s, f'session start {at(s):%Y-%m-%d %H:%M:%S}', 'wb')

    def ue(self, s, text, mode='ab'):
        frac = int((s % 1) * 10_000_000) or 1234567
        self.raw(self.ue_path, f'[{at(int(s)):%Y-%m-%d %H:%M:%S}.{frac:07d}] {text}\n', mode)

    def new_ue(self, s, menu=True, lua=8):
        """A game start: UE4SS rewrites its log; its Lua mods start `lua` seconds later."""
        mods = 'C:\\Games\\E33\\Sandfall\\Binaries\\Win64\\ue4ss\\Mods'
        self.ue(s, 'Console created', 'wb')
        self.ue(s + 0.01, 'UE4SS - v3.0.1 Beta #0 - Git SHA #527a483b')
        self.ue(s + 0.02, 'Setting up mods...')
        self.ue(s + 0.03, f'Starting mods (from mods.txt ({mods}\\mods.txt) load order)...')
        self.ue(s + 0.04, f'Starting mods (from enabled.txt ({mods}), no defined load order)...')
        self.ue(s + lua, f'Starting mods (from mods.txt ({mods}\\mods.txt) load order)...')
        self.ue(s + lua + 0.1, "Starting Lua mod 'Keybinds'")
        self.ue(s + lua + 0.2, f'Starting mods (from enabled.txt ({mods}), no defined load order)...')
        if menu:
            self.ue(s + lua + 0.3, "Mod 'E33Wardrobe' has enabled.txt, starting mod.")


def keys(m):
    return {p['key']: p for p in m.snapshot()['problems']}


tmp = tempfile.mkdtemp(prefix='e33mon_')
try:
    g = Game(os.path.join(tmp, 'game'))
    os.makedirs(os.path.join(g.crashes, 'UECC-Windows-OLD_0000'))     # a crash from before: not reported
    proc = {'v': False}
    m = mon.Monitor(g.paths, process_check=lambda: proc['v'], crash_dir=g.crashes, process_interval=0)

    # ------------------------------------------------------------------ nothing there yet
    m.poll_once()
    s = m.snapshot()
    check('no logs yet: nothing known, no problems',
          s['since'] is None and s['problems'] == [] and s['on_screen'] == [] and not s['game_running']
          and not s['watching'] and s['tail'] == [], s)

    # ------------------------------------------------------------------ the game starts; the files appear
    g.new_ue(0)
    g.new_live_session(8)
    g.live(8, 'report: start')
    g.live(10, 'log: loaded 3 slot(s)')
    g.ue(10.3, '[Lua] [E33Wardrobe] loaded 3 slot(s)')
    g.live(10, 'wardrobe: 3 slot(s)')
    g.live(10, '  slot 1 Lune Outfit Options: Variants [Lune] 4 variant(s), selected: off')
    g.live(10, '  slot 2 Altered Flower Suit: Main [Sciel] 1 variant(s), selected: off')
    g.live(10, '  slot 3 Maelle Travel Coat: Main [Maelle] 1 variant(s), selected: Maelle Travel Coat/Main')
    g.live(10, 'game-thread work runs in one game-thread loop every 50 ms (LoopInGameThreadWithDelay)')
    ready = '1.1.0 ready (6 policy hook(s)) - press DEL for the menu. slot 1/3 Lune Outfit Options: Variants [Lune only] = off (vanilla)'
    g.live(10, 'log: ' + ready)
    g.ue(10.4, '[Lua] [E33Wardrobe] ' + ready)
    g.live(11, 'log: applied to 12 skin actor(s)')
    g.live(11, 'pass (reload: variants.lua + selection.txt): 2 change(s)')
    g.live(11, '  on screen: Maelle Travel Coat: Main = on: 3/4 asset(s); not shown: Maelle_Coat_Normal; worn (Wear)')
    g.live(11, '  on screen: Lune Outfit Options: Variants = 843 Clea: Shorter Skirt: 2/2 asset(s)')
    m.poll_once()
    s = m.snapshot()
    check('files appearing later are read from the start', s['since'] == hms(8), s['since'])
    check('menu_active after the ready line', s['menu_active'] is True)
    check('on_screen parsed (labels with ": " inside, worn flag)', s['on_screen'] == [
        {'slot': 'Maelle Travel Coat: Main', 'variant': 'on', 'shown': 3, 'total': 4, 'worn': True},
        {'slot': 'Lune Outfit Options: Variants', 'variant': '843 Clea: Shorter Skirt', 'shown': 2, 'total': 2,
         'worn': False}], s['on_screen'])
    check('last_activity = time of the last live_log line', s['last_activity'] == hms(11), s['last_activity'])
    check('tail: session lines, "HH:MM:SS message" without the #N',
          s['tail'][0] == f'{hms(8)} session start {at(8):%Y-%m-%d %H:%M:%S}' and len(s['tail']) == 13
          and not any(' #' in t for t in s['tail']), s['tail'][:2])
    check('no problems in a clean start', s['problems'] == [], s['problems'])
    check('game_running: live_log.txt grew just now', s['game_running'] is True)

    # ------------------------------------------------------------------ rules and counting
    miss = 'could not load /Game/Mods/LuneOutfitOptions/Textures/Lune_Skirt_N.Lune_Skirt_N'
    g.live(20, 'log: ' + miss)
    g.ue(20.2, '[Lua] [E33Wardrobe] ' + miss)
    m.poll_once()
    p = keys(m).get('load:Lune_Skirt_N')
    check('"could not load" -> warn naming the asset', p and p['level'] == 'warn' and 'Lune_Skirt_N' in p['title'], p)
    check('the same message in both logs counts once', p and p['count'] == 1, p and p['count'])
    g.live(40, 'log: ' + miss)
    m.poll_once()
    g.ue(40.5, '[Lua] [E33Wardrobe] ' + miss)        # its UE4SS copy only in the next poll
    m.poll_once()
    p = keys(m)['load:Lune_Skirt_N']
    check('repeat counted, first/last kept, late copy from the other log not counted',
          p['count'] == 2 and p['first'] == hms(20) and p['last'] == hms(40), p)

    # ------------------------------------------------------------------ watchdog
    g.live(60, '  change BP_CharacterSkinBase_Lune_C_1 [Lune].Body: mesh /Game/A/SK_A -> /Game/B/SK_B')
    g.live(60, '    loading /Game/Mods/LuneOutfitOptions/Meshes/SK_Lune_Clea.SK_Lune_Clea')
    for n in (6, 21, 36):
        g.live(60 + n, f'WATCHDOG: the game thread has not run for {n} s; mod state: apply pass (after map load) '
                       f'(since {hms(60)})')
    m.poll_once()
    p = keys(m).get('watchdog-work')
    check('watchdog while the menu works: warn, one stall, longest time in the title',
          p and p['level'] == 'warn' and p['count'] == 1 and p['title'] == 'The game stopped responding for 36 s', p)
    check('  detail names the state and the last step',
          p and 'apply pass (after map load)' in p['detail'] and 'SK_Lune_Clea' in p['detail'], p and p['detail'])
    g.live(100, f'WATCHDOG: the game thread has not run for 7 s; mod state: idle (since {hms(93)})')
    m.poll_once()
    p = keys(m).get('watchdog-idle')
    check('watchdog while idle: the pause came from the game (info for a short stall)',
          p and p['level'] == 'info' and 'game itself' in p['detail'] and p['title'].endswith('7 s'), p)
    g.live(118, f'WATCHDOG: the game thread has not run for 31 s; mod state: idle (since {hms(87)})')
    m.poll_once()
    p = keys(m)['watchdog-idle']
    check('  a second, long idle stall: count 2, warn', p['count'] == 2 and p['level'] == 'warn' and '31 s' in p['title'], p)

    # ------------------------------------------------------------------ UE4SS.log errors
    g.ue(120, 'Ref was not function')
    g.ue(121, '[Lua::call_function] lua_pcall returned LUA_ERRRUN => C:\\Users\\Ann\\Games\\E33\\ue4ss\\Mods\\'
              'E33Wardrobe\\Scripts\\main.lua:120: attempt to index a nil value')
    g.ue(122, '[Lua::call_function] lua_pcall returned LUA_ERRRUN => [string "chunk"]:3: bad argument #1')
    g.raw(g.ue_path, 'stack traceback:\n\t[C]: in ?\n\tC:\\Games\\E33\\ue4ss\\Mods\\E33Wardrobe\\Scripts\\menu.lua:88: '
                     "in function 'draw'\n")
    g.ue(123, '[Lua::call_function] lua_pcall returned LUA_ERRRUN => OtherMod\\Scripts\\main.lua:5: oops')
    g.ue(124, '[Lua] [E33Wardrobe] applied to 12 skin actor(s)')
    g.ue(125, '[Lua] [OtherMod] error: something of its own')
    m.poll_once()
    k = keys(m)
    p = k.get('ref-not-function')
    check('"Ref was not function" -> error explaining the threading problem',
          p and p['level'] == 'error' and 'threading' in p['detail'] and 'Update UE4SS' in p['hint'], p)
    lua = [p for p in k.values() if p['key'].startswith('ue4ss-lua:')]
    check('Lua errors naming the menu: 2 (one direct, one through its stack traceback), none for another mod',
          len(lua) == 2 and all(p['level'] == 'error' for p in lua), [p['detail'] for p in lua])
    check('  user name in paths replaced by <user>', any('<user>' in p['detail'] for p in lua)
          and not any('Ann' in p['detail'] for p in lua), [p['detail'] for p in lua])
    check('  the traceback one carries the error text', any('bad argument' in p['detail'] for p in lua))

    # ------------------------------------------------------------------ the menu's own messages
    err = "apply failed on BP_CharacterSkinBase_Lune_C_2147: main.lua:900: attempt to index a nil value (field '?')"
    g.live(130, 'log: ' + err)
    g.ue(130.6, '[Lua] [E33Wardrobe] ' + err)
    g.live(131, "log: menu action 'Fix look' failed: menu.lua:12: boom")
    g.live(132, 'log: dropped 2 pick(s) of mods no longer in the wardrobe')
    g.live(132, 'log: slot 2/3 Altered Flower Suit: Main [Sciel only] = Failed Experiment')   # a label, not a problem
    m.poll_once()
    k = keys(m)
    ap = [p for p in k.values() if p['key'].startswith('apply:')]
    check('"apply failed" -> one error, counted once across both logs',
          len(ap) == 1 and ap[0]['level'] == 'error' and ap[0]['count'] == 1, ap)
    check("menu button failure names the button", any(p['title'] == "The menu button 'Fix look' failed" for p in k.values()))
    p = k.get('dropped-picks')
    check('"dropped" picks -> info', p and p['level'] == 'info' and p['title'] == 'Cleared 2 pick(s) of removed mods', p)
    check('slot descriptions are not problems', not any('Failed Experiment' in p['detail'] for p in k.values()))

    # ------------------------------------------------------------------ a pick that shows nothing, Auto Wear, empty textures
    g.live(140, 'menu shows: Sciel · Altered Flower: on')
    g.live(140, 'log: slot 2/3 Altered Flower Suit: Main [Sciel only] = on')
    g.live(141, 'log: applied to 12 skin actor(s)')
    g.live(141, 'pass (Altered Flower Suit: Main = on): 0 change(s) - nothing loaded needed changing')
    g.live(141, '  on screen: Maelle Travel Coat: Main = on: 3/4 asset(s); worn (Wear)')
    g.live(141, '  on screen: Altered Flower Suit: Main = on: 0/5 asset(s); not shown: SK_Sciel_Flower, Sciel_Flower_BaseColor')
    m.poll_once()
    s = m.snapshot()
    p = keys(m).get('unseen:Altered Flower Suit: Main')
    check('a new pass replaces the on-screen table', [r['slot'] for r in s['on_screen']] ==
          ['Maelle Travel Coat: Main', 'Altered Flower Suit: Main'] and s['on_screen'][1]['shown'] == 0, s['on_screen'])
    check('a pick showing 0 of its pieces -> info naming the character, Wear / Auto Wear hint',
          p and p['level'] == 'info' and 'Sciel' in p['detail'] and 'Auto Wear' in p['hint'], p)
    g.live(141, "Auto Wear: Altered Flower Suit: Main doesn't fit what Sciel wears; worn in place of it")
    g.live(141, 'log: setting wear = Altered Flower Suit/Main')
    g.live(142, "  change BP_CharacterSkinBase_Sciel_C_5 [Sciel].Body: mat2 texture Color_MAIN: empty (the mod's material "
                "points at a texture it doesn't have) -> /Game/Characters/Heros/Sciel/ZWABC123/Sciel_Body_Color "
                "(the mod's own texture for it)")
    g.live(142, "  change BP_GameMenu_Sciel_C_6 [Sciel].Body: mat2 texture Color_MAIN: empty (the mod's material "
                "points at a texture it doesn't have) -> /Game/Characters/Heros/Sciel/ZWABC123/Sciel_Body_Color "
                "(the mod's own texture for it)")
    g.live(142, 'pass (Auto Wear on: Altered Flower Suit: Main): 3 change(s)')
    g.live(142, '  on screen: Maelle Travel Coat: Main = on: 3/4 asset(s); worn (Wear)')
    g.live(142, '  on screen: Altered Flower Suit: Main = on: 5/5 asset(s); worn (Wear)')
    m.poll_once()
    k, s = keys(m), m.snapshot()
    check('Auto Wear line -> info, and the "nothing changed" item goes away',
          'auto-wear:Altered Flower Suit: Main' in k and 'unseen:Altered Flower Suit: Main' not in k, list(k))
    check('  on screen now 5/5, worn', s['on_screen'][1] == {'slot': 'Altered Flower Suit: Main', 'variant': 'on',
                                                             'shown': 5, 'total': 5, 'worn': True}, s['on_screen'])
    p = k.get('empty-texture:Sciel:Color_MAIN:Sciel_Body_Color')
    check('empty texture filled -> info naming texture and source',
          p and p['level'] == 'info' and 'Sciel_Body_Color' in p['detail'] and "the mod's own" in p['detail']
          and 'automatically' in p['detail'], p)
    check('  the same fill on two actors in one pass counts once', p and p['count'] == 1, p and p['count'])
    g.live(150, "  change BP_GameMenu_Lune_C_9 [Lune].Body: mat0 texture Normal_MAIN: empty (the mod's material points "
                "at a texture it doesn't have) -> /Game/Characters/Heros/Lune/ZW99/Lune_Body_N (what the body showed before)")
    g.live(150, 'pass (Lune Outfit Options: Variants = 843 Clea: Shorter Skirt): 4 change(s)')
    g.live(150, '  on screen: Lune Outfit Options: Variants = 843 Clea: Shorter Skirt: 2/2 asset(s)')
    m.poll_once()
    p = keys(m).get('empty-texture:Lune:Normal_MAIN:Lune_Body_N')
    check('  the pick of that pass is named', p and 'Seen after picking Lune Outfit Options: Variants = 843 Clea: '
                                                    'Shorter Skirt' in p['detail'], p and p['detail'])
    g.live(160, 'pass (after map load): 0 change(s) - nothing loaded needed changing')
    g.live(160, 'map loaded: Level_Camp_Main')
    m.poll_once()
    check('a pass without on-screen lines empties the table', m.snapshot()['on_screen'] == [], m.snapshot()['on_screen'])

    # ------------------------------------------------------------------ partial last line, bad bytes
    g.raw(g.live_path, f'{hms(170)} #{g.seq + 1} log: could not lo')
    g.seq += 1
    m.poll_once()
    check('a partial last line waits', 'load:Sciel_Coat' not in keys(m))
    g.raw(g.live_path, 'ad /Game/Mods/TravelCoat/Sciel_Coat.Sciel_Coat\r\n')
    m.poll_once()
    check('  and is read once complete', keys(m).get('load:Sciel_Coat', {}).get('count') == 1, list(keys(m)))
    g.raw(g.live_path, f'{hms(171)} #{g.seq + 1} menu shows: '.encode() + b'\xff\xfe broken bytes\r\n')
    g.seq += 1
    m.poll_once()
    check('invalid UTF-8 is replaced, not fatal', any('\ufffd' in t for t in m.snapshot()['tail']))

    # ------------------------------------------------------------------ problems_text
    txt = m.problems_text()
    check('problems_text: blocks with level, time, title, detail, count, hint',
          "[ERROR] " in txt and "UE4SS reported 'Ref was not function'" in txt and 'What to do: ' in txt
          and f'{hms(20)} to {hms(40)}, 2 times' in txt and 'threading' in txt, txt[:600])
    check('problems_text: header and the on-screen line', txt.startswith('E33 Wardrobe: game log problems')
          and 'in-game menu: started (1.1.0)' in txt and 'UE4SS v3.0.1 Beta #0 - Git SHA #527a483b' in txt
          and 'On screen: nothing reported yet.' in txt, txt[:300])
    errs = [i for i, ln in enumerate(txt.splitlines()) if ln.startswith('[ERROR]')]
    infos = [i for i, ln in enumerate(txt.splitlines()) if ln.startswith('[INFO]')]
    check('problems_text: errors before info', errs and infos and max(errs) < min(infos))

    # ------------------------------------------------------------------ the game process goes away
    proc['v'] = True
    m.poll_once()
    g.live(180, "  change BP_CharacterSkinBase_Lune_C_1 [Lune].Body: mat0 /Game/A/MI_A -> /Game/B/MI_B")
    m.poll_once()
    g.live(181, 'log: menu closed')
    m.poll_once()
    proc['v'] = False
    m.poll_once()
    check('game gone after the menu was closed: no warning (conservative)', 'stopped-working' not in keys(m))
    proc['v'] = True
    m.poll_once()
    g.live(190, "  change BP_CharacterSkinBase_Lune_C_1 [Lune].Body: mat1 /Game/A/MI_C -> /Game/B/MI_D")
    m.poll_once()
    proc['v'] = False
    m.poll_once()
    p = keys(m).get('stopped-working')
    check('game gone right after the menu changed something -> warn', p and p['level'] == 'warn'
          and 'changing an outfit' in p['detail'], p)
    m.poll_once()
    check('old crash folders are not reported', not any(k.startswith('crash:') for k in keys(m)))
    os.makedirs(os.path.join(g.crashes, 'UECC-Windows-1A2B3C_0000'))
    m.poll_once()
    k = keys(m)
    p = k.get('crash:UECC-Windows-1A2B3C_0000')
    check('a new crash folder -> error "The game crashed at HH:MM"',
          p and p['level'] == 'error' and p['title'].startswith('The game crashed at ') and len(p['title']) == 25
          and 'crash folder' in p['hint'] and 'report.txt' in p['hint'], p)
    check('  it replaces the "closed while working" warning and says the menu was working',
          'stopped-working' not in k and p and 'working' in p['detail'], list(k))

    # ------------------------------------------------------------------ a new session
    before = len(m.snapshot()['problems'])
    g.new_live_session(300)
    g.live(300, 'report: start')
    m.poll_once()
    s = m.snapshot()
    check('new session start line: since, empty table, tail of this session only',
          s['since'] == hms(300) and s['on_screen'] == [] and len(s['tail']) == 2 and not s['menu_active'], s)
    check('  problems reset to one "Previous session had N problem(s)" item',
          len(s['problems']) == 1 and s['problems'][0]['key'] == 'previous-session'
          and s['problems'][0]['title'] == f'Previous session had {before} problem(s)', s['problems'])

    # ------------------------------------------------------------------ UE4SS.log rewritten shorter, menu doesn't start
    size_before = os.path.getsize(g.ue_path)
    g.new_ue(400, menu=False, lua=40)                  # a slow PC: Lua mods start 40 s in
    check('(the rewritten UE4SS.log is shorter)', os.path.getsize(g.ue_path) < size_before)
    m.poll_once()
    s = m.snapshot()
    check('rewritten UE4SS.log = a game start: since moves, old items dropped',
          s['since'] == hms(400) and s['problems'] == [], s)
    g.ue(470, '[Lua] [Keybinds] loaded')
    m.poll_once()
    check('70 s after UE4SS started but 30 s after its Lua mods: no warning yet', 'menu-not-started' not in keys(m))
    g.ue(505, '[Lua] [Keybinds] tick')
    m.poll_once()
    p = keys(m).get('menu-not-started')
    check('65 s after the Lua mods and no E33Wardrobe start or ready line -> warn, hint names the missing enabled.txt',
          p and p['level'] == 'warn' and 'enabled.txt' in p['hint'], p)

    # ------------------------------------------------------------------ next game: UE4SS too old
    g.new_ue(520)
    g.new_live_session(528)
    old = ('This UE4SS build is too old for E33Wardrobe: it has no LoopInGameThreadWithDelay. Use a UE4SS experimental '
           'build from December 2025 or newer (tested: 3.0.1-1125-g527a483b). The mod stays off.')
    g.live(528, 'log: ' + old)
    g.ue(528.5, '[Lua] [E33Wardrobe] ' + old)
    m.poll_once()
    s, k = m.snapshot(), keys(m)
    check('UE4SS start then the menu session start: one session, since = the session line',
          s['since'] == hms(528) and k.get('previous-session', {}).get('title') == 'Previous session had 1 problem(s)', s)
    p = k.get('ue4ss-too-old')
    check('UE4SS too old -> error with what to install, counted once',
          p and p['level'] == 'error' and p['count'] == 1 and 'Experimental' in p['hint'], p)
    g.ue(620, '[Lua] [Keybinds] tick')
    m.poll_once()
    check('  the "too old" error explains the menu not being ready: no second warning',
          'menu-not-ready' not in keys(m) and 'menu-not-started' not in keys(m), list(keys(m)))

    # ------------------------------------------------------------------ first look at a big log: only the last 256 KB
    g2 = Game(os.path.join(tmp, 'game2'))
    lines = [f'{hms(0)} #1 session start {at(0):%Y-%m-%d %H:%M:%S}', f'{hms(1)} #2 log: could not load /Game/Old/Early_Asset.Early_Asset']
    filler = '  change BP_CharacterSkinBase_Lune_C_1 [Lune].Body: mat0 /Game/Characters/Lune/MI_Lune_Body -> /Game/X/MI_Y'
    lines += [f'{hms(2)} #{i} {filler}' for i in range(3, 6003)]
    lines += [f'{hms(3)} #6003 log: could not load /Game/New/Late_Asset.Late_Asset']
    g2.raw(g2.live_path, '\r\n'.join(lines) + '\r\n', 'wb')
    check('(the big log is over 256 KB)', os.path.getsize(g2.live_path) > 2 * mon.INITIAL_TAIL)
    g2.new_ue(-5)
    m2 = mon.Monitor(g2.paths, process_check=None, crash_dir=None)
    m2.poll_once()
    s, k = m2.snapshot(), keys(m2)
    check('first look reads the end only: late line seen, early line not',
          'load:Late_Asset' in k and 'load:Early_Asset' not in k, list(k))
    check('  since comes from the session line at the top of the file', s['since'] == hms(0), s['since'])
    check('  tail holds the last 200 lines', len(s['tail']) == 200 and 'Late_Asset' in s['tail'][-1], len(s['tail']))
    check('  a first look is not growth: game not running', s['game_running'] is False)
    proc2 = {'v': True}
    m5 = mon.Monitor(g2.paths, process_check=lambda: proc2['v'], crash_dir=None, process_interval=0)
    m5.poll_once()
    proc2['v'] = False
    m5.poll_once()
    check('  old work lines read at the first look don\'t make a game exit look like a crash',
          'stopped-working' not in keys(m5), list(keys(m5)))

    # rewritten with more bytes than before (the size alone doesn't show it; the first line does)
    g2.ue(-5, 'Console created', 'wb')
    for i in range(400):
        g2.ue(-4 + i * 0.01, f'Already constructed: ["/Script/Engine", "Thing{i}"]')
    g2.ue(10, 'Ref was not function')
    m2.poll_once()
    check('a rewritten UE4SS.log that is longer than before is still noticed', 'ref-not-function' in keys(m2),
          list(keys(m2)))

    # ------------------------------------------------------------------ speed
    t = time.perf_counter()
    for _ in range(1000):
        m.poll_once()
    took = time.perf_counter() - t
    check(f'1000 polls with nothing new: {took * 1000:.0f} ms (< 1 s)', took < 1.0, took)

    # ------------------------------------------------------------------ the thread
    m3 = mon.Monitor(g.paths, process_check=lambda: False, crash_dir=None)
    m3.start()
    first = m3._thread
    m3.start()
    check('start() is idempotent', m3._thread is first and first.is_alive())
    time.sleep(1.3)
    s = m3.snapshot()
    check('the thread polls: watching, session known', s['watching'] and s['since'] == hms(528), s['since'])
    m3.stop()
    check('stop() ends it', not m3.snapshot()['watching'])
    m3.start()
    check('start() after stop() runs again', m3.snapshot()['watching'])
    m3.stop()

    m4 = mon.Monitor(lambda: {'game_root': None, 'paks': None, 'ue4ss_dir': None, 'menu_dir': None},
                     process_check=None, crash_dir=None)
    m4.poll_once()
    check('no paths: empty monitor, "No problems" text', 'No problems seen this session.' in m4.problems_text()
          and m4.snapshot()['problems'] == [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
