"""class Api: every method of app/API.md. Methods never raise: a failure is
{"ok": false, "error": "<plain sentence>"}. Long work goes to the job queue (jobs.py); the page
polls poll().

The window code sets `api.dialogs` to an object with folder() -> path | None and files() -> [paths].
"""
import functools
import hashlib
import os
import re
import subprocess
import threading
import time
import traceback
import webbrowser

from . import archives, assets, culprit, fixes, jobs, library, paths, repair

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


MATERIAL_CLASSES = ('MaterialInstanceConstant', 'MaterialInstance', 'Material')


def _ver_key(v):
    return [int(x) if x.isdigit() else 0 for x in re.split(r'[.\-]', v or '')]


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

    def _known(self, mod_id, v=None):
        if not isinstance(mod_id, str) or library.safe_child(self._library() or os.sep, mod_id) is None:
            return None
        v = v if isinstance(v, library.View) else self._view()
        if v.folder(mod_id) or mod_id in v.by_name:
            return v
        return None

    @api_method
    def reinstall_mod(self, mod_id, _view=None):
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        v = self._known(mod_id, _view)
        if v is None or not v.folder(mod_id):
            return {'ok': False, 'error': f'The folder of "{mod_id}" is missing from the library.'}
        same = self._jobs.pending('reinstall', mod_id)
        if same:
            return {'ok': True, 'jobs': [same]}
        return {'ok': True, 'jobs': [self._jobs.reinstall(mod_id, library.folder_size(v.folder(mod_id)))]}

    @api_method
    def remove_mod(self, mod_id, delete_files=False, _view=None):
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        v = self._known(mod_id, _view)
        if v is None:
            return {'ok': False, 'error': f'There is no mod named "{mod_id}".'}
        if culprit.in_hunt(mod_id):
            return {'ok': False, 'error': f'Finding the problem mod manages {mod_id} right now. Finish it (or Stop and '
                                          'turn all back on) first.'}
        same = self._jobs.pending('remove', mod_id)
        if same:
            return {'ok': True, 'jobs': [same]}
        return {'ok': True, 'jobs': [self._jobs.remove(mod_id, bool(delete_files))]}

    def _many(self, ids, one):
        if isinstance(ids, str):
            ids = [ids]
        if not isinstance(ids, (list, tuple)) or not ids:
            return {'ok': False, 'error': 'No mods given.'}
        jobs_out, errors = [], []
        view = self._view() if self._game else None      # one read of the library for the whole batch
        for mod_id in ids:
            r = one(mod_id, view)
            if r.get('ok'):
                jobs_out += [j for j in r.get('jobs', []) if j not in jobs_out]
            else:
                errors.append({'id': mod_id, 'error': r.get('error') or 'Something went wrong.'})
        if not jobs_out:
            return {'ok': False, 'error': errors[0]['error'] if len(errors) == 1 else
                    f"None of the {len(errors)} mods could be queued: {errors[0]['error']}", 'errors': errors}
        return {'ok': True, 'jobs': jobs_out, 'errors': errors}

    @api_method
    def reinstall_mods(self, mod_ids):
        """reinstall_mod for each; one job per mod. {ok, jobs, errors: [{id, error}]}"""
        return self._many(mod_ids, lambda m, v: self.reinstall_mod(m, _view=v))

    @api_method
    def remove_mods(self, mod_ids, delete_files=False):
        """remove_mod for each; one job per mod. {ok, jobs, errors: [{id, error}]}"""
        return self._many(mod_ids, lambda m, v: self.remove_mod(m, delete_files, _view=v))

    @api_method
    def texture_preview(self, mod_id, ref, max_px=1024):
        if not isinstance(mod_id, str) or self._known(mod_id) is None:
            return {'ok': False, 'error': f'There is no mod named "{mod_id}".'}
        from . import assets
        return assets.texture_preview(self._view(), mod_id, ref, max_px)

    # ------------------------------------------------------------------ fixes (fixes.json, e33fixes)

    def _fix_ctx(self, mod_id=None, prepared=True):
        """(view, paks, lua_dir) for a fix of a mod; raises JobFailed with the reason."""
        if not self._game:
            raise jobs.JobFailed(NO_GAME)
        lua = self._lua_dir()
        if not lua or not os.path.isdir(lua):
            raise jobs.JobFailed("The in-game menu isn't installed. Install it in Setup first.")
        try:
            fixes.tool()
        except fixes.FixError as e:
            raise jobs.JobFailed(str(e))
        v = self._view()
        if mod_id is not None:
            if self._known(mod_id, v) is None:
                raise jobs.JobFailed(f'There is no mod named "{mod_id}".')
            if prepared and mod_id not in v.by_name:
                raise jobs.JobFailed(f'{mod_id} is not prepared for the menu yet. Install it first.')
        return v, self._game['paks'], lua

    @api_method
    def set_disabled(self, mod_id, on):
        v, paks, lua = self._fix_ctx(mod_id)
        if culprit.in_hunt(mod_id):
            return {'ok': False, 'error': f'Finding the problem mod manages {mod_id} right now. Finish it (or Stop and '
                                          'turn all back on) first.'}
        if mod_id in self._jobs.active_mod_ids():
            return {'ok': False, 'error': f'Wait for the task of {mod_id} to finish.'}
        if self._game_running_strict():
            return {'ok': False, 'error': 'Close the game first: its files are in use while it runs.'}
        r = fixes.tool().set_disabled(paks, lua, mod_id, bool(on)) or {'ok': True}
        self._bump()
        return r

    def _game_running_strict(self):
        """The relocator's check: the process list, or a prepared .ucas the game holds locked."""
        try:
            out_root = os.path.join(self._game['paks'], '~mods', '_E33Wardrobe') if self._game else None
            probe = []
            if out_root and os.path.isdir(out_root):
                for dp, _ds, fs in os.walk(out_root):
                    probe += [os.path.join(dp, f) for f in fs if f.lower().endswith('.ucas')]
                    if len(probe) >= 20:
                        break
            return bool(paths.tools()['common'].game_running(fresh=True, probe=probe[:20]))
        except Exception:
            return self._game_running()

    def _not_busy(self, mod_id):
        """A fix edit is refused while a task of that mod waits or runs (it rewrites fixes.json and variants.lua)."""
        if mod_id in self._jobs.active_mod_ids():
            raise jobs.JobFailed(f'Wait for the task of {mod_id} to finish.')

    @api_method
    def rows_editor(self, mod_id):
        v, _paks, _lua = self._fix_ctx(mod_id)
        d = v.describe(mod_id, swatches=False, fixes=False)
        return dict(fixes.editor_model(d, fixes.mod_entry(v.fixes, mod_id)), ok=True)

    @api_method
    def save_rows(self, mod_id, model):
        v, _paks, lua = self._fix_ctx(mod_id)
        if not isinstance(model, dict):
            return {'ok': False, 'error': 'Nothing to save.'}
        self._not_busy(mod_id)
        try:
            keys = fixes.rows_entry(v.describe(mod_id, swatches=False, fixes=False), model)
        except fixes.FixError as e:
            return {'ok': False, 'error': str(e)}

        def change(e):
            for k in fixes.ROW_KEYS:
                e.pop(k, None)
            e.update({k: val for k, val in keys.items() if val})
        fixes.edit(lua, mod_id, change)
        self._bump()
        return {'ok': True}

    def _variant_classes(self, v, mod_id, variant_id):
        if not isinstance(variant_id, str) or not variant_id.startswith(mod_id + '/'):
            raise jobs.JobFailed(f'That option is not part of "{mod_id}".')
        r, regv = assets._variant(v, mod_id, variant_id)
        classes = library.filled(r.get('classes') or (regv or {}).get('classes') or {})
        if not classes:
            raise jobs.JobFailed('This option is not prepared yet.')
        return r, regv, classes

    @api_method
    def texture_choices(self, mod_id, variant_id, material, param=None):
        v, _paks, _lua = self._fix_ctx(mod_id)
        r, regv, classes = self._variant_classes(v, mod_id, variant_id)
        outfit = any(library._cls(c) == 'SkeletalMesh' and library.is_skeletal_leaf(p) for p, c in classes.items())
        sw = v.variant_swatches(r, regv, v.report_dir(mod_id))
        key = f'{material}|{param or "*"}'
        rule = next((x['value'] for x in v.option_rules(mod_id, variant_id) if x['kind'] == 'texture'
                     and x['key'].lower() == key.lower()), None)
        mat = next((p for p in classes if isinstance(material, str) and p.lower() == material.lower()), material)
        return {'ok': True, 'variant': variant_id, 'material': mat, 'param': param or '*', 'current': rule,
                'choices': [im for im in v.option_images(variant_id, classes, sw, outfit)
                            if im.get('path') and library._cls(classes.get(im['path'])) == 'Texture2D']}

    @api_method
    def set_texture_rule(self, mod_id, variant_id, material, param, texture):
        v, _paks, lua = self._fix_ctx(mod_id)
        self._not_busy(mod_id)
        _r, _regv, classes = self._variant_classes(v, mod_id, variant_id)
        if not isinstance(material, str) or not material.startswith('/'):
            return {'ok': False, 'error': 'No material given.'}
        if texture not in (None, 'game'):
            low = {p.lower(): p for p, c in classes.items() if library._cls(c) == 'Texture2D'}
            if not isinstance(texture, str) or texture.lower() not in low:
                return {'ok': False, 'error': 'That texture is not part of this option.'}
            texture = low[texture.lower()]
        fixes.set_rule(lua, mod_id, 'textures', variant_id, f'{material}|{param or "*"}', texture)
        self._bump()
        return {'ok': True}

    @api_method
    def material_choices(self, mod_id, variant_id, mesh, slot):
        v, _paks, _lua = self._fix_ctx(mod_id)
        _r, _regv, classes = self._variant_classes(v, mod_id, variant_id)
        key = f'{mesh}|{slot}'
        rule = next((x['value'] for x in v.option_rules(mod_id, variant_id) if x['kind'] == 'material'
                     and x['key'].lower() == key.lower()), None)
        mats = sorted(p for p, c in classes.items() if library._cls(c) in MATERIAL_CLASSES)
        choices = [{'value': 'body', 'label': "The body's own material", 'sub': 'What the character wore before'},
                   {'value': 'hide', 'label': 'Hidden', 'sub': 'The slot shows nothing'}]
        choices += [{'value': p, 'label': library.leaf(p), 'sub': 'A material of this option'} for p in mats]
        mesh_case = next((p for p in classes if isinstance(mesh, str) and p.lower() == mesh.lower()), mesh)
        return {'ok': True, 'variant': variant_id, 'mesh': mesh_case, 'slot': slot, 'current': rule, 'choices': choices}

    @api_method
    def set_material_rule(self, mod_id, variant_id, mesh, slot, choice):
        v, _paks, lua = self._fix_ctx(mod_id)
        self._not_busy(mod_id)
        _r, _regv, classes = self._variant_classes(v, mod_id, variant_id)
        if choice not in (None, 'body', 'hide'):
            low = {p.lower(): p for p, c in classes.items() if library._cls(c) in MATERIAL_CLASSES}
            if not isinstance(choice, str) or choice.lower() not in low:
                return {'ok': False, 'error': 'That material is not part of this option.'}
            choice = low[choice.lower()]
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'No material slot given.'}
        fixes.set_rule(lua, mod_id, 'materials', variant_id, f'{mesh}|{slot}', choice)
        self._bump()
        return {'ok': True}

    @api_method
    def bundle_plan(self, mod_id, variant_id):
        """What Bundle would copy for the missing files of one option, and from where."""
        v, _paks, _lua = self._fix_ctx(mod_id)
        d = library.mod_details(v, mod_id)
        opts = {o['id']: o for r in d['rows'] for o in r['options']}
        o = opts.get(variant_id)
        if not o:
            return {'ok': False, 'error': 'That option is not part of this mod.'}
        sources = []
        for m in o.get('missing') or []:
            for src in m.get('found_in') or []:
                pkg = src['package']
                if any(s['package'].lower() == pkg.lower() for s in sources):
                    continue
                files = assets.bundle_files(v, src['mod'], src['option'], pkg)
                into = [f"{r['label']} · {x['label']}" for r in d['rows'] for x in r['options']
                        if any(pkg.lower() in (n.lower() for n in mm.get('names') or []) for mm in x.get('missing') or [])]
                sources.append(dict(src, files=files, into=into))
        if not sources:
            return {'ok': False, 'error': 'No other mod in the library has the missing files of this option.'}
        return {'ok': True, 'variant': variant_id, 'sources': sources}

    @api_method
    def bundle(self, mod_id, from_mod, from_option, packages):
        v, _paks, _lua = self._fix_ctx(mod_id)
        if self._known(from_mod, v) is None or not v.folder(from_mod):
            return {'ok': False, 'error': f'The folder of "{from_mod}" is missing from the library.'}
        if not isinstance(packages, list) or not packages or not all(isinstance(p, str) and p.startswith('/') for p in packages):
            return {'ok': False, 'error': 'Nothing to bundle.'}
        if self._game_running_strict():
            return {'ok': False, 'error': 'Close the game first.'}
        self._not_busy(mod_id)
        jid = self._jobs.bundle(mod_id, {'from_mod': from_mod, 'from_option': from_option, 'packages': packages})
        return {'ok': True, 'jobs': [jid]}

    @api_method
    def undo_fix(self, mod_id, ref):
        _v, _paks, lua = self._fix_ctx(mod_id, prepared=False)
        if not isinstance(ref, dict):
            return {'ok': False, 'error': 'Unknown fix.'}
        self._not_busy(mod_id)
        if ref.get('kind') == 'bundle':                     # removing a bundle needs the mod prepared again
            return {'ok': True, 'jobs': [self._jobs.bundle(mod_id, {'remove': ref.get('id')})]}
        try:
            fixes.undo(lua, mod_id, ref)
        except fixes.FixError as e:
            return {'ok': False, 'error': str(e)}
        self._bump()
        return {'ok': True, 'jobs': []}

    @api_method
    def undo_all_fixes(self, mod_id):
        _v, _paks, lua = self._fix_ctx(mod_id, prepared=False)
        self._not_busy(mod_id)
        e = fixes.mod_entry(fixes.load(lua), mod_id)
        bundles = [b.get('id') for b in e.get('bundles') or []]

        def change(x):
            for k in fixes.ROW_KEYS + ('textures', 'materials'):
                x.pop(k, None)
        fixes.edit(lua, mod_id, change)
        jobs_out = [self._jobs.bundle(mod_id, {'remove': b}) for b in bundles]
        self._bump()
        return {'ok': True, 'jobs': jobs_out}

    # ------------------------------------------------------------------ check & repair, compare

    @api_method
    def check_mods(self):
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        res = repair.check(self._view(), self._lua_dir())
        return dict(res, ok=True)

    @api_method
    def repair(self, problem_ids):
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        if self._game_running_strict():
            return {'ok': False, 'error': 'Close the game first.'}
        found = {p['id']: p for p in repair.check(self._view(), self._lua_dir())['problems']}
        want = [found[i] for i in (problem_ids or []) if i in found and found[i].get('action')]
        jobs_out, menu, by_mod, whole, moved, errors = [], False, {}, set(), [], []
        for p in want:
            a = p['action']
            if a['kind'] in ('move_back', 'move_out'):
                r = fixes.tool().set_disabled(self._game['paks'], self._lua_dir(), a['mod'], a['kind'] == 'move_out') or {}
                (moved if r.get('ok', True) else errors).append(a['mod'] if r.get('ok', True) else f"{a['mod']}: {r.get('error')}")
            elif a['kind'] == 'menu':
                menu = True
            elif a['kind'] == 'mod':
                whole.add(a['mod'])
            else:
                by_mod.setdefault(a['mod'], []).extend(a['rels'])
        if menu:
            jobs.write_menu(self._lua_dir()) if fixes.available() else self._rewrite_menu()
        for mod in sorted(whole):
            jobs_out += self.reinstall_mod(mod).get('jobs', [])
        for mod, rels in sorted(by_mod.items()):
            if mod not in whole:
                jobs_out.append(self._jobs.reinstall(mod, only=sorted(set(rels))))
        self._bump()
        return {'ok': True, 'jobs': jobs_out, 'menu': menu, 'moved': moved, 'errors': errors}

    @api_method
    def reconcile(self):
        """At app start: put prepared folders on the right side of Disable (an interrupted move, or
        files moved by hand). {ok, moved: [mods], errors: [sentences]}"""
        if not self._game or not self._lua_dir() or not fixes.available():
            return {'ok': True, 'moved': [], 'errors': []}
        probs = repair.misplaced(self._view())
        if not probs:
            return {'ok': True, 'moved': [], 'errors': []}
        if self._game_running_strict():
            return {'ok': True, 'moved': [], 'errors': ['The game runs: prepared files on the wrong side of Disable '
                                                        'are left for Check & repair.']}
        r = self.repair([p['id'] for p in probs])
        return {'ok': True, 'moved': r.get('moved', []), 'errors': r.get('errors', [])}

    def _rewrite_menu(self):
        lua = self._lua_dir()
        reg = paths.read_json(os.path.join(lua, 'wardrobe_registry.json'), [])
        paths.tools()['relocate'].write_variants_lua(os.path.join(lua, 'Scripts', 'variants.lua'),
                                                     reg if isinstance(reg, list) else [])

    @api_method
    def compare_mods(self, a, b):
        if not self._game:
            return {'ok': False, 'error': NO_GAME}
        v = self._view()
        out = []
        for mid in (a, b):
            if self._known(mid, v) is None:
                return {'ok': False, 'error': f'There is no mod named "{mid}".'}
            d = v.describe(mid, swatches=False)
            src = library.source_of(mid) or {}
            files = src.get('files') or []
            versions, times = [], []
            for f in files:
                n = archives.parse_nexus_name(os.path.splitext(f)[0])
                if n:
                    versions.append(n[2].replace('-', '.'))
                    times.append(n[3])
            folder = v.folder(mid)
            added = src.get('added')
            if not added and folder:
                added = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(folder)))
            out.append({'id': mid, 'files': files, 'version': max(versions, key=_ver_key) if versions else None,
                        'uploaded': time.strftime('%Y-%m-%d', time.localtime(max(times))) if times else None,
                        'added': added, 'options': d['options'], 'rows': len(d['rows']), 'size': d['size'],
                        'state': d['state']})
        mine, theirs = v.shared_files(v.by_name.get(a) or {'name': a}), v.shared_files(v.by_name.get(b) or {'name': b})
        shared = sorted({mine[k] for k in set(mine) & set(theirs)}, key=str.lower)
        return {'ok': True, 'mods': out, 'shared': shared}

    # ------------------------------------------------------------------ find the problem mod

    def _switch(self, mod, on):
        g = self._game or {}
        try:
            r = fixes.tool().set_disabled(g.get('paks'), self._lua_dir(), mod, not on) or {'ok': True}  # on: back in the game
        except Exception as e:
            r = {'ok': False, 'error': str(e)}
        if not r.get('ok', True):
            raise culprit.CulpritError(f"Couldn't turn {mod} {'on' if on else 'off'}: {r.get('error')}")

    def _is_off(self, mod):
        return mod in fixes.disabled_mods(fixes.load(self._lua_dir()))

    @api_method
    def culprit(self, action, value=None):
        """action: status | start | answer (value: true = still happens) | finish (value: keep the found mod off)
        | forget (turn back on what it can, then end it anyway)."""
        if action == 'status':
            return dict(culprit.status(), ok=True)
        v, _paks, _lua = self._fix_ctx()
        if self._game_running_strict():
            return {'ok': False, 'error': 'Close the game first, then answer.'}
        if self._jobs.busy():
            return {'ok': False, 'error': 'Wait for the tasks to finish.'}
        try:
            if action == 'start':
                mods = [m['name'] for m in v.registry]
                res = culprit.start(mods, sorted(v.disabled), self._switch, self._is_off)
            elif action == 'answer':
                res = culprit.answer(bool(value), self._switch, self._is_off)
            elif action in ('finish', 'forget'):
                res = culprit.finish(bool(value) and action == 'finish', self._switch, known={m['name'] for m in v.registry},
                                     forget=action == 'forget')
                if res['errors']:
                    self._bump()
                    return dict(res, ok=action == 'forget', error=' '.join(res['errors'])
                                + ('' if action == 'forget' else ' Close the game or the program using those files, '
                                   'then try again, or use Forget.'))
            else:
                return {'ok': False, 'error': 'Unknown action.'}
        except culprit.CulpritError as e:
            self._bump()
            return {'ok': False, 'error': str(e)}
        self._bump()
        return dict(res, ok=True)

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
                if fixes.available():
                    fixes.tool().write_menu(lua)            # with fixes.json: disabled mods stay out
                else:
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
                snap = self._monitor.snapshot()
            except Exception:
                _log_error('monitor.snapshot', traceback.format_exc())
            else:
                self._add_repair_fixes(snap)
                return snap
        return {'watching': False, 'game_running': self._game_running(), 'since': None, 'menu_active': False,
                'last_activity': None, 'ended': None, 'date': None, 'problems': [], 'on_screen': [], 'tail': []}

    def _add_repair_fixes(self, snap):
        """A "couldn't load <prepared path>" problem gets fix {kind: repair, mod, variant}: the path
        belongs to that option's prepared files."""
        probs = [p for p in snap.get('problems') or [] if not p.get('fix') and str(p.get('key', '')).startswith('load:')]
        if not probs or not self._lua_dir():
            return
        reg_path = os.path.join(self._lua_dir(), 'wardrobe_registry.json')
        try:
            key = os.path.getmtime(reg_path)
        except OSError:
            return
        if getattr(self, '_new_paths', (None,))[0] != key:
            index = {}
            for m in paths.read_json(reg_path, []) or []:
                for sl in (m or {}).get('slots', []) if isinstance(m, dict) else []:
                    for v in sl.get('variants', []):
                        for new in (v.get('map') or {}).values():
                            index[str(new).lower()] = (m['name'], v['id'])
            self._new_paths = (key, index)
        index = self._new_paths[1]
        for p in probs:
            for ln in p.get('lines') or []:
                hit = next((index[x.lower()] for x in re.findall(r'(/Game/[^\s.]+)', ln) if x.lower() in index), None)
                if hit:
                    p['fix'] = {'kind': 'repair', 'mod': hit[0], 'variant': hit[1]}
                    break

    @api_method
    def repair_option(self, mod_id, variant_id):
        """Prepare one option again (the Game log's Repair button)."""
        v, _paks, _lua = self._fix_ctx(mod_id)
        if not v.folder(mod_id):
            return {'ok': False, 'error': f'The folder of "{mod_id}" is missing from the library.'}
        if not isinstance(variant_id, str) or not variant_id.startswith(mod_id + '/'):
            return {'ok': False, 'error': 'That option is not part of this mod.'}
        if self._game_running():
            return {'ok': False, 'error': 'Close the game first.'}
        rel = variant_id.split('/', 1)[1]
        return {'ok': True, 'jobs': [self._jobs.reinstall(mod_id, only=[rel])]}

    _LOG_FILES = {'last': ('live_log.txt', True), 'previous': ('live_log_previous.txt', False), 'ue4ss': (None, True)}

    @api_method
    def monitor_file(self, which, known=None):
        """The logs of a game that has ended, read once through the monitor's rules. which: 'last'
        (live_log.txt and UE4SS.log), 'previous' (live_log_previous.txt) or 'ue4ss' (UE4SS.log).
        known: the version the page already has; then only {unchanged, version} comes back."""
        if which not in self._LOG_FILES:
            return {'ok': False, 'error': 'Unknown log.'}
        from . import monitor as mon
        g = self._game or {}
        menu, ue = self._lua_dir(), paths.ue4ss_dir(g.get('root')) if g.get('root') else None
        live_name, with_ue = self._LOG_FILES[which]
        live = os.path.join(menu, live_name) if (menu and live_name) else None
        uel = os.path.join(ue, 'UE4SS.log') if (ue and with_ue) else None
        files = [f for f in (live, uel) if f]
        key = (which, tuple((f, *self._stat(f)) for f in files))
        version = hashlib.sha1(repr(key).encode('utf-8')).hexdigest()[:16]
        if known and known == version:
            return {'ok': True, 'unchanged': True, 'version': version, 'which': which}
        hit = getattr(self, '_file_cache', {}).get(which)
        if hit and hit[0] == key:
            res = hit[1]
        else:
            res = mon.analyse(live=live, ue=uel, menu_dir=menu)
            if which == 'ue4ss':
                res['tail'] = res['ue_tail']
            res.pop('ue_tail', None)
            res['files'] = [f for f in files if os.path.isfile(f)]
            self._file_cache = dict(getattr(self, '_file_cache', {}), **{which: (key, res)})
        return dict(res, which=which, exists=bool(res['files']), version=version)

    @staticmethod
    def _stat(f):
        try:
            st = os.stat(f)
            return st.st_size, st.st_mtime_ns
        except OSError:
            return None, None

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
