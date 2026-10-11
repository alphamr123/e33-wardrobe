#!/usr/bin/env python3
"""E33 Relocator - turn replacer variant paks into side-by-side "wardrobe" paks.

Each variant's assets are moved to unique same-length paths, so all variants can be
installed at once without overriding the game. The E33Wardrobe UE4SS Lua mod then puts the
chosen variant on the characters at runtime (in-game menu, keys, console).

  py e33_relocate.py --mod "<library>\\<mod folder>"              (Paks folder saved or found automatically)
  py e33_relocate.py --paks "<game>\\Sandfall\\Content\\Paks" --mod "<library>\\<mod folder>"
  py e33_relocate.py --remove "<mod name>"                       (take a mod out of the wardrobe)

Needs retoc.exe (https://github.com/trumank/retoc) next to this script or on PATH. On first
use retoc may download oo2core_9_win64.dll next to itself (needs internet once).
Nothing in the game folder is modified except:
  * Paks\\~mods\\_E33Wardrobe\\<mod>\\   (new relocated paks)
  * <game>\\Sandfall\\Binaries\\Win64 (or WinGDK)\\ue4ss\\Mods\\E33Wardrobe\\   (Lua mod + variant table)
A temporary work folder is created next to Paks and deleted afterwards (one left by an
interrupted run is removed by the next run).
"""
import sys

if sys.version_info < (3, 8):
    sys.exit('The E33 Wardrobe relocator needs Python 3.8 or newer (python.org).')

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e33common  # noqa: E402
import e33legacy  # noqa: E402
import e33rules  # noqa: E402
import e33tex  # noqa: E402
import e33utoc  # noqa: E402

ENGINE = 'UE5_4'
LUA_TEMPLATE = os.environ.get('E33_LUA_TEMPLATE') or os.path.join(os.path.dirname(HERE), 'lua', 'E33Wardrobe')
TOC_VERSIONS = ['Invalid', 'Initial', 'DirectoryIndex', 'PartitionSize', 'PerfectHash', 'PerfectHashWithOverflow',
                'OnDemandMetaData', 'RemovedOnDemandMetaData', 'ReplaceIoChunkHashWithIoHash']
CHARACTERS = ['Lune', 'Sciel', 'Maelle', 'Verso', 'Monoco', 'Gustave']
BULK_EXTS = ('.ubulk', '.uptnl', '.m.ubulk')
FILTER_CHARS = 20000                  # stay well under the Windows 32k command-line limit
TESTED_RETOC = '0.1.5'                # uses its --no-compres-shaders spelling
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0   # no console flashing up from a windowed app
SWATCHES, SWATCH_PX = 2, 64           # small colour swatches per variant, for the app (<out>/<mod>/swatches)
# Paths on this PC (paks_dir, library, retoc): saved with --save. The Mixer's settings file is read
# when this one doesn't exist yet. E33_CONFIG points the tests elsewhere.
CONFIG_PATH = os.environ.get('E33_CONFIG') or os.path.join(HERE, 'e33wardrobe_config.json')
OLD_CONFIG_PATH = os.path.join(HERE, 'e33mixer_config.json')


def find_retoc(explicit):
    for c in [explicit, os.path.join(HERE, 'retoc.exe'), os.path.join(HERE, 'retoc'),
              shutil.which('retoc'), shutil.which('retoc.exe')]:
        if c and os.path.isfile(c):
            return c
    raise SystemExit('retoc not found. Download it from https://github.com/trumank/retoc/releases '
                     'and put retoc.exe next to e33_relocate.py (or pass --retoc).')


class RetocError(RuntimeError):
    pass


def run(cmd, log):
    log.write('> ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd) + '\n')
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    out = p.stdout + p.stderr
    log.write(out + '\n')
    if p.returncode != 0:
        last = [l for l in out.strip().splitlines() if l.strip()]
        raise RetocError(f'retoc {cmd[1]} failed: {last[-1] if last else "no output"}')
    return out


def link_or_fail(src, dst):
    try:
        os.link(src, dst)
    except OSError as e:
        raise SystemExit(f'Could not hard-link {src}\n  -> {dst}\n  {e}\n'
                         'The work folder must be on the same drive as the game. Use --work to choose one.')


def safe_name(s, maxlen=120):
    """File-name form of a mod / variant name. Spaces and path separators become '_' as before;
    a name with other characters (non-ASCII, brackets, '&'...) or a very long one gets a short
    hash, so two different names never share an output file. ('-' before the hash: UE reads
    '_<digits>_P' as a pak priority.)"""
    t = re.sub(r'[^A-Za-z0-9_-]+', '_', s).strip('_') or 'x'
    if re.search(r'[^A-Za-z0-9 _/\\.-]', s) or len(t) > maxlen:
        t = f"{t[:maxlen]}-{hashlib.sha1(s.encode('utf-8')).hexdigest()[:8]}"
    return t


def variant_stem(vid, taken):
    """Pak name of a variant; unique within a run (`taken`: lower-case stem -> variant id)."""
    base = re.sub(r'_P$', '', safe_name(vid))
    stem = base + '_P'
    if taken.get(stem.lower(), vid) != vid:
        stem = f"{base}-{hashlib.sha1(vid.encode('utf-8')).hexdigest()[:8]}_P"
    taken[stem.lower()] = vid
    return stem


def write_json(path, data):
    """Write through a .tmp file, so an interrupted run never leaves half a file."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def read_config():
    """Saved paths (paks_dir, library, retoc): this tool's settings, else the Mixer's."""
    for path in ([CONFIG_PATH] if os.environ.get('E33_CONFIG') else [CONFIG_PATH, OLD_CONFIG_PATH]):
        try:
            with open(path, encoding='utf-8') as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg
        except (OSError, ValueError):
            pass
    return {}


def save_config(cfg):
    write_json(CONFIG_PATH, {k: v for k, v in cfg.items() if v})
    print('Saved to', CONFIG_PATH)


def default_lua_dir(paks):
    """<game>\\Sandfall\\Binaries\\<Win64 | WinGDK (Game Pass)>\\ue4ss\\Mods\\E33Wardrobe."""
    binaries = os.path.join(os.path.dirname(os.path.dirname(os.path.normpath(paks))), 'Binaries')
    plat = 'Win64'
    if not os.path.isdir(os.path.join(binaries, 'Win64')) and os.path.isdir(os.path.join(binaries, 'WinGDK')):
        plat = 'WinGDK'
    return os.path.join(binaries, plat, 'ue4ss', 'Mods', 'E33Wardrobe')


def install_lua(template, lua_dir):
    """Copy the Lua mod, writing only files that are missing or different. A file is replaced by
    removing it first, so a copy installed by a mod manager as a hard link is never written
    through. The user's config.lua and the generated variants.lua are left alone."""
    keep = {'variants.lua', 'config.lua'}
    changed = 0
    for dp, _ds, fs in os.walk(template):
        rel = os.path.relpath(dp, template)
        for f in fs:
            if f in keep or f.endswith(('.txt', '.json')) and f != 'enabled.txt':
                continue
            src, dst = os.path.join(dp, f), os.path.normpath(os.path.join(lua_dir, rel, f))
            try:
                with open(src, 'rb') as a, open(dst, 'rb') as b:
                    if a.read() == b.read():
                        continue
            except OSError:
                pass
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                os.remove(dst)
            shutil.copy2(src, dst)
            changed += 1
    return changed


def retoc_version(retoc):
    try:
        out = subprocess.run([retoc, '--version'], capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=30, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        m = re.search(r'(\d+\.\d+\.\d+)', out.stdout + out.stderr)
        return m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def character_of(text):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text or '')          # "ScielBodyLight" -> "Sciel Body Light"
    hits = [c for c in CHARACTERS if re.search(rf'(?i)(^|[^a-z]){c}([^a-z]|$)', text)]
    return hits[0] if len(hits) == 1 else None


class ConsoleTee:
    """Everything the relocator prints also goes to <out>\\relocate_console.txt (appended per run),
    so the console output never has to be copied by hand; the in-game report includes it."""
    MAX = 5 * 1024 * 1024

    def __init__(self):
        self.f, self.out, self.err = None, sys.stdout, sys.stderr

    def start(self, path, argv):
        try:
            if os.path.isfile(path) and os.path.getsize(path) > self.MAX:
                os.replace(path, path[:-4] + '_old.txt')
            self.f = open(path, 'a', encoding='utf-8')
        except OSError:
            return
        self.f.write(f'\n===== run {time.strftime("%Y-%m-%d %H:%M:%S")}: e33_relocate.py {e33common.VERSION} '
                     + ' '.join(f'"{x}"' if ' ' in x else x for x in argv) + '\n')
        tee = self

        class _W:
            def __init__(self, base):
                self.base = base

            def write(self, s):
                self.base.write(s)
                if tee.f:
                    tee.f.write(s)
                return len(s)

            def flush(self):
                self.base.flush()
                if tee.f:
                    tee.f.flush()

            def __getattr__(self, k):
                return getattr(self.base, k)
        sys.stdout, sys.stderr = _W(self.out), _W(self.err)

    def file_only(self, text):
        if self.f:
            self.f.write(text + '\n')

    def stop(self):
        sys.stdout, sys.stderr = self.out, self.err
        if self.f:
            self.f.close()
            self.f = None


class RunLog:
    """The retoc/command log. Each mod gets its own relocate_log.txt in its output folder (so
    relocating another mod no longer replaces it); lines written before the first mod (game
    linking) are repeated at the top of every mod's log."""
    def __init__(self):
        self.header, self.f = [], None

    def write(self, s):
        if self.f:
            self.f.write(s)
        else:
            self.header.append(s)

    def start(self, path):
        self.close()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, 'w', encoding='utf-8')
        self.f.write(''.join(self.header))

    def close(self):
        if self.f:
            self.f.close()
            self.f = None


def option_slots(mod_root):
    """Group option folders into wardrobe slots by their parent folder name (e.g. 'Lune outfit').

    Folders not inside a group (like '_only Lune mod_fix_P') become their own on/off slot.
    """
    opts = e33rules.find_option_folders(mod_root)
    by_parent = {}
    for rel in opts:
        parent = rel.rsplit('/', 1)[0] if '/' in rel else ''
        by_parent.setdefault(parent, []).append(rel)
    slots = {}
    for parent, kids in by_parent.items():
        grouped = len([k for k in kids if not os.path.basename(k).startswith('_')]) >= 2
        for rel in kids:
            base = os.path.basename(rel)
            if grouped and not base.startswith('_'):
                key = os.path.basename(parent) or 'Variants'
                prefix = os.path.dirname(parent)
            else:
                key = base or 'Main'
                prefix = parent
            label = ((os.path.basename(prefix) + ': ' if prefix else '') + e33rules.pretty(base)) or 'on'   # one-option mod
            slots.setdefault(key, []).append({'rel': rel, 'label': label})
    return slots


# ------------------------------------------------------------------------------ game containers

def game_container_files(paks):
    """Base-game .utoc/.ucas at the top of Paks (not ~mods). Mod-looking containers dropped
    straight into Paks ('*_P' not named global/pakchunk*) are left out of the composite."""
    out = []
    for f in os.listdir(paks):
        stem, ext = os.path.splitext(f)
        if ext.lower() not in ('.utoc', '.ucas'):
            continue
        if stem.lower().endswith('_p') and not re.match(r'(?i)^(global|pakchunk\d+)', stem):
            continue
        out.append(f)
    return out


def game_packages(game_links):
    pk = set()
    for f in os.listdir(game_links):
        if f.lower().endswith('.utoc') and not f.lower().startswith('zz'):
            try:
                pkgs, info = e33utoc.packages_in(os.path.join(game_links, f))
                pk.update(p.lower() for p in pkgs)
            except Exception:       # encrypted or unreadable container: can't classify its packages
                pass
    return pk


def toc_version(utoc):
    with open(utoc, 'rb') as f:
        head = f.read(17)
    return head[16] if len(head) == 17 else None


class VersionMismatch(Exception):
    pass


def add_to_composite(src_utoc, game_links, name, game_version):
    """Copy a mod container into the composite folder under `name` (priority via its suffix).
    retoc refuses to mix container versions, and a pak built for another engine version
    can't be read as UE5.4 anyway, so such paks are rejected."""
    v = toc_version(src_utoc)
    if game_version is not None and v is not None and v != game_version:
        tv = TOC_VERSIONS[v] if v < len(TOC_VERSIONS) else v
        gv = TOC_VERSIONS[game_version] if game_version < len(TOC_VERSIONS) else game_version
        raise VersionMismatch(f'{os.path.basename(src_utoc)} is container version {tv}, the game uses {gv} '
                              '(built for a different Unreal version?)')
    copied = []
    for ext in ('.utoc', '.ucas'):
        s = src_utoc[:-5] + ext
        if os.path.isfile(s):
            d = os.path.join(game_links, name + ext)
            try:
                os.link(s, d)
            except OSError:
                shutil.copy2(s, d)  # library on another drive
            copied.append(d)
    return copied


def publish(retoc, legacy_dir, work, out_dir, stem, log):
    """retoc to-zen into the work folder, then move the finished triplet into place, so a failed
    run never leaves a half-written container in ~mods."""
    stage = os.path.join(work, 'stage')
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run([retoc, 'to-zen', '--version', ENGINE, legacy_dir, os.path.join(stage, stem + '.utoc')], log)
    os.makedirs(out_dir, exist_ok=True)
    for ext in ('.pak', '.utoc', '.ucas'):
        src = os.path.join(stage, stem + ext)
        if os.path.isfile(src):
            os.replace(src, os.path.join(out_dir, stem + ext))
    return os.path.join(out_dir, stem + '.utoc')


def build_shared(retoc, game_links, mod_root, work, out_dir, mod_name, ctx, log):
    """One pak with every mod-only package of the mod (paths the game doesn't have) at its
    original path, extracted from all of the mod's containers at once - independent of
    --only and of variants that failed. References between options (an outfit mesh using a
    color/common pak's material) resolve through it; it overrides nothing in the game."""
    own, cand, flat = set(), set(), set()
    for dp, _ds, fs in os.walk(mod_root):
        for f in fs:
            if f.lower().endswith('.utoc'):
                try:
                    p0 = os.path.join(dp, f)
                    pk, fl, ow, _info = index_entries(ctx.get('fixed', {}).get(os.path.normcase(p0), p0))
                except Exception:
                    continue
                own |= ow
                flat |= fl
                cand.update(p for p in pk if p.lower() not in ctx['game_pkgs'] and not p.lower().startswith('/game/mods/'))
    if not cand and not flat:
        return None, []
    legacy = os.path.join(work, 'shared_legacy')
    shutil.rmtree(legacy, ignore_errors=True)
    os.makedirs(legacy)
    extract(retoc, game_links, legacy, cand, flat, log)
    prune_bulk(legacy, own)
    at_root = {}
    found = normalize_legacy(legacy, at_root)
    flat_low = {f.lower() for f in flat}
    flat_names = {n.lower() for st, n in at_root.items() if st in flat_low}
    mod_only = {k for k in found if k not in ctx['game_pkgs'] and not k.startswith('/game/mods/')
                and (k in {c.lower() for c in cand} or k in flat_names)}
    keep_only(legacy, mod_only)
    if not mod_only:
        return None, []
    out = publish(retoc, legacy, work, out_dir, safe_name(mod_name) + '_Shared_P', log)
    return out, sorted(mod_only)


# ------------------------------------------------------------------------------ one variant

def _package_files(root, pkg):
    """Legacy files (.uasset/.uexp/.ubulk/...) that belong to package `pkg` under root."""
    base = os.path.join(root, *e33legacy.package_to_rel(pkg).split('/'))
    d, stem = os.path.dirname(base), os.path.basename(base).lower()
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in os.listdir(d) if f.lower().split('.', 1)[0] == stem]


def _split_ext(path):
    low = path.lower()
    for ext in ('.m.ubulk',) + tuple(e for e in ('.uasset', '.umap', '.uexp', '.ubulk', '.uptnl', '.utoc', '.ucas', '.pak')):
        if low.endswith(ext):
            return path[:-len(ext)], ext
    return os.path.splitext(path)


def index_entries(utoc):
    """From a container's file index: (/Game packages, flat stems, own files as {(stem, ext)}, info).

    Some packers write a *flat* index ('BP_X.uasset' with no Content folder). The game finds
    packages by an ID hashed from the real name, so such paks work in game, but their real
    package names are only known after extraction (see normalize_legacy)."""
    pk, info = e33utoc.packages_in(utoc)
    flat, own = set(), set()
    for f in info['files']:
        stem, ext = _split_ext((info['mount_point'] + f).replace('\\', '/'))
        own.add((os.path.basename(stem).lower(), ext.lower()))
        g = e33utoc.game_path(info['mount_point'], f)
        if g and not g.startswith('/Game/') and g.count('/') == 1:
            flat.add(os.path.basename(stem))
    return [p for p in pk if p.startswith('/Game/')], flat, own, info


def extract(retoc, game_links, out, packages, flat, log):
    """retoc to-legacy from the composite for these /Game packages and flat-indexed stems."""
    filters = [e33legacy.package_to_rel(p) + '.' for p in sorted(set(packages))]
    filters += ['/' + st + '.' for st in sorted(flat)]
    batch, size = [], 0
    for f in filters:
        batch += ['--filter', f]
        size += len(f) + 12
        if size > FILTER_CHARS:
            run([retoc, 'to-legacy', game_links, out, '--no-shaders', '--no-script-objects'] + batch, log)
            batch, size = [], 0
    if batch:
        run([retoc, 'to-legacy', game_links, out, '--no-shaders', '--no-script-objects'] + batch, log)


def prune_bulk(root, own, notes=None):
    """retoc looks bulk data up across the whole composite: drop payload files that the mod's own
    containers don't list (by file stem, so flat-indexed paks keep theirs)."""
    for dp, _ds, fs in os.walk(root):
        for f in fs:
            stem, ext = _split_ext(f)
            if ext.lower() in BULK_EXTS and (stem.lower(), ext.lower()) not in own:
                os.remove(os.path.join(dp, f))
                if notes is not None:
                    notes.append(f'dropped base-game bulk file {f}')


def normalize_legacy(root, from_root=None):
    """Move every extracted package to the folder its real name gives (flat chunk paths land at
    the output root). Returns {lower-case real package name: real name}; names of packages that
    were at the root are added to `from_root` (a dict stem -> name) when given."""
    found, moves = {}, []
    for dp, _ds, fs in os.walk(root):
        for f in fs:
            stem, ext = _split_ext(f)
            if ext.lower() not in ('.uasset', '.umap'):
                continue
            try:
                with open(os.path.join(dp, f), 'rb') as fh:
                    name = e33legacy.read_summary(fh.read())['package_name']
            except Exception:
                continue
            if not name.startswith('/Game/'):
                continue
            if not e33legacy.safe_package(name):         # a crafted name must not leave the work folder
                print(f'  note: skipped a package with an invalid name: {name[:120]!r}')
                continue
            found[name.lower()] = name
            if from_root is not None and os.path.normcase(dp) == os.path.normcase(root):
                from_root[stem.lower()] = name
            want = os.path.join(root, *e33legacy.package_to_rel(name).split('/'))
            have = os.path.join(dp, stem)
            if os.path.normcase(have) != os.path.normcase(want):
                for g in os.listdir(dp):
                    if _split_ext(g)[0].lower() == stem.lower():
                        moves.append((os.path.join(dp, g), want + _split_ext(g)[1]))
    for src, dst in moves:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
    return found


def repair_flat(retoc, game_links, utoc, work, log):
    """Return a copy of `utoc` whose file index has real folders, or `utoc` itself if its index
    is fine. Real names come from the packages (extracted against global.utoc only); the index is
    rewritten with retoc unpack-raw / pack-raw. Package IDs and data are unchanged."""
    _pk, flat, _own, info = index_entries(utoc)
    if not flat:
        return utoc, {}
    tag = safe_name(os.path.basename(utoc)[:-5]) + '_' + hashlib.sha1(utoc.encode('utf-8')).hexdigest()[:8]
    comp, out = os.path.join(work, 'fixA_' + tag), os.path.join(work, 'fixA_out_' + tag)
    for d in (comp, out):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    for ext in ('.utoc', '.ucas'):
        try:
            os.link(os.path.join(game_links, 'global' + ext), os.path.join(comp, 'global' + ext))
        except OSError:
            shutil.copy2(os.path.join(game_links, 'global' + ext), os.path.join(comp, 'global' + ext))
        shutil.copy2(utoc[:-5] + ext, os.path.join(comp, 'zz_fix_999_P' + ext))
    args = []
    for st in sorted(flat):
        args += ['--filter', '/' + st + '.']
    run([retoc, 'to-legacy', comp, out, '--no-shaders', '--no-script-objects'] + args, log)
    names = {}
    normalize_legacy(out, names)                       # stem -> real name for root-level files
    shutil.rmtree(comp, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    if not names:
        return utoc, {}
    raw = os.path.join(work, 'fixRaw_' + tag)
    shutil.rmtree(raw, ignore_errors=True)
    run([retoc, 'unpack-raw', utoc, raw], log)
    man_path = os.path.join(raw, 'manifest.json')
    with open(man_path, encoding='utf-8') as f:
        man = json.load(f)
    fixed = 0
    for cid, path in list(man.get('chunk_paths', {}).items()):
        if not path:
            continue
        rel = path.replace('\\', '/')
        while rel.startswith('../'):
            rel = rel[3:]
        stem, ext = _split_ext(rel)
        if '/' not in stem and stem.lower() in names:
            man['chunk_paths'][cid] = '../../../' + e33legacy.package_to_rel(names[stem.lower()]) + ext
            fixed += 1
    with open(man_path, 'w', encoding='utf-8') as f:
        json.dump(man, f)
    dst_dir = os.path.join(work, 'fixed_' + tag)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(utoc))
    run([retoc, 'pack-raw', raw, dst], log)
    shutil.rmtree(raw, ignore_errors=True)
    log.write(f'repaired flat index of {utoc}: {fixed} chunk path(s)\n')
    return dst, names


def keep_only(root, keep):
    """Delete extracted packages that aren't in `keep` (lower-case names), so a broad filter
    can never pack a base-game asset into a variant at its original path."""
    for dp, _ds, fs in os.walk(root):
        for f in fs:
            stem, ext = _split_ext(f)
            info = e33legacy.rel_to_package(os.path.relpath(os.path.join(dp, stem + '.uasset'), root))
            if info and info[0].lower() not in keep and ext.lower() in ('.uasset', '.umap', '.uexp') + BULK_EXTS:
                os.remove(os.path.join(dp, f))


def _shader_chunk(variant_id, taken):
    n = 40000 + int(hashlib.sha256(variant_id.encode()).hexdigest(), 16) % 20000
    while n in taken:
        n += 1
    taken.add(n)
    return n


def texture_info(base, entry, candidates):
    """Record an extracted texture's size and pixel format in its classes entry, and list it as a
    swatch candidate if it looks like a base-colour texture. Never fails (header reads only)."""
    try:
        tex = e33tex.parse_texture(base)
        fmt = tex['vt']['layer_types'][0] if tex['vt'] and not tex['mips'] else tex['format']
        entry.update(width=tex['width'], height=tex['height'], format=fmt)
        score = e33tex.color_score(entry.get('object') or os.path.basename(base), fmt)
        if score >= 0:
            candidates.append((-score, base))
    except Exception:
        pass


def write_swatches(candidates, packages_by_base, out_dir, stem):
    """Up to SWATCHES small PNGs (SWATCH_PX) of the best base-colour candidates, from a small mip
    only; a texture whose smallest mip is still large is skipped. Returns (file names, packages)."""
    d = os.path.join(out_dir, 'swatches')
    names, pkgs = [], []
    for _score, base in sorted(candidates)[:SWATCHES + 2]:
        if len(names) >= SWATCHES:
            break
        try:
            tex = e33tex.parse_texture(base)
            if tex['vt'] is None:
                sizes = [max(w, h) for w, h, desc in tex['mips'] if tex['bulk'].payload(desc)]
                if not sizes or min(sizes) > 1024:
                    continue
            _fmt, w, h, px = e33tex.decode_texture(base, 192)
            w, h, px = e33tex.downscale(w, h, px, SWATCH_PX)
            os.makedirs(d, exist_ok=True)
            name = f'{stem}_{len(names) + 1}.png'
            with open(os.path.join(d, name + '.tmp'), 'wb') as f:
                f.write(e33tex.png_bytes(w, h, px))
            os.replace(os.path.join(d, name + '.tmp'), os.path.join(d, name))
            names.append(name)
            pkgs.append(packages_by_base.get(base))
        except Exception:
            continue
    if os.path.isdir(d):                               # fewer swatches than an earlier build
        for f in os.listdir(d):
            m = re.fullmatch(re.escape(stem) + r'_(\d+)\.png', f)
            if m and f not in names:
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass
    return names, pkgs


def relocate_variant(retoc, game_links, mod_root, rel, work, out_dir, variant_id, log, ctx, from_legacy=None):
    """ctx: dict(used=set, game_pkgs=set, game_version=int|None, skeletons=str, physics=str, chunks=set)."""
    src_dir = os.path.join(mod_root, *rel.split('/')) if rel else mod_root
    utocs = [f for f in os.listdir(src_dir) if f.lower().endswith('.utoc')]
    fixed = ctx.get('fixed', {})
    upath = lambda u: fixed.get(os.path.normcase(os.path.join(src_dir, u)), os.path.join(src_dir, u))  # noqa: E731
    if from_legacy is None and not utocs:
        return None, 'no .utoc in this folder (legacy .pak-only mods are not supported yet)'
    legacy = os.path.join(work, 'legacy')
    renamed = os.path.join(work, 'renamed')
    for d in (legacy, renamed):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    packages, notes, own_files = [], [], set()
    if from_legacy:
        shutil.copytree(from_legacy, legacy, dirs_exist_ok=True)
        for dp, _ds, fs in os.walk(legacy):
            for f in fs:
                r = os.path.relpath(os.path.join(dp, f), legacy).replace(os.sep, '/')
                own_files.add(r.lower())
                info = e33legacy.rel_to_package(r)
                if info and info[1] in ('.uasset', '.umap'):
                    packages.append(info[0])
    else:
        copied, flat, own = [], set(), set()
        try:
            # The variant gets top priority; the mod's other paks join below it so assets the
            # variant imports from a sibling/fix pak still resolve during extraction.
            for i, u in enumerate(sorted(utocs, key=str.lower)):
                pk, fl, ow, info = index_entries(upath(u))
                if info['encrypted']:
                    return None, f'{u} is encrypted'
                packages += pk
                flat |= fl
                own |= ow
                try:
                    copied += add_to_composite(upath(u), game_links,
                                               f'zzz_variant_{i}_{safe_name(u[:-5])}_{999 - i}_P',
                                               ctx['game_version'])
                except VersionMismatch as e:
                    return None, str(e)
                run([retoc, 'to-legacy', upath(u), legacy, '--no-assets',
                     '--no-script-objects', '--no-compres-shaders'], log)
            if not packages and not flat:
                files = [f for u in utocs for f in e33utoc.read_utoc(os.path.join(src_dir, u))['files']]
                return None, ('container lists no /Game packages (contents: '
                              + (', '.join(files[:4]) if files else 'nothing in its file index') + ')')
            extract(retoc, game_links, legacy, packages, flat, log)
        finally:
            for d in copied:
                try:
                    os.remove(d)
                except OSError:
                    pass
        prune_bulk(legacy, own, notes)
        at_root = {}
        normalize_legacy(legacy, at_root)
        flat_low = {f.lower() for f in flat}
        resolved = [n for st, n in at_root.items() if st in flat_low]
        if flat:
            notes.append(f'{len(flat)} package(s) had no folder in the pak index; real paths: '
                         + ', '.join(sorted(resolved)[:3]) + ('...' if len(resolved) > 3 else ''))
            missing_flat = sorted(flat_low - {n.rsplit('/', 1)[1].lower() for n in resolved})
            if missing_flat:
                return None, f'could not find the real path of {", ".join(missing_flat[:3])}'
        packages = list(packages) + resolved
        keep_only(legacy, {p.lower() for p in packages})
    packages = sorted(set(packages))

    # Inspect what was extracted.
    classes, unresolved = {}, {}
    swatch_cands, tex_pkgs = [], {}
    for p in packages:
        ua = os.path.join(legacy, *e33legacy.package_to_rel(p).split('/')) + '.uasset'
        try:
            info = e33legacy.read_package_info(ua)
            classes[p] = {'class': info['main_class'], 'object': info['main_name'],
                          'override': p.lower() in ctx['game_pkgs']}
            n = sum(1 for x in info['imported_packages'] if x.startswith('/Engine/UnknownPackage'))
            if n:
                unresolved[p] = n
            if (info['main_class'] or '').startswith('Texture2D'):
                tex_pkgs[ua[:-7]] = p
                texture_info(ua[:-7], classes[p], swatch_cands)
        except FileNotFoundError:
            classes[p] = {'class': None, 'error': 'not extracted (see relocate_log.txt)'}
        except Exception as e:      # malformed or unexpected layout: report
            classes[p] = {'class': None, 'error': f'{type(e).__name__}: {e}'}
    missing = [p for p, c in classes.items() if c.get('error')]
    if missing:
        return None, f'{len(missing)} package(s) could not be extracted, e.g. {missing[0]}: {classes[missing[0]]["error"]}'
    if unresolved:
        where = ', '.join(f'{p.rsplit("/", 1)[1]} ({n})' for p, n in sorted(unresolved.items()))
        if ctx.get('strict_imports'):
            return None, (f'{sum(unresolved.values())} import(s) could not be resolved in {where}: the variant '
                          'references assets that are neither in the game nor in this mod - is a required pak '
                          'from the mod page missing from the library?')
        # The game resolves imports against the same game + mod data, so it can't find these either
        # when the original mod is installed: the reference is empty in game too. Cooked mods often
        # carry such references to assets that were never cooked.
        notes.append(f'{where}: {sum(unresolved.values())} reference(s) to an asset that is in neither the game '
                     'nor this mod - left empty, as the game does with the original mod '
                     '(--strict-imports refuses such variants)')

    # (--from-legacy testing only) collect mod-only packages for the shared pak
    if from_legacy and ctx.get('shared_dir') is not None:
        for p, c in classes.items():
            if not c['override'] and p.lower() not in ctx['shared_provided']:
                for f in _package_files(legacy, p):
                    d = os.path.join(ctx['shared_dir'], os.path.relpath(f, legacy))
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    shutil.copy2(f, d)
                ctx['shared_provided'].add(p.lower())

    # Shared assets that must stay at their real path when they override the game.
    keep = []
    for p, c in classes.items():
        if c['class'] == 'Skeleton' and c['override'] and ctx['skeletons'] != 'relocate':
            keep.append(p)
        if c['class'] == 'PhysicsAsset' and c['override'] and ctx['physics'] == 'game':
            keep.append(p)
        if p.lower().startswith('/game/mods/'):
            keep.append(p)
            notes.append(f'{p} kept at its path (logic mods are found by path)')
    for p in keep:
        c = classes[p]['class']
        if (c == 'Skeleton' and ctx['skeletons'] == 'original') or (c == 'PhysicsAsset' and ctx['physics'] == 'game'):
            for f in _package_files(legacy, p):
                os.remove(f)
            notes.append(f'using the game\'s {c} {p} (mod copy dropped)')
        elif c == 'Skeleton':
            notes.append(f'skeleton {p} still overrides the game globally (--skeletons override)')
    mapping = e33legacy.plan_relocation([p for p in packages if p not in keep], variant_id, ctx['used'])
    report = e33legacy.relocate_tree(legacy, renamed, mapping)

    # Shader libraries: give each variant its own chunk number so libraries don't collide.
    shader_files = [os.path.join(dp, f) for dp, _ds, fs in os.walk(renamed) for f in fs
                    if f.startswith(('ShaderArchive-', 'ShaderAssetInfo-'))]
    chunk = None
    if shader_files:
        chunk = _shader_chunk(variant_id, ctx['chunks'])
        for f in shader_files:
            d, n = os.path.split(f)
            n2 = re.sub(r'_Chunk\d+-', f'_Chunk{chunk}-', n)
            if n2 == n:
                n2 = re.sub(r'^(Shader(?:Archive|AssetInfo)-[^-]+?)-', rf'\1_Chunk{chunk}-', n, count=1)
            os.replace(f, os.path.join(d, n2))
        notes.append(f'has its own shaders: packed as pakchunk{chunk}')
    stem = f'pakchunk{chunk}-Windows_P' if chunk else variant_stem(variant_id, ctx['stems'])
    out_utoc = publish(retoc, renamed, work, out_dir, stem, log)
    swatches, swatch_textures = write_swatches(swatch_cands, tex_pkgs, out_dir, stem)
    return {'map': mapping, 'classes': classes, 'rewrites': report['rewrites'],
            'appended_names': report['appended_names'], 'missing': [], 'notes': notes,
            'unresolved': unresolved, 'output': out_utoc, 'swatches': swatches,
            'swatch_textures': swatch_textures}, None


# ------------------------------------------------------------------------------ Lua table

def lua_quote(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def write_variants_lua(path, mods):
    lines = ['-- Generated by e33_relocate.py. Re-run the relocator instead of editing by hand.', 'return {']
    for mod in mods:
        lines.append(f'  {{ mod = {lua_quote(mod["name"])}, slots = {{')
        for slot in mod['slots']:
            ch = f', character = {lua_quote(slot["character"])}' if slot.get('character') else ''
            lines.append(f'    {{ id = {lua_quote(slot["id"])}, label = {lua_quote(slot["label"])}{ch}, variants = {{')
            for v in slot['variants']:
                lines.append(f'      {{ id = {lua_quote(v["id"])}, label = {lua_quote(v["label"])}, map = {{')
                for old, new in sorted(v['map'].items()):
                    cls = v['classes'].get(old, {})
                    obj = cls.get('object') or old.rsplit('/', 1)[1]
                    over = 'true' if cls.get('override', True) else 'false'
                    lines.append(f'        [{lua_quote(old)}] = {{ {lua_quote(new)}, {lua_quote(obj)}, '
                                 f'{lua_quote(cls.get("class") or "")}, {over} }},')
                lines.append('      } },')
            lines.append('    } },')
        lines.append('  } },')
    lines.append('}')
    lines[0] += f' (version {e33common.VERSION})'
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, path)


def update_registry(path, mods_out, partial):
    """Keep every relocated mod in the wardrobe, not just the ones from this run."""
    reg = []
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                reg = json.load(f)
        except ValueError:
            reg = []
    if not isinstance(reg, list):
        reg = []
    by_name = {m['name']: m for m in reg if isinstance(m, dict) and 'name' in m}
    for mod in mods_out:
        old = by_name.get(mod['name'])
        if partial and old:                      # --only: merge new variants into the existing slots
            if 'shared' in mod:
                old['shared'] = mod['shared']
            slots = {s['id']: s for s in old['slots']}
            for s in mod['slots']:
                tgt = slots.setdefault(s['id'], {**s, 'variants': []})
                keep = {v['id']: v for v in tgt['variants']}
                keep.update({v['id']: v for v in s['variants']})
                tgt['variants'] = sorted(keep.values(), key=lambda v: v['id'])
            old['slots'] = sorted(slots.values(), key=lambda s: s['id'])
        elif mod['slots']:
            by_name[mod['name']] = mod
    reg = [by_name[k] for k in sorted(by_name)]
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(reg, f, indent=1)
    os.replace(tmp, path)
    return reg


# ------------------------------------------------------------------------------ main

def remove_mods(names, out_root, lua_dir):
    """--remove: take mods out of the wardrobe (registry, variants.lua, their relocated paks)."""
    reg_path = os.path.join(lua_dir, 'wardrobe_registry.json') if lua_dir else None
    reg = []
    if reg_path and os.path.isfile(reg_path):
        try:
            with open(reg_path, encoding='utf-8') as f:
                reg = json.load(f)
        except ValueError:
            reg = []
    if not isinstance(reg, list):
        reg = []
    gone = 0
    for name in names:
        hit = [m for m in reg if isinstance(m, dict) and m.get('name', '').lower() == name.lower()]
        if not hit:
            print(f'"{name}" is not in the wardrobe. Relocated mods:',
                  ', '.join(m.get('name', '?') for m in reg if isinstance(m, dict)) or '(none)')
            continue
        for m in hit:
            reg.remove(m)
            outs = {os.path.dirname(v.get('output') or '') for sl in m.get('slots', [])
                    for v in sl.get('variants', []) if v.get('output')}
            for d in outs | {os.path.join(out_root, safe_name(m['name']))}:
                if d and os.path.isdir(d) and os.path.normcase(os.path.abspath(d)).startswith(
                        os.path.normcase(os.path.abspath(out_root)) + os.sep):
                    shutil.rmtree(d, ignore_errors=True)
                    if os.path.isdir(d):
                        print(f'  could not delete {d} (is a file in it open?); delete it by hand')
            print(f'removed "{m["name"]}" from the wardrobe')
            gone += 1
    if gone and reg_path:
        tmp = reg_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(reg, f, indent=1)
        os.replace(tmp, reg_path)
        write_variants_lua(os.path.join(lua_dir, 'Scripts', 'variants.lua'), reg)
        print('In game: Settings > Reload (or Ctrl+F8) to update the menu.')
    return 0 if gone else 1


def main(argv=None):
    e33common.safe_console()
    tee = ConsoleTee()
    try:
        return _main(argv, tee)
    except KeyboardInterrupt:
        print('\ninterrupted: the wardrobe was not changed (it is only updated at the end of a run)')
        return 130
    except SystemExit as e:
        if e.code not in (None, 0) and not isinstance(e.code, int):
            tee.file_only(str(e.code))
        raise
    except BaseException:
        tee.file_only(traceback.format_exc())
        raise
    finally:
        tee.stop()


def _main(argv, tee):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--version', action='version', version=f'E33 Wardrobe relocator {e33common.VERSION}')
    ap.add_argument('--paks', help='game Sandfall\\Content\\Paks folder (default: the saved setting, or found '
                                   'automatically)')
    ap.add_argument('--library', help='mod library folder, for --mod with just a name (default: Paks_ModLibrary '
                                      'next to Paks)')
    ap.add_argument('--save', action='store_true',
                    help='remember --paks, --library and --retoc for later runs (tools\\e33wardrobe_config.json)')
    ap.add_argument('--mod', action='append', help='mod folder, or a folder name in the library (repeatable)')
    ap.add_argument('--remove', action='append', metavar='MOD',
                    help='take a relocated mod out of the wardrobe (deletes its relocated paks; repeatable)')
    ap.add_argument('--retoc', help='path to retoc.exe (default: next to this script, the saved setting, or PATH)')
    ap.add_argument('--out', help='output folder for relocated paks (default Paks\\~mods\\_E33Wardrobe)')
    ap.add_argument('--lua-dir', help='UE4SS Mods\\E33Wardrobe folder (default derived from --paks)')
    ap.add_argument('--work', help='parent folder for the temporary work folder (same drive as the game)')
    ap.add_argument('--skeletons', choices=['original', 'override', 'relocate'], default='original',
                    help='mod copies of game Skeletons: drop them and use the game skeleton (default), '
                         'keep them overriding the game globally, or relocate them like other assets')
    ap.add_argument('--physics', choices=['mod', 'game'], default='mod',
                    help='mod copies of game PhysicsAssets: relocate with the variant (default) or use the game\'s')
    ap.add_argument('--only', help='regex: only relocate option folders whose path matches')
    ap.add_argument('--strict-imports', action='store_true',
                    help='refuse variants that reference assets found neither in the game nor in the mod '
                         '(default: keep them; such references are empty in game with the original mod too)')
    ap.add_argument('--from-legacy', help=argparse.SUPPRESS)   # testing: use pre-extracted legacy assets
    ap.add_argument('--keep-work', action='store_true',
                    help='keep the work folder for debugging. It holds hard links to the game\'s files: delete it '
                         'afterwards (the next run also removes it)')
    a = ap.parse_args(argv)

    cfg = read_config()
    if not a.paks and not a.from_legacy:
        a.paks = cfg.get('paks_dir')
        if not e33common.is_paks_dir(a.paks):
            a.paks = e33common.detect_paks_dir()
        if a.paks:
            print('Paks folder:', a.paks)
    if not a.from_legacy and not (a.paks and os.path.isdir(a.paks)):
        raise SystemExit('Could not find the game. Pass --paks "<game>\\Sandfall\\Content\\Paks" '
                         '(add --save to remember it).')
    if not a.from_legacy and not e33common.is_paks_dir(a.paks):
        raise SystemExit(f'{a.paks} is not the game\'s Paks folder (it has no global.utoc).')
    out_root = a.out or os.path.join(a.paks, '~mods', '_E33Wardrobe')
    lua_dir = a.lua_dir or (default_lua_dir(a.paks) if a.paks else None)
    if a.remove:
        if not a.from_legacy and e33common.game_running(fresh=True):
            raise SystemExit('The game is running. Close it first: its paks are locked while it runs.')
        return remove_mods(a.remove, out_root, lua_dir)
    if a.save:
        cfg = dict(cfg, paks_dir=a.paks, **({'library': a.library} if a.library else {}),
                   **({'retoc': a.retoc} if a.retoc else {}))
        save_config(cfg)
        if not a.mod:
            return 0
    if not a.mod:
        ap.error('give at least one --mod (or --remove)')
    library = a.library or cfg.get('library') or (os.path.join(os.path.dirname(a.paks), 'Paks_ModLibrary') if a.paks else None)
    mods = []
    for m in a.mod:
        m = m.strip().rstrip('"')                 # the Windows "...\\" quoting slip
        if not os.path.isdir(m) and library and os.path.isdir(os.path.join(library, m)):
            m = os.path.join(library, m)
        if not os.path.isdir(m):
            raise SystemExit(f'Mod folder not found: {m}')
        if not a.from_legacy and not any(f.lower().endswith(('.utoc', '.pak'))
                                         for _dp, _ds, fs in os.walk(m) for f in fs):
            raise SystemExit(f'No .utoc or .pak files in {m}: is this the mod\'s folder?')
        mods.append(os.path.normpath(m))
    a.mod = mods
    names = [os.path.basename(m).lower() for m in mods]
    if len(set(names)) != len(names):
        raise SystemExit('Two --mod folders have the same name; rename one so their outputs stay apart.')
    if a.only:
        try:
            only_re = re.compile(a.only.replace('\\', '/'))
        except re.error as e:
            raise SystemExit(f'--only is not a valid regular expression: {e}')
    retoc = find_retoc(a.retoc or cfg.get('retoc'))
    if not a.from_legacy:
        rv = retoc_version(retoc)
        if rv != TESTED_RETOC:
            print(f'WARNING: retoc {rv or "(unknown version)"} found; E33 Wardrobe is tested with retoc {TESTED_RETOC}.')
        probe = [os.path.join(dp, f) for dp, _ds, fs in os.walk(out_root) if os.path.isdir(out_root)
                 for f in fs if f.lower().endswith('.ucas')][:20]
        if e33common.game_running(fresh=True, probe=probe):
            raise SystemExit('The game is running. Close it first: its paks are locked while it runs.')
    if lua_dir and not a.lua_dir and not os.path.isdir(os.path.dirname(os.path.dirname(lua_dir))):
        print(f'WARNING: UE4SS was not found at {os.path.dirname(os.path.dirname(lua_dir))}. Install UE4SS '
              '(see docs/INSTALL.md), or pass --lua-dir with your ue4ss\\Mods\\E33Wardrobe folder.')
    # Always a fresh folder we create (and later delete) - never the folder the user named.
    parent = a.work or (os.path.dirname(a.paks) if a.paks else None)
    if parent and a.paks and os.path.normcase(os.path.abspath(parent) + os.sep).startswith(
            os.path.normcase(os.path.abspath(a.paks) + os.sep)):
        raise SystemExit('--work must not be inside the Paks folder (the game would load the work files).')
    if parent:
        os.makedirs(parent, exist_ok=True)
        e33common.clean_stale_work(parent)
    work = tempfile.mkdtemp(prefix='_e33wardrobe_work_', dir=parent)
    lock = open(os.path.join(work, '.lock'), 'w')
    game_links = os.path.join(work, 'game')
    os.makedirs(game_links, exist_ok=True)
    os.makedirs(out_root, exist_ok=True)
    tee.start(os.path.join(out_root, 'relocate_console.txt'), sys.argv[1:] if argv is None else list(argv))
    log = RunLog()
    log_paths = []
    ctx = {'used': set(), 'game_pkgs': set(), 'game_version': None, 'skeletons': a.skeletons,
           'physics': a.physics, 'chunks': set(), 'strict_imports': a.strict_imports, 'stems': {}}
    # The previous run's wardrobe: a variant that fails this time keeps its earlier build.
    previous, other_mods = {}, set()
    if lua_dir and os.path.isfile(os.path.join(lua_dir, 'wardrobe_registry.json')):
        try:
            with open(os.path.join(lua_dir, 'wardrobe_registry.json'), encoding='utf-8') as f:
                for m in json.load(f):
                    other_mods.add(m['name'])
                    for sl in m.get('slots', []):
                        for v in sl.get('variants', []):
                            previous[v['id']] = (sl['id'], v)
        except (OSError, ValueError, KeyError, TypeError):
            previous = {}
    # Output folder per mod: a mod whose cleaned name equals another mod's folder gets a hash.
    taken = {safe_name(n).lower(): n for n in other_mods}
    mod_dirs = {}
    for m in a.mod:
        n = os.path.basename(m)
        d = safe_name(n)
        if taken.get(d.lower(), n) != n:
            d = f"{d}-{hashlib.sha1(n.encode('utf-8')).hexdigest()[:8]}"
        taken[d.lower()] = n
        mod_dirs[n] = d
    try:
        if not a.from_legacy:
            n = 0
            for f in game_container_files(a.paks):
                link_or_fail(os.path.join(a.paks, f), os.path.join(game_links, f))
                n += 1
            g = os.path.join(game_links, 'global.utoc')
            if not os.path.isfile(g):
                raise SystemExit('global.utoc not found in the Paks folder - is --paks right?')
            ctx['game_version'] = toc_version(g)
            ctx['game_pkgs'] = game_packages(game_links)
            print(f'linked {n} game container files; the game has {len(ctx["game_pkgs"])} packages '
                  f'(TOC version {ctx["game_version"]})')

        report, mods_out = {}, []
        for mod_root in a.mod:
            mod_root = os.path.normpath(mod_root)
            mod_name = os.path.basename(mod_root)
            log_paths.append(os.path.join(out_root, mod_dirs[mod_name], 'relocate_log.txt'))
            log.start(log_paths[-1])
            # All of the mod's paks join the composite once, below the variant being extracted,
            # so assets a variant imports from a sibling or fix pak still resolve.
            siblings = []
            ctx['fixed'] = {}
            if not a.from_legacy:
                # Repair flat file indexes first (some paks list files without folders).
                for dp, _ds, fs in os.walk(mod_root):
                    for f in fs:
                        if f.lower().endswith('.utoc'):
                            orig = os.path.join(dp, f)
                            try:
                                fx, names = repair_flat(retoc, game_links, orig, work, log)
                            except Exception as e:      # keep the original; the fallback still tries
                                fx, names = orig, {}
                                print(f'  note: could not repair the file index of {f}: {e}')
                            if fx != orig:
                                ctx['fixed'][os.path.normcase(orig)] = fx
                                print(f'  repaired the file index of {os.path.relpath(orig, mod_root)} '
                                      f'({len(names)} package(s) had no folder)')
                for j, sib in enumerate(sorted(ctx['fixed'].get(os.path.normcase(os.path.join(dp, f)), os.path.join(dp, f))
                                               for dp, _ds, fs in os.walk(mod_root)
                                               for f in fs if f.lower().endswith('.utoc'))):
                    try:
                        siblings += add_to_composite(sib, game_links, f'zzy_sibling_{j}_500_P', ctx['game_version'])
                    except VersionMismatch as e:
                        print(f'  note: left out of lookups: {e}')
            slots = option_slots(mod_root)
            mod_entry = {'name': mod_name, 'slots': []}
            ctx['shared_dir'] = os.path.join(work, 'shared_' + safe_name(mod_name))
            ctx['shared_provided'] = set()
            shutil.rmtree(ctx['shared_dir'], ignore_errors=True)
            os.makedirs(ctx['shared_dir'])
            for slot_key, options in slots.items():
                slot = {'id': f'{mod_name}/{slot_key}', 'label': f'{mod_name}: {slot_key}',
                        'character': character_of(slot_key) or character_of(mod_name), 'variants': []}
                for opt in options:
                    if a.only and not only_re.search(opt['rel'].replace('\\', '/')):
                        continue
                    vid = f'{mod_name}/{opt["rel"]}'
                    print(f'[{mod_name}] {opt["rel"]} ...', flush=True)
                    try:
                        res, err = relocate_variant(retoc, game_links, mod_root, opt['rel'], work,
                                                    os.path.join(out_root, mod_dirs[mod_name]),
                                                    vid, log, ctx, a.from_legacy)
                    except Exception as e:      # one bad variant must not stop the others
                        res, err = None, f'{type(e).__name__}: {e}'
                    report[vid] = res or {'error': err}
                    if err:
                        print('    skipped:', err.splitlines()[0])
                        old = previous.get(vid)
                        mod_out_dir = os.path.join(out_root, mod_dirs[mod_name])
                        old_out = (old[1].get('output') if old else None) or os.path.join(
                            mod_out_dir, variant_stem(vid, ctx['stems']) + '.utoc')
                        if old and old[0] == slot['id'] and os.path.isfile(old_out) and not a.from_legacy:
                            slot['variants'].append({**old[1], 'output': old_out})
                            report[vid]['kept_previous'] = old_out
                            print('    kept the build from the previous run, so this variant stays available')
                        continue
                    kinds = sorted({c['class'] or '?' for c in res['classes'].values()})
                    over = sum(1 for c in res['classes'].values() if c.get('override'))
                    print(f'    {len(res["map"])} assets relocated ({", ".join(kinds)}); '
                          f'{over} of them replace game assets')
                    for n in res['notes'][:8]:
                        print('    note:', n)
                    slot['variants'].append({'id': vid, 'label': opt['label'], 'map': res['map'],
                                             'classes': res['classes'], 'output': res['output']})
                if slot['variants']:
                    mod_entry['slots'].append(slot)
            mods_out.append(mod_entry)
            if not slots:
                print(f'  WARNING: no option folders with paks found in {mod_root}; nothing changed for this mod')
            mod_out = os.path.join(out_root, mod_dirs[mod_name])
            try:
                if a.from_legacy:
                    shared, shared_pk = None, sorted(ctx['shared_provided'])
                    if shared_pk:
                        shared = publish(retoc, ctx['shared_dir'], work, mod_out, safe_name(mod_name) + '_Shared_P', log)
                else:
                    shared, shared_pk = build_shared(retoc, game_links, mod_root, work, mod_out, mod_name, ctx, log)
                if shared:
                    report[f'{mod_name}/(shared)'] = {'output': shared, 'packages': shared_pk}
                    mod_entry['shared'] = shared_pk
                    print(f'  shared pak: {len(shared_pk)} mod-only asset(s) at their original paths')
            except Exception as e:      # shared pak is an add-on; keep the variants
                print(f'  WARNING: shared pak failed: {e}')
            # Remove outputs of variants that no longer exist (full runs only; never when the mod
            # yielded nothing, e.g. its folders were moved away).
            if not a.only and slots and os.path.isdir(mod_out):
                keep = {os.path.splitext(os.path.basename(r.get('output') or r.get('kept_previous')))[0].lower()
                        for k, r in report.items()
                        if k.startswith(mod_name + '/') and (r.get('output') or r.get('kept_previous'))}
                for f in os.listdir(mod_out):
                    stem, ext = os.path.splitext(f)
                    if ext.lower() in ('.pak', '.utoc', '.ucas') and stem.lower() not in keep:
                        try:
                            os.remove(os.path.join(mod_out, f))
                            print(f'  removed stale {f}')
                        except OSError:
                            pass
                sw = os.path.join(mod_out, 'swatches')
                for f in (os.listdir(sw) if os.path.isdir(sw) else []):
                    m = re.fullmatch(r'(.+)_\d+\.png', f)
                    if m and m.group(1).lower() not in keep:
                        try:
                            os.remove(os.path.join(sw, f))
                        except OSError:
                            pass
            for d in siblings:
                try:
                    os.remove(d)
                except OSError:
                    pass
    finally:
        log.close()
        lock.close()
        if not a.keep_work:
            shutil.rmtree(work, ignore_errors=True)

    # Reports: one per mod in its folder, plus relocate_report.json merging every mod relocated so far.
    run_mods = {os.path.basename(os.path.normpath(m)) for m in a.mod}
    for mname in run_mods:
        mine = {k: v for k, v in report.items() if k.startswith(mname + '/')}
        os.makedirs(os.path.join(out_root, mod_dirs[mname]), exist_ok=True)
        write_json(os.path.join(out_root, mod_dirs[mname], 'relocate_report.json'), mine)
    merged = {}
    try:
        with open(os.path.join(out_root, 'relocate_report.json'), encoding='utf-8') as f:
            merged = json.load(f)
        if not isinstance(merged, dict):
            merged = {}
    except (OSError, ValueError):
        merged = {}
    if a.only:
        merged.update(report)
    else:
        merged = {k: v for k, v in merged.items() if k.split('/', 1)[0] not in run_mods}
        merged.update(report)
    write_json(os.path.join(out_root, 'relocate_report.json'), merged)
    if lua_dir:
        os.makedirs(os.path.join(lua_dir, 'Scripts'), exist_ok=True)
        if os.path.isdir(LUA_TEMPLATE):
            n = install_lua(LUA_TEMPLATE, lua_dir)
            if n:
                print(f'Lua mod: {n} file(s) installed or updated')
        registry = update_registry(os.path.join(lua_dir, 'wardrobe_registry.json'), mods_out, bool(a.only))
        clashes = {}
        for m in registry:
            for p in m.get('shared', []):
                clashes.setdefault(p, []).append(m['name'])
        dup = {p: n for p, n in clashes.items() if len(n) > 1}
        if dup:
            p, n = next(iter(dup.items()))
            print(f'WARNING: {len(dup)} mod-only asset path(s) exist in several mods\' shared paks '
                  f'(e.g. {p}: {", ".join(n)}). Two versions of one mod? Keep only one in the library.')
        write_variants_lua(os.path.join(lua_dir, 'Scripts', 'variants.lua'), registry)
        print('Lua mod written to', lua_dir, f'({len(registry)} mod(s) in the wardrobe)')
    print('Relocated paks in', out_root)
    print('Report (all mods):', os.path.join(out_root, 'relocate_report.json'))
    for lp in log_paths:
        print('Log and report of this mod:', os.path.dirname(lp))
    variants = {k: r for k, r in report.items() if not k.endswith('/(shared)')}
    ok = sum(1 for r in variants.values() if 'error' not in r)
    kept = sum(1 for r in variants.values() if r.get('kept_previous'))
    warned = sum(1 for r in variants.values() if r.get('unresolved'))
    print(f'{ok}/{len(variants)} variants relocated'
          + (f', {kept} failed one(s) kept from the previous run' if kept else '')
          + (f'; {warned} with references to assets that exist nowhere (see the notes above)' if warned else ''))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
