"""Reading a mod's files on demand, for the Mods tab:

  texture_preview(view, mod_id, ref, max_px)   a bigger picture of one texture for the image viewer
  missing_names(view, option_dir, unresolved)  the names of files that links point to but that are
                                               in neither the game nor the mod

Both use retoc, as the relocator does, and only read: the texture comes from the option's
prepared pak (Paks\\~mods\\_E33Wardrobe\\<mod>), decoded by tools/e33tex.py; the names come from
the option's own paks in the library. A zen package keeps the names of the packages it imports;
retoc drops the ones it can't find (it writes /Engine/UnknownPackage), so the relocator's report
only has a count.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading

from . import paths

NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
MAX_PX = 2048                   # largest preview side (a 2048 px PNG is a few MB as a data URL)
CACHE_FILES = 200               # previews kept in the app data folder
_LOCK = threading.Lock()        # one retoc run at a time (decoding runs outside it)


def _t():
    return paths.tools()


def _leaf(p):
    return (p or '').rstrip('/').rsplit('/', 1)[-1]


def _ci_get(d, key):
    """dict lookup ignoring case (package paths are case-insensitive)."""
    if not d or not key:
        return None
    if key in d:
        return d[key]
    low = key.lower()
    for k, v in d.items():
        if k.lower() == low:
            return v
    return None


def _run(cmd, timeout=120):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=timeout)
    if p.returncode != 0:
        last = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()]
        raise RuntimeError(f'retoc {cmd[1]} failed: {last[-1] if last else "no output"}')
    return p.stdout + p.stderr


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


class _WorkDir:
    """A fresh folder next to Paks (same drive, so the game's files can be hard-linked), named
    like the relocator's work folders so an interrupted one is cleaned up by its next run. A .lock
    kept open while in use stops that cleanup from deleting it (on Windows)."""

    def __init__(self, paks):
        parent = os.path.dirname(os.path.normpath(paks)) if paks else None
        try:
            self.path = tempfile.mkdtemp(prefix='_e33wardrobe_work_', dir=parent)
        except OSError:
            self.path = tempfile.mkdtemp(prefix='_e33wardrobe_work_')
        self._lock = open(os.path.join(self.path, '.lock'), 'w')

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        try:
            self._lock.close()
        except OSError:
            pass
        shutil.rmtree(self.path, ignore_errors=True)


# ------------------------------------------------------------------------------ texture previews

def _cache_dir():
    d = os.path.join(paths.app_data_dir(), 'previews')
    os.makedirs(d, exist_ok=True)
    return d


def _prune_cache(d):
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith('.png')]
        if len(files) <= CACHE_FILES:
            return
        files.sort(key=lambda f: os.path.getmtime(f))
        for f in files[:len(files) - CACHE_FILES]:
            for x in (f, f[:-4] + '.json'):
                try:
                    os.remove(x)
                except OSError:
                    pass
    except OSError:
        pass


def _data_url(png):
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def _header(tex_mod, base):
    """(width, height, format) of an extracted texture from its header, also when the full parse
    fails (the relocator's texture_info only records sizes when it succeeds)."""
    try:
        t = tex_mod.parse_texture(base)
        fmt = t['vt']['layer_types'][0] if t['vt'] and not t['mips'] else t['format']
        return t['width'], t['height'], fmt
    except Exception:
        pass
    try:
        return tex_mod.texture_header(base)
    except Exception:
        return 0, 0, ''


def _variant(view, mod_id, vid):
    """(report entry, registry variant) of one option."""
    r = view.report(mod_id).get(vid) or {}
    regv = None
    for s in (view.by_name.get(mod_id) or {}).get('slots', []):
        for v in s.get('variants', []):
            if v.get('id') == vid:
                regv = v
    return r, regv


def texture_preview(view, mod_id, ref, max_px=1024):
    """A bigger picture of one texture of a mod. ref: an image's ref from ModDetails
    ('<variant id>|<texture package>', or '<variant id>|#<n>' for a swatch without a known texture).
    -> {ok, url, width, height (of the picture), tex_width, tex_height, format, name, path,
        source: 'texture' | 'swatch', note}"""
    if not isinstance(ref, str) or '|' not in ref:
        return {'ok': False, 'error': 'No image given.'}
    try:
        max_px = max(64, min(MAX_PX, int(max_px or 1024)))
    except (TypeError, ValueError):
        max_px = 1024
    vid, _, pkg = ref.partition('|')
    if not vid.startswith(mod_id + '/') and vid != mod_id:
        return {'ok': False, 'error': f'That image is not part of "{mod_id}".'}
    r, regv = _variant(view, mod_id, vid)
    if not r and not regv:
        return {'ok': False, 'error': 'This option is not prepared yet. Install the mod first.'}
    classes = r.get('classes') or (regv or {}).get('classes') or {}
    sw = view.variant_swatches(r, regv, view.report_dir(mod_id))
    if pkg.startswith('#'):
        try:
            n = int(pkg[1:])
            if n < 0:
                raise IndexError
            p = sw[n][0]
        except (ValueError, IndexError):
            return {'ok': False, 'error': 'That swatch is gone. Refresh (F5).'}
        return _swatch_result(p, {'name': os.path.basename(p), 'path': ''},
                              "Only this small swatch is saved; the option doesn't say which texture it shows.")
    c = _ci_get(classes, pkg)
    if c is None or not str(c.get('class') or '').startswith('Texture'):
        return {'ok': False, 'error': 'That is not a texture of this option.'}
    info = {'name': _leaf(pkg), 'path': pkg, 'tex_width': int(c.get('width') or 0),
            'tex_height': int(c.get('height') or 0), 'format': re.sub(r'^PF_', '', c.get('format') or '')}
    swatch = next((p for p, tex in sw if tex and tex.lower() == pkg.lower()), None)
    out = view.resolve_output(r.get('output') or r.get('kept_previous') or (regv or {}).get('output'))
    new = _ci_get(r.get('map') or (regv or {}).get('map') or {}, pkg) or pkg
    if not out:
        return _swatch_result(swatch, info, "This option's prepared files are missing. Reinstall the mod.")
    retoc = paths.find_retoc()
    if not retoc:
        return _swatch_result(swatch, info, "retoc is missing, so the texture can't be read. Reinstall the app.")
    try:
        st = os.stat(out)
    except OSError:
        return _swatch_result(swatch, info, "This option's prepared files are missing. Reinstall the mod.")
    key = hashlib.sha1(f'{os.path.normcase(os.path.abspath(out))}|{st.st_size}|{st.st_mtime_ns}|{new.lower()}|'
                       f'{max_px}|2'.encode('utf-8')).hexdigest()
    cache = _cache_dir()
    png_p, meta_p = os.path.join(cache, key + '.png'), os.path.join(cache, key + '.json')
    if os.path.isfile(png_p) and os.path.isfile(meta_p):
        try:
            with open(meta_p, encoding='utf-8') as f:
                meta = json.load(f)
            with open(png_p, 'rb') as f:
                png = f.read()
            os.utime(png_p)
            return dict(meta, ok=True, url=_data_url(png))
        except (OSError, ValueError):
            pass
    tex = _t()['tex']
    import e33legacy                # on the path once tools() ran
    rel = e33legacy.package_to_rel(new)
    paks = view.paks
    try:
        with _WorkDir(paks) as work:
            comp, legacy = os.path.join(work, 'c'), os.path.join(work, 'l')
            os.makedirs(comp)
            for n in ('global.utoc', 'global.ucas'):
                g = os.path.join(paks or '', n)
                if os.path.isfile(g):
                    _link_or_copy(g, os.path.join(comp, n))
            stem = os.path.splitext(out)[0]
            for ext in ('.utoc', '.ucas', '.pak'):
                if os.path.isfile(stem + ext):
                    _link_or_copy(stem + ext, os.path.join(comp, os.path.basename(stem) + ext))
            with _LOCK:
                _run([retoc, 'to-legacy', comp, legacy, '--no-shaders', '--no-script-objects', '--filter', rel + '.'])
            base = os.path.join(legacy, *rel.split('/'))
            if not os.path.isfile(base + '.uexp'):
                return _swatch_result(swatch, info, "retoc didn't give this texture back from the prepared pak.")
            w0, h0, fmt = _header(tex, base)
            info.update(tex_width=w0 or info['tex_width'], tex_height=h0 or info['tex_height'],
                        format=re.sub(r'^PF_', '', fmt or '') or info['format'])
            try:
                _fmt, w, h, px = tex.decode_texture(base, max_px)
            except Exception as e:
                return _swatch_result(swatch, info, f"This texture couldn't be decoded ({e}).")
    except Exception as e:
        return _swatch_result(swatch, info, f"The texture couldn't be read ({e}).")
    if max(w, h) > max_px:
        w, h, px = tex.downscale(w, h, px, max_px)
    png = tex.png_bytes(w, h, px, level=6)
    tw, th = info['tex_width'] or w, info['tex_height'] or h
    note = '' if (w, h) == (tw, th) else f'Shown at {w} x {h}, a smaller copy (mip) of the {tw} x {th} texture.'
    meta = dict(info, width=w, height=h, tex_width=tw, tex_height=th, source='texture', note=note, max_px=max_px)
    try:
        with open(png_p + '.tmp', 'wb') as f:
            f.write(png)
        os.replace(png_p + '.tmp', png_p)
        with open(meta_p, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        _prune_cache(cache)
    except OSError:
        pass
    return dict(meta, ok=True, url=_data_url(png))


def _swatch_result(swatch_path, info, why):
    """The small swatch instead of the texture, with the reason; ok false when there is none."""
    png = None
    if swatch_path:
        try:
            with open(swatch_path, 'rb') as f:
                png = f.read()
        except OSError:
            png = None
    if not png or not png.startswith(b'\x89PNG'):
        return dict(info, ok=False, error=why)
    w, h = struct.unpack_from('>II', png, 16)
    return dict(info, ok=True, url=_data_url(png), width=w, height=h, source='swatch',
                tex_width=info.get('tex_width') or 0, tex_height=info.get('tex_height') or 0,
                format=info.get('format') or '', note=f'{why} Showing the {w} px swatch instead.')


# ------------------------------------------------------------------------------ names of missing files

_NAMES = {}                     # (utoc, size, mtime, package) -> [imported package names]
_GAME = {}                      # paks folder -> (key, set of lower-case game packages)


def zen_imported_packages(buf):
    """Names of the packages a zen package (cooked UE5.3+) imports: the ImportedPackageNames
    name batch, whose offset is the last field of FZenPackageSummary. [] when absent or unreadable."""
    try:
        header_size = struct.unpack_from('<I', buf, 4)[0]
        off = struct.unpack_from('<i', buf, 0x30)[0]
        if not 0x34 <= off < min(len(buf), header_size or len(buf)):
            return []
        count = struct.unpack_from('<I', buf, off)[0]
        if count == 0 or count > 100000:
            return []
        nbytes, hash_version = struct.unpack_from('<IQ', buf, off + 4)
        end = off + 16 + 10 * count + nbytes
        if hash_version != 0xC1640000 or end > len(buf) or (header_size and end > header_size):
            return []
        p = off + 16 + 8 * count
        headers = [struct.unpack_from('>H', buf, p + 2 * i)[0] for i in range(count)]
        p += 2 * count
        start, out = p, []
        for h in headers:
            wide, n = bool(h & 0x8000), h & 0x7FFF
            if wide:
                if (p - start) % 2:
                    p += 1
                s = buf[p:p + 2 * n].decode('utf-16-le', 'replace')
                p += 2 * n
            else:
                s = buf[p:p + n].decode('latin-1')
                p += n
            out.append(s)
        if p - start > nbytes:
            return []
        return [s for s in out if re.fullmatch(r'/[\w./ -]+', s)]
    except (struct.error, ValueError):
        return []


def _game_packages(paks):
    """Lower-case package paths of the game's own containers (as the relocator picks them: Paks\\*.utoc,
    not ~mods and not loose *_P mods). None when they can't be read."""
    try:
        names = sorted(f for f in _t()['relocate'].game_container_files(paks) if f.lower().endswith('.utoc'))
        key = tuple((n, os.path.getsize(os.path.join(paks, n))) for n in names)
    except OSError:
        return None
    hit = _GAME.get(paks)
    if hit and hit[0] == key:
        return hit[1]
    U = _t()['utoc']
    pk = set()
    for n in names:
        try:
            pk.update(p.lower() for p in U.packages_in(os.path.join(paks, n))[0])
        except Exception:
            continue
    if not pk:
        return None
    _GAME[paks] = (key, pk)
    return pk


def missing_names(view, mod_dir, option_dir, unresolved, cache=None):
    """{package: [missing package paths]} for the packages of one option with unresolved links
    ({package: count}). A name counts as missing when neither the game's containers nor any of the
    mod's paks list it (what the relocator checked). Packages that can't be read are left out.
    cache: a dict kept for one describe() (the mod's own packages are listed once)."""
    retoc = paths.find_retoc()
    if not retoc or not unresolved or not option_dir or not view.paks:
        return {}
    U = _t()['utoc']
    from . import library
    cache = cache if cache is not None else {}
    own = cache.get('own')
    if own is None:
        own = cache['own'] = set()
        for dp, ds, fs in os.walk(paths.lp(mod_dir)):
            ds[:] = [d for d in ds if not d.startswith('.')]
            for f in fs:
                if f.lower().endswith('.utoc'):
                    own.update(p.lower() for p in library.packages_of(os.path.join(dp, f)))
    found = {}
    want = {p.lower(): p for p in unresolved}
    game = None
    for u in library.utocs_in(option_dir):
        try:
            info = U.read_utoc(paths.lp(u))
            st = os.stat(paths.lp(u))
        except Exception:
            continue
        for rel, chunk in zip(info['files'], info.get('chunks') or []):
            g = U.game_path(info['mount_point'], rel)
            if not g or g.lower() not in want or not chunk:
                continue
            pkg = want[g.lower()]
            key = (os.path.normcase(u), st.st_size, int(st.st_mtime), pkg.lower())
            if key not in _NAMES:
                try:
                    with _WorkDir(view.paks) as work:
                        dst = os.path.join(work, 'chunk.bin')
                        with _LOCK:
                            _run([retoc, 'get', u, chunk, dst], timeout=30)
                        with open(dst, 'rb') as f:
                            _NAMES[key] = zen_imported_packages(f.read())
                except Exception:           # not cached: retoc may work next time
                    continue
            imported = _NAMES[key]
            if not imported:
                continue
            if game is None:
                game = _game_packages(view.paks)
                if not game:                # without the game's list every import would look missing
                    return {}
            miss = [n for n in imported if not n.lower().startswith('/script/') and n.lower() not in own
                    and n.lower() not in game]
            if miss:
                found[pkg] = sorted(set(miss), key=str.lower)
    return found
