"""class Api: every method of app/API.md. Methods never raise: a failure is
{"ok": false, "error": "<plain sentence>"}. Long work goes to the job queue (jobs.py); the page
polls poll().

The window code sets `api.dialogs` to an object with folder() -> path | None and files() -> [paths].
"""
import functools
import os
import subprocess
import threading
import time
import traceback
import webbrowser

from . import archives, jobs, library, paths

URLS = {
    'ue4ss': 'https://www.nexusmods.com/clairobscurexpedition33/mods/630?tab=files',
    'nexus': 'https://www.nexusmods.com/clairobscurexpedition33/mods/938',
    'github': 'https://github.com/alphamr123/e33-wardrobe',
    'guide': 'https://github.com/alphamr123/e33-wardrobe/blob/main/docs/USAGE.md',
}
NO_GAME = 'Pick the game folder first.'


def _log_error(where, text):
    try:
        p = os.path.join(paths.app_data_dir(), 'backend.log')
        if os.path.isfile(p) and os.path.getsize(p) > 1024 * 1024:
            os.replace(p, p + '.old')
        with open(p, 'a', encoding='utf-8') as f:
            f.write(f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] {where}:\n{text}\n')
    except OSError:
        pass


def api_method(fn):
    """Never raise to the page."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kw):
        try:
            return fn(self, *args, **kw)
        except jobs.JobFailed as e:
            return {'ok': False, 'error': str(e)}
        except Exception as e:
            _log_error(fn.__name__, traceback.format_exc())
            return {'ok': False, 'error': f'Something went wrong ({type(e).__name__}: {e}).'}
    return wrapper


class Api:
    def __init__(self, start_monitor=True):
        self.dialogs = None
        self._lock = threading.RLock()
        self._changed = 1
        self._settings = self._load_settings()
        self._game = None
        self._init_game()
        self._jobs = jobs.JobQueue(self)
        self._recover_backups()
        self._monitor = None
        try:
            from .monitor import Monitor
        except Exception:           # not written yet, or broken: the app works without it
            Monitor = None
        if Monitor is not None:
            try:
                self._monitor = Monitor(self._monitor_paths)
                if start_monitor and self._settings.get('watch_game', True):
                    self._monitor.start()
            except Exception:
                _log_error('monitor', traceback.format_exc())
                self._monitor = None

    # ------------------------------------------------------------------ internals

    def _load_settings(self):
        s = paths.read_json(paths.settings_path(), {})
        return s if isinstance(s, dict) else {}

    def _save_settings(self):
        with self._lock:
            paths.write_json(paths.settings_path(), self._settings)

    def _bump(self):
        with self._lock:
            self._changed += 1

    def _init_game(self):
        saved = paths.normalize_game_folder(self._settings.get('game_root'))
        if saved:
            self._set_game(saved, 'saved', save=False)
            return
        try:
            found = paths.detect_game()
        except Exception:
            found = None
        if found:
            self._set_game(found, 'detected', save=False)

    def _set_game(self, res, source, save=True):
        root, paks = res
        with self._lock:
            self._game = {'root': root, 'paks': paks, 'store': paths.store_of(root), 'source': source}
            if save:
                self._settings['game_root'] = root
                self._save_settings()
        self._bump()

    def _library(self):
        lib = self._settings.get('library')
        if lib:
            return lib
        if self._game:
            return os.path.join(os.path.dirname(self._game['paks']), 'Paks_ModLibrary')
        return None

    def _lua_dir(self):
        if not self._game:
            return None
        return paths.menu_dir(self._game['root'], self._game['paks'])

    def _context(self):
        """For jobs: dict(root, paks, library, lua_dir, retoc). Raises JobFailed without a game."""
        g = self._game
        if not g or not paths.is_game_root(g['root']):
            raise jobs.JobFailed(NO_GAME)
        return {'root': g['root'], 'paks': g['paks'], 'library': self._library(), 'lua_dir': self._lua_dir(),
                'retoc': paths.find_retoc()}

    def _view(self):
        g = self._game or {}
        return library.View(self._library(), g.get('paks'), self._lua_dir(), self._jobs.active_mod_ids())

    def _monitor_paths(self):
        g = self._game or {}
        return {'game_root': g.get('root'), 'paks': g.get('paks'), 'ue4ss_dir': paths.ue4ss_dir(g.get('root')),
                'menu_dir': self._lua_dir()}

    def _recover_backups(self):
        """'<mod>.old' left by an update that was interrupted: put it back if the mod is gone."""
        lib = self._library()
        if not lib or not os.path.isdir(lib):
            return
        try:
            for n in os.listdir(lib):
                if n.lower().endswith('.old') and os.path.isdir(os.path.join(lib, n)):
                    orig = os.path.join(lib, n[:-4])
                    if not os.path.exists(orig):
                        os.replace(os.path.join(lib, n), orig)
        except OSError:
            pass

    def _game_running(self):
        try:
            return bool(paths.tools()['common'].game_running())
        except Exception:
            return False

    def _formats(self):
        f = ['zip']
        if paths.has_py7zr():
            f.append('7z')
        if archives.rar_tool():
            f.append('rar')
        return f

    def _open(self, p, select=False):
        if not paths.IS_WINDOWS:
            return {'ok': True, 'path': p}
        if select:
            subprocess.Popen(['explorer', '/select,', os.path.normpath(p)], creationflags=0x08000000)
        else:
            os.startfile(p)          # noqa: only on Windows
        return {'ok': True, 'path': p}

    def shutdown(self):
        """Stop the monitor (window closing). Not part of API.md."""
        if self._monitor is not None:
            try:
                self._monitor.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ state

    @api_method
    def get_state(self):
        g = self._game
        root = g['root'] if g else None
        if root:
            u = paths.ue4ss_info(root)
            ue4ss = {'installed': u['installed'], 'version': u['version'], 'ok': u['ok'], 'problem': u['problem']}
        else:
            ue4ss = {'installed': False, 'version': None, 'ok': False, 'problem': None}
        lua = self._lua_dir()
        if lua:
            menu = paths.menu_info(lua)
        else:
            menu = {'installed': False, 'version': None, 'update': False,
                    'bundled': paths.lua_version(os.path.join(paths.lua_template(), 'Scripts', 'main.lua'))}
        return {
            'version': paths.app_version(),
            'first_run': not os.path.isfile(paths.settings_path()),
            'game': {'found': bool(g), 'root': root, 'paks': g['paks'] if g else None,
                     'store': g['store'] if g else None, 'source': g['source'] if g else None},
            'ue4ss': ue4ss,
            'menu': menu,
            'library': self._library(),
            'game_running': self._game_running(),
            'tools': {'retoc': bool(paths.find_retoc()), 'formats': self._formats()},
        }

    @api_method
    def set_game_folder(self, path):
        res = paths.normalize_game_folder(path if isinstance(path, str) else None)
        if not res:
            return {'ok': False, 'error': 'No game found there. Pick the Expedition 33 folder (the one with '
                                          'Sandfall in it).', 'state': self.get_state()}
        self._set_game(res, 'picked')
        return {'ok': True, 'state': self.get_state()}

    @api_method
    def pick_game_folder(self):
        if self.dialogs is None:
            return {'ok': False, 'error': 'not available'}
        p = self.dialogs.folder()
        if not p:
            return {'ok': False, 'error': 'cancelled'}
        return self.set_game_folder(p)

    @api_method
    def detect_game(self):
        res = paths.detect_game()
        if not res:
            return {'ok': False, 'error': "The game wasn't found automatically. Pick its folder.",
                    'state': self.get_state()}
        self._set_game(res, 'detected')
        return {'ok': True, 'state': self.get_state()}

    # ------------------------------------------------------------------ adding mods

    @api_method
    def pick_files(self):
        if self.dialogs is None:
            return {'ok': False, 'error': 'not available'}
        files = self.dialogs.files()
        if not files:
            return {'ok': False, 'error': 'cancelled'}
        return self.add_paths(list(files))

    @api_method
    def pick_library_folder(self):
        if self.dialogs is None:
            return {'ok': False, 'error': 'not available'}
        p = self.dialogs.folder()
        if not p:
            return {'ok': False, 'error': 'cancelled'}
        return self.save_settings({'library': p})

    @api_method
    def clear_jobs(self):
        return {'ok': True, 'cleared': self._jobs.clear_finished()}

    @api_method
    def pick_folder(self):
        if self.dialogs is None:
            return {'ok': False, 'error': 'not available'}
        p = self.dialogs.folder()
        if not p:
            return {'ok': False, 'error': 'cancelled'}
        return self.add_paths([p])

    @api_method
    def add_paths(self, paths_in):
        if isinstance(paths_in, str):
            paths_in = [paths_in]
        if not isinstance(paths_in, (list, tuple)):
            return {'ok': False, 'error': 'Expected a list of files or folders.'}
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        lib = self._library()
        items, refused = [], []
        for p in paths_in:
            if not isinstance(p, str) or not p.strip():
                continue
            a = os.path.abspath(p.strip().strip('"'))
            if lib and (paths.is_inside(lib, a) or os.path.normcase(a) == os.path.normcase(os.path.abspath(lib))):
                refused.append(os.path.basename(a) or a)       # the library itself, or a folder holding it
                continue
            if lib and paths.is_inside(a, os.path.join(lib, '.incoming')):
                continue
            items.append(a)
        groups, bad = archives.plan_items(items)
        ids = [self._jobs.add(g) for g in groups]
        skipped = refused + [os.path.basename(b) or b for b in bad]
        if not ids:
            return {'ok': False, 'error': 'Nothing to add. Drop .zip, .7z or .rar files, or mod folders.'
                    + (f" Not used: {', '.join(skipped[:5])}." if skipped else '')}
        out = {'ok': True, 'jobs': ids}
        if skipped:
            out['skipped'] = skipped
        return out

    @api_method
    def poll(self):
        with self._lock:
            changed = self._changed
        return {'busy': self._jobs.busy(), 'changed': changed, 'jobs': self._jobs.snapshot()}

    # ------------------------------------------------------------------ mods

    @api_method
    def list_mods(self):
        if not self._library():
            return []
        return library.list_mods(self._view())

    @api_method
    def mod_details(self, mod_id):
        if not isinstance(mod_id, str) or not mod_id:
            return {'ok': False, 'error': 'No mod given.'}
        d = library.mod_details(self._view(), mod_id)
        if d is None:
            return {'ok': False, 'error': f'There is no mod named "{mod_id}".'}
        return d

    def _known(self, mod_id):
        if library.safe_child(self._library() or os.sep, mod_id) is None:
            return None
        v = self._view()
        if v.folder(mod_id) or mod_id in v.by_name:
            return v
        return None

    @api_method
    def reinstall_mod(self, mod_id):
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        v = self._known(mod_id)
        if v is None or not v.folder(mod_id):
            return {'ok': False, 'error': f'The folder of "{mod_id}" is missing from the library.'}
        same = self._jobs.pending('reinstall', mod_id)
        if same:
            return {'ok': True, 'jobs': [same]}
        return {'ok': True, 'jobs': [self._jobs.reinstall(mod_id, library.folder_size(v.folder(mod_id)))]}

    @api_method
    def remove_mod(self, mod_id, delete_files=False):
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        v = self._known(mod_id)
        if v is None:
            return {'ok': False, 'error': f'There is no mod named "{mod_id}".'}
        same = self._jobs.pending('remove', mod_id)
        if same:
            return {'ok': True, 'jobs': [same]}
        return {'ok': True, 'jobs': [self._jobs.remove(mod_id, bool(delete_files))]}

    # ------------------------------------------------------------------ the in-game menu

    @api_method
    def install_menu(self):
        if not self._game:
            return {'ok': False, 'error': NO_GAME, 'state': self.get_state()}
        u = paths.ue4ss_info(self._game['root'])
        if not u['installed']:
            return {'ok': False, 'error': 'Install UE4SS first: the menu runs inside it.', 'state': self.get_state()}
        if self._game_running():
            return {'ok': False, 'error': 'Close the game first.', 'state': self.get_state()}
        R = paths.tools()['relocate']
        lua = self._lua_dir()
        template = paths.lua_template()
        if not os.path.isfile(os.path.join(template, 'Scripts', 'main.lua')):
            return {'ok': False, 'error': 'The menu files are missing from the app. Reinstall the app.',
                    'state': self.get_state()}
        os.makedirs(os.path.join(lua, 'Scripts'), exist_ok=True)
        R.install_lua(template, lua)
        vl = os.path.join(lua, 'Scripts', 'variants.lua')
        if not os.path.isfile(vl):
            reg = paths.read_json(os.path.join(lua, 'wardrobe_registry.json'), [])
            if isinstance(reg, list) and reg:
                R.write_variants_lua(vl, reg)
            else:
                with open(vl + '.tmp', 'w', encoding='utf-8', newline='\n') as f:
                    f.write('-- Replaced by E33 Wardrobe with your relocated variants.\nreturn {}\n')
                os.replace(vl + '.tmp', vl)
        self._bump()
        return {'ok': True, 'state': self.get_state()}

    # ------------------------------------------------------------------ opening things

    @api_method
    def open_path(self, what):
        if not isinstance(what, str) or not what:
            return {'ok': False, 'error': 'Nothing to open.'}
        g = self._game
        if what == 'library':
            lib = self._library()
            if not lib:
                return {'ok': False, 'error': NO_GAME}
            os.makedirs(lib, exist_ok=True)
            return self._open(lib)
        if not g:
            return {'ok': False, 'error': NO_GAME}
        if what == 'game':
            return self._open(g['root'])
        if what == 'mods':
            p = os.path.join(g['paks'], '~mods', '_E33Wardrobe')
            if not os.path.isdir(p):
                return {'ok': False, 'error': 'No mods are prepared for the menu yet.'}
            return self._open(p)
        if what == 'menu':
            p = self._lua_dir()
            if not p or not os.path.isdir(p):
                return {'ok': False, 'error': "The in-game menu isn't installed."}
            return self._open(p)
        if what == 'report':
            p = os.path.join(self._lua_dir() or '', 'report.txt')
            if not os.path.isfile(p):
                return {'ok': False, 'error': 'No report.txt yet. In game, press Ctrl+F9 to write one.'}
            return self._open(p, select=True)
        if what == 'crashes':
            cands = []
            if os.environ.get('LOCALAPPDATA'):
                cands.append(os.path.join(os.environ['LOCALAPPDATA'], 'Sandfall', 'Saved', 'Crashes'))
            cands.append(os.path.join(g['root'], 'Sandfall', 'Saved', 'Crashes'))
            for p in cands:
                if os.path.isdir(p):
                    return self._open(p)
            return {'ok': False, 'error': 'No crash reports found.'}
        v = self._view()
        f = v.folder(what)
        if f:
            return self._open(f)
        return {'ok': False, 'error': f'There is no folder for "{what}".'}

    @api_method
    def open_url(self, name):
        url = URLS.get(name) if isinstance(name, str) else None
        if not url:
            return {'ok': False, 'error': 'Unknown link.'}
        if paths.IS_WINDOWS:
            webbrowser.open(url)
        return {'ok': True, 'url': url}

    # ------------------------------------------------------------------ monitor

    @api_method
    def monitor(self):
        if self._monitor is not None:
            try:
                return self._monitor.snapshot()
            except Exception:
                _log_error('monitor.snapshot', traceback.format_exc())
        return {'watching': False, 'game_running': self._game_running(), 'since': None, 'menu_active': False,
                'last_activity': None, 'problems': [], 'on_screen': [], 'tail': []}

    @api_method
    def problems_text(self):
        if self._monitor is not None:
            try:
                return self._monitor.problems_text()
            except Exception:
                _log_error('monitor.problems_text', traceback.format_exc())
        s = self.get_state()
        lines = [f"E33 Wardrobe {s.get('version')}"]
        g = s.get('game') or {}
        lines.append(f"Game: {g.get('root')} ({g.get('store') or 'store unknown'})" if g.get('found') else 'Game: not found')
        u = s.get('ue4ss') or {}
        lines.append(f"UE4SS: {u.get('version') or 'version unknown'}" if u.get('installed') else 'UE4SS: not installed')
        if u.get('problem'):
            lines.append('  ' + u['problem'])
        m = s.get('menu') or {}
        lines.append(f"Menu: {m.get('version') or 'not installed'} (app has {m.get('bundled')})")
        lines.append('Live monitor: not available in this build.')
        return '\n'.join(lines) + '\n'

    # ------------------------------------------------------------------ settings

    @api_method
    def get_settings(self):
        return {'library': self._library(), 'watch_game': bool(self._settings.get('watch_game', True))}

    @api_method
    def save_settings(self, data):
        if not isinstance(data, dict):
            return {'ok': False, 'error': 'Expected settings.'}
        new = dict(self._settings)
        if 'library' in data:
            lib = data.get('library')
            if lib in (None, ''):
                new.pop('library', None)
            elif not isinstance(lib, str):
                return {'ok': False, 'error': 'The library must be a folder.'}
            else:
                lib = os.path.abspath(lib.strip().strip('"'))
                if self._game and paths.is_inside(lib, self._game['paks']):
                    return {'ok': False, 'error': "The library can't be inside the Paks folder: the game would load "
                                                  'its files.'}
                if os.path.exists(lib) and not os.path.isdir(lib):
                    return {'ok': False, 'error': 'The library must be a folder.'}
                try:
                    os.makedirs(lib, exist_ok=True)
                except OSError as e:
                    return {'ok': False, 'error': f"Couldn't create the library folder ({e.strerror})."}
                default = os.path.join(os.path.dirname(self._game['paks']), 'Paks_ModLibrary') if self._game else None
                if default and os.path.normcase(lib) == os.path.normcase(os.path.abspath(default)):
                    new.pop('library', None)
                else:
                    new['library'] = lib
        if 'watch_game' in data:
            new['watch_game'] = bool(data.get('watch_game'))
        if self._game and not new.get('game_root'):
            new['game_root'] = self._game['root']
        with self._lock:
            old_watch = self._settings.get('watch_game', True)
            self._settings = new
            self._save_settings()
        if self._monitor is not None and old_watch != new.get('watch_game', True):
            try:
                (self._monitor.start if new.get('watch_game', True) else self._monitor.stop)()
            except Exception:
                _log_error('monitor start/stop', traceback.format_exc())
        self._bump()
        out = self.get_settings()
        out['ok'] = True
        return out
