"""Where things are: the app's own data, bundled resources, the game, UE4SS and the in-game menu.

Works from the repository and from the frozen app (PyInstaller: sys.frozen, sys._MEIPASS).
Environment overrides (tests, unusual setups): E33_APPDATA, E33_RETOC, E33_LUA_TEMPLATE.
"""
import json
import os
import re
import shutil
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
APP_DIR_NAME = 'E33Wardrobe'
IS_WINDOWS = sys.platform == 'win32'
TOO_OLD_TEXT = 'This UE4SS build is too old for E33Wardrobe'
UE4SS_TOO_OLD = "UE4SS is too old for the in-game menu. Get 'UE4SS - Experimental (Newer)'."
UE4SS_MISSING = "UE4SS is not installed. The in-game menu runs inside it: get 'UE4SS - Experimental (Newer)'."


# ------------------------------------------------------------------------------ app folders

def resource_dir():
    """Bundled files: sys._MEIPASS when frozen, else the repository root."""
    if FROZEN and getattr(sys, '_MEIPASS', None):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def tools_dir():
    return os.path.join(resource_dir(), 'tools')


def exe_dir():
    """The folder of E33 Wardrobe.exe (frozen) or the repository root."""
    return os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else resource_dir()


def app_data_dir(create=True):
    """%APPDATA%\\E33Wardrobe on Windows, ~/.config/e33wardrobe elsewhere (E33_APPDATA overrides)."""
    d = os.environ.get('E33_APPDATA')
    if not d:
        if IS_WINDOWS and os.environ.get('APPDATA'):
            d = os.path.join(os.environ['APPDATA'], APP_DIR_NAME)
        else:
            d = os.path.join(os.path.expanduser('~'), '.config', 'e33wardrobe')
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def settings_path():
    return os.path.join(app_data_dir(), 'app.json')


def relocator_config_path():
    return os.path.join(app_data_dir(), 'relocator.json')


def lua_template():
    """The Lua mod as shipped (lua/E33Wardrobe)."""
    return os.environ.get('E33_LUA_TEMPLATE') or os.path.join(resource_dir(), 'lua', 'E33Wardrobe')


# ------------------------------------------------------------------------------ the tools

_TOOLS = {}


def tools():
    """Import the command-line tools (e33common, e33rules, e33utoc, e33tex, e33_relocate) once.
    E33_CONFIG and E33_LUA_TEMPLATE are set first: e33_relocate reads them at import."""
    if _TOOLS:
        return _TOOLS
    td = tools_dir()
    if os.path.isdir(td) and td not in sys.path:
        sys.path.insert(0, td)
    os.environ.setdefault('E33_CONFIG', relocator_config_path())
    os.environ.setdefault('E33_LUA_TEMPLATE', lua_template())
    import e33common
    import e33rules
    import e33utoc
    import e33tex
    import e33_relocate
    # In case e33_relocate was imported before the environment was set.
    e33_relocate.CONFIG_PATH = os.environ['E33_CONFIG']
    e33_relocate.LUA_TEMPLATE = os.environ['E33_LUA_TEMPLATE']
    _TOOLS.update(common=e33common, rules=e33rules, utoc=e33utoc, tex=e33tex, relocate=e33_relocate)
    return _TOOLS


def app_version():
    return tools()['common'].VERSION


def _first_file(cands):
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def find_retoc():
    """retoc: E33_RETOC, bin/ of the app, next to the tools, then PATH. In the frozen app the
    bundled copy is copied to the app data folder once, so the Oodle DLL retoc downloads next to
    itself on first use is kept (the app's own folder may not be writable)."""
    names = ('retoc.exe', 'retoc') if IS_WINDOWS else ('retoc', 'retoc.exe')
    env = os.environ.get('E33_RETOC')
    if env and os.path.isfile(env):
        return env
    bundled = _first_file([os.path.join(d, n) for d in (os.path.join(resource_dir(), 'bin'),
                                                        os.path.join(exe_dir(), 'bin'), exe_dir(), tools_dir())
                           for n in names])
    if bundled and FROZEN and IS_WINDOWS:
        own = os.path.join(app_data_dir(), 'bin', os.path.basename(bundled))
        try:
            if not os.path.isfile(own) or os.path.getsize(own) != os.path.getsize(bundled):
                os.makedirs(os.path.dirname(own), exist_ok=True)
                shutil.copy2(bundled, own + '.tmp')
                os.replace(own + '.tmp', own)
            return own
        except OSError:
            return bundled
    if bundled:
        return bundled
    return _first_file([shutil.which(n) for n in names])


def find_7z():
    """7-Zip's command-line program (for .rar): bundled bin/7z.exe, PATH, or Program Files."""
    cands = [os.path.join(resource_dir(), 'bin', '7z.exe'), os.path.join(exe_dir(), 'bin', '7z.exe')]
    cands += [shutil.which(n) for n in ('7z', '7z.exe', '7za', '7zz')]
    for env in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)'):
        if os.environ.get(env):
            cands.append(os.path.join(os.environ[env], '7-Zip', '7z.exe'))
    cands += [r'C:\Program Files\7-Zip\7z.exe', r'C:\Program Files (x86)\7-Zip\7z.exe']
    return _first_file(cands)


def find_unrar():
    cands = [shutil.which(n) for n in ('unrar', 'UnRAR.exe')]
    cands += [r'C:\Program Files\WinRAR\UnRAR.exe', r'C:\Program Files (x86)\WinRAR\UnRAR.exe']
    return _first_file(cands)


def has_py7zr():
    try:
        import py7zr  # noqa: F401
        return True
    except ImportError:
        return False


# ------------------------------------------------------------------------------ the game

def paks_of(root):
    return os.path.join(root, 'Sandfall', 'Content', 'Paks')


def is_game_root(root):
    return bool(root) and os.path.isfile(os.path.join(paks_of(root), 'global.utoc'))


def normalize_game_folder(path):
    """(root, paks) for the game folder or anything inside it (Sandfall, Content, Paks,
    Binaries\\Win64, the .exe), else None. Game Pass's outer folder (with Content\\Sandfall) works too."""
    if not path or not isinstance(path, str):
        return None
    p = path.strip().strip('"').strip()
    if not p:
        return None
    p = os.path.abspath(os.path.expanduser(p))
    if os.path.isfile(p):
        p = os.path.dirname(p)
    if not os.path.isdir(p):
        return None
    for c in (p, os.path.join(p, 'Content')):           # Game Pass: <XboxGames\Game>\Content\Sandfall
        if is_game_root(c):
            return os.path.normpath(c), os.path.normpath(paks_of(c))
    cur = p
    while True:
        if is_game_root(cur):
            return os.path.normpath(cur), os.path.normpath(paks_of(cur))
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def store_of(root):
    low = (root or '').replace('\\', '/').lower()
    if 'steamapps' in low:
        return 'Steam'
    binaries = os.path.join(root or '', 'Sandfall', 'Binaries')
    gdk_only = os.path.isdir(os.path.join(binaries, 'WinGDK')) and not os.path.isdir(os.path.join(binaries, 'Win64'))
    if 'xboxgames' in low or 'wingdk' in low or gdk_only:
        return 'Game Pass'
    return None


def detect_game():
    """(root, paks) found automatically (Steam libraries, default Game Pass folder), else None."""
    paks = tools()['common'].detect_paks_dir()
    return normalize_game_folder(paks) if paks else None


# ------------------------------------------------------------------------------ UE4SS and the menu

_UE4SS_VERSION = re.compile(r'UE4SS - v(\S+)((?: [A-Za-z]+)?)(?: #\d+)?(?: - Git SHA #([0-9a-fA-F]+))?')


def ue4ss_version_from_log(text):
    """'3.0.1 Beta (527a483b)' from 'UE4SS - v3.0.1 Beta #0 - Git SHA #527a483b'; a version that
    already carries its build ('3.0.1-1125-g527a483b') is returned as it is."""
    m = _UE4SS_VERSION.search(text or '')
    if not m:
        return None
    ver, tag, sha = m.group(1), m.group(2).strip(), m.group(3)
    out = ver + (' ' + tag if tag else '')
    if sha and sha.lower() not in ver.lower():
        out += f' ({sha})'
    return out


def _read_log(path, limit=8 * 1024 * 1024):
    """A UE4SS.log as text (head and tail of a very large one)."""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            if size <= limit:
                data = f.read()
            else:
                data = f.read(limit // 2)
                f.seek(size - limit // 2)
                data += b'\n' + f.read()
        return data.decode('utf-8', errors='replace')
    except OSError:
        return None


def ue4ss_dir(root):
    """The ue4ss folder in Binaries\\Win64 or Binaries\\WinGDK (with UE4SS.dll, or dwmapi.dll
    next to it), else None. No file is read."""
    if not root:
        return None
    plats = ['Win64', 'WinGDK']
    if store_of(root) == 'Game Pass':
        plats.reverse()
    for plat in plats:
        b = os.path.join(root, 'Sandfall', 'Binaries', plat)
        u = os.path.join(b, 'ue4ss')
        if os.path.isdir(u) and (os.path.isfile(os.path.join(u, 'UE4SS.dll'))
                                 or os.path.isfile(os.path.join(b, 'dwmapi.dll'))):
            return os.path.normpath(u)
    return None


_LOG_FACTS = {}


def _log_facts(path):
    """(version, too old) from a UE4SS.log, cached by size and time."""
    try:
        st = os.stat(path)
    except OSError:
        return None, False
    key = (path, st.st_size, int(st.st_mtime))
    if key not in _LOG_FACTS:
        text = _read_log(path) or ''
        _LOG_FACTS.clear()
        _LOG_FACTS[key] = (ue4ss_version_from_log(text), TOO_OLD_TEXT in text)
    return _LOG_FACTS[key]


def ue4ss_info(root):
    """UE4SS in Binaries\\Win64 or Binaries\\WinGDK: dict(installed, dir, version, ok, problem)."""
    out = {'installed': False, 'dir': None, 'version': None, 'ok': False, 'problem': None}
    if not root:
        return out
    u = ue4ss_dir(root)
    if not u:
        out['problem'] = UE4SS_MISSING
        return out
    version, too_old = _log_facts(os.path.join(u, 'UE4SS.log'))
    out.update(installed=True, dir=u, ok=not too_old, version=version, problem=UE4SS_TOO_OLD if too_old else None)
    return out


def menu_dir(root, paks=None):
    """<ue4ss>\\Mods\\E33Wardrobe: where UE4SS is, else where the relocator would put it."""
    u = ue4ss_dir(root)
    if u:
        return os.path.join(u, 'Mods', 'E33Wardrobe')
    paks = paks or paks_of(root)
    return tools()['relocate'].default_lua_dir(paks)


_LUA_VERSION = re.compile(r'^\s*local\s+VERSION\s*=\s*"([^"]+)"', re.M)


def lua_version(main_lua):
    try:
        with open(main_lua, encoding='utf-8', errors='replace') as f:
            m = _LUA_VERSION.search(f.read(20000))
        return m.group(1) if m else None
    except OSError:
        return None


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or ''))


def menu_info(lua_dir):
    """dict(installed, version, bundled, update) for the in-game menu (the UE4SS Lua mod)."""
    main = os.path.join(lua_dir, 'Scripts', 'main.lua') if lua_dir else ''
    installed = bool(main) and os.path.isfile(main)
    version = lua_version(main) if installed else None
    bundled = lua_version(os.path.join(lua_template(), 'Scripts', 'main.lua'))
    update = bool(installed and bundled and (version is None or version_tuple(bundled) > version_tuple(version)))
    return {'installed': installed, 'version': version, 'bundled': bundled, 'update': update}


# ------------------------------------------------------------------------------ small helpers

def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def lp(path):
    """Windows long-path form for deep library folders (no-op elsewhere)."""
    if IS_WINDOWS:
        a = os.path.abspath(path)
        if not a.startswith('\\\\?\\') and len(a) > 240:
            return '\\\\?\\' + a
        return a
    return path


def is_inside(path, parent):
    try:
        a = os.path.normcase(os.path.abspath(path))
        b = os.path.normcase(os.path.abspath(parent))
        return a == b or a.startswith(b.rstrip('\\/') + os.sep)
    except (TypeError, ValueError):
        return False
