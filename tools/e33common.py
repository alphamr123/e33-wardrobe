"""Shared by the E33 Wardrobe tools: version, "is the game running?", console set-up."""
import os
import re
import shutil
import subprocess
import sys
import time

VERSION = '1.3.0'
GAME_EXES = ('SandFall-Win64-Shipping.exe', 'SandFall-WinGDK-Shipping.exe')   # Steam, Game Pass

_RUNNING = {'t': 0.0, 'v': False}


def safe_console():
    """Never crash on a mod name the console code page can't show (redirected or piped output)."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError):
            pass


def game_running(fresh=False, probe=(), lp=lambda p: p):
    """True if E33 is running: process list (Steam/Game Pass exe) or, failing that, one of the
    `probe` files is locked (the engine opens paks without write sharing). Windows only."""
    if sys.platform != 'win32':
        return False
    now = time.time()
    if not fresh and not probe and now - _RUNNING['t'] < 2:
        return _RUNNING['v']
    running = False
    try:
        out = subprocess.run(['tasklist', '/NH', '/FO', 'CSV'], capture_output=True, timeout=10,
                             creationflags=0x08000000).stdout
        text = out.decode('ascii', errors='replace').lower()     # exe names are ASCII
        running = any(f'"{exe.lower()}"' in text for exe in GAME_EXES)
    except Exception:          # tasklist missing, timed out or odd output: fall back to the lock probe
        pass
    if not running:
        for f in probe:
            try:
                with open(lp(f), 'r+b'):
                    pass
            except PermissionError as e:
                if getattr(e, 'winerror', None) in (32, 33):   # sharing / lock violation only
                    running = True
                    break
            except OSError:
                pass
    _RUNNING.update(t=now, v=running)
    return running


def is_paks_dir(path):
    """The game's Content\\Paks folder (it holds global.utoc)."""
    return bool(path) and os.path.isfile(os.path.join(path, 'global.utoc'))


WORK_PREFIXES = ('_e33wardrobe_work_', '_e33mixer_swatch_')


def clean_stale_work(parent):
    """Work folders left by a run that was killed (console closed): they hold hard links to the
    game's containers, so they would keep old game data alive after an update. A folder whose
    run is still alive keeps its .lock open, which Windows won't let us delete."""
    try:
        names = os.listdir(parent)
    except OSError:
        return
    for n in names:
        p = os.path.join(parent, n)
        if not n.startswith(WORK_PREFIXES) or not os.path.isdir(p):
            continue
        try:
            if time.time() - os.path.getmtime(p) < 120:
                continue
            lock = os.path.join(p, '.lock')
            if os.path.exists(lock):
                os.remove(lock)
        except OSError:
            continue
        shutil.rmtree(p, ignore_errors=True)
        print(f'removed a work folder left by an interrupted run: {n}')


STEAM_APPID = '1903340'


def steam_libraries():
    roots = []
    if sys.platform == 'win32':
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                              (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for val in ('SteamPath', 'InstallPath'):
                            try:
                                roots.append(winreg.QueryValueEx(k, val)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    else:
        roots += [os.path.expanduser('~/.steam/steam'), os.path.expanduser('~/.local/share/Steam')]
    libs = []
    for r in roots:
        vdf = os.path.join(r, 'steamapps', 'libraryfolders.vdf')
        libs.append(r)
        if os.path.isfile(vdf):
            for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, encoding='utf-8', errors='replace').read()):
                libs.append(m.group(1).replace('\\\\', '\\'))
    seen, out = set(), []
    for lib in libs:
        k = os.path.normcase(os.path.normpath(lib))
        if k not in seen:
            seen.add(k)
            out.append(lib)
    return out


def detect_paks_dir():
    """The game's Sandfall\\Content\\Paks folder: Steam libraries, then the default Game Pass folder."""
    cands = []
    for lib in steam_libraries():
        acf = os.path.join(lib, 'steamapps', f'appmanifest_{STEAM_APPID}.acf')
        installdir = 'Expedition 33'
        if os.path.isfile(acf):
            m = re.search(r'"installdir"\s+"([^"]+)"', open(acf, encoding='utf-8', errors='replace').read())
            if m:
                installdir = m.group(1)
        cands.append(os.path.join(lib, 'steamapps', 'common', installdir, 'Sandfall', 'Content', 'Paks'))
    if sys.platform == 'win32':
        import string
        for drive in string.ascii_uppercase:
            cands.append(rf'{drive}:\XboxGames\Clair Obscur- Expedition 33\Content\Sandfall\Content\Paks')
    for c in cands:
        if os.path.isfile(os.path.join(c, 'global.utoc')):
            return c
    return None
