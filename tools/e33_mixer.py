#!/usr/bin/env python3
"""E33 Mod Mixer - keep variant mods in a library and switch combinations without hand-copying.

  python e33_mixer.py gui                 # browser UI on http://127.0.0.1:47333
  python e33_mixer.py scan                # list library mods and their choices
  python e33_mixer.py apply               # write the current selection into ~mods
  python e33_mixer.py preset save NAME | load NAME | list | delete NAME
  python e33_mixer.py set MOD CHOICE=VALUE ... [enabled=1] [priority=NN]
  python e33_mixer.py off                 # remove everything the mixer placed in ~mods

Only files inside ~mods/_E33Mixer/ are ever created or deleted (that folder belongs to the
mixer). Mods you installed by hand are left alone. Changes take effect the next time the game
starts (paks mount at launch), and the mixer refuses to touch paks while the game runs.
"""
import sys

if sys.version_info < (3, 8):
    sys.exit('E33 Mod Mixer needs Python 3.8 or newer (python.org).')

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import struct  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e33common  # noqa: E402
import e33previews  # noqa: E402
import e33rules  # noqa: E402
import e33utoc  # noqa: E402
from e33rules import lp  # noqa: E402

MANAGED_DIR = '_E33Mixer'
MANIFEST = '.e33mixer_manifest.json'
GAME_EXES = e33common.GAME_EXES
STEAM_APPID = '1903340'
CONFIG_PATH = os.path.join(HERE, 'e33mixer_config.json')
DEFAULT_PORT = 47333
DEFAULT_PRIORITY = 50
WARNINGS = []                 # problems found while loading files, shown in the UI


# ----------------------------------------------------------------------------- small helpers

def read_json(path, default):
    """Load JSON; a corrupt file is kept aside as <name>.corrupt-<time> and `default` returned."""
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        bad = f'{path}.corrupt-{time.strftime("%Y%m%d-%H%M%S")}'
        try:
            os.replace(path, bad)
        except OSError:
            pass
        WARNINGS.append(f'{os.path.basename(path)} was damaged ({e}); kept as {os.path.basename(bad)} and started fresh.')
        return default


def write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def retry(fn, tries=3, wait=0.4):
    """Retry briefly: antivirus / indexers lock fresh files for a moment."""
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(wait)


def pak_priority(stem):
    """UE pak priority from the file name: '_<N>_P' -> 100*(N+1), '_P' -> 100, else 0."""
    m = re.search(r'_(\d+)_P$', stem, re.IGNORECASE)
    if m:
        return 100 * (int(m.group(1)) + 1)
    return 100 if stem.lower().endswith('_p') else 0


def winner(entries):
    """entries: [(label, path_from_Paks)] -> label that UE mounts last (wins). Higher pak priority
    wins; on a tie the alphabetically smallest path wins (it is mounted last)."""
    def key(e):
        stem = os.path.splitext(os.path.basename(e[1]))[0]
        return (-pak_priority(stem), e[1].lower())
    return sorted(entries, key=key)[0][0]


def is_link(path):
    """Symlink or Windows junction (any reparse point)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if os.path.islink(path):
        return True
    return bool(getattr(st, 'st_file_attributes', 0) & 0x400)     # FILE_ATTRIBUTE_REPARSE_POINT


def container_id(utoc):
    try:
        with open(lp(utoc), 'rb') as f:
            head = f.read(64)
        if head[:16] == e33utoc.TOC_MAGIC:
            return struct.unpack_from('<Q', head, 56)[0]
    except OSError:
        pass
    return None


# ----------------------------------------------------------------------------- config & discovery

_steam_libraries = e33common.steam_libraries   # shared with the relocator
detect_paks_dir = e33common.detect_paks_dir


def load_config():
    cfg = read_json(CONFIG_PATH, {})
    if not cfg.get('paks_dir'):
        cfg['paks_dir'] = detect_paks_dir()
    if not cfg.get('library') and cfg.get('paks_dir'):
        cfg['library'] = os.path.join(os.path.dirname(cfg['paks_dir']), 'Paks_ModLibrary')
    cfg.setdefault('rules_dirs', [os.path.join(HERE, 'rules')])
    return cfg


def save_config(cfg):
    write_json(CONFIG_PATH, {k: v for k, v in cfg.items()
                             if k != 'rules_dirs' or v != [os.path.join(HERE, 'rules')]})


# ----------------------------------------------------------------------------- game detection

def game_running(fresh=False, probe=()):
    """True if E33 is running (see e33common.game_running)."""
    return e33common.game_running(fresh, probe, lp)


# ----------------------------------------------------------------------------- state

class Mixer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.RLock()
        self.library = cfg.get('library')
        self.paks_dir = cfg.get('paks_dir')
        self.state_path = os.path.join(self.library, '.e33mixer_state.json') if self.library else None
        self.state = {'mods': {}, 'presets': {}}
        if self.state_path:
            loaded = read_json(self.state_path, {})
            if isinstance(loaded, dict):
                self.state.update(loaded)
        self.mods = {}
        self.previews = e33previews.PreviewStore(self.library)
        self.swatch_job = e33previews.SwatchJob()
        self.shots = []                 # latest screenshot paths, indexed by the UI
        self.rescan()

    @property
    def mods_dir(self):
        return os.path.join(self.paks_dir, '~mods') if self.paks_dir else None

    @property
    def target(self):
        return os.path.join(self.mods_dir, MANAGED_DIR) if self.mods_dir else None

    def save(self):
        if self.state_path:
            os.makedirs(self.library, exist_ok=True)
            write_json(self.state_path, self.state)

    def rescan(self):
        with self.lock:
            self.mods = {}
            if not self.library or not os.path.isdir(self.library):
                return
            for name in sorted(os.listdir(self.library), key=str.lower):
                root = os.path.join(self.library, name)
                if name.startswith('.') or not os.path.isdir(root):
                    continue
                try:
                    mod = e33rules.Mod(root, self.cfg['rules_dirs'], name=name)
                    if mod.folders():
                        self.mods[name] = mod
                except Exception as e:      # one odd folder must not hide the others
                    WARNINGS.append(f'{name}: {e}')

    def mod_state(self, name):
        st = self.state['mods'].setdefault(name, {'enabled': False, 'choices': {}})
        st.setdefault('priority', DEFAULT_PRIORITY)
        return st

    def folder_for(self, name):
        safe = ''.join(c if c.isalnum() or c in ' -_.()' else '_' for c in name).strip() or 'mod'
        prio = max(0, min(99, int(self.mod_state(name).get('priority', DEFAULT_PRIORITY))))
        return f'{prio:02d} {safe}'

    # ------------------------------------------------------------------ resolution & checks

    def resolve_all(self):
        out = {}
        for name, mod in self.mods.items():
            st = self.mod_state(name)
            try:
                res = mod.resolve(st['choices'])
                st['choices'] = dict((k, v) for k, v in res['env'].items()
                                     if k not in mod.rules.get('flags', {}))
            except Exception as e:      # a broken rules file or odd folder must not break other mods
                res = {'choices': [], 'env': dict(st['choices']), 'paks': [], 'files': [],
                       'messages': [{'level': 'error', 'text': f'Rules error: {type(e).__name__}: {e}'}]}
            out[name] = res
        self._cross_checks(out)
        return out

    def loose_paks(self):
        """Pak/utoc files installed by hand anywhere under Paks except the base game and _E33Mixer."""
        found = []
        if not self.paks_dir or not os.path.isdir(self.paks_dir):
            return found
        for dirpath, dirs, files in os.walk(lp(self.paks_dir)):
            dirs[:] = [d for d in dirs if d != MANAGED_DIR and not d.startswith('_e33wardrobe_work')]
            if os.path.normcase(dirpath) == os.path.normcase(lp(self.paks_dir)):
                continue                                         # base game containers
            for f in files:
                if f.lower().endswith(('.pak', '.utoc')):
                    found.append(os.path.join(dirpath, f))
        return found

    def _cross_checks(self, resolved):
        """Conflicts between enabled mods and hand-installed paks: same asset overridden twice
        (and which one wins in game), duplicate file names, duplicate container IDs."""
        paks_root = lp(self.paks_dir) if self.paks_dir else ''
        owners = {}                     # package -> [(label, path_from_Paks, mixer_mod or None)]
        utocs = []                      # (label, path, mixer_mod or None)
        for name, res in resolved.items():
            if not self.mod_state(name)['enabled']:
                continue
            folder = f'~mods/{MANAGED_DIR}/{self.folder_for(name)}'
            for src, fn in res['files']:
                if fn.lower().endswith('.utoc'):
                    utocs.append((f'{name} ({fn})', src, f'{folder}/{fn}', name))
        for f in self.loose_paks():
            if f.lower().endswith('.utoc'):
                rel = os.path.relpath(f, paks_root).replace(os.sep, '/') if paks_root else f
                utocs.append((f'{rel} (installed by hand)', f, rel, None))
        ids = {}
        for label, path, rel, mod in utocs:
            try:
                pkgs, _ = e33utoc.packages_in(lp(path))
            except Exception as e:      # truncated/odd .utoc: warn, don't fail the page
                if mod:
                    resolved[mod]['messages'].append({'level': 'warn', 'text': f'Could not read {os.path.basename(path)}: {e}'})
                continue
            for p in pkgs:
                owners.setdefault(p, []).append((label, rel, mod))
            cid = container_id(path)
            if cid:
                ids.setdefault(cid, []).append((label, rel, mod))
        pair_assets = {}
        for p, o in owners.items():
            if len(o) > 1 and any(m for _, _, m in o):
                key = tuple(sorted({(lbl, rel, m) for lbl, rel, m in o}))
                pair_assets.setdefault(key, []).append(p)
        for key, assets in pair_assets.items():
            win = winner([(lbl, rel) for lbl, rel, _ in key])
            who = ', '.join(lbl for lbl, _, _ in key)
            for _, _, m in key:
                if m:
                    resolved[m]['messages'].append({'level': 'warn', 'text':
                        f'{len(assets)} asset(s) are changed by several paks ({who}), e.g. {assets[0]}. '
                        f'In game "{win}" wins; change a mod\'s priority to choose.'})
        for cid, o in ids.items():
            if len({rel for _, rel, _ in o}) > 1:
                for lbl, rel, m in o:
                    if m:
                        others = ', '.join(l for l, r2, _ in o if r2 != rel)
                        resolved[m]['messages'].append({'level': 'warn', 'text':
                            f'{lbl} has the same container ID as {others} - Unreal may mount only one of them.'})
        names = {}
        for name, res in resolved.items():
            if self.mod_state(name)['enabled']:
                for _src, fn in res['files']:
                    names.setdefault(fn.lower(), set()).add(name)
        for fn, mods in names.items():
            if len(mods) > 1:
                for m in mods:
                    resolved[m]['messages'].append({'level': 'error',
                                                    'text': f'File name {fn} is used by several enabled mods.'})

    def loose_duplicates(self, resolved):
        wanted = {fn.lower() for name, r in resolved.items() for _s, fn in r['files']}
        root = lp(self.paks_dir) if self.paks_dir else ''
        return sorted(os.path.relpath(f, root) for f in self.loose_paks() if os.path.basename(f).lower() in wanted)

    # ------------------------------------------------------------------ apply

    def plan(self, resolved):
        desired, problems = {}, []
        for name, res in resolved.items():
            if not self.mod_state(name)['enabled']:
                continue
            errs = [m['text'] for m in res['messages'] if m['level'] == 'error']
            if errs:
                problems.append(f'{name}: ' + '; '.join(errs))
                continue
            for src, fn in res['files']:
                desired[f'{self.folder_for(name)}/{fn}'] = src
        return desired, problems

    def installed(self):
        """Files actually present in ~mods/_E33Mixer (everything there belongs to the mixer).
        Symlinks and junctions are never followed, so nothing outside the folder is touched."""
        out = set()
        t = self.target
        if not t or not os.path.isdir(lp(t)) or is_link(lp(t)):
            return out
        for dirpath, dirs, files in os.walk(lp(t)):
            dirs[:] = [d for d in dirs if not is_link(os.path.join(dirpath, d))]
            for f in files:
                if f == MANIFEST or f.endswith('.tmp'):
                    continue
                out.add(os.path.relpath(os.path.join(dirpath, f), lp(t)).replace(os.sep, '/'))
        return out

    def _sig(self, src):
        st = os.stat(lp(src))
        # Same-named files from different variants often share size and timestamp, so the
        # source path is part of the signature.
        return [os.path.normcase(os.path.abspath(src)), st.st_size, int(st.st_mtime)]

    def _up_to_date(self, rel, src, on_disk, old):
        """The installed file `rel` is the current version of `src` (same rule for the page
        and for Apply: a mod updated in the library with the same file names is not current)."""
        if rel not in on_disk:
            return False
        try:
            dst = lp(os.path.join(self.target, *rel.split('/')))
            return old.get(rel, {}).get('sig') == self._sig(src) and os.path.getsize(dst) == os.stat(lp(src)).st_size
        except OSError:
            return False

    def pending(self, desired, on_disk):
        if sorted(desired) != sorted(on_disk):
            return True
        old = read_json(lp(os.path.join(self.target, MANIFEST)), {}).get('files', {})
        return not all(self._up_to_date(rel, src, set(on_disk), old) for rel, src in desired.items())

    def apply(self):
        with self.lock:
            if not self.mods_dir:
                raise RuntimeError('Game Paks folder not set. Use: e33_mixer.py --paks "<...\\Content\\Paks>" config --save')
            if not e33common.is_paks_dir(self.paks_dir):
                return {'ok': False, 'log': [], 'errors': [f'{self.paks_dir} is not the game\'s Paks folder (no global.utoc '
                                                           'in it). Set it with: e33_mixer.py --paks "<game>\\Sandfall\\'
                                                           'Content\\Paks" config --save']}
            target = self.target
            on_disk = self.installed()
            probe = [os.path.join(target, r) for r in on_disk if r.lower().endswith('.ucas')][:20]
            if game_running(fresh=True, probe=probe):
                return {'ok': False, 'log': [], 'errors': ['The game is running. Close it first: paks are locked '
                                                           'while it runs and a half-swapped mod can crash it.']}
            resolved = self.resolve_all()
            desired, problems = self.plan(resolved)
            if problems:
                return {'ok': False, 'log': [], 'errors': problems}
            os.makedirs(lp(target), exist_ok=True)
            man_path = os.path.join(target, MANIFEST)
            old = read_json(lp(man_path), {}).get('files', {})
            log, errors, new_manifest = [], [], {}
            for dirpath, dirs, files in os.walk(lp(target)):
                dirs[:] = [d for d in dirs if not is_link(os.path.join(dirpath, d))]
                for f in files:
                    if f.endswith('.tmp') and f != MANIFEST:
                        try:
                            os.remove(os.path.join(dirpath, f))
                        except OSError:
                            pass
            try:
                for rel in sorted(on_disk - set(desired)):
                    p = lp(os.path.join(target, *rel.split('/')))
                    try:
                        retry(lambda: os.remove(p))
                        log.append(f'removed {rel}')
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        errors.append(f'cannot remove {rel}: {e}')
                        new_manifest[rel] = old.get(rel, {'src': None, 'sig': None})
                for rel, src in sorted(desired.items()):
                    dst = lp(os.path.join(target, *rel.split('/')))
                    try:
                        sig = self._sig(src)
                        if self._up_to_date(rel, src, on_disk, old):
                            new_manifest[rel] = old[rel]
                            continue
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if os.path.exists(dst):
                            retry(lambda: os.remove(dst))
                        try:
                            os.link(lp(src), dst)
                            how = 'linked'
                        except OSError:
                            # another drive: copy next to it, then rename, so a killed copy never
                            # leaves a truncated pak under the real name
                            tmp = dst + '.tmp'
                            retry(lambda: shutil.copy2(lp(src), tmp))
                            retry(lambda: os.replace(tmp, dst))
                            how = 'copied'
                        new_manifest[rel] = {'src': src, 'sig': sig}
                        log.append(f'{how} {rel}')
                    except OSError as e:
                        errors.append(f'cannot place {rel}: {e}')
                        if os.path.exists(dst):
                            new_manifest[rel] = {'src': None, 'sig': None}   # unknown content: replace next time
                for dirpath, _dirs, _files in os.walk(lp(target), topdown=False, followlinks=False):
                    if os.path.normcase(dirpath) != os.path.normcase(lp(target)):
                        try:
                            if not os.listdir(dirpath):
                                os.rmdir(dirpath)
                        except OSError:
                            pass                                 # Explorer/antivirus holding it: harmless
            finally:
                try:
                    write_json(lp(man_path), {'written': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': new_manifest})
                except OSError as e:
                    errors.append(f'cannot write manifest: {e}')
                self.save()
            return {'ok': not errors, 'log': log, 'errors': errors, 'game_running': False,
                    'installed': sorted(new_manifest)}

    def off(self):
        with self.lock:
            for st in self.state['mods'].values():
                st['enabled'] = False
            return self.apply()

    # ------------------------------------------------------------------ presets

    def preset_save(self, name):
        with self.lock:
            self.resolve_all()
            self.state['presets'][name] = json.loads(json.dumps(self.state['mods']))
            self.save()

    def preset_load(self, name):
        with self.lock:
            if name not in self.state['presets']:
                raise KeyError(f'no preset named {name!r}')
            saved = self.state['presets'][name]
            for mod in list(self.state['mods']):
                if mod not in saved:
                    self.state['mods'][mod]['enabled'] = False
            for mod, st in saved.items():
                self.state['mods'][mod] = json.loads(json.dumps(st))
            self.save()

    def preset_delete(self, name):
        with self.lock:
            self.state['presets'].pop(name, None)
            self.save()

    # ------------------------------------------------------------------ previews

    def list_shots(self):
        dirs = e33previews.screenshot_dirs(self.cfg.get('screenshot_dirs', []), _steam_libraries())
        self.shots = e33previews.latest_screenshots(dirs)
        return {'dirs': dirs, 'shots': [{'id': i, 'name': os.path.basename(p),
                                         'time': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(p)))}
                                        for i, p in enumerate(self.shots)]}

    def save_look(self, name, image):
        with self.lock:
            if name not in self.mods:
                raise KeyError(name)
            res = self.resolve_all()[name]
            choices = {k: v for k, v in res['env'].items() if k not in self.mods[name].rules.get('flags', {})}
            return self.previews.save_look(name, image, choices, res['paks'])

    def apply_look(self, name, lid):
        with self.lock:
            lk = next((x for x in self.previews.mod(name)['looks'] if x['id'] == lid), None)
            if not lk:
                raise KeyError(lid)
            self.mod_state(name)['choices'].update(lk['choices'])
            self.save()

    def start_swatches(self, name, force=False):
        mod = self.mods[name]
        self.swatch_job.start(self.previews, mod, mod.folders(), self.paks_dir,
                              e33previews.find_retoc(self.cfg.get('retoc')), force)

    def _previews_for(self, name, res):
        """Look for the current combination, swatches of the installed folders, and a small
        preview per option button (its own swatch, or the best-matching screenshot)."""
        store, mod = self.previews, self.mods[name]
        looks = store.mod(name)['looks']
        flags = mod.rules.get('flags', {})
        cur = {k: v for k, v in res['env'].items() if k not in flags}
        look, exact = store.best_look(looks, cur)
        per_option = {}
        for ch in res['choices']:
            if not ch['visible'] or len(ch['options']) < 2:
                continue
            paks_by_value = {}
            for opt in ch['options']:
                try:
                    paks_by_value[opt['value']] = set(mod.resolve({**cur, ch['id']: opt['value']})['paks'])
                except Exception:
                    paks_by_value[opt['value']] = set()
            common = set.intersection(*paks_by_value.values()) if paks_by_value else set()
            for opt in ch['options']:
                sw = None
                for rel in sorted(paks_by_value[opt['value']] - common):
                    imgs = store.swatches_for(name, rel)
                    if imgs:
                        sw = imgs[0]['file']
                        break
                lk, _ = store.best_look(looks, cur, require={ch['id']: opt['value']})
                if sw or lk:
                    per_option.setdefault(ch['id'], {})[opt['value']] = {'swatch': sw, 'look': lk['file'] if lk else None}
        return {'looks': looks, 'look': look['file'] if look else None, 'look_exact': exact,
                'look_id': look['id'] if look else None,
                'swatches': [{'folder': rel, 'images': store.swatches_for(name, rel)} for rel in res['paks']
                             if store.swatches_for(name, rel)],
                'per_option': per_option,
                'swatched': len(store.mod(name)['swatches'])}

    # ------------------------------------------------------------------ view

    def view(self):
        with self.lock:
            resolved = self.resolve_all()
            mods = []
            for name, res in resolved.items():
                st = self.mod_state(name)
                rules = self.mods[name].rules
                mods.append({'name': name, 'enabled': st['enabled'], 'priority': st['priority'],
                             'choices': res['choices'], 'paks': res['paks'],
                             'files': [fn for _s, fn in res['files']],
                             'messages': res['messages'], 'rules': rules.get('_source'),
                             'rules_name': rules.get('name'), 'notes': rules.get('notes', ''),
                             'auto': rules.get('auto', False), 'previews': self._previews_for(name, res)})
            on_disk = sorted(self.installed())
            desired, _ = self.plan(resolved)
            warnings = list(WARNINGS)
            if self.paks_dir and not e33common.is_paks_dir(self.paks_dir):
                warnings.append(f'{self.paks_dir} is not the game\'s Paks folder (no global.utoc in it); '
                                'Apply is refused until it is set right.')
            return {'library': self.library, 'paks_dir': self.paks_dir, 'mods_dir': self.mods_dir,
                    'mods': mods, 'presets': sorted(self.state['presets']), 'installed': on_disk,
                    'pending': self.pending(desired, on_disk), 'loose_duplicates': self.loose_duplicates(resolved),
                    'game_running': game_running(), 'warnings': warnings, 'version': e33common.VERSION,
                    'swatch_job': dict(self.swatch_job.state),
                    'retoc_found': bool(e33previews.find_retoc(self.cfg.get('retoc')))}


# ----------------------------------------------------------------------------- web UI

PAGE = open(os.path.join(HERE, 'e33_mixer_ui.html'), encoding='utf-8').read() \
    if os.path.isfile(os.path.join(HERE, 'e33_mixer_ui.html')) else '<h1>e33_mixer_ui.html missing</h1>'


def _ctype(path):
    return {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.bmp': 'image/bmp',
            '.webp': 'image/webp'}.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')


def make_handler(mixer, token, allowed_hosts):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            return (self.headers.get('Host') or '').lower() in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {'error': 'bad host'})
            try:
                if self.path in ('/', '/index.html') or self.path.startswith('/?'):
                    return self._send(200, PAGE.replace('__TOKEN__', token).encode(), 'text/html; charset=utf-8')
                if self.path == '/api/state':
                    return self._send(200, mixer.view())
                if self.path.startswith('/previews/'):
                    p = mixer.previews.file_path(self.path[len('/previews/'):].split('?')[0])
                    if p:
                        return self._send(200, open(p, 'rb').read(), _ctype(p))
                    return self._send(404, {'error': 'not found'})
                if self.path == '/api/shots':
                    return self._send(200, mixer.list_shots())
                if self.path.startswith('/api/shot?id='):
                    try:
                        p = mixer.shots[int(self.path.split('=', 1)[1])]
                    except (ValueError, IndexError):
                        return self._send(404, {'error': 'not found'})
                    return self._send(200, open(p, 'rb').read(), _ctype(p))
                self._send(404, {'error': 'not found'})
            except Exception as e:      # show the problem in the page instead of a dead request
                self._send(500, {'error': f'{type(e).__name__}: {e}'})

        def do_POST(self):
            if not self._host_ok() or self.headers.get('X-Token') != token:
                return self._send(403, {'error': 'bad token'})
            try:
                n = int(self.headers.get('Content-Length') or 0)
                if n > 8 * 1024 * 1024:
                    return self._send(413, {'error': 'request too large'})
                body = json.loads(self.rfile.read(n) or b'{}')
                r = self.route(self.path, body)
                self._send(200, r if r is not None else mixer.view())
            except Exception as e:      # surface any failure in the UI instead of a dead request
                self._send(400, {'error': f'{type(e).__name__}: {e}'})

        def route(self, path, b):
            if path == '/api/select':
                with mixer.lock:
                    st = mixer.mod_state(b['mod'])
                    if 'enabled' in b:
                        st['enabled'] = bool(b['enabled'])
                    if 'choice' in b:
                        st['choices'][b['choice']] = b['value']
                    if 'priority' in b:
                        st['priority'] = max(0, min(99, int(b['priority'])))
                    mixer.save()
                return None
            if path == '/api/apply':
                return {'apply': mixer.apply(), **mixer.view()}
            if path == '/api/off':
                return {'apply': mixer.off(), **mixer.view()}
            if path == '/api/rescan':
                mixer.rescan()
                return None
            if path == '/api/preset/save':
                mixer.preset_save(b['name'].strip())
                return None
            if path == '/api/preset/load':
                mixer.preset_load(b['name'])
                return None
            if path == '/api/preset/delete':
                mixer.preset_delete(b['name'])
                return None
            if path == '/api/look/save':
                mixer.save_look(b['mod'], b['image'])
                return None
            if path == '/api/look/delete':
                mixer.previews.delete_look(b['mod'], b['id'])
                return None
            if path == '/api/look/apply':
                mixer.apply_look(b['mod'], b['id'])
                return None
            if path == '/api/swatches':
                mixer.start_swatches(b['mod'], bool(b.get('force')))
                return None
            if path == '/api/open':
                target = {'library': mixer.library, 'mods': mixer.mods_dir}.get(b.get('what'))
                if target and os.path.isdir(target) and sys.platform == 'win32':
                    os.startfile(target)
                return {'ok': True}
            raise KeyError(path)
    return H


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port already in use (two mixers on
    # one port answer at random); there, bind exclusively so the fallback port is used.
    allow_reuse_address = sys.platform != 'win32'

    def server_bind(self):
        if sys.platform == 'win32':
            import socket
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, getattr(socket, 'SO_EXCLUSIVEADDRUSE', -5), 1)
            except OSError:
                pass
        super().server_bind()


def run_gui(mixer, port, open_browser=True):
    import secrets
    token = secrets.token_hex(16)
    hosts = set()
    try:
        srv = _Server(('127.0.0.1', port), make_handler(mixer, token, hosts))
    except OSError:
        srv = _Server(('127.0.0.1', 0), make_handler(mixer, token, hosts))
    real_port = srv.server_address[1]
    hosts.update({f'127.0.0.1:{real_port}', f'localhost:{real_port}'})
    url = f'http://127.0.0.1:{real_port}/'
    print(f'E33 Mod Mixer {e33common.VERSION} running at {url}  (close this window to quit)')
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return srv


# ----------------------------------------------------------------------------- CLI

def print_scan(mixer):
    v = mixer.view()
    print(f'Library : {v["library"]}\n~mods   : {v["mods_dir"]}\n')
    for w in v['warnings']:
        print('WARNING:', w)
    if not v['mods']:
        print('No mods in the library yet. Extract each mod archive into its own folder there.')
    for m in v['mods']:
        print(f'[{"x" if m["enabled"] else " "}] {m["name"]}   priority {m["priority"]}   rules: {m["rules_name"] or "auto"}')
        for c in m['choices']:
            if not c['visible']:
                continue
            opts = ', '.join(o['value'] if '/' not in o['value'] else o['label'] for o in c['options'])
            cur = next((o['label'] for o in c['options'] if o['value'] == c['value']), c['value'])
            print(f'      {c["id"]:<14} = {cur:<22} ({opts})')
        for f in m['paks']:
            print(f'      -> {f}')
        for msg in m['messages']:
            print(f'      {msg["level"].upper()}: {msg["text"]}')
    if v['loose_duplicates']:
        print('\nThese files are also installed by hand under Paks; remove them so they do not clash:')
        for d in v['loose_duplicates']:
            print('   ', d)


def main(argv=None):
    e33common.safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--version', action='version', version=f'E33 Mod Mixer {e33common.VERSION}')
    ap.add_argument('--library', help='folder holding one sub-folder per mod (overrides config)')
    ap.add_argument('--paks', help='game Content\\Paks folder (overrides config)')
    sub = ap.add_subparsers(dest='cmd')
    g = sub.add_parser('gui', help='open the browser UI (the default)')
    g.add_argument('--port', type=int, default=DEFAULT_PORT)
    g.add_argument('--no-browser', action='store_true')
    sub.add_parser('scan', help='list library mods and their choices')
    sw = sub.add_parser('swatches', help='build color swatches for a mod (needs retoc.exe)')
    sw.add_argument('mod')
    sw.add_argument('--force', action='store_true')
    sub.add_parser('apply', help='install the current selection into ~mods')
    sub.add_parser('off', help='remove everything the mixer installed')
    s = sub.add_parser('set', help='change a mod\'s choices, enabled state or priority')
    s.add_argument('mod')
    s.add_argument('pairs', nargs='*', help='CHOICE=VALUE, enabled=1/0 or priority=NN')
    p = sub.add_parser('preset', help='save / load / list / delete presets (load only selects; then apply)')
    p.add_argument('action', choices=['save', 'load', 'list', 'delete'])
    p.add_argument('name', nargs='?')
    c = sub.add_parser('config', help='show, and with --save remember, --library / --paks')
    c.add_argument('--save', action='store_true', help='remember --library/--paks in e33mixer_config.json')
    a = ap.parse_args(argv)

    cfg = load_config()
    if a.library:
        cfg['library'] = a.library
    if a.paks:
        cfg['paks_dir'] = a.paks
    if a.cmd == 'config':
        print(json.dumps({k: cfg.get(k) for k in ('paks_dir', 'library')}, indent=2))
        if a.save and not e33common.is_paks_dir(cfg.get('paks_dir')):
            print(f'Not saved: {cfg.get("paks_dir")} is not the game\'s Paks folder (it has no global.utoc).')
            return 2
        if a.save:
            save_config(cfg)
            print('saved to', CONFIG_PATH)
        return 0
    if not cfg.get('library'):
        print('Could not find the game. Run:  e33_mixer.py --paks "<game>\\Sandfall\\Content\\Paks" config --save')
        return 2
    os.makedirs(cfg['library'], exist_ok=True)
    mixer = Mixer(cfg)
    if a.cmd in (None, 'gui'):
        run_gui(mixer, getattr(a, 'port', DEFAULT_PORT), not getattr(a, 'no_browser', False))
    elif a.cmd == 'scan':
        print_scan(mixer)
    elif a.cmd == 'swatches':
        mod = next((m for m in mixer.mods if m.lower() == a.mod.lower()), None)
        if not mod:
            print('unknown mod; choose from:', ', '.join(mixer.mods))
            return 2
        try:
            mixer.start_swatches(mod, a.force)
        except RuntimeError as e:
            print('ERROR', e)
            return 1
        job = mixer.swatch_job
        while job.state['running']:
            time.sleep(0.5)
            print(f'\r  {job.state["done"]}/{job.state["total"]} {job.state["current"][:60]:<60}', end='', flush=True)
        print()
        for line in job.state['log']:
            print('  ', line)
    elif a.cmd == 'set':
        mod = next((m for m in mixer.mods if m.lower() == a.mod.lower()), None)
        if not mod:
            print('unknown mod; choose from:', ', '.join(mixer.mods))
            return 2
        st = mixer.mod_state(mod)
        for pair in a.pairs:
            k, _, v = pair.partition('=')
            if k == 'enabled':
                st['enabled'] = v.lower() in ('1', 'true', 'yes', 'on')
            elif k == 'priority':
                try:
                    st['priority'] = max(0, min(99, int(v)))
                except ValueError:
                    print(f'priority must be a number 0-99, not {v!r}')
                    return 2
            else:
                st['choices'][k] = v
        mixer.save()
        print_scan(mixer)
    elif a.cmd == 'apply' or a.cmd == 'off':
        r = mixer.apply() if a.cmd == 'apply' else mixer.off()
        for line in r.get('log', []):
            print('  ', line)
        for line in r.get('errors', []):
            print('  ERROR', line)
        print('done' if r['ok'] else 'finished with errors')
        return 0 if r['ok'] else 1
    elif a.cmd == 'preset':
        if a.action == 'list':
            print('\n'.join(sorted(mixer.state['presets'])) or '(no presets)')
        elif not a.name:
            print('preset name required')
            return 2
        elif a.action == 'save':
            mixer.preset_save(a.name)
        elif a.action == 'load':
            if a.name not in mixer.state['presets']:
                print('unknown preset; choose from:', ', '.join(sorted(mixer.state['presets'])) or '(none)')
                return 2
            mixer.preset_load(a.name)
            print_scan(mixer)
            print('\nPreset selected. Run "apply" to install it.')
        else:
            mixer.preset_delete(a.name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
