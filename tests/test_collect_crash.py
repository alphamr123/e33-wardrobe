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
    check('  and the mod\'s last steps before the watchdog are shown',
          'components: property Face' in p.stdout and 'WATCHDOG' in p.stdout, p.stdout[-400:])
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
