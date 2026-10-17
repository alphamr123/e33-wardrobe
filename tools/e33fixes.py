"""Per-mod edits and fix rules for the in-game menu, kept in fixes.json in the menu folder
(ue4ss\\Mods\\E33Wardrobe). The app writes it; the relocator and the app both apply it whenever
they write variants.lua, so it survives Reinstall. Nothing here changes the mod library.

fixes.json:
  {"version": 1, "mods": {"<mod name>": {
     "disabled": true,                                   files moved out of ~mods, not in the menu
     "rows": {"<slot id>": {"label": "..."}},            renamed rows
     "new_rows": [{"id": "<mod>/+<n>", "label": "...", "character": "Lune" | null}],
     "options": {"<variant id>": {"label": "...", "row": "<slot id>", "hidden": true}},
     "row_order": ["<slot id>", ...], "option_order": {"<slot id>": ["<variant id>", ...]},
     "textures": {"<variant id>": {"<material original path>|<param or *>": "<texture original path>" | "game"}},
     "materials": {"<variant id>": {"<mesh original path>|<slot index>": "body" | "hide" | "<material original path>"}},
     "bundles": [{"id": "b1", "from_mod": "...", "from_option": "...", "requested": [...], "packages": [...],
                  "utoc": "bundles/<mod>/<id>/<stem>.utoc", "size": 0, "added": "YYYY-MM-DD HH:MM"}]}}}

Ids are the registry's (the menu splits multi-character slots itself). Paths compare
case-insensitively. A texture rule with param "*" covers any empty texture link of that material.
"""
import contextlib
import copy
import datetime
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid

FILE = 'fixes.json'
REGISTRY = 'wardrobe_registry.json'
DISABLED_DIR = 'E33Wardrobe_Disabled'
BUNDLES_DIR = 'bundles'


class FixError(RuntimeError):
    """A fix that can't be made, with a plain sentence for the user."""


# Every read-modify-write of fixes.json and every write of variants.lua holds this lock: the app
# runs API calls and the relocator (in its job worker) in different threads of one process.
LOCK = threading.RLock()


def _tmp(path):
    return f'{path}.{os.getpid()}-{threading.get_ident()}.tmp'


# ------------------------------------------------------------------------------ the file

def fixes_path(lua_dir):
    return os.path.join(lua_dir, FILE)


def load(lua_dir, strict=False):
    """The fixes (an empty skeleton when there are none). strict: a fixes.json that exists but
    can't be read is kept as fixes.json.bad-<time> and FixError is raised, so a following save
    can't wipe every fix (the editing paths use strict; applying them doesn't)."""
    data = None
    path = fixes_path(lua_dir)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        if strict:
            bad = path + '.bad-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            try:
                shutil.copy2(path, bad)
            except OSError:
                bad = None
            raise FixError(f'fixes.json can\'t be read ({e}).' + (f' A copy is kept as {os.path.basename(bad)}.' if bad else '')
                           + ' Fix or delete it, then try again.')
    if data is not None and not isinstance(data, dict):
        if strict:
            raise FixError('fixes.json has an unexpected layout. Fix or delete it, then try again.')
        data = None
    if not isinstance(data, dict):
        data = {}
    data.setdefault('version', 1)
    if not isinstance(data.get('mods'), dict):
        data['mods'] = {}
    return data


def save(lua_dir, data):
    with LOCK:
        os.makedirs(lua_dir, exist_ok=True)
        data['mods'] = {k: v for k, v in (data.get('mods') or {}).items() if v}
        tmp = _tmp(fixes_path(lua_dir))
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, fixes_path(lua_dir))


@contextlib.contextmanager
def edit(lua_dir):
    """with edit(lua_dir) as data: ...  - load, change, save under the lock. Nothing is saved
    when the block raises."""
    with LOCK:
        data = load(lua_dir, strict=True)
        yield data
        save(lua_dir, data)


def _ci(d, key):
    """d[key], else the entry whose key matches case-insensitively."""
    if not isinstance(d, dict) or key is None:
        return None
    if key in d:
        return d[key]
    low = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == low:
            return v
    return None


def entry(data, mod, create=True):
    mods = data.setdefault('mods', {})
    e = _ci(mods, mod)
    if e is None and create:
        e = mods[mod] = {}
    return e


def is_disabled(data, mod):
    return bool((entry(data, mod, create=False) or {}).get('disabled'))


def read_registry(lua_dir):
    try:
        with open(os.path.join(lua_dir, REGISTRY), encoding='utf-8') as f:
            reg = json.load(f)
        return reg if isinstance(reg, list) else []
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------------------ applying

def _rule_key(k):
    """'<Path>|<rest>' -> '<path lower>|<rest>' (param names keep their case)."""
    p, sep, rest = k.rpartition('|')
    return (p.lower() + sep + rest) if sep else k.lower()


def apply(registry, data):
    """The mods for variants.lua: disabled mods and hidden options left out; labels, moves, new
    rows and order applied; texture/material rules attached to their variants as v['fix']."""
    out = []
    for mod in registry:
        if not isinstance(mod, dict) or 'name' not in mod:
            continue
        e = entry(data, mod['name'], create=False) or {}
        if e.get('disabled'):
            continue
        m = copy.deepcopy(mod)
        slots, order = {}, []
        for s in m.get('slots', []):
            slots[s['id']] = s
            order.append(s['id'])
        for nr in e.get('new_rows') or []:
            if isinstance(nr, dict) and nr.get('id') and _ci(slots, nr['id']) is None:
                slots[nr['id']] = {'id': nr['id'], 'label': nr.get('label') or nr['id'],
                                   'character': nr.get('character'), 'variants': []}
                order.append(nr['id'])
        for sid, r in (e.get('rows') or {}).items():
            s = _ci(slots, sid)
            if s is not None and isinstance(r, dict) and r.get('label'):
                s['label'] = r['label']
        opts = e.get('options') or {}
        moved = {}
        for sid in order:
            s = slots[sid]
            keep = []
            for v in s.get('variants', []):
                o = _ci(opts, v['id']) or {}
                if o.get('label'):
                    v['label'] = o['label']
                if o.get('hidden'):
                    continue
                tgt = _ci(slots, o.get('row')) if o.get('row') else None
                if tgt is not None and tgt is not s:
                    moved.setdefault(tgt['id'], []).append(v)
                    continue
                keep.append(v)
            s['variants'] = keep
        for sid, vs in moved.items():
            slots[sid]['variants'] += vs
        for sid, ids in (e.get('option_order') or {}).items():
            s = _ci(slots, sid)
            if s is not None and isinstance(ids, list):
                rank = {str(i).lower(): n for n, i in enumerate(ids)}
                s['variants'].sort(key=lambda v: rank.get(v['id'].lower(), len(rank)))
        ro = e.get('row_order')
        if isinstance(ro, list):
            rank = {str(i).lower(): n for n, i in enumerate(ro)}
            order.sort(key=lambda sid: rank.get(sid.lower(), len(rank)))
        tex, mat = e.get('textures') or {}, e.get('materials') or {}
        for sid in order:
            for v in slots[sid]['variants']:
                fx = {}
                t, mm = _ci(tex, v['id']), _ci(mat, v['id'])
                if isinstance(t, dict) and t:
                    fx['tex'] = {_rule_key(k): val for k, val in t.items() if isinstance(val, str)}
                if isinstance(mm, dict) and mm:
                    fx['mat'] = {_rule_key(k): val for k, val in mm.items() if isinstance(val, str)}
                if fx:
                    v['fix'] = fx
        m['slots'] = [slots[sid] for sid in order if slots[sid]['variants']]
        if m['slots']:
            out.append(m)
    return out


def write_menu(lua_dir):
    """Rewrite variants.lua from wardrobe_registry.json and fixes.json (after an edit). The
    in-game menu picks it up on Reload. Returns the number of mods in the menu."""
    import e33_relocate
    with LOCK:
        mods = apply(read_registry(lua_dir), load(lua_dir))
        os.makedirs(os.path.join(lua_dir, 'Scripts'), exist_ok=True)
        e33_relocate.write_variants_lua(os.path.join(lua_dir, 'Scripts', 'variants.lua'), mods)
    return len(mods)


# ------------------------------------------------------------------------------ disable / enable

def disabled_root(paks):
    """Outside Paks: the game mounts every pak under Paks, ~mods included."""
    return os.path.join(os.path.dirname(os.path.normpath(paks)), DISABLED_DIR)


def default_out_root(paks):
    return os.path.join(paks, '~mods', '_E33Wardrobe')


def prepared_dir_name(registry, mod):
    """The mod's folder under ~mods\\_E33Wardrobe, from its prepared files."""
    for m in registry:
        if isinstance(m, dict) and str(m.get('name', '')).lower() == mod.lower():
            for s in m.get('slots', []):
                for v in s.get('variants', []):
                    if v.get('output'):
                        return os.path.basename(os.path.dirname(v['output'].replace('\\', os.sep)))
    return None


def move_dir(src, dst, aside=None):
    """Move a prepared folder by renaming it: all or nothing. A rename fails while a file in it is
    open (the game, an antivirus scan) or across drives; then nothing has changed and OSError is
    raised. An old copy at dst is renamed into `aside` (default: next to dst; give a folder
    outside Paks when dst is in ~mods) first, put back if the move fails, and deleted after."""
    if not os.path.isdir(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    old = None
    if os.path.exists(dst):
        side = aside or os.path.dirname(dst)
        os.makedirs(side, exist_ok=True)
        old = os.path.join(side, f'.old-{os.path.basename(dst)}-{uuid.uuid4().hex[:8]}')
        os.rename(dst, old)
    try:
        os.rename(src, dst)
    except OSError:
        if old:
            try:
                os.rename(old, dst)
            except OSError:
                pass
        raise
    if old:
        shutil.rmtree(old, ignore_errors=True)
    return True


def out_root_of(registry, mod, paks=None):
    """The folder that holds the mod's prepared folder (~mods\\_E33Wardrobe, or the relocator's
    --out), from its prepared files; else the default."""
    for m in registry:
        if isinstance(m, dict) and str(m.get('name', '')).lower() == mod.lower():
            for sl in m.get('slots', []):
                for v in sl.get('variants', []):
                    if v.get('output'):
                        return os.path.dirname(os.path.dirname(v['output'].replace('\\', os.sep)))
    return default_out_root(paks) if paks else None


def set_disabled(paks, lua_dir, mod, on, out_root=None):
    """Disable (on=True) or enable a mod: its prepared folder moves out of / back into ~mods and
    the menu leaves it out / shows it again. Picks are kept. {ok, error?}"""
    reg = read_registry(lua_dir)
    out_root = out_root or out_root_of(reg, mod, paks)
    name = prepared_dir_name(reg, mod)
    if not name or name in ('.', '..') or name.lower() == os.path.basename(os.path.normpath(out_root)).lower():
        # never move (or replace) anything but a mod's own folder inside out_root
        return {'ok': False, 'error': f'"{mod}" has no prepared files. Install it first.'}
    inside, outside = os.path.join(out_root, name), os.path.join(disabled_root(paks), name)
    src, dst = (inside, outside) if on else (outside, inside)
    with LOCK:
        try:
            moved = move_dir(src, dst, aside=disabled_root(paks))
        except OSError as e:
            return {'ok': False, 'error': f'Could not move the prepared files ({e}). Nothing was changed. '
                                          'Close the game (and anything that has those files open) and try again.'}
        try:
            with edit(lua_dir) as data:
                e = entry(data, mod)
                if on:
                    e['disabled'] = True
                else:
                    e.pop('disabled', None)
            write_menu(lua_dir)
        except Exception as ex:                 # keep files and fixes.json in step
            if moved:
                try:
                    move_dir(dst, src, aside=disabled_root(paks))
                except OSError:
                    pass
            return {'ok': False, 'error': f'Could not save the change ({ex}). Nothing was changed.'}
    return {'ok': True}


# ------------------------------------------------------------------------------ bundles

def bundle_key(mod):
    """Short folder name for a mod's bundles (Windows paths stay short; unique per mod name)."""
    return hashlib.sha1(mod.lower().encode('utf-8')).hexdigest()[:10]


def _inside(path, root):
    try:
        p, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
        return p != r and os.path.commonpath([p, r]) == r
    except ValueError:                          # another drive
        return False


def bundle_utocs(lua_dir, mod):
    """Containers of the mod's bundles that exist (for the relocator's lookups and shared pak)."""
    out = []
    for b in (entry(load(lua_dir), mod, create=False) or {}).get('bundles') or []:
        p = os.path.join(lua_dir, *str(b.get('utoc', '')).replace('\\', '/').split('/'))
        if b.get('utoc') and os.path.isfile(p) and _inside(p, os.path.join(lua_dir, BUNDLES_DIR)):
            out.append(p)
    return out


def bundled_packages(lua_dir, mod):
    return sorted({p.lower() for b in (entry(load(lua_dir), mod, create=False) or {}).get('bundles') or []
                   for p in b.get('packages') or []})


def make_bundle(paks, lua_dir, mod, source_mod_root, packages, retoc=None, from_option=None, from_mod=None):
    """Copy `packages` from another mod (source_mod_root, a library folder) plus the source-only
    files they import into a small container under the menu folder's bundles\\. Afterwards the
    mod needs a Reinstall: the relocator then puts them into its shared pak. Returns the bundle
    record (also saved in fixes.json). Raises FixError with a plain sentence."""
    import e33_relocate as R
    import e33legacy
    if not packages:
        raise FixError('Nothing to bundle.')
    try:
        retoc = R.find_retoc(retoc)
    except SystemExit:
        raise FixError('retoc is missing, so the files can\'t be copied.')
    parent = os.path.dirname(os.path.normpath(paks))
    work = tempfile.mkdtemp(prefix='_e33wardrobe_work_', dir=parent if os.path.isdir(parent) else None)
    lock = open(os.path.join(work, '.lock'), 'w')
    log = R.RunLog()
    try:
        game_links = os.path.join(work, 'game')
        os.makedirs(game_links)
        try:
            for f in R.game_container_files(paks):
                R.link_or_fail(os.path.join(paks, f), os.path.join(game_links, f))
        except SystemExit as e:
            raise FixError(str(e).splitlines()[0])
        gv = R.toc_version(os.path.join(game_links, 'global.utoc'))
        game_pkgs = R.game_packages(game_links)
        src, own = {}, set()
        utocs = sorted((os.path.join(dp, f) for dp, _ds, fs in os.walk(source_mod_root)
                        for f in fs if f.lower().endswith('.utoc')), key=str.lower)
        for j, u in enumerate(utocs):
            try:
                pk, _fl, ow, info = R.index_entries(u)
                if info['encrypted']:
                    continue
                R.add_to_composite(u, game_links, f'zzy_src_{j}_500_P', gv)
            except Exception:
                continue
            for p in pk:
                src.setdefault(p.lower(), p)
            own |= ow
        want = {p.lower() for p in packages}
        absent = sorted(p for p in want if p not in src)
        if absent:
            raise FixError(f'"{os.path.basename(source_mod_root)}" doesn\'t have {absent[0]}.')
        legacy = os.path.join(work, 'legacy')
        os.makedirs(legacy)
        done, todo = set(), set(want)
        while todo:
            R.extract(retoc, game_links, legacy, [src[p] for p in sorted(todo)], set(), log)
            done |= todo
            todo = set()
            for p in sorted(done):
                ua = os.path.join(legacy, *e33legacy.package_to_rel(src[p]).split('/')) + '.uasset'
                try:
                    imports = e33legacy.read_package_info(ua)['imported_packages']
                except Exception:
                    continue
                for imp in imports:
                    low = imp.lower()
                    if low in src and low not in game_pkgs and low not in done:
                        todo.add(low)
        R.prune_bulk(legacy, own)
        R.normalize_legacy(legacy)
        R.keep_only(legacy, done)
        key, tag = bundle_key(mod), uuid.uuid4().hex[:8]
        staged = os.path.join(work, 'bundle_out')
        try:
            utoc = R.publish(retoc, legacy, work, staged, f'B{key}_{tag}_P', log)
        except Exception as ex:
            raise FixError(f'The files couldn\'t be packed ({ex}).')
        # the record goes in under the lock, from a fresh read (edits made meanwhile are kept)
        with edit(lua_dir) as data:
            bundles = entry(data, mod).setdefault('bundles', [])
            taken = {b.get('id') for b in bundles}
            n = 1
            while f'b{n}' in taken:
                n += 1
            bid = f'b{n}'
            out_dir = os.path.join(lua_dir, BUNDLES_DIR, key, bid)
            if os.path.isdir(out_dir):          # left over from a forgotten record of this mod
                shutil.rmtree(out_dir, ignore_errors=True)
            os.makedirs(out_dir, exist_ok=True)
            for f in os.listdir(staged):
                shutil.move(os.path.join(staged, f), os.path.join(out_dir, f))
            size = sum(os.path.getsize(os.path.join(out_dir, f)) for f in os.listdir(out_dir))
            rec = {'id': bid, 'from_mod': from_mod or os.path.basename(os.path.normpath(source_mod_root)),
                   'from_option': from_option, 'requested': sorted(src[p] for p in want),
                   'packages': sorted(src[p] for p in done),
                   'utoc': os.path.relpath(os.path.join(out_dir, os.path.basename(utoc)), lua_dir).replace(os.sep, '/'),
                   'size': size, 'added': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
            bundles.append(rec)
        return rec
    finally:
        lock.close()
        shutil.rmtree(work, ignore_errors=True)


def remove_bundle(lua_dir, mod, bundle_id):
    """Forget a bundle and delete its container. The mod needs a Reinstall afterwards. Only a
    folder inside the menu folder's bundles\\ is ever deleted."""
    gone = None
    with edit(lua_dir) as data:
        e = entry(data, mod, create=False)
        if not e:
            return False
        keep = []
        for b in e.get('bundles') or []:
            if b.get('id') == bundle_id:
                gone = b
            else:
                keep.append(b)
        if gone is None:
            return False
        if keep:
            e['bundles'] = keep
        else:
            e.pop('bundles', None)
    rel = str(gone.get('utoc') or '').replace('\\', '/')
    if rel:
        folder = os.path.dirname(os.path.join(lua_dir, *rel.split('/')))
        if _inside(folder, os.path.join(lua_dir, BUNDLES_DIR)):
            shutil.rmtree(folder, ignore_errors=True)
    return True
