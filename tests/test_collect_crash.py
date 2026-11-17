"""scripts/collect_crash.py on a fake game folder: the newest dump is moved, the logs copied, the mod's
last steps shown (no game, no retoc; the dump reading itself is tested by hand on real dumps)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    tmp = tempfile.mkdtemp(prefix='e33crash_')
    win64 = os.path.join(tmp, 'Win64')
    mod = os.path.join(win64, 'ue4ss', 'Mods', 'E33Wardrobe')
    os.makedirs(mod)
    old = os.path.join(win64, 'ue4ss', 'crash_2026_10_17_14_00_00.1.dmp')
    new = os.path.join(win64, 'ue4ss', 'crash_2026_10_17_14_52_26.5.dmp')
    open(old, 'wb').write(b'MDMP old')
    open(new, 'wb').write(b'MDMP new')
    t = time.time()
    os.utime(old, (t - 600, t - 600))
    open(os.path.join(win64, 'ue4ss', 'UE4SS.log'), 'w').write('UE4SS - v3.0.1\n')
    open(os.path.join(win64, 'ReShade.log'), 'w').write('reshade\n')
    open(os.path.join(mod, 'settings.txt'), 'w').write('b_swap = param\n')
    open(os.path.join(mod, 'live_log.txt'), 'w', encoding='utf-8').write(
        '14:52:26 #1 look BP_Character_Camp_Maelle_Relationship_Lvl2_C\n'
        '14:52:32 #2 WATCHDOG: the game thread has not run for 6 s; mod state: apply pass\n'
        '14:52:32 #3   step     -1 ms: components: property Face\n')
    out = os.path.join(tmp, 'reports')
    p = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'collect_crash.py'), '--win64', win64,
                        '--out', out, '--no-analyze'], capture_output=True, text=True, encoding='utf-8')
    folders = os.listdir(out) if os.path.isdir(out) else []
    got = os.listdir(os.path.join(out, folders[0])) if folders else []
    check('the newest dump is moved into a dated crash folder, the older one stays',
          p.returncode == 0 and folders and folders[0].endswith('_crash') and 'crash_2026_10_17_14_52_26.5.dmp' in got
          and not os.path.exists(new) and os.path.exists(old), (p.stdout[-300:], p.stderr[-300:], folders, got))
    check('  the logs are copied (UE4SS.log, the mod\'s live log and settings, ReShade.log)',
          {'UE4SS.log', 'live_log.txt', 'settings.txt', 'ReShade.log'} <= set(got), got)
    check('  and the stall the log ends in is shown, with the mod\'s last steps after the WATCHDOG line',
          'components: property Face' in p.stdout and 'WATCHDOG' in p.stdout, p.stdout[-400:])
    # book ch 20: the excerpt was the region around the last WATCHDOG line, wherever it was
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import collect_crash as cc
    steps = [f'16:09:43 #{100 + k}   step   -{40 - k} ms: look {k}' for k in range(40)]
    long_stall = (['16:09:30 #90 change BP_A [Lune].Body: mesh a -> b',
                   '16:09:43 #99 WATCHDOG: the game thread has not run for 6 s; mod state: idle (since 16:09:37)',
                   '16:09:43 #100 WATCHDOG: last mod step: idle'] + steps
                  + [f'16:{10 + k}:00 #{200 + k} WATCHDOG: the game thread has not run for {23 + 15 * k} s; mod state: '
                     'idle (since 16:09:37)' for k in range(5)])
    what, block = cc.end_of_log(long_stall)
    check('end of log, a long stall: its first WATCHDOG line, all its steps, and the last repeat',
          block[0].endswith('(since 16:09:37)') and '6 s' in block[0] and sum(' step ' in x for x in block) == 40
          and block[-1] == long_stall[-1] and len(block) == 43, (what, block[:3], block[-2:], len(block)))
    went_on = ['21:11:10 #50 WATCHDOG: the game thread has not run for 7 s; mod state: idle (since 21:11:03)',
               '21:11:10 #51 WATCHDOG: last mod step: idle',
               '21:11:12 #52 WATCHDOG: the game thread ran again after 9 s',
               '21:11:13 #53 stats (60 s): 2 looks'] + [f'21:51:{k:02d} #{60 + k} change camp {k}' for k in range(10)]
    what, block = cc.end_of_log(went_on)
    check('  a crash with no watchdog line at the end: the last lines, not an older stall that went on',
          'does not end in a stall' in what and block == went_on[-8:] and not any('WATCHDOG' in x for x in block),
          (what, block))
    loop_after = ['22:32:35 #2250 WATCHDOG: the game thread has not run for 6 s; mod state: idle (since 22:32:29)',
                  '22:32:37 #2260 hitch: a frame took 7100 ms']
    check('  a stall the loop wrote after (an older build with no "ran again"): not the end',
          'does not end in a stall' in cc.end_of_log(loop_after)[0], cc.end_of_log(loop_after))
    # PC 17 Oct: UE4SS still writing a full dump holds it open without sharing; the script crashed
    if os.name == 'nt':
        import ctypes
        busy = os.path.join(win64, 'ue4ss', 'crash_2026_10_17_16_09_37.6.dmp')
        open(busy, 'wb').write(b'MDMP busy')
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW(busy, 0x80000000, 0, None, 3, 0x80, None)   # GENERIC_READ, no sharing, OPEN_EXISTING
        try:
            p = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'collect_crash.py'), '--win64', win64,
                                '--out', out, '--no-analyze'], capture_output=True, text=True, encoding='utf-8')
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
        check('a dump the game still holds open: no traceback, the logs are collected, run again later',
              p.returncode == 3 and 'Traceback' not in p.stderr and 'still open by the game' in p.stdout
              and 'run this again once the game has closed' in p.stdout and os.path.exists(busy),
              (p.returncode, p.stdout[-300:], p.stderr[-300:]))
    else:
        print('SKIP locked dump check: Windows only')
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
