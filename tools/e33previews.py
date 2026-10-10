"""Outfit previews for the E33 Mod Mixer.

  * Looks: your own in-game screenshots, cropped in the browser and saved together with the
    choices that were selected - shown for the current combination and on option buttons.
  * Swatches: small images of each option's base-color textures, extracted from its pak with
    retoc and decoded by e33tex (no game launch needed).

Everything lives in <library>\\.e33mixer_previews\\ (index.json + image files).
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import e33common
import e33legacy
import e33tex

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
STEAM_APPID = '1903340'
SAFE_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,120}$')
MAX_LOOK_BYTES = 3 * 1024 * 1024


def _key(*parts):
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:16]


class PreviewStore:
    def __init__(self, library):
        self.root = os.path.join(library, '.e33mixer_previews') if library else None
        self.lock = threading.RLock()
        self.index = {}
        if self.root and os.path.isfile(os.path.join(self.root, 'index.json')):
            try:
                with open(os.path.join(self.root, 'index.json'), encoding='utf-8') as f:
                    self.index = json.load(f)
            except (OSError, ValueError):
                self.index = {}

    def _save(self):
        os.makedirs(self.root, exist_ok=True)
        tmp = os.path.join(self.root, 'index.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, indent=1)
        os.replace(tmp, os.path.join(self.root, 'index.json'))

    def mod(self, name):
        return self.index.setdefault(name, {'looks': [], 'swatches': {}})

    def file_path(self, name):
        """Absolute path of a stored image, or None if the name is not a plain file name."""
        if not self.root or not SAFE_NAME.match(name or ''):
            return None
        p = os.path.join(self.root, name)
        return p if os.path.isfile(p) else None

    # ------------------------------------------------------------------ looks

    def save_look(self, mod, data_url, choices, paks):
        m = re.match(r'^data:image/(jpeg|png|webp);base64,(.+)$', data_url or '', re.S)
        if not m:
            raise ValueError('expected a data:image/jpeg|png|webp;base64 URL')
        data = base64.b64decode(m.group(2), validate=False)
        if len(data) > MAX_LOOK_BYTES:
            raise ValueError('image too large')
        if not (data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n' or data[8:12] == b'WEBP'):
            raise ValueError('not an image')
        ext = {'jpeg': '.jpg', 'png': '.png', 'webp': '.webp'}[m.group(1)]
        with self.lock:
            os.makedirs(self.root, exist_ok=True)
            lid = _key(mod, str(time.time()), str(len(data)))
            name = f'look_{lid}{ext}'
            with open(os.path.join(self.root, name), 'wb') as f:
                f.write(data)
            self.mod(mod)['looks'].append({'id': lid, 'file': name, 'choices': dict(choices),
                                           'paks': list(paks), 'created': time.strftime('%Y-%m-%d %H:%M')})
            self._save()
            return lid

    def delete_look(self, mod, lid):
        with self.lock:
            looks = self.mod(mod)['looks']
            for lk in [x for x in looks if x['id'] == lid]:
                looks.remove(lk)
                p = self.file_path(lk['file'])
                if p:
                    os.remove(p)
            self._save()

    @staticmethod
    def best_look(looks, choices, require=None):
        """Look whose stored choices best match `choices` (and satisfy `require`)."""
        best, score = None, -1
        for lk in looks:
            lc = lk.get('choices', {})
            if require and any(lc.get(k) != v for k, v in require.items()):
                continue
            s = sum(1 for k, v in choices.items() if lc.get(k) == v)
            if s > score:
                best, score = lk, s
        exact = best is not None and all(best['choices'].get(k) == v for k, v in choices.items())
        return best, exact

    # ------------------------------------------------------------------ swatches

    def swatches_for(self, mod, rel):
        return self.mod(mod)['swatches'].get(rel, {}).get('images', [])


# ---------------------------------------------------------------------------- screenshots

def screenshot_dirs(extra=(), steam_roots=()):
    dirs = list(extra)
    home = os.path.expanduser('~')
    for root in steam_roots:
        ud = os.path.join(root, 'userdata')
        if os.path.isdir(ud):
            for user in os.listdir(ud):
                dirs.append(os.path.join(ud, user, '760', 'remote', STEAM_APPID, 'screenshots'))
    dirs += [os.path.join(home, 'Videos', 'Captures'),                         # Xbox Game Bar
             os.path.join(home, 'Pictures', 'Screenshots')]                    # Win+PrtScn
    for env in ('OneDrive', 'OneDriveConsumer'):
        if os.environ.get(env):
            dirs.append(os.path.join(os.environ[env], 'Pictures', 'Screenshots'))
    local = os.environ.get('LOCALAPPDATA')
    if local:
        dirs.append(os.path.join(local, 'Sandfall', 'Saved', 'Screenshots'))  # in-game HighResShot
    seen, out = set(), []
    for d in dirs:
        k = os.path.normcase(os.path.abspath(d))
        if k not in seen and os.path.isdir(d):
            seen.add(k)
            out.append(d)
    return out


def latest_screenshots(dirs, limit=16):
    found = []
    for d in dirs:
        for dirpath, subdirs, files in os.walk(d):
            if dirpath.count(os.sep) - d.count(os.sep) >= 2:
                subdirs[:] = []
            subdirs[:] = [s for s in subdirs if s.lower() != 'thumbnails']
            for f in files:
                if f.lower().endswith(IMAGE_EXTS):
                    p = os.path.join(dirpath, f)
                    try:
                        found.append((os.path.getmtime(p), p))
                    except OSError:
                        pass
    found.sort(reverse=True)
    return [p for _t, p in found[:limit]]


# ---------------------------------------------------------------------------- swatch job

def find_retoc(cfg_path=None):
    here = os.path.dirname(os.path.abspath(__file__))
    for c in [cfg_path, os.path.join(here, 'retoc.exe'), os.path.join(here, 'retoc'),
              shutil.which('retoc'), shutil.which('retoc.exe')]:
        if c and os.path.isfile(c):
            return c
    return None


class SwatchJob:
    """Builds swatches for one mod in a background thread; state is polled by the UI."""
    def __init__(self):
        self.state = {'running': False, 'mod': None, 'done': 0, 'total': 0, 'current': '', 'log': []}
        self.thread = None

    def start(self, store, mod, option_folders, paks_dir, retoc, force=False):
        if self.state['running']:
            raise RuntimeError('a swatch job is already running')
        if not retoc:
            raise RuntimeError('retoc.exe not found - put it next to the tools (see docs/INSTALL.md, retoc).')
        if not paks_dir or not os.path.isfile(os.path.join(paks_dir, 'global.utoc')):
            raise RuntimeError('game Paks folder (with global.utoc) not found')
        self.state = {'running': True, 'mod': mod.name, 'done': 0, 'total': len(option_folders),
                      'current': '', 'log': []}
        self.thread = threading.Thread(target=self._run, args=(store, mod, option_folders, paks_dir, retoc, force),
                                       daemon=True)
        self.thread.start()

    def _log(self, msg):
        self.state['log'] = (self.state['log'] + [msg])[-40:]

    def _run(self, store, mod, option_folders, paks_dir, retoc, force):
        work, lock = None, None
        try:
            e33common.clean_stale_work(os.path.dirname(paks_dir))
            work = tempfile.mkdtemp(prefix='_e33mixer_swatch_', dir=os.path.dirname(paks_dir))
            lock = open(os.path.join(work, '.lock'), 'w')      # tells a later cleanup this run is alive
            for rel in option_folders:
                self.state['current'] = rel
                try:
                    n = build_swatches(store, mod, rel, paks_dir, retoc, work, force)
                    self._log(f'{rel}: {n} swatch(es)' if n else f'{rel}: no color texture found')
                except Exception as e:      # keep going with the other options
                    self._log(f'{rel}: {type(e).__name__}: {e}')
                self.state['done'] += 1
        finally:
            if lock:
                lock.close()
            if work:
                shutil.rmtree(work, ignore_errors=True)
            self.state['running'] = False
            self.state['current'] = ''


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build_swatches(store, mod, rel, paks_dir, retoc, work, force=False, max_images=2, size=96):
    """Extract one option's textures and save up to `max_images` base-color swatches."""
    folder = os.path.join(mod.root, *rel.split('/')) if rel else mod.root
    utocs = sorted(f for f in os.listdir(folder) if f.lower().endswith('.utoc'))
    if not utocs:
        return 0
    sig = [[f, os.path.getsize(os.path.join(folder, f)), int(os.path.getmtime(os.path.join(folder, f)))] for f in utocs]
    entry = store.mod(mod.name)['swatches'].get(rel)
    if entry and entry.get('sig') == sig and not force:
        return len(entry.get('images', []))
    comp = os.path.join(work, 'comp')
    out = os.path.join(work, 'legacy')
    for d in (comp, out):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    for ext in ('.utoc', '.ucas'):
        _link_or_copy(os.path.join(paks_dir, 'global' + ext), os.path.join(comp, 'global' + ext))
    for i, u in enumerate(utocs):
        for ext in ('.utoc', '.ucas'):
            src = os.path.join(folder, u[:-5] + ext)
            if os.path.isfile(src):
                _link_or_copy(src, os.path.join(comp, f'zz_opt_{i}_{900 + i}_P' + ext))
    p = subprocess.run([retoc, 'to-legacy', comp, out, '--no-shaders', '--no-script-objects'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       creationflags=0x08000000 if sys.platform == 'win32' else 0)
    if p.returncode != 0:
        last = [l for l in (p.stdout + p.stderr).splitlines() if l.strip()]
        raise RuntimeError(f'retoc failed: {last[-1] if last else ""}')
    candidates = []
    for dirpath, _ds, files in os.walk(out):
        for f in files:
            if not f.endswith('.uasset'):
                continue
            ua = os.path.join(dirpath, f)
            try:
                info = e33legacy.read_package_info(ua)
            except Exception:
                continue
            if not (info['main_class'] or '').startswith('Texture2D'):
                continue
            base = ua[:-7]
            try:
                tex = e33tex.parse_texture(base)
                fmt = tex['vt']['layer_types'][0] if tex['vt'] and not tex['mips'] else tex['format']
            except Exception:
                continue
            score = e33tex.color_score(info['main_name'] or f, fmt)
            if score >= 0:
                candidates.append((-score, f, base, fmt))
    candidates.sort()
    images = []
    for _s, f, base, fmt in candidates[:max_images]:
        try:
            fmt2, w, h, px = e33tex.decode_texture(base, max(size * 2, 128))
            w, h, px = e33tex.downscale(w, h, px, size)
            name = f'swatch_{_key(mod.name, rel, f)}.png'
            os.makedirs(store.root, exist_ok=True)
            with open(os.path.join(store.root, name), 'wb') as fh:
                fh.write(e33tex.png_bytes(w, h, px))
            images.append({'file': name, 'texture': f[:-7], 'format': fmt2})
        except Exception:
            continue
    with store.lock:
        store.mod(mod.name)['swatches'][rel] = {'sig': sig, 'images': images}
        store._save()
    return len(images)
