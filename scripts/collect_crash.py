"""Collect a game crash in one folder: the newest crash dump, the logs, and a first reading of it.

    python scripts/collect_crash.py [--win64 <game>\\Sandfall\\Binaries\\Win64] [--out <folder>] [--no-analyze]

The game folder: --win64, else the E33_WIN64 environment variable, else the install the relocator
finds (Steam, Game Pass).

Run it after a crash and BEFORE starting the game again (a new start replaces live_log.txt; the
old one becomes live_log_previous.txt, which is collected too). What it does:
  * the newest crash dump: UE4SS's ue4ss\\crash_*.dmp, or the engine's
    %LOCALAPPDATA%\\Sandfall\\Saved\\Crashes\\*\\UEMinidump.dmp; it is MOVED (full dumps are GBs);
  * copies UE4SS.log, the mod's live_log.txt / live_log_previous.txt / settings.txt /
    selection.txt / report.txt / dump.txt, and ReShade.log / ClairObscurFix.log from Win64;
  * runs scripts/analyze_dump.py on the dump (UE4SS frames named with UE4SS.pdb) into analysis.txt,
    and prints the exception and the mod's last steps before the watchdog line.
Default --out: handoff/reports in this repository (git-ignored, never pushed).
"""
import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_FILES = ('live_log.txt', 'live_log_previous.txt', 'settings.txt', 'selection.txt', 'report.txt', 'dump.txt')


def default_win64():
    """E33_WIN64, else the game the relocator finds (Steam, Game Pass), else None."""
    if os.environ.get('E33_WIN64'):
        return os.environ['E33_WIN64']
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    try:
        import e33common
        paks = e33common.detect_paks_dir()
    except Exception:
        paks = None
    return os.path.normpath(os.path.join(paks, '..', '..', 'Binaries', 'Win64')) if paks else None


def newest_dump(win64):
    cands = glob.glob(os.path.join(win64, 'ue4ss', 'crash_*.dmp'))
    local = os.environ.get('LOCALAPPDATA')
    if local:
        cands += glob.glob(os.path.join(local, 'Sandfall', 'Saved', 'Crashes', '*', '*.dmp'))
    return max(cands, key=os.path.getmtime) if cands else None


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)

    def opt(flag, default):
        if flag in args:
            i = args.index(flag)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    win64 = opt('--win64', None) or default_win64()
    out_root = opt('--out', os.path.join(ROOT, 'handoff', 'reports'))
    analyze = '--no-analyze' not in args
    if not win64 or not os.path.isdir(win64):
        print(f'no game folder at {win64} (use --win64 <game>\\Sandfall\\Binaries\\Win64, or set E33_WIN64)')
        return 2
    dmp = newest_dump(win64)
    stamp = time.strftime('%Y-%m-%d_%H%M', time.localtime(os.path.getmtime(dmp) if dmp else time.time()))
    out = os.path.join(out_root, stamp + '_crash')
    os.makedirs(out, exist_ok=True)
    got, locked = [], False
    if dmp:
        dst = os.path.join(out, os.path.basename(dmp))
        try:
            shutil.move(dmp, dst)
            got.append(os.path.basename(dmp) + ' (moved)')
            dmp = dst
        except OSError as e:
            # PC 17 Oct: UE4SS was still writing a 16 GB full dump; the game looked frozen meanwhile.
            # Across drives the move is a copy: a full disk fails too.
            locked = True
            if os.path.exists(dst):
                try:
                    os.remove(dst)                  # a partial copy
                except OSError:
                    pass
            if isinstance(e, PermissionError):
                print(f'the crash dump is still open by the game (UE4SS may still be writing it, a full dump '
                      f'takes minutes): {dmp}\n  collecting the logs now; run this again once the game has '
                      f'closed (end it in Task Manager if it stays frozen) to move and read the dump')
            else:
                print(f'could not move the crash dump {dmp}: {e}\n  it stays where it is; collecting the logs now')
    else:
        print('no crash dump found (ue4ss\\crash_*.dmp or Saved\\Crashes): collecting the logs only')
    mod = os.path.join(win64, 'ue4ss', 'Mods', 'E33Wardrobe')
    for src in ([os.path.join(win64, 'ue4ss', 'UE4SS.log')] + [os.path.join(mod, f) for f in MOD_FILES]
                + [os.path.join(win64, f) for f in ('ReShade.log', 'ClairObscurFix.log')]):
        if os.path.isfile(src):
            try:
                with open(src, 'rb') as f:              # shared read: the game may still hold it open
                    data = f.read()
                with open(os.path.join(out, os.path.basename(src)), 'wb') as f:
                    f.write(data)
                got.append(os.path.basename(src))
            except OSError as e:
                print(f'  could not copy {src}: {e}')
    print(f'collected into {out}:\n  ' + '\n  '.join(got))
    if dmp and analyze and not locked:
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'analyze_dump.py'), dmp,
                            '--ue4ss', os.path.join(win64, 'ue4ss')], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        with open(os.path.join(out, 'analysis.txt'), 'w', encoding='utf-8') as f:
            f.write(p.stdout + p.stderr)
        print('\n' + '\n'.join(x for x in p.stdout.splitlines() if 'ACCESS_VIOLATION' in x or 'exception' in x.lower()
                               or x.startswith('game thread'))[:2000])
    live = os.path.join(out, 'live_log.txt')
    if os.path.isfile(live):
        with open(live, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
        wd = [i for i, x in enumerate(lines) if 'WATCHDOG: the game thread has not run' in x]
        tail = lines[max(0, wd[-1] - 3):wd[-1] + 6] if wd else lines[-8:]
        print('\nthe mod\'s log at the end' + (' (watchdog)' if wd else '') + ':\n  ' + '\n  '.join(x[:200] for x in tail))
    return 3 if locked else 0


if __name__ == '__main__':
    sys.exit(main())
