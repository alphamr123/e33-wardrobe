"""Live game-log watcher: the `Monitor` of app/API.md (monitor(), problems_text()).

While the game runs, the in-game menu writes ue4ss\\Mods\\E33Wardrobe\\live_log.txt (one line per
event, "HH:MM:SS #N message", flushed per line; renamed to live_log_previous.txt at the next game
start) and UE4SS writes ue4ss\\UE4SS.log (rewritten at every game start). This module only reads
them. Each poll stats both files and, when one changed, opens it, reads the bytes added since the
last poll and closes it again, so nothing stays open between polls. New lines go through RULES
(below) and become problems, deduplicated by key with a count and first/last times. The lines are
explained in docs/TROUBLESHOOTING.md.

    m = Monitor(paths_provider)   # paths_provider() -> {"game_root", "paks", "ue4ss_dir", "menu_dir"}
    m.start(); m.stop()           # background thread, one poll per second; start() is idempotent
    m.snapshot()                  # the Monitor shape of API.md (a copy)
    m.problems_text()             # plain text for a bug report
    m.poll_once()                 # one step without the thread (tests)
    analyse(live=path, ue=path)   # one read of finished logs (the Game log tab when the game is closed)

Each problem keeps the log lines that raised it (`lines`, the newest MAX_PROBLEM_LINES), so the
Game log tab can show them on their own.
"""
import collections
import datetime as _dt
import os
import re
import string
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, 'tools')
if os.path.isdir(_TOOLS) and _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
try:
    import e33common
except ImportError:             # then "running" only comes from the session log growing
    e33common = None

POLL_S = 1.0                    # one poll per second
INITIAL_TAIL = 256 * 1024       # a rewritten file larger than MAX_READ is read from its last 256 KB
FIRST_LOOK = 4 * 1024 * 1024    # the first look at a file (the app starting) reads its last 4 MB:
                                # the whole of a normal session, so its problems show after the game closed
MAX_READ = 8 * 1024 * 1024
TAIL_LINES = 500
FILE_TAIL_LINES = 5000          # analyse(): lines kept of a finished log
MAX_PROBLEMS = 150
MAX_PROBLEM_LINES = 25          # log lines kept per problem (they go to the page with every poll)
GROWTH_RUNNING_S = 5.0          # live_log.txt grew this recently: the game runs
LIVE_LOG, UE4SS_LOG = 'live_log.txt', 'UE4SS.log'
LEVEL_ORDER = {'error': 0, 'warn': 1, 'info': 2}
PUBLIC = ('key', 'level', 'title', 'detail', 'hint', 'first', 'last', 'count')   # plus 'lines'
_DEFAULT = object()

SEND_REPORT = 'Send report.txt (Ctrl+F9 in game writes it) and say what you did just before.'
WEAR_HINT = ('Press Wear on that row in the menu to put it on over the current outfit, '
             'or switch on Auto Wear in Settings.')


def default_crash_dir():
    """Where the game's crash reporter writes on Windows: %LOCALAPPDATA%\\Sandfall\\Saved\\Crashes."""
    base = os.environ.get('LOCALAPPDATA')
    if sys.platform != 'win32' or not base:
        return None
    return os.path.join(base, 'Sandfall', 'Saved', 'Crashes')


# --------------------------------------------------------------------------- reading without locking

def _open_plain(path):
    return open(path, 'rb')


_open_shared = _open_plain
if sys.platform == 'win32':
    # Python's open() doesn't pass FILE_SHARE_DELETE, so while it has live_log.txt open for a
    # moment, the menu's rename to live_log_previous.txt at game start would fail. CreateFileW
    # with every share flag never gets in the writer's way.
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes
        _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _CreateFileW = _k32.CreateFileW
        _CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        _CreateFileW.restype = wintypes.HANDLE
        _INVALID = (None, 0, ctypes.c_void_p(-1).value)

        def _open_shared(path):     # noqa: F811
            try:
                h = _CreateFileW(path, 0x80000000, 0x7, None, 3, 0x80, None)  # GENERIC_READ, share all, OPEN_EXISTING
            except Exception:
                return _open_plain(path)
            if h in _INVALID:
                raise OSError(ctypes.get_last_error(), 'cannot open', path)
            try:
                fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
            except Exception:
                _k32.CloseHandle(h)
                raise
            return os.fdopen(fd, 'rb')
    except Exception:
        _open_shared = _open_plain


class _Tail:
    """Follows one growing text file: only the new complete lines on each read."""
    HEAD = 64

    def __init__(self, path, first_look=FIRST_LOOK):
        self.path = path
        self.first_look = first_look
        self.seen = False           # opened at least once
        self.looked = False         # stat-ed at least once (a file that appears later is growth)
        self.offset = 0
        self.size = -1              # -1: missing (or not looked at yet)
        self.mtime = -1
        self.head = b''             # the first bytes: a rewritten file starts differently
        self.buf = b''              # an unfinished last line
        self.grew = None            # time.monotonic() of the last growth after the first look
        self.history = False        # the last read was the first look at an existing file

    def read(self):
        """-> (lines, event, mid). event: None, 'new' (first look: from the last `first_look` bytes) or
        'rotated' (rewritten or replaced: from the start). mid: reading began inside the file."""
        first_look, self.looked = not self.looked, True
        try:
            st = os.stat(self.path)
        except OSError:
            if self.size >= 0:      # gone (renamed / deleted): the next one is a new file
                self.size, self.mtime, self.offset, self.buf, self.head = -1, -1, 0, b'', b''
            return [], None, False
        if st.st_size == self.size and st.st_mtime_ns == self.mtime:
            return [], None, False
        event, mid = None, False
        try:
            with _open_shared(self.path) as f:
                head = f.read(self.HEAD)
                if not self.seen:
                    self.seen, event = True, 'new'
                    self.offset, self.buf = max(0, st.st_size - self.first_look), b''
                elif self.size < 0 or st.st_size < self.offset or not _same_start(head, self.head):
                    event, self.offset, self.buf = 'rotated', 0, b''
                if event == 'rotated' and st.st_size > MAX_READ:
                    self.offset = st.st_size - INITIAL_TAIL
                mid = event is not None and self.offset > 0
                f.seek(self.offset)
                data = f.read(MAX_READ)
        except OSError:
            return [], None, False
        self.head = head
        self.size, self.mtime = st.st_size, st.st_mtime_ns
        self.offset += len(data)
        self.history = event == 'new' and first_look
        if data and not self.history:
            self.grew = time.monotonic()
        data = self.buf + data
        if mid:                     # began inside a line: drop that piece
            cut = data.find(b'\n')
            data = data[cut + 1:] if cut >= 0 else b''
        end = data.rfind(b'\n')
        if end < 0:
            self.buf = data if len(data) < (1 << 20) else b''
            return [], event, mid
        self.buf = data[end + 1:]
        text = data[:end].decode('utf-8', errors='replace')
        return [ln.rstrip('\r') for ln in text.split('\n')], event, mid


def _same_start(a, b):
    n = min(len(a), len(b))
    return a[:n] == b[:n]


# --------------------------------------------------------------------------- text helpers

class _Vars(dict):
    def __missing__(self, key):
        return ''


_FMT = string.Formatter()
_USER_RX = re.compile(r'([\\/][Uu]sers[\\/]+)[^\\/\r\n"\']+')


def _fill(tpl, v):
    return _FMT.vformat(tpl, (), v) if tpl else ''


def _redact(s):
    """C:\\Users\\<name>\\... -> C:\\Users\\<user>\\..., as report.txt does."""
    return _USER_RX.sub(lambda m: m.group(1) + '<user>', s)


def _short(s, n):
    s = (s or '').strip()
    return s if len(s) <= n else s[:n - 3].rstrip() + '...'


def _cap(s, n=1000):
    """A log line for the page, at most n characters (keeps the indentation)."""
    return s if len(s) <= n else s[:n - 3] + '...'


def _norm(s):
    """For keys: numbers and addresses don't make an error a different one."""
    return re.sub(r'0x[0-9A-Fa-f]+|\d+', '#', s or '').strip()[:120]


def _leaf(path):
    seg = re.split(r'[\\/]', (path or '').rstrip('\\/'))[-1]
    return seg.split('.')[0] or seg


def _hms(dt):
    return dt.strftime('%H:%M:%S') if dt else None


def _sentence(s):
    return s[:1].upper() + s[1:]


# --------------------------------------------------------------------------- rules

class Rule:
    """One line pattern -> one problem. `on`: 'mod' (the menu's own messages: "[E33Wardrobe] ..."
    in UE4SS.log, "log: ..." in live_log.txt), 'live', 'ue4ss' or 'any'. `need` is a plain
    substring checked before the regex (most lines are skipped by it). Templates use the regex's
    named groups plus: line, linekey, errkey (from err), leaf / name (from path), texleaf / srcnote
    (from tex / src), whonote (the pick seen after an empty-texture fill). `special` names a
    method that handles the match itself."""

    def __init__(self, on, need, pattern, level=None, title='', detail='', hint='', key='',
                 special=None, explains=False, attrib=False, exclude=None):
        self.on, self.need, self.rx = on, need, re.compile(pattern)
        self.level, self.title, self.detail, self.hint, self.key = level, title, detail, hint, key
        self.special, self.explains, self.attrib = special, explains, attrib
        self.exclude = re.compile(exclude) if exclude else None


# Lines of the menu that are not about problems even when a label happens to say "failed".
_NOT_PROBLEMS = r'^(slot \d+/\d+ |\s+matched: |\s+\d+: |setting |favorites\.txt|applied to )'

RULES = [
    # The menu's own messages (log() in main.lua / menu.lua), from either log.
    Rule('mod', 'too old for E33Wardrobe', r'This UE4SS build is too old for E33Wardrobe', 'error',
         'UE4SS is too old for the in-game menu',
         'This UE4SS build has no safe way to run the menu on the game thread, so the menu stays off.',
         "Install 'UE4SS - Experimental (Newer)' from Nexus Mods (December 2025 or later), "
         'then start the game again.', 'ue4ss-too-old', explains=True),
    Rule('mod', 'LoopInGameThreadWithDelay failed', r'^LoopInGameThreadWithDelay failed \((?P<err>.*)\)', 'error',
         "The in-game menu couldn't start", "UE4SS refused the menu's game-thread loop ({err}), so the menu stays off.",
         'Update UE4SS to the newest experimental build. If it still fails, send report.txt.',
         'menu-loop', explains=True),
    Rule('mod', 'could not reach the game thread', r'^could not reach the game thread \((?P<err>.*)\)', 'error',
         "The in-game menu couldn't start", "UE4SS couldn't run the menu on the game thread ({err}), so the menu stays off.",
         'Update UE4SS to the newest experimental build. If it still fails, send report.txt.',
         'menu-thread', explains=True),
    Rule('mod', 'menu not available', r'^menu not available: (?P<err>.*)', 'error',
         'The in-game menu failed to load', '{err}',
         'Install the menu again from the app (Install menu). If it still fails, send report.txt.', 'menu-load'),
    Rule('mod', 'menu could not be built', r'^menu could not be built: (?P<err>.*)', 'error',
         "The in-game menu couldn't open", '{err}', SEND_REPORT, 'menu-build'),
    Rule('mod', 'error while drawing', r'^menu closed after an error while drawing it: (?P<err>.*)', 'error',
         'The in-game menu closed after an error', '{err}', SEND_REPORT, 'menu-draw:{errkey}'),
    Rule('mod', 'no player controller', r'^menu: no player controller yet', 'info',
         'The menu needs a loaded save', 'The menu key was pressed before a save was loaded, so the menu stayed closed.',
         'Load a save, then press the menu key (Delete).', 'menu-no-player'),
    Rule('mod', 'variants.lua missing', r'^variants\.lua missing or invalid \((?P<err>.*)\)', 'warn',
         "The menu couldn't read its outfit list", 'variants.lua is missing or damaged ({err}), so the menu has no outfits.',
         'Reinstall a mod in the app, then press Reload files in the menu.', 'variants'),
    Rule('mod', 'config.lua has an error', r'^config\.lua has an error, so the default keys are used: (?P<err>.*)',
         'warn', 'config.lua has an error', 'The menu uses the default keys. {err}',
         'Fix Scripts\\config.lua in the menu folder, or delete it.', 'config'),
    Rule('mod', 'config.lua: ', r'^config\.lua: (?P<what>.*)', 'warn', 'A key in config.lua was not bound', '{what}',
         'Use the key names listed at the top of config.example.lua.', 'config-key:{what}'),
    Rule('mod', 'could not bind', r'^could not bind (?P<k>\S+): (?P<err>.*)', 'warn',
         "Couldn't bind the {k} key", '{err}', 'Pick another key in config.lua.', 'bind:{k}'),
    Rule('mod', "' failed", r"^menu action '(?P<action>[^']*)' failed: (?P<err>.*)", 'error',
         "The menu button '{action}' failed", '{err}', SEND_REPORT, 'action:{action}:{errkey}'),
    Rule('mod', 'apply failed', r'^apply failed(?: on (?P<actor>\S+))?: (?P<err>.*)', 'error',
         'Applying the picks failed', '{err}', SEND_REPORT, 'apply:{errkey}'),
    Rule('mod', 'error: ', r'^error: (?P<err>.*)', 'error', 'The menu hit a Lua error', '{err}', SEND_REPORT,
         'lua:{errkey}'),
    Rule('mod', '[', r'^\[(?:Error|Fatal)\]\s*(?P<err>.*)', 'error', 'The menu hit a Lua error', '{err}',
         SEND_REPORT, 'lua:{errkey}'),
    Rule('mod', 'could not load', r'^could not load (?P<path>\S+)', 'warn', "Couldn't load {leaf}",
         "{path} didn't load, so that piece stays the game's own.",
         'Reinstall the mod it belongs to in the app. If it keeps failing, send report.txt.', 'load:{leaf}'),
    Rule('mod', 'stopped early', r'^(?P<file>dump\.txt|report\.txt) stopped early: (?P<err>.*)', 'warn',
         '{file} is incomplete', 'Writing it stopped early: {err}',
         'Write it again with Ctrl+F9. If it stops again, send what it has.', 'early:{file}'),
    Rule('mod', 'cannot write', r'^cannot write (?P<path>.+)', 'warn', "Couldn't write {name}",
         'The menu could not write {path}.',
         'Make sure the game folder is not read-only and no other program has the file open.', 'write:{name}'),
    Rule('mod', 'dropped ', r'^dropped (?P<n>\d+) pick\(s\) of mods no longer in the wardrobe', 'info',
         'Cleared {n} pick(s) of removed mods', 'Those mods are no longer in the wardrobe, so their picks were dropped.',
         '', 'dropped-picks'),
    Rule('mod', 'dropped Wear', r'^dropped Wear from slots that have no mesh to wear', 'info',
         'Wear was switched off on some rows', 'Those rows have no outfit mesh, so Wear had nothing to put on.',
         '', 'dropped-wear'),
    Rule('mod', 'RegisterBeginPlayPostHook', r'^RegisterBeginPlayPostHook unavailable', 'info',
         'New characters are dressed a little later',
         'This UE4SS build has no RegisterBeginPlayPostHook, so characters that appear later are only dressed by full passes.',
         'Update UE4SS to the newest experimental build.', 'no-begin-play'),
    Rule('mod', '', r'\.lua:\d+: |stack traceback|attempt to (?:index|call|compare|perform|concatenate)', 'error',
         'The menu hit a Lua error', '{line}', SEND_REPORT, 'lua:{linekey}', exclude=_NOT_PROBLEMS),
    Rule('mod', 'failed', r'\bfailed\b', 'error', 'Something in the menu failed', '{line}', SEND_REPORT,
         'failed:{linekey}', exclude=_NOT_PROBLEMS),
    Rule('mod', 'could not', r'\bcould not\b', 'warn', 'The menu could not finish something', '{line}', SEND_REPORT,
         'could-not:{linekey}', exclude=_NOT_PROBLEMS),

    # live_log.txt (the session recorder's own lines)
    Rule('live', 'WATCHDOG', r'^WATCHDOG: the game thread has not run for (?P<s>\d+) s; mod state: (?P<state>.+?)'
         r'(?: \(since (?P<since>[\d:]+)\))?$', special='_watchdog'),
    Rule('live', 'Auto Wear: ', r"^Auto Wear: (?P<slot>.+) doesn't fit what (?P<char>.+?) wears; worn in place of it",
         special='_autowear'),
    Rule('live', 'empty (the mod', r'^change \S+ \[(?P<char>[^\]]*)\]\.\S+: mat\d+ texture (?P<param>.+?): empty '
         r"\(the mod's material points at a texture it doesn't have\) -> (?P<tex>\S+)(?: \((?P<src>[^)]*)\))?",
         'info', 'Filled in a missing texture for {char}',
         "The outfit mod's material points at a {param} texture the mod doesn't include. "
         'It was filled in automatically with {texleaf}{srcnote}.{whonote}',
         '', 'empty-texture:{char}:{param}:{texleaf}', attrib=True),
    # A worn mod mesh with empty material slots (the game's skin Blueprint would fill them; Wear
    # cleared that): the menu fills the slot with the body's material, or can't.
    Rule('live', "mesh has no material for slot", r"^change \S+ \[(?P<char>[^\]]*)\]\.\S+: mat(?P<idx>\d+) empty "
         r"\(the mod's mesh has no material for slot (?P<slot>[^)]*)\) and nothing to fill it with",
         'warn', "An outfit part shows grey: the mod's mesh has no material for slot {slot}",
         "{char}'s outfit: material {idx} (slot {slot}) is empty in the mod's mesh, and the body has no material "
         'to fill it with, so that part shows grey.{whonote}', SEND_REPORT, 'grey-slot:{char}:{slot}', attrib=True),
    Rule('live', "mesh has no material for slot", r"^change \S+ \[(?P<char>[^\]]*)\]\.\S+: mat(?P<idx>\d+) empty "
         r"\(the mod's mesh has no material for slot (?P<slot>[^)]*)\) -> (?P<mat>\S+)(?: \((?P<src>[^)]*)\))?",
         'info', "Filled an empty material slot on {char}'s outfit",
         "The mod's mesh has no material for slot {slot} (material {idx}), so the menu used {matleaf}{srcnote}."
         '{whonote}',
         "The mod's mesh leaves this slot to the game; the menu uses the body's own material so it isn't grey. "
         'If it looks wrong, send report.txt.', 'empty-material:{char}:{slot}:{matleaf}', attrib=True),
    Rule('live', 'ApplyCurrentCharacterSkin failed', r'^Fix look: ApplyCurrentCharacterSkin failed on (?P<who>\S+): (?P<err>.*)',
         'warn', "Fix look didn't work on some characters", '{err}', "Re-equip the outfit in the game's own menu instead.",
         'fix-look'),
    Rule('live', 'clean: could not', r'^clean: could not make the all-zero texture: (?P<err>.*)', 'warn',
         "Clean couldn't make its blank texture", 'Blood and dirt stay as the game draws them. {err}', SEND_REPORT,
         'clean-texture'),
    Rule('live', 'live log reached 20 MB', r'live log reached 20 MB', 'info', 'The session log is full (20 MB)',
         'Later events only go to UE4SS.log, so this window shows less until the next game start.', '', 'live-full'),

    # Any line (menu status texts)
    Rule('any', 'nothing on screen changed', r'nothing on screen changed: made for (?P<made>[^;]+); '
         r'(?P<char>\S+) wears (?P<worn>[^.;]+)', 'info', 'The picked outfit is made for {made}',
         '{char} wears {worn}, so nothing on screen changed.', WEAR_HINT, 'made-for:{char}:{made}'),
    Rule('any', 'nothing on screen changed', r'nothing on screen changed: (?P<why>.+)', 'info',
         'Nothing on screen changed', '{why}', WEAR_HINT, 'unseen-why:{why}'),

    # UE4SS.log lines that are not the menu's own messages
    Rule('ue4ss', 'Ref was not function', r'Ref was not function', 'error', "UE4SS reported 'Ref was not function'",
         'A UE4SS threading problem: a Lua callback ran while the game thread used the same Lua state. '
         'It can freeze or crash the game. Another UE4SS mod can cause it too.',
         'Update UE4SS to the newest experimental build. If it happens again, send report.txt and UE4SS.log.',
         'ref-not-function'),
    Rule('ue4ss', 'E33Wardrobe', r'E33Wardrobe[\\/\'"\]]', special='_ue_lua'),
]
RULE_UE_LUA = Rule('ue4ss', '', r'', 'error', 'Lua error in the in-game menu', '{line}',
                   'Send report.txt and a copy of UE4SS.log (the next game start overwrites it).', 'ue4ss-lua:{linekey}')
_BY_SOURCE = {on: [r for r in RULES if r.on == on] for on in ('mod', 'live', 'ue4ss', 'any')}
_CONT_RULES = [r for r in RULES if r.key == 'live-full']

_LIVE_TS = re.compile(r'^(\d\d):(\d\d):(\d\d) #\d+ ?(.*)$')
_UE_TS = re.compile(r'^\[(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)(?:\.(\d+))?\] ?(.*)$')
_SESSION = re.compile(r'^session start (\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)')
_READY = re.compile(r'^(\S+) ready \(')
_PASS = re.compile(r'^pass \((?P<reasons>.*)\): (?P<n>\d+) change\(s\)')
_RECHECK = re.compile(r'^re-check after spawn: (?P<n>\d+) change\(s\)')
_ON_SCREEN = re.compile(r'^on screen: (?P<slot>.+?) = (?P<variant>.+): (?P<shown>\d+)/(?P<total>\d+) asset\(s\)(?P<rest>.*)$')
_SLOT_LINE = re.compile(r'^slot \d+ (?P<label>.+) \[(?P<chars>[^\]]*)\] \d+ variant\(s\), selected: ')
_WEAR_REASON = re.compile(r'^(?:Auto )?Wear (on|off): (.+)$')
_PICK_REASON = re.compile(r'^(.+?) = (.+)$')
_UE_VERSION = re.compile(r'UE4SS - (v\S+.*?Git SHA #\w+)')
_LUA_ERR = re.compile(r'(?i)lua_pcall|LUA_ERR|luaL_|stack traceback|attempt to |\.lua:\d+:|\berror\b|exception')
_LUA_GENERIC = re.compile(r'lua_pcall returned|LUA_ERR|luaL_loadfile|\[Lua::|stack traceback')
_NOT_FRAMES = ('has enabled.txt', 'Starting Lua mod', 'disabled in mods.txt')


# --------------------------------------------------------------------------- the monitor

class Monitor:
    def __init__(self, paths_provider, process_check=_DEFAULT, crash_dir=_DEFAULT, process_interval=3.0,
                 tail_lines=TAIL_LINES, first_look=FIRST_LOOK):
        """process_check() -> bool (default: e33common.game_running on Windows); crash_dir: folder
        whose new subfolders are crashes (default: default_crash_dir(); None: off).
        paths_provider() may also give 'live_file' / 'ue_file' (a path, or None for none) to read
        other files than live_log.txt and UE4SS.log (analyse())."""
        self._paths_provider = paths_provider
        self._tail_lines, self._first_look = tail_lines, first_look
        if process_check is _DEFAULT:
            process_check = e33common.game_running if (e33common and sys.platform == 'win32') else None
        self._proc_check = process_check
        self._proc_interval = process_interval
        self._crash_dir = default_crash_dir() if crash_dir is _DEFAULT else crash_dir
        self._lock = threading.RLock()
        self._thread = self._proc_thread = None
        self._stop_ev = None
        self._paths_key, self._paths_t, self._menu_dir = None, None, None
        self._live = self._uel = None
        self._proc_v, self._proc_t, self._proc_prev = False, None, False
        self._crash_known, self._crash_m, self._crash_t, self._crash_mono = None, _DEFAULT, 0.0, None
        self.last_error = None
        self._reset()

    def _reset(self):
        self.problems = {}
        self._n = 0
        self.since = self.last_activity = None
        self.menu_active = False
        self.game_running = False
        self.on_screen = []
        self.tail = collections.deque(maxlen=self._tail_lines)
        self._screen_new = None         # on-screen rows of the pass being read
        self._picks, self._pick_texts, self._slot_char = set(), [], {}
        self._session_dt = self._session_origin = None
        self._xsrc = collections.deque(maxlen=400)   # recent menu messages, to count each once
        self._pass_keys = []
        self._last_step, self._work_mono, self._work_desc, self._quiet = '', None, '', False
        self._last_map = ''
        self._menu_version = self._ue4ss_version = None
        self._ue = self._new_ue(None)
        self._pending_lua = None
        self._lp_date = self._lp_tod = self._lp_dt = None
        self._up_dt = None
        self._history = False
        self._cur_line = None           # the line being read: problems keep it (see _add_lines)
        self.ue_tail = collections.deque(maxlen=self._tail_lines)    # UE4SS.log lines, "HH:MM:SS text"
        self._newest = None             # time of the newest line read from either log
        self._n_lines = 0               # lines read (both logs)

    @staticmethod
    def _new_ue(start):
        return {'start': start, 'last': start, 'starting_mods': 0, 'loading_at': None, 'started_at': None, 'ready': False,
                'disabled': False, 'explained': False, 'warned': False}

    # ------------------------------------------------------------------ public

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            stop = self._stop_ev = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(stop,), name='e33-monitor', daemon=True)
            self._thread.start()
            if self._proc_check:
                self._proc_thread = threading.Thread(target=self._proc_loop, args=(stop,), name='e33-monitor-proc',
                                                     daemon=True)
                self._proc_thread.start()

    def stop(self):
        with self._lock:
            stop, threads = self._stop_ev, (self._thread, self._proc_thread)
            if stop:
                stop.set()
        for t in threads:
            if t and t is not threading.current_thread():
                t.join(timeout=3)

    def snapshot(self):
        with self._lock:
            probs = sorted(self.problems.values(),
                           key=lambda p: (3 if p['key'] == 'previous-session' else LEVEL_ORDER.get(p['level'], 3), p['_n']))
            return {
                'watching': bool(self._thread and self._thread.is_alive()),
                'game_running': bool(self.game_running),
                'since': self.since,
                'menu_active': bool(self.menu_active),
                'last_activity': self.last_activity,
                'ended': _hms(self._newest),
                'date': self._newest.strftime('%Y-%m-%d') if self._newest else None,
                'problems': [dict({k: p[k] for k in PUBLIC}, lines=list(p.get('_lines') or [])) for p in probs],
                'on_screen': [dict(r) for r in self.on_screen],
                'tail': list(self.tail),
            }

    def problems_text(self):
        with self._lock:
            s = self.snapshot()
            menu_v, ue_v = self._menu_version, self._ue4ss_version
        head = [f"Game running: {'yes' if s['game_running'] else 'no'}"]
        if s['since']:
            head.append(f"session since {s['since']}")
        head.append('in-game menu: ' + (f"started{f' ({menu_v})' if menu_v else ''}" if s['menu_active'] else 'not started'))
        if ue_v:
            head.append(f'UE4SS {ue_v}')
        out = [f"E33 Wardrobe: game log problems ({_dt.datetime.now():%H:%M:%S})", ', '.join(head), '']
        if not s['problems']:
            out += ['No problems seen this session.', '']
        for p in s['problems']:
            span = p['first'] if p['first'] == p['last'] else f"{p['first']} to {p['last']}"
            when = span if p['count'] == 1 else f"{span}, {p['count']} times"
            out.append(f"[{p['level'].upper()}] {when}: {p['title']}")
            if p['detail']:
                out.append('  ' + p['detail'])
            if p['hint']:
                out.append('  What to do: ' + p['hint'])
            for ln in p['lines'][-3:]:
                out.append('  Log: ' + ln)
            out.append('')
        if s['on_screen']:
            out.append('On screen after the last pass:')
            for r in s['on_screen']:
                out.append(f"  {r['slot']} = {r['variant']}: {r['shown']}/{r['total']} piece(s)"
                           + (', worn (Wear)' if r['worn'] else ''))
        else:
            out.append('On screen: nothing reported yet.')
        return '\n'.join(out) + '\n'

    def poll_once(self):
        with self._lock:
            now = time.monotonic()
            self._refresh_paths(now)
            events = []
            if self._uel:
                events += self._read_ue()
            if self._live:
                events += self._read_live()
            if events:
                events.sort(key=lambda e: e[0])        # stable: each file keeps its order
                try:
                    self._read_events(events, now)
                finally:
                    self._history = False
                    self._cur_line = None
            proc = self._proc_running(now)
            if self._proc_prev and not proc:
                self._on_exit(now)
            self._proc_prev = proc
            grew = self._live is not None and self._live.grew is not None and now - self._live.grew <= GROWTH_RUNNING_S
            self.game_running = bool(proc or grew)
            self._check_crashes(now)
            self._check_menu_start()

    def _read_events(self, events, now):
        for dt, src, text, cont, hist in events:
            self._history = hist            # old lines: no "the menu is working right now"
            if dt is not None and (self._newest is None or dt > self._newest):
                self._newest = dt
            self._n_lines += src != 'ue-start'
            if src == 'ue-start':
                self._cur_line = None
                self._ue_start(dt)
            elif src == 'live':
                self._cur_line = text if cont else f'{_hms(dt)} {text}'
                self._live_line(dt, text, cont, now)
            else:
                self.ue_tail.append(_cap(text if cont else f'{_hms(dt)} {text}'))
                self._cur_line = f'{_hms(dt)} [UE4SS] {text.strip()}'
                self._ue_line(dt, text, cont, now)
            self._cur_line = None

    # ------------------------------------------------------------------ threads

    def _run(self, stop):
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception as e:          # keep watching; the next poll may work
                self.last_error = f'{type(e).__name__}: {e}'
            stop.wait(POLL_S)

    def _proc_loop(self, stop):
        while not stop.is_set():
            self._proc_v, self._proc_t = self._call_proc(), time.monotonic()
            stop.wait(self._proc_interval)

    def _call_proc(self):
        try:
            return bool(self._proc_check())
        except Exception:
            return False

    def _proc_running(self, now):
        if not self._proc_check:
            return False
        if self._proc_thread and self._proc_thread.is_alive():
            return self._proc_v             # the process list is slow on Windows: its own thread
        if self._proc_t is None or now - self._proc_t >= self._proc_interval:
            self._proc_v, self._proc_t = self._call_proc(), now
        return self._proc_v

    # ------------------------------------------------------------------ files

    def _refresh_paths(self, now):
        if self._paths_t is not None and now - self._paths_t < 2.0:
            return
        self._paths_t = now
        try:
            p = self._paths_provider() or {}
        except Exception:
            p = {}
        ue = p.get('ue4ss_dir')
        menu = p.get('menu_dir') or (os.path.join(ue, 'Mods', 'E33Wardrobe') if ue else None)
        key = (p['live_file'] if 'live_file' in p else (os.path.join(menu, LIVE_LOG) if menu else None),
               p['ue_file'] if 'ue_file' in p else (os.path.join(ue, UE4SS_LOG) if ue else None))
        if key == self._paths_key:
            return
        if self._paths_key is not None:     # another game folder: start over
            self._reset()
        self._paths_key, self._menu_dir = key, menu
        self._live = _Tail(key[0], self._first_look) if key[0] else None
        self._uel = _Tail(key[1], self._first_look) if key[1] else None

    def _read_ue(self):
        lines, event, _mid = self._uel.read()
        out = []
        if event:
            self._up_dt, self._pending_lua = None, None
            m = _UE_TS.match(self._uel.head.split(b'\n', 1)[0].decode('utf-8', 'replace').lstrip('\ufeff'))
            out.append([_ue_dt(m) if m else None, 'ue-start', '', False])
        for raw in lines:
            raw = raw.lstrip('\ufeff')
            m = _UE_TS.match(raw)
            if m:
                self._up_dt = _ue_dt(m)
                text, cont = m.group(8), False
            else:
                text, cont = raw, True
            if not text.strip():
                continue
            out.append([self._up_dt or _dt.datetime.now(), 'ue', text, cont])
        if out and out[0][0] is None:       # no time at the top of the file: the first one found
            out[0][0] = next((e[0] for e in out[1:]), None) or _dt.datetime.now()
        hist = self._uel.history
        return [(*e, hist) for e in out]

    def _read_live(self):
        lines, event, mid = self._live.read()
        out = []
        if event:
            self._lp_date = self._lp_tod = self._lp_dt = None
            if mid:                         # the session start line is at the top of the file
                first = self._live.head.split(b'\n', 1)[0].decode('utf-8', 'replace')
                m = _LIVE_TS.match(first)
                if m and _SESSION.match(m.group(4)):
                    out.append(self._live_event(m))
        hist = self._live.history
        for raw in lines:
            m = _LIVE_TS.match(raw)
            if m:
                out.append(self._live_event(m))
            elif raw.strip():
                out.append((self._lp_dt or _dt.datetime.now(), 'live', raw, True))
        return [e + (hist,) for e in out]

    def _live_event(self, m):
        h, mi, s, msg = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        tod = h * 3600 + mi * 60 + s
        sm = _SESSION.match(msg)
        if sm:
            self._lp_date = _dt.date(int(sm.group(1)), int(sm.group(2)), int(sm.group(3)))
        elif self._lp_date is None:         # no session line seen: today (or yesterday, before midnight)
            now = _dt.datetime.now()
            self._lp_date = now.date()
            if _dt.datetime.combine(self._lp_date, _dt.time(h, mi, s)) > now + _dt.timedelta(minutes=1):
                self._lp_date -= _dt.timedelta(days=1)
        elif self._lp_tod is not None and tod < self._lp_tod - 43200:
            self._lp_date += _dt.timedelta(days=1)      # past midnight
        self._lp_tod = tod
        self._lp_dt = _dt.datetime.combine(self._lp_date, _dt.time(h, mi, s))
        return (self._lp_dt, 'live', msg, False)

    # ------------------------------------------------------------------ sessions

    def _new_session(self, dt, origin):
        prev = [p for p in self.problems.values() if p['key'] != 'previous-session']
        self.problems = {}
        if prev:
            self._cur_line, cur = None, self._cur_line      # the line that started the new session isn't one of them
            prev.sort(key=lambda p: (LEVEL_ORDER.get(p['level'], 3), p['_n']))
            names = '; '.join(p['title'] for p in prev[:3])
            more = f'; and {len(prev) - 3} more' if len(prev) > 3 else ''
            p = self._put('previous-session', 'info', f'Previous session had {len(prev)} problem(s)',
                          f'{names}{more}.', "They are in live_log_previous.txt, which report.txt includes.", None,
                          hms=max(p['last'] for p in prev))
            p['first'] = min(x['first'] for x in prev)
            self._cur_line = cur
        self.since, self._session_dt, self._session_origin = _hms(dt), dt, origin
        self._session_reset()
        self.menu_active = False

    def _session_reset(self):
        self.on_screen, self._screen_new = [], None
        self.tail.clear()
        self._picks, self._pick_texts, self._slot_char, self._pass_keys = set(), [], {}, []
        self._last_step, self._work_mono, self._work_desc, self._quiet, self._last_map = '', None, '', False, ''

    def _ue_start(self, dt):
        """UE4SS.log seen for the first time or rewritten: a game start."""
        self._ue = self._new_ue(dt)
        self._new_session(dt, 'ue4ss')

    def _live_session(self, dt):
        """"session start" in live_log.txt. Right after a UE4SS start it is the same game start."""
        if self._session_origin == 'ue4ss' and self._session_dt and dt >= self._session_dt - _dt.timedelta(seconds=5):
            self.since, self._session_dt, self._session_origin = _hms(dt), dt, 'live'
            self._session_reset()
        else:
            self._new_session(dt, 'live')

    # ------------------------------------------------------------------ lines

    def _live_line(self, dt, msg, cont, now):
        if cont:
            self.tail.append(_cap(msg))
            self._apply(_CONT_RULES, msg, 'live', dt)
            return
        s = msg.lstrip()
        if s.startswith('session start '):
            self._live_session(dt)
        hms = _hms(dt)
        self.tail.append(_cap(f'{hms} {msg}'))
        self.last_activity = hms
        if s.startswith('on screen: '):
            self._on_screen_line(s, dt)
            return
        if self._screen_new is not None:    # the pass's on-screen lines are complete
            self.on_screen, self._screen_new = self._screen_new, None
        if s.startswith(('pass (', 're-check after spawn:')):
            self._pass_line(s, now)
            return
        if s.startswith('slot '):
            m = _SLOT_LINE.match(s)
            if m:
                ch = m.group('chars').split(',')[0].strip()
                if ch and ch != 'everyone':
                    self._slot_char[m.group('label')] = ch
            return
        if s.startswith('map loaded: '):
            self._last_map = s[12:].strip()
        elif s.startswith('recording switched off'):
            self._quiet = True
        elif s.startswith(('change ', 'loading ', 'loaded (', 'mesh set')):
            self._last_step = s
            self._work(now, 'loading ' + _leaf(s[8:]) if s.startswith('loading ') else
                       'setting a mesh' if s.startswith('mesh set') else
                       'loading an asset' if s.startswith('loaded (') else 'changing an outfit')
        if msg.startswith('log: '):
            self._mod_msg(msg[5:].strip(), 'live', dt)
        elif not self._apply(_BY_SOURCE['live'], s, 'live', dt):
            self._apply(_BY_SOURCE['any'], s, 'live', dt)

    def _ue_line(self, dt, text, cont, now):
        u = self._ue
        u['last'] = dt if u['last'] is None else max(u['last'], dt)
        pl = self._pending_lua
        if pl is not None:                  # a Lua error a few lines up: is it the menu's?
            if 'E33Wardrobe' in text and '[E33Wardrobe] ' not in text and not any(x in text for x in _NOT_FRAMES):
                self._pending_lua = None
                self._cur_line = [pl[3], self._cur_line]
                self._hit(RULE_UE_LUA, f'{pl[0].strip()} / {text.strip()}', 'ue', pl[1])
                return
            pl[2] -= 1
            if pl[2] <= 0:
                self._pending_lua = None
        if cont:
            return
        if 'E33Wardrobe' in text:
            if "Mod 'E33Wardrobe' has enabled.txt" in text or "Starting Lua mod 'E33Wardrobe'" in text:
                u['started_at'] = dt
                u['loading_at'] = u['loading_at'] or dt
            elif "Mod 'E33Wardrobe' disabled in mods.txt" in text:
                u['disabled'] = True
            i = text.find('[E33Wardrobe] ')
            if i >= 0:
                self._mod_msg(text[i + 14:].strip(), 'ue', dt)
                return
        if text.startswith(('Starting Lua mod', "Mod '")):
            u['loading_at'] = u['loading_at'] or dt       # UE4SS's Lua mods phase
        elif text.startswith('Starting mods'):
            u['starting_mods'] += 1                       # twice at UE4SS start, again for the Lua mods
            if u['starting_mods'] >= 3:
                u['loading_at'] = u['loading_at'] or dt
        elif text.startswith('UE4SS - '):
            m = _UE_VERSION.search(text)
            if m:
                self._ue4ss_version = m.group(1)
        if not self._apply(_BY_SOURCE['ue4ss'], text, 'ue', dt) and _LUA_GENERIC.search(text):
            self._pending_lua = [text, dt, 8, self._cur_line]

    def _mod_msg(self, text, src, dt):
        if text.startswith('menu closed'):
            self._quiet = True
        m = _READY.match(text)
        if m:
            self.menu_active = True
            self._ue['ready'] = True
            self._menu_version = m.group(1)
        if not self._apply(_BY_SOURCE['mod'], text, src, dt, mod=True):
            self._apply(_BY_SOURCE['any'], text, src, dt, mod=True)

    def _apply(self, rules, text, src, dt, mod=False):
        for r in rules:
            if r.need and r.need not in text:
                continue
            if r.exclude is not None and r.exclude.search(text):
                continue
            m = r.rx.search(text)
            if not m:
                continue
            if r.special:
                if getattr(self, r.special)(m, text, src, dt):
                    return True
                continue
            self._hit(r, text, src, dt, m, mod)
            return True
        return False

    def _hit(self, r, text, src, dt, m=None, mod=False):
        v = _Vars({k: _redact(x.strip()) for k, x in (m.groupdict() if m else {}).items() if x is not None})
        v['line'], v['linekey'] = _short(_redact(text), 300), _norm(text)
        if 'err' in v:
            v['errkey'] = _norm(v['err'])
        if 'path' in v:
            v['leaf'], v['name'] = _leaf(v['path']), re.split(r'[\\/]', v['path'])[-1]
        if 'tex' in v:
            v['texleaf'] = _leaf(v['tex'])
            src_note = v.get('src', '')
            v['srcnote'] = " (the mod's own)" if 'own' in src_note else (f' ({src_note})' if src_note else '')
        if 'mat' in v:
            v['matleaf'] = _leaf(v['mat'])
            v['srcnote'] = f" ({v['src']})" if v.get('src') else ''
        key = _short(_fill(r.key, v), 200)
        if mod and self._dup(key, text, src, dt):
            return None
        if r.attrib and key in self._pass_keys:     # the same fill on another actor in this pass
            p = self.problems.get(key)
            if p is not None:
                self._add_lines(p)
            return p
        p = self._put(key, r.level, _fill(r.title, v), _fill(r.detail, v), _fill(r.hint, v), dt, rule=r, v=v)
        if r.explains:
            self._ue['explained'] = True
        if r.attrib and p is not None and key not in self._pass_keys:
            self._pass_keys.append(key)
        return p

    def _dup(self, key, text, src, dt):
        """The menu's messages reach both logs: count the second copy (other log, same text,
        within 2 s) as the same event."""
        for e in self._xsrc:
            if not e[4] and e[2] != src and e[0] == key and e[1] == text and abs((e[3] - dt).total_seconds()) <= 2.5:
                e[4] = True
                return True
        self._xsrc.append([key, text, src, dt, False])
        return False

    def _put(self, key, level, title, detail, hint, dt, rule=None, v=None, hms=None):
        t = hms or _hms(dt or _dt.datetime.now())
        p = self.problems.get(key)
        if p:
            p['count'] += 1
            p['last'] = t
            self._add_lines(p)
            return p
        if len(self.problems) >= MAX_PROBLEMS and level != 'error':
            return None
        self._n += 1
        p = {'key': key, 'level': level, 'title': _short(title, 120), 'detail': _short(detail, 500),
             'hint': _short(hint, 300), 'first': t, 'last': t, 'count': 1, '_n': self._n, '_rule': rule, '_v': v,
             '_lines': []}
        self.problems[key] = p
        self._add_lines(p)
        return p

    def _add_lines(self, p):
        """Keep the log line(s) being read with the problem they raised."""
        cur = self._cur_line
        if not cur:
            return
        lines = p.setdefault('_lines', [])
        for ln in (cur if isinstance(cur, list) else [cur]):
            ln = _short(_redact(ln or ''), 500)        # user names hidden: these go into copied bug reports
            if ln and (not lines or lines[-1] != ln):
                lines.append(ln)
        if len(lines) > MAX_PROBLEM_LINES:
            del lines[:len(lines) - MAX_PROBLEM_LINES]

    def _work(self, now, desc):
        if not self._history:
            self._work_mono, self._work_desc, self._quiet = now, desc, False

    # ------------------------------------------------------------------ passes and the on-screen table

    def _pass_line(self, s, now):
        self._screen_new = []
        m = _PASS.match(s)
        picks, texts, n, reasons = set(), [], 0, ''
        if m:
            reasons, n = m.group('reasons'), int(m.group('n'))
            for r in reasons.split(' + '):
                w = _WEAR_REASON.match(r)
                if w:
                    if w.group(1) == 'on':
                        picks.add(w.group(2))
                    continue
                pm = _PICK_REASON.match(r)
                if pm and pm.group(2) != 'off':
                    picks.add(pm.group(1))
                    texts.append(r)
        else:
            m = _RECHECK.match(s)
            n = int(m.group('n')) if m else 0
        self._picks, self._pick_texts = picks, texts
        if self._pass_keys:                 # empty-texture fills of this pass: name the pick
            who = ', '.join(texts)
            for k in self._pass_keys:
                p = self.problems.get(k)
                if p and who and p['_v'] is not None and not p['_v'].get('who'):
                    p['_v']['who'], p['_v']['whonote'] = who, f' Seen after picking {who}.'
                    p['detail'] = _short(_fill(p['_rule'].detail, p['_v']), 500)
            self._pass_keys = []
        if n > 0:
            self._work(now, f'a pass ({_short(reasons, 60)})' if reasons else 'a re-check after a spawn')
        self._last_step = s

    def _on_screen_line(self, s, dt):
        m = _ON_SCREEN.match(s)
        if not m:
            return
        row = {'slot': m.group('slot'), 'variant': m.group('variant'), 'shown': int(m.group('shown')),
               'total': int(m.group('total')), 'worn': '; worn (Wear)' in m.group('rest')}
        if self._screen_new is None:
            self._screen_new = []
        self._screen_new.append(row)
        self.on_screen = list(self._screen_new)
        self._unseen(row, dt)

    def _unseen(self, row, dt):
        """A slot just picked (or worn) that shows none of its pieces."""
        slot, key = row['slot'], 'unseen:' + row['slot']
        if row['shown'] > 0:
            self.problems.pop(key, None)
            return
        if row['total'] == 0 or slot not in self._picks:
            return
        who = self._slot_char.get(slot) or 'the character'
        if row['worn']:
            detail = (f"It is worn, but none of its {row['total']} pieces show. {_sentence(who)} may not be in "
                      'this scene; if they are, press Fix look in the menu.')
            hint = "If Fix look doesn't help, send report.txt."
        else:
            detail = (f"None of its {row['total']} pieces show. Usually the mod is made for an outfit {who} "
                      f"isn't wearing, or {who} isn't in this scene.")
            hint = WEAR_HINT
        self._put(key, 'info', f'{slot}: nothing on screen changed', detail, hint, dt)

    # ------------------------------------------------------------------ special rules

    def _watchdog(self, m, text, src, dt):
        secs, state, since = int(m.group('s')), m.group('state').strip(), m.group('since') or ''
        idle = state == 'idle'
        key = 'watchdog-idle' if idle else 'watchdog-work'
        p = self.problems.get(key)
        if p and p['_v'].get('since') == since and since:
            p['last'] = _hms(dt)            # the same stall, still going: not another one
            self._add_lines(p)
        else:
            p = self._put(key, 'warn', '', '', '', dt, v=_Vars(max=0))
            if p is None:
                return True
            p['_v']['since'] = since
        if secs >= p['_v']['max']:
            p['_v']['max'] = secs
            if idle:
                p['detail'] = ('The menu was idle, so the pause came from the game itself. '
                               'During a loading screen this is normal.')
                p['hint'] = 'Nothing to do if it was a loading screen. If the game froze, send report.txt.'
            else:
                step = f' Its last step: {_short(self._last_step, 140)}.' if self._last_step else ''
                p['detail'] = f'It happened while the menu was working ({state}).{step}'
                p['hint'] = ('If the game is frozen: before closing it, create a dump file in Task Manager '
                             "(see 'If the game freezes' in the guide), then send report.txt.")
        mx = p['_v']['max']
        p['title'] = f'The game stopped responding for {mx} s'
        p['level'] = 'warn' if (not idle or mx >= 30) else 'info'
        if not idle:
            self._work(time.monotonic(), state)
        return True

    def _autowear(self, m, text, src, dt):
        slot, char = m.group('slot'), m.group('char')
        self.problems.pop('unseen:' + slot, None)
        self._put('auto-wear:' + slot, 'info', f'Auto Wear put on {slot}',
                  f"It's made for another outfit than the one {char} wears, so it is worn in place of that outfit.",
                  f"To keep {char}'s own outfit, switch Wear off on that row.", dt)
        return True

    def _ue_lua(self, m, text, src, dt):
        if not _LUA_ERR.search(text) or any(x in text for x in _NOT_FRAMES):
            return False
        self._hit(RULE_UE_LUA, text, src, dt)
        return True

    # ------------------------------------------------------------------ game exit, crashes, menu start

    def _on_exit(self, now):
        """The game process went away. Warn only when the menu was in the middle of something."""
        if self._work_mono is None or self._quiet:
            return
        if now - self._work_mono > 10 + self._proc_interval + POLL_S:
            return
        if self._last_map.lower().startswith('level_mainmenu'):
            return
        if self._crash_mono is not None and abs(now - self._crash_mono) < 60:
            return
        self._put('stopped-working', 'warn', 'The game closed while the menu was working',
                  f"The game ended right after the menu's last step ({self._work_desc}), without the menu "
                  "being closed. If you didn't quit, it probably crashed.",
                  'Send report.txt (the next game start writes it, with this session in it) and a copy of UE4SS.log '
                  'made before that start.', _dt.datetime.now())

    def _check_crashes(self, now):
        d = self._crash_dir
        if not d:
            return
        try:
            mt = os.stat(d).st_mtime_ns
        except OSError:
            mt = None
        if mt == self._crash_m and now - self._crash_t < 10:
            return
        self._crash_m, self._crash_t = mt, now
        names = set()
        if mt is not None:
            try:
                names = {n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))}
            except OSError:
                pass
        if self._crash_known is None:       # the first look: what is there is old
            self._crash_known = names
            return
        for n in sorted(names - self._crash_known):
            try:
                t = _dt.datetime.fromtimestamp(os.stat(os.path.join(d, n)).st_mtime)
            except OSError:
                t = _dt.datetime.now()
            detail = f'Windows saved a crash report in the folder {n}.'
            working = self.problems.pop('stopped-working', None) is not None or (
                self._work_mono is not None and not self._quiet and now - self._work_mono <= 15)
            if working and self._work_desc:
                detail += f' The menu was working at that moment ({self._work_desc}).'
            self._put('crash:' + n, 'error', f'The game crashed at {t:%H:%M}', detail,
                      'Send that crash folder and report.txt. Copy UE4SS.log first: the next game start overwrites it.', t)
            self._crash_mono = now
        self._crash_known |= names

    def _check_menu_start(self):
        """UE4SS loaded its Lua mods but the menu never said it was ready: 60 s after the Lua mods
        started (not after UE4SS's first line: on a slow PC the engine alone can take 30 s)."""
        u = self._ue
        if u['start'] is None or u['warned'] or u['ready'] or self.menu_active or u['explained'] or not u['loading_at']:
            return
        since = u['started_at'] or u['loading_at']
        end = u['last'] or since
        if self.game_running:
            end = max(end, _dt.datetime.now())
        if (end - since).total_seconds() < 60:
            return
        u['warned'] = True
        at = since + _dt.timedelta(seconds=60)
        if u['started_at']:
            self._put('menu-not-ready', 'warn', "The in-game menu didn't finish starting",
                      'UE4SS started it, but it never reported that it was ready.',
                      'Look for an error above. Send report.txt and a copy of UE4SS.log.', at)
            return
        md = self._menu_dir
        if u['disabled']:
            hint = ("mods.txt in ue4ss\\Mods switches it off: change the E33Wardrobe line to "
                    "'E33Wardrobe : 1' or delete it, then start the game again.")
        elif not md or not os.path.isdir(md):
            hint = "The menu isn't installed. Use Install menu in the app, then start the game again."
        elif not os.path.isfile(os.path.join(md, 'enabled.txt')):
            hint = ('ue4ss\\Mods\\E33Wardrobe has no enabled.txt. Use Install menu in the app to repair it, '
                    'then start the game again.')
        elif not os.path.isfile(os.path.join(md, 'Scripts', 'main.lua')):
            hint = ('ue4ss\\Mods\\E33Wardrobe\\Scripts\\main.lua is missing (perhaps one folder too deep). '
                    'Use Install menu in the app, then start the game again.')
        else:
            hint = ('If you installed the menu after that game start, start the game again. Otherwise use '
                    "Install menu in the app, and send UE4SS.log if it still doesn't start.")
        self._put('menu-not-started', 'warn', "The in-game menu didn't start",
                  'UE4SS loaded its mods, but E33Wardrobe was not among them.', hint, at)


def _ue_dt(m):
    return _dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)),
                        int(m.group(6)), int((m.group(7) or '0')[:6].ljust(6, '0')))


def analyse(live=None, ue=None, tail_lines=FILE_TAIL_LINES, menu_dir=None):
    """One read of logs of a game that has ended: `live` (live_log.txt or live_log_previous.txt)
    and/or `ue` (UE4SS.log), through the same rules as the live monitor. Missing files are
    skipped. Returns the Monitor shape (watching and game_running false) plus 'ue_tail' (UE4SS.log
    lines), 'lines' (lines read), 'menu_version' and 'ue4ss_version'. Lines are cut at 1000
    characters, as in the live tail. menu_dir: for the hints when the menu didn't start."""
    files = {'live_file': live if live and os.path.isfile(live) else None,
             'ue_file': ue if ue and os.path.isfile(ue) else None, 'menu_dir': menu_dir}
    m = Monitor(lambda: files, process_check=None, crash_dir=None, tail_lines=tail_lines, first_look=MAX_READ)
    m.poll_once()
    snap = m.snapshot()
    snap.update(watching=False, game_running=False, ue_tail=list(m.ue_tail), lines=m._n_lines,
                menu_version=m._menu_version, ue4ss_version=m._ue4ss_version)
    return snap
