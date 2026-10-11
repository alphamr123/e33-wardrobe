"""The mod library: sorting a mod's options by outfit, and describing each mod for the UI.

Sources: the library folders, <menu>\\wardrobe_registry.json (every relocated mod: slots, variants,
map, classes) and Paks\\~mods\\_E33Wardrobe\\<mod>\\relocate_report.json (per variant: classes with
texture sizes, notes, unresolved links, errors, swatches). Shapes: app/API.md.
"""
import base64
import os
import re
import shutil

from . import paths
from .archives import common_words, has_paks, sanitize_name

SKIP_LIBRARY = ('.', '_e33wardrobe_work_', '_e33mixer_swatch_')
BODY_HINTS = ('Body', 'body', 'BTLS', 'skin')


def _t():
    return paths.tools()


# ------------------------------------------------------------------------------ names

def characters():
    return list(_t()['relocate'].CHARACTERS)


def leaf(pkg):
    return (pkg or '').rstrip('/').rsplit('/', 1)[-1]


def is_skeletal_leaf(pkg):
    return leaf(pkg).upper().startswith('SK_')


def split_camel(word):
    return re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', word).split()


def humanize(name):
    """One CamelCase word as words: 'LuneFelineSorceressBarefoot' -> 'Lune Feline Sorceress Barefoot'.
    Anything with spaces or other characters stays as it is."""
    s = (name or '').strip()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', s):
        return s
    words = split_camel(s)
    return ' '.join(words) if len(words) >= 2 else s


def base_body_name(option_names, mod_name=''):
    """What to call options that replace a character's base body mesh (SK_<Char>_Placeholder):
    the words several options share ('Expedition'), else 'Base body'. Never the mod's own name or
    a single option's folder name."""
    if len([n for n in option_names if n]) >= 2:
        w = humanize(common_words(option_names))
        if w and w.lower() != (mod_name or '').strip().lower():
            return w
    return 'Base body'


def outfit_name(pkg):
    """Outfit name of a skeletal mesh: SK_Lune_Clea_Skin -> 'Clea', SK_Lune_CivilianSkirt_skin ->
    'Civilian Skirt', SK_Lune_Bikini_A_skin -> 'Bikini A'. None for SK_<Character>_Placeholder
    (the base body)."""
    name = leaf(pkg)
    s = name[3:] if name[:3].upper() == 'SK_' else name
    chars = {c.lower() for c in characters()}
    parts = [p for p in s.split('_') if p and p.lower() not in chars]
    while parts and parts[-1].lower() == 'skin':
        parts.pop()
    if len(parts) == 1 and parts[0].lower() == 'placeholder':
        return None
    if not parts:
        return name
    words = []
    for p in parts:
        words += split_camel(p)
    return ' '.join(words)


def row_name(meshes, option_names):
    """Menu row name for options that replace `meshes`; the base body takes the options' common
    leading words ('Expedition'), else 'Base body'."""
    names = []
    for m in sorted(meshes):
        n = outfit_name(m)
        if n is None:
            n = common_words(option_names) or 'Base body'
        if n not in names:
            names.append(n)
    return ' + '.join(names) or 'Outfit'


def pretty(name):
    return _t()['rules'].pretty(name or '')


def option_label(folder_name, row_label=None):
    """'843_Clea - Shorter Skirt.' in row 'Clea' -> 'Shorter Skirt'; '843 - Clea (No Thights)' -> 'No Thights'."""
    s = pretty(folder_name)
    s = re.sub(r'^\s*\d+(?=[\s.\-]|$)', '', s).strip(' -_.,:')
    if row_label:
        pat = r'^' + r'[\s_-]*'.join(re.escape(w) for w in row_label.split()) + r'\d*\b'
        rest = re.sub(pat, '', s, count=1, flags=re.I).strip(' -_.,:')
        if rest:
            s = rest
    m = re.fullmatch(r'\((.*)\)', s)
    if m and m.group(1).strip():
        s = m.group(1)
    s = s.strip().rstrip('.').strip()
    return s or pretty(folder_name) or folder_name


def row_label(key, mod_name, rels=None):
    """Menu row name of a relocator slot key. 'Main' (one option at the mod's root) and the default
    'Variants' (options straight in the mod's folder) take the mod's name."""
    if not key or key == 'Main' or (key == 'Variants' and rels and all('/' not in r for r in rels)):
        return mod_name
    return humanize(pretty(key.lstrip('_'))) or key


def size_label(px):
    """4096 -> '4K', 2048 -> '2K', 1024 -> '1K', smaller -> '512 px'."""
    if not px:
        return ''
    if px >= 1024:
        return f'{int(round(px / 1024.0))}K'
    return f'{px} px'


def plural(n, word, many=None):
    return f'{n} {word if n == 1 else (many or word + "s")}'


def character_of(text):
    return _t()['relocate'].character_of(text)


# ------------------------------------------------------------------------------ package lists

_PKG_CACHE = {}


def packages_of(utoc):
    """Package paths a .utoc lists (cached by size and time); [] if unreadable."""
    try:
        st = os.stat(paths.lp(utoc))
    except OSError:
        return []
    key = (os.path.normcase(os.path.abspath(utoc)), st.st_size, int(st.st_mtime))
    if key not in _PKG_CACHE:
        try:
            _PKG_CACHE[key] = _t()['utoc'].packages_in(paths.lp(utoc))[0]
        except Exception:
            _PKG_CACHE[key] = []
    return _PKG_CACHE[key]


def utocs_in(folder):
    try:
        return sorted(os.path.join(folder, f) for f in os.listdir(paths.lp(folder)) if f.lower().endswith('.utoc'))
    except OSError:
        return []


def folder_packages(folder):
    out = []
    for u in utocs_in(folder):
        out += packages_of(u)
    return sorted(set(out))


def option_folders(mod_folder):
    """Folders of the mod that directly hold paks (relative, '/'), as the relocator sees them."""
    return _t()['rules'].find_option_folders(mod_folder)


def safe_child(parent, name):
    """<parent>\\<name> for a plain folder name, else None (no separators, drive letters, '..')."""
    if not parent or not isinstance(name, str) or not name or name != name.strip() or name in ('.', '..') \
            or any(ch in name for ch in '/\\:'):
        return None
    f = os.path.join(parent, name)
    if os.path.normcase(os.path.dirname(os.path.abspath(f))) != os.path.normcase(os.path.abspath(parent)):
        return None
    return f


def folder_size(folder):
    total = 0
    for dp, ds, fs in os.walk(paths.lp(folder)):
        ds[:] = [d for d in ds if not d.startswith('.')]
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


# ------------------------------------------------------------------------------ sorting by outfit

def arrange_by_outfit(mod_folder, packages=None):
    """If the mod's option folders are siblings and together replace two or more different
    skeletal meshes, move them into one subfolder per replaced mesh (or set of meshes), so the
    relocator makes one menu row per outfit. Returns the groups:
    [{'label': 'Clea', 'folder': 'Clea', 'count': 6, 'options': [...], 'meshes': [...]}];
    [] when nothing was moved. `packages(utoc)` lists a container's packages (tests)."""
    packages = packages or packages_of
    opts = [r for r in option_folders(mod_folder) if utocs_in(os.path.join(mod_folder, *r.split('/')) if r else mod_folder)]
    if len(opts) < 2 or '' in opts:
        return []
    parents = {r.rsplit('/', 1)[0] if '/' in r else '' for r in opts}
    if len(parents) != 1:
        return []
    parent = parents.pop()
    parent_dir = os.path.join(mod_folder, *parent.split('/')) if parent else mod_folder
    meshes = {}
    for rel in opts:
        if os.path.basename(rel).startswith('_'):          # on/off extras stay their own row
            continue
        sk = set()
        for u in utocs_in(os.path.join(mod_folder, *rel.split('/'))):
            sk.update(p for p in packages(u) if is_skeletal_leaf(p))
        if sk:
            meshes[rel] = frozenset(sk)
    keys = []
    for rel in opts:
        k = meshes.get(rel)
        if k and k not in keys:
            keys.append(k)
    if len(keys) < 2:
        return []
    groups = []
    for k in keys:
        rels = [r for r in opts if meshes.get(r) == k]
        names = [os.path.basename(r) for r in rels]
        groups.append({'label': row_name(k, names), 'meshes': sorted(k), 'options': names, 'count': len(rels),
                       'rels': rels})
    # Same label twice (two characters' base bodies): add the characters.
    for g in groups:
        if sum(1 for x in groups if x['label'] == g['label']) > 1:
            who = sorted({c for c in (character_of(m) for m in g['meshes']) if c})
            if who:
                g['label'] += f' ({", ".join(who)})'
    moving = {os.path.basename(r).lower() for g in groups for r in g['rels']}
    taken = {e.lower() for e in os.listdir(paths.lp(parent_dir)) if e.lower() not in moving}
    for g in groups:
        base, n, name = sanitize_name(g['label']), 2, sanitize_name(g['label'])
        while name.lower() in taken:
            name = f'{base} {n}'
            n += 1
        taken.add(name.lower())
        g['folder'] = name
    stage = os.path.join(parent_dir, '.arranging')
    shutil.rmtree(paths.lp(stage), ignore_errors=True)
    done = []
    try:
        for g in groups:
            os.makedirs(paths.lp(os.path.join(stage, g['folder'])))
            for rel in g['rels']:
                src = os.path.join(mod_folder, *rel.split('/'))
                dst = os.path.join(stage, g['folder'], os.path.basename(rel))
                os.replace(paths.lp(src), paths.lp(dst))
                done.append((src, dst))
        for g in groups:
            os.replace(paths.lp(os.path.join(stage, g['folder'])), paths.lp(os.path.join(parent_dir, g['folder'])))
    except OSError:
        for g in groups:                                     # put everything back
            moved = os.path.join(parent_dir, g['folder'])
            for rel in g['rels']:
                for d in (os.path.join(moved, os.path.basename(rel)), os.path.join(stage, g['folder'], os.path.basename(rel))):
                    if os.path.isdir(paths.lp(d)):
                        try:
                            os.replace(paths.lp(d), paths.lp(os.path.join(mod_folder, *rel.split('/'))))
                        except OSError:
                            pass
            try:
                os.rmdir(paths.lp(moved))
            except OSError:
                pass
        shutil.rmtree(paths.lp(stage), ignore_errors=True)
        raise
    shutil.rmtree(paths.lp(stage), ignore_errors=True)
    for g in groups:
        del g['rels']
    return groups


def group_tags(groups):
    return [f"{g['label']} · {g['count']}" for g in groups]


def menu_rows(mod_folder):
    """[(row label, option count)] as the relocator will make them."""
    slots = _t()['relocate'].option_slots(mod_folder)
    name = os.path.basename(os.path.normpath(mod_folder))
    return [(row_label(k, name, [o['rel'] for o in v]), len(v)) for k, v in slots.items()]


# ------------------------------------------------------------------------------ summaries

def guess_class(pkg):
    """Class from the usual name prefixes, for options not prepared yet."""
    u = leaf(pkg).upper()
    if u.startswith('SK_'):
        return 'SkeletalMesh'
    if u.startswith('SM_'):
        return 'StaticMesh'
    if u.startswith(('MI_', 'MIC_', 'MID_')):
        return 'MaterialInstanceConstant'
    if u.startswith(('M_', 'MAT_')):
        return 'Material'
    if u.startswith(('T_', 'TX_', 'TEX_')):
        return 'Texture2D'
    if u.startswith(('PA_', 'PHYS_', 'PHA_')) or u.endswith(('_PHYSICS', '_PHYSICSASSET', '_PHYS')):
        return 'PhysicsAsset'
    if u.startswith('SKEL_') or u.endswith('_SKELETON'):
        return 'Skeleton'
    if u.startswith(('BP_', 'ABP_')):
        return 'BlueprintGeneratedClass'
    return None


def guessed_classes(pkgs, game_override=True):
    return {p: {'class': guess_class(p), 'object': leaf(p), 'override': game_override} for p in pkgs}


def filled(classes):
    """Report classes with a guessed class where the relocator couldn't name one."""
    return {p: (c if (c or {}).get('class') not in (None, '', 'UnknownExport') else dict(c or {}, **{'class': guess_class(p)}))
            for p, c in classes.items()}


def is_body_texture(pkg, c=None):
    text = (pkg or '') + ' ' + ((c or {}).get('object') or '')
    return any(h in text for h in BODY_HINTS)


def _cls(c):
    return (c or {}).get('class') or ''


def is_blueprint(cls):
    return cls == 'BlueprintGeneratedClass' or cls.endswith('_C')


def changes_summary(classes):
    """'Outfit mesh, 2 materials, 5 textures'."""
    meshes = [p for p, c in classes.items() if _cls(c) in ('SkeletalMesh', 'StaticMesh')]
    mats = [p for p, c in classes.items() if _cls(c).startswith('Material')]
    texs = [p for p, c in classes.items() if _cls(c).startswith('Texture')]
    bps = [p for p, c in classes.items() if is_blueprint(_cls(c))]
    parts = []
    if len(meshes) == 1:
        m = meshes[0]
        if _cls(classes[m]) == 'SkeletalMesh' and is_skeletal_leaf(m):
            parts.append('body mesh' if outfit_name(m) is None else 'outfit mesh')
        else:
            parts.append('mesh')
    elif meshes:
        parts.append(plural(len(meshes), 'mesh', 'meshes'))
    if mats:
        parts.append(plural(len(mats), 'material'))
    if texs:
        parts.append(plural(len(texs), 'texture'))
    if bps:
        parts.append('Blueprint' if len(bps) == 1 else f'{len(bps)} Blueprints')
    if any(_cls(c) == 'PhysicsAsset' for c in classes.values()):
        parts.append('physics')
    if any(_cls(c) == 'Skeleton' for c in classes.values()):
        parts.append('skeleton')
    if not parts and classes:
        parts.append(plural(len(classes), 'file'))
    text = ', '.join(parts)
    return text[:1].upper() + text[1:]


def texture_kinds(classes, outfit_mod):
    """{'body': 4096, 'outfit': 2048} (largest side per kind; 0 when the size is unknown)."""
    kinds = {}
    for p, c in classes.items():
        if not _cls(c).startswith('Texture'):
            continue
        kind = 'body' if is_body_texture(p, c) else ('outfit' if outfit_mod else 'textures')
        size = max(int(c.get('width') or 0), int(c.get('height') or 0))
        kinds[kind] = max(kinds.get(kind, 0), size)
    return kinds


def texture_summary(classes, outfit_mod, guessed=False):
    """'Body 4K, outfit 2K' or ''. A prepared option whose texture sizes weren't recorded says so:
    'Outfit (size ?)'."""
    kinds = texture_kinds(classes, outfit_mod)
    unknown = '' if guessed else ' (size ?)'
    parts = [f'{k} {size_label(kinds[k])}' if kinds[k] else k + unknown for k in ('body', 'outfit', 'textures')
             if k in kinds]
    text = ', '.join(parts)
    return text[:1].upper() + text[1:]


_TYPE_ORDER = ('Outfit mesh', 'Body mesh', 'Mesh', 'Material', 'Body texture', 'Texture', 'Blueprint', 'Physics',
               'Skeleton', 'Asset label')


def file_type(pkg, c):
    """What a package is, in words: 'Outfit mesh', 'Material', 'Body texture'..."""
    cls = _cls(c)
    if cls == 'SkeletalMesh':
        if is_skeletal_leaf(pkg):
            return 'Body mesh' if outfit_name(pkg) is None else 'Outfit mesh'
        return 'Mesh'
    if cls == 'StaticMesh':
        return 'Mesh'
    if cls.startswith('Material'):
        return 'Material'
    if cls.startswith('Texture'):
        return 'Body texture' if is_body_texture(pkg, c) else 'Texture'
    if is_blueprint(cls):
        return 'Blueprint'
    if cls == 'PhysicsAsset':
        return 'Physics'
    if cls == 'Skeleton':
        return 'Skeleton'
    if cls == 'PrimaryAssetLabel':
        return 'Asset label'
    return cls or 'File'


def option_files(classes):
    """[{path, type, game}] of a variant: every package, meshes first; game: it replaces a game file."""
    out = [{'path': p, 'type': file_type(p, c), 'game': bool((c or {}).get('override'))} for p, c in classes.items()]
    order = {t: i for i, t in enumerate(_TYPE_ORDER)}
    return sorted(out, key=lambda f: (order.get(f['type'], len(order)), leaf(f['path']).lower()))


def format_label(fmt):
    """'PF_BC7' -> 'BC7', 'PF_DXT1' -> 'DXT1'."""
    return re.sub(r'^PF_', '', fmt or '')


def is_label(c):
    return _cls(c) == 'PrimaryAssetLabel'


_PLAIN_ERRORS = [
    (r'no \.utoc in this folder', "Only a .pak file, no .utoc: this option can't be switched in game."),
    (r'is encrypted', "Its pak is encrypted, so it can't be repacked."),
    (r'different Unreal version', 'Its pak was built for a different version of the game engine.'),
    (r'container lists no /Game packages', 'Its pak contains no game assets.'),
    (r'could not find the real path', "Some files in its pak have no folder and couldn't be placed."),
    (r'could not be extracted', "Some files couldn't be unpacked from its pak."),
    (r'could not be resolved', 'It links to files that are in neither the game nor the mod.'),
    (r'could not hard-link', "Couldn't link the game's files into a work folder next to Paks. Is the game folder "
                             'read-only?'),
]


def plain_error(err):
    """A relocator message as a short sentence for the UI."""
    text = (err or '').strip()
    if not text:
        return 'Unknown error.'
    for pat, msg in _PLAIN_ERRORS:
        if re.search(pat, text, re.I):
            return msg
    m = re.match(r'retoc (\S+) failed: (.*)', text, re.S)
    if m:
        return f'retoc failed ({m.group(2).splitlines()[0][:140]}).'
    first = text.splitlines()[0].strip()
    if len(first) > 200:
        first = first[:197].rstrip() + '...'
    first = first[:1].upper() + first[1:]
    return first if first.endswith(('.', '!', '?', ')')) else first + '.'


def option_notes(r, classes, names=None):
    """Plain sentences from a variant's report entry. names: {package: [missing package paths]}
    when they could be read from the mod's files (missing_names())."""
    out = []
    for p, n in sorted((r.get('unresolved') or {}).items()):
        name = leaf(p)
        one = n == 1
        known = list((names or {}).get(p) or [])
        if known:
            shown = ', '.join(known[:2]) + (f' and {len(known) - 2} more' if len(known) > 2 else '')
            target = shown + (', which is' if len(known) == 1 else ', which are') + ' in neither the game nor the mod'
        else:
            target = "a file the mod doesn't include"
        if _cls(classes.get(p)).startswith('Material'):
            out.append(f"{'One texture link' if one else f'{n} texture links'} in {name} point{'s' if one else ''} to "
                       f"{target}; the menu fills {'it' if one else 'them'} in game.")
        else:
            out.append(f"{'One link' if one else f'{n} links'} in {name} point{'s' if one else ''} to {target}; "
                       f"the game leaves {'it' if one else 'them'} empty, as with the original mod.")
    for n in r.get('notes') or []:
        if "using the game's Skeleton" in n:
            out.append("Uses the game's skeleton, so animations keep working.")
        elif "using the game's PhysicsAsset" in n:
            out.append("Uses the game's physics instead of the mod's.")
        elif 'still overrides the game globally' in n:
            out.append("Its skeleton replaces the game's for every outfit.")
        elif 'logic mods are found by path' in n:
            out.append('Has a logic-mod part, which stays at its own path.')
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen


_DATA_CACHE = {}


def data_url(path):
    """A small PNG as a data: URL, or None."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_size, int(st.st_mtime))
    if key not in _DATA_CACHE:
        url = None
        if st.st_size < 256 * 1024:
            try:
                with open(path, 'rb') as f:
                    b = f.read()
                if b.startswith(b'\x89PNG\r\n\x1a\n'):
                    url = 'data:image/png;base64,' + base64.b64encode(b).decode('ascii')
            except OSError:
                url = None
        _DATA_CACHE[key] = url
    return _DATA_CACHE[key]


def opt_name(row, opt, multi_rows=True):
    """'Lune color · Lace dress: black' (the row only when the mod has several)."""
    return f'{row} \u00b7 {opt}' if multi_rows and row and row != opt else opt


def name_list(pairs, multi_rows=True, limit=3):
    """[(row, option)] -> 'A, B, C and 8 more'."""
    names = [opt_name(r, o, multi_rows) for r, o in pairs]
    return few(names, limit)


def few(names, limit=3):
    names = list(names)
    if len(names) <= limit:
        return ', '.join(names[:-1]) + (' and ' if len(names) > 1 else '') + (names[-1] if names else '')
    return ', '.join(names[:limit]) + f' and {len(names) - limit} more'


def names_of(paths, limit=3):
    """Package paths -> their last parts, 'T_A, T_B and 2 more'."""
    return few([leaf(p) for p in paths], limit)


# ------------------------------------------------------------------------------ the library view

class View:
    """One read of the library, the wardrobe registry and the reports."""

    def __init__(self, library, paks, lua_dir, active=()):
        self.library = library
        self.paks = paks
        self.lua_dir = lua_dir
        self.active = set(active or ())
        self.out_root = os.path.join(paks, '~mods', '_E33Wardrobe') if paks else None
        reg = paths.read_json(os.path.join(lua_dir, 'wardrobe_registry.json'), []) if lua_dir else []
        self.registry = [m for m in (reg if isinstance(reg, list) else []) if isinstance(m, dict) and m.get('name')]
        self.by_name = {m['name']: m for m in self.registry}
        self._reports = {}
        self._all_reports = None
        self._keys = {}
        self._shared = {}

    # -- discovery
    def mod_ids(self):
        ids = []
        if self.library and os.path.isdir(self.library):
            for n in sorted(os.listdir(paths.lp(self.library)), key=str.lower):
                if n.startswith(SKIP_LIBRARY) or n.lower().endswith('.old'):
                    continue
                f = os.path.join(self.library, n)
                if os.path.isdir(paths.lp(f)) and (has_paks(f) or n in self.by_name):   # not a mod: no paks
                    ids.append(n)
        low = {i.lower() for i in ids}
        ids += [m['name'] for m in self.registry if m['name'].lower() not in low]
        return sorted(ids, key=str.lower)

    def folder(self, mod_id):
        f = safe_child(self.library, mod_id)
        return f if f and os.path.isdir(paths.lp(f)) else None

    def resolve_output(self, path):
        """A registry output path, also after the game folder moved."""
        if not path:
            return None
        if os.path.isfile(path):
            return path
        if self.out_root:
            alt = os.path.join(self.out_root, os.path.basename(os.path.dirname(path)), os.path.basename(path))
            if os.path.isfile(alt):
                return alt
        return None

    def report_dir(self, name):
        reg = self.by_name.get(name)
        if reg:
            for s in reg.get('slots', []):
                for v in s.get('variants', []):
                    out = self.resolve_output(v.get('output'))
                    if out:
                        return os.path.dirname(out)
        if not self.out_root:
            return None
        cand = os.path.join(self.out_root, _t()['relocate'].safe_name(name))
        if os.path.isfile(os.path.join(cand, 'relocate_report.json')):
            rep = paths.read_json(os.path.join(cand, 'relocate_report.json'), {}) or {}
            if not rep or any(k.startswith(name + '/') for k in rep):
                return cand
        if self._all_reports is None:
            self._all_reports = {}
            if os.path.isdir(self.out_root):
                for d in os.listdir(self.out_root):
                    f = os.path.join(self.out_root, d, 'relocate_report.json')
                    if os.path.isfile(f):
                        rep = paths.read_json(f, {}) or {}
                        if isinstance(rep, dict):
                            for k in rep:
                                self._all_reports.setdefault(k.split('/', 1)[0], os.path.join(self.out_root, d))
        return self._all_reports.get(name)

    def report(self, name):
        if name not in self._reports:
            d = self.report_dir(name)
            rep = paths.read_json(os.path.join(d, 'relocate_report.json'), {}) if d else {}
            self._reports[name] = ({k: v for k, v in rep.items() if k.startswith(name + '/') and isinstance(v, dict)}
                                   if isinstance(rep, dict) else {})
        return self._reports[name]

    # -- one mod
    def structure(self, mod_id, folder, reg):
        """[(slot key, [(rel, relocator label)])] from the library folder, else from the registry."""
        if folder:
            slots = _t()['relocate'].option_slots(folder)
            return [(k, [(o['rel'], o['label']) for o in v]) for k, v in slots.items()]
        out = []
        for s in (reg or {}).get('slots', []):
            key = s.get('id', '').split('/', 1)[1] if '/' in s.get('id', '') else s.get('id', '')
            out.append((key, [(v['id'].split('/', 1)[1] if '/' in v['id'] else v['id'], v.get('label', ''))
                              for v in s.get('variants', [])]))
        return out

    def variant_swatches(self, r, regv, out_dir):
        """[(file path, texture package or None)] of a variant's swatches."""
        out = []
        names = list((r or {}).get('swatches') or [])
        texs = list((r or {}).get('swatch_textures') or [])
        output = self.resolve_output((r or {}).get('output') or (r or {}).get('kept_previous')
                                     or (regv or {}).get('output'))
        d = os.path.join(os.path.dirname(output), 'swatches') if output else (
            os.path.join(out_dir, 'swatches') if out_dir else None)
        if not d or not os.path.isdir(d):
            return out
        if not names and output:                     # e.g. a build kept from an earlier run
            stem = os.path.splitext(os.path.basename(output))[0]
            names = sorted(f for f in os.listdir(d) if re.fullmatch(re.escape(stem) + r'_\d+\.png', f))
        for i, n in enumerate(names):
            if isinstance(n, str) and re.fullmatch(r'[^\\/:]+\.png', n):
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    out.append((p, texs[i] if i < len(texs) else None))
        return out

    def describe(self, mod_id, swatches=True, names=False):
        """Everything about one mod: the ModDetails shape plus a few fields for the summary.
        names: also look up the names of files that links point to but nobody has (slower: reads the
        mod's paks; mod_details only)."""
        folder = self.folder(mod_id)
        reg = self.by_name.get(mod_id)
        if not folder and not reg:
            return None
        rep = self.report(mod_id)
        out_dir = self.report_dir(mod_id)
        reg_vars, reg_slots = {}, {}
        for s in (reg or {}).get('slots', []):
            key = s.get('id', '').split('/', 1)[-1]
            reg_slots[key] = s
            for v in s.get('variants', []):
                reg_vars[v.get('id')] = v
        struct = self.structure(mod_id, folder, reg)
        all_classes = {}
        for k, opts in struct:
            for rel, _l in opts:
                vid = f'{mod_id}/{rel}'
                r = rep.get(vid) or {}
                c = r.get('classes') or (reg_vars.get(vid) or {}).get('classes')
                if c:
                    all_classes.update(filled(c))
                elif folder:
                    all_classes.update(guessed_classes(folder_packages(os.path.join(folder, *rel.split('/')) if rel else folder)))
        outfit_mod = any(_cls(c) == 'SkeletalMesh' and is_skeletal_leaf(p) for p, c in all_classes.items())

        rows, chars_all, replaces, mod_swatches, skin_swatches, skin_images = [], [], [], [], [], []
        n_opts = n_failed = 0
        unresolved_opts = []            # (row label, option label, {package: links})
        names_cache = {}                # missing_names(): the mod's own packages, listed once
        tex_body = 0
        has_body = False
        installed_variants = 0
        missing_outputs = 0
        for key, opts in struct:
            label = row_label(key, mod_id, [r for r, _l in opts])
            slot = reg_slots.get(key) or {}
            row_chars, row_meshes, row_names = set(), set(), []
            options = []
            for rel, reloc_label in opts:
                n_opts += 1
                vid = f'{mod_id}/{rel}'
                r = rep.get(vid) or {}
                regv = reg_vars.get(vid)
                base = os.path.basename(rel) if rel else mod_id
                row_names.append(base)
                if regv:
                    installed_variants += 1
                    if not self.resolve_output(regv.get('output')):
                        missing_outputs += 1
                classes = r.get('classes') or (regv or {}).get('classes')
                guessed = False
                if classes:
                    classes = filled(classes)
                else:
                    pk = folder_packages(os.path.join(folder, *rel.split('/')) if rel else folder) if folder else []
                    classes = guessed_classes(pk)
                    guessed = True
                err = r.get('error')
                ok, error = True, None
                unresolved = {p: int(n) for p, n in (r.get('unresolved') or {}).items() if n}
                found = self.missing_names(folder, rel, unresolved, names_cache) if (names and unresolved and folder) else {}
                notes = option_notes(r, classes, found) if not guessed else []
                if err and r.get('kept_previous'):
                    notes.insert(0, f"Couldn't be prepared this time ({plain_error(err).rstrip('.')}); the menu keeps "
                                    'the earlier build.')
                elif err:
                    ok, error = False, plain_error(err)
                    n_failed += 1
                for p, c in classes.items():
                    ch = character_of(p)
                    if ch and (_cls(c) == 'SkeletalMesh' or c.get('override')):
                        row_chars.add(ch)
                    if _cls(c) == 'SkeletalMesh' and is_skeletal_leaf(p) and c.get('override', True):
                        row_meshes.add(p)
                kinds = texture_kinds(classes, outfit_mod)
                if 'body' in kinds:
                    has_body = True
                    tex_body = max(tex_body, kinds['body'])
                tags = []
                if any(_cls(c) == 'PhysicsAsset' for c in classes.values()):
                    tags.append('physics')
                if any('pakchunk' in n for n in (r.get('notes') or [])) or \
                        os.path.basename((r.get('output') or '')).lower().startswith('pakchunk'):
                    tags.append('own shaders')
                sw = self.variant_swatches(r, regv, out_dir) if swatches else []
                swatch = data_url(sw[0][0]) if sw else None
                images = self.option_images(vid, classes, sw, outfit_mod)
                for img in images:
                    if img['kind'] == 'Body' and img['swatch']:
                        if len(skin_swatches) < 4 and img['swatch'] not in skin_swatches:
                            skin_swatches.append(img['swatch'])
                        if not any(x['path'] == img['path'] and x['swatch'] == img['swatch'] for x in skin_images):
                            skin_images.append(img)
                if swatch:
                    mod_swatches.append((len(options), swatch))
                shown = option_label(base, label if label != mod_id else None)
                if ': ' in (reloc_label or '') and rel.count('/') >= 2:
                    shown = reloc_label.split(': ', 1)[0] + ': ' + shown
                missing = [{'in': p, 'name': leaf(p), 'links': n, 'texture': _cls(classes.get(p)).startswith('Material'),
                            'names': list(found.get(p) or [])} for p, n in sorted(unresolved.items())]
                if unresolved and not guessed:
                    unresolved_opts.append((label, shown, missing))
                options.append({'id': vid, 'label': shown, 'changes': changes_summary(classes),
                                'textures': texture_summary(classes, outfit_mod, guessed), 'tags': tags, 'swatch': swatch,
                                'ok': ok, 'error': error, 'notes': notes,
                                'files': option_files(classes) if not guessed else [],
                                'images': images, 'missing': missing})
            ch = slot.get('character') or character_of(key) or character_of(mod_id)
            if not ch and len(row_chars) == 1:
                ch = next(iter(row_chars))
            for c in ([ch] if ch else sorted(row_chars)):
                if c not in chars_all:
                    chars_all.append(c)
            for m in sorted(row_meshes):
                n = outfit_name(m)
                if n is None:
                    n = base_body_name(row_names, mod_id)
                if n not in replaces:
                    replaces.append(n)
            rows.append({'id': f'{mod_id}/{key}', 'label': label, 'character': ch, 'options': options})

        # state
        report_variants = [v for k, v in rep.items() if not k.endswith('/(shared)')]
        if mod_id in self.active:
            state = 'working'
        elif reg and installed_variants and not missing_outputs:
            state = 'ready'
        elif report_variants and all(v.get('error') and not v.get('kept_previous') for v in report_variants):
            state = 'failed'
        else:
            state = 'not_installed'

        multi_rows = len(rows) > 1
        notes = []
        if state == 'failed':
            notes.append({'level': 'warn', 'text': "None of the options could be prepared for the in-game menu."})
        elif n_failed:
            bad = [(row['label'], o['label']) for row in rows for o in row['options'] if o['ok'] is False]
            notes.append({'level': 'warn', 'text': f"{n_failed} of {n_opts} options couldn't be prepared and aren't "
                                                   f"in the menu: {name_list(bad, multi_rows)}.",
                          'items': [opt_name(rl, ol, multi_rows) for rl, ol in bad], 'what': 'options'})
        if missing_outputs:
            notes.append({'level': 'warn', 'text': 'Some prepared files are missing. Reinstall the mod.'})
        if unresolved_opts:
            n = len(unresolved_opts)
            items = []
            for rl, ol, miss in unresolved_opts:
                where = '; '.join(
                    f"{m['name']}: {plural(m['links'], 'link')}" + (f" to {few(m['names'], 2)}" if m['names'] else '')
                    for m in miss)
                items.append(f'{opt_name(rl, ol, multi_rows)} ({where})')
            notes.append({'level': 'info', 'text': f"{plural(n, 'option')} {'links' if n == 1 else 'link'} to files the "
                                                   f"mod doesn't include: "
                                                   f"{name_list([(rl, ol) for rl, ol, _m in unresolved_opts], multi_rows)}.",
                          'items': items, 'what': 'options'})
        if folder:
            for part in _t()['rules'].extra_parts(folder):
                notes.append({'level': 'info', 'text': f'Also has a {part} part. Install that part by hand, as the '
                                                       'mod page says.'})
        overlaps = self.overlaps(mod_id) if reg else []
        if reg:
            mine = self.shared_files(reg)
            for other in self.registry:
                if other['name'] == mod_id:
                    continue
                common = sorted(set(mine) & set(self.shared_files(other)))
                if common:
                    files = sorted({mine[p] for p in common}, key=str.lower)
                    notes.append({'level': 'warn',
                                  'text': f'"{other["name"]}" has {len(files)} of this mod\'s new files '
                                          f'({names_of(files)}). Two versions of one mod? Keep only one in the library.',
                                  'items': files, 'what': 'files'})

        who = ' and '.join(chars_all) if chars_all else ''
        if has_body:
            size = f' ({size_label(tex_body)})' if tex_body else ''
            text = f'Brings its own body textures{size}' + (f' for {who}.' if who else '.')
            if outfit_mod:
                text += " They show only with this mod's outfits."
        else:
            text = ''
        if folder:
            size_bytes = folder_size(folder)
        else:
            size_bytes = 0
            for v in reg_vars.values():
                out = self.resolve_output(v.get('output'))
                if out:
                    for ext in ('.utoc', '.ucas', '.pak'):
                        try:
                            size_bytes += os.path.getsize(out[:-5] + ext)
                        except OSError:
                            pass
        summary_swatches = []
        for _i, u in sorted(mod_swatches, key=lambda x: x[0]):      # first option of each row first
            if u not in summary_swatches:
                summary_swatches.append(u)
            if len(summary_swatches) >= 4:
                break
        return {
            'id': mod_id, 'name': mod_id, 'characters': chars_all, 'replaces': replaces, 'options': n_opts,
            'size': size_bytes, 'folder': folder, 'state': state, 'rows': rows,
            'skin': {'has': has_body, 'text': text, 'swatches': skin_swatches, 'images': skin_images},
            'overlaps': overlaps, 'notes': notes,
            '_swatches': summary_swatches,
        }

    def option_images(self, vid, classes, sw, outfit_mod):
        """The textures of one option for the image viewer: [{ref, name, path, kind, width, height,
        format, swatch}], the ones with a swatch first. ref = '<variant id>|<texture package>' (for
        texture_preview), or '<variant id>|#<n>' for a swatch whose texture isn't recorded."""
        by_tex, loose = {}, []
        low = {k.lower(): k for k in classes}
        for i, (p, tex) in enumerate(sw):
            key = low.get(tex.lower()) if tex else None
            if key and key not in by_tex:
                by_tex[key] = p
            elif not tex:
                loose.append((i, p))
        out = []
        for p, c in classes.items():
            if not _cls(c).startswith('Texture'):
                continue
            kind = 'Body' if is_body_texture(p, c) else ('Outfit' if outfit_mod else 'Texture')
            out.append({'ref': f'{vid}|{p}', 'name': leaf(p) or c.get('object') or p, 'path': p, 'kind': kind,
                        'width': int(c.get('width') or 0), 'height': int(c.get('height') or 0),
                        'format': format_label(c.get('format')), 'swatch': data_url(by_tex[p]) if p in by_tex else None})
        order = {t: i for i, t in enumerate(by_tex)}
        out.sort(key=lambda x: (order.get(x['path'], len(order)), x['name'].lower()))
        for i, p in loose:
            u = data_url(p)
            if u:
                out.insert(0, {'ref': f'{vid}|#{i}', 'name': os.path.basename(p), 'path': '', 'kind': '',
                               'width': 0, 'height': 0, 'format': '', 'swatch': u})
        return out

    def shared_files(self, mod):
        """{lower-case path: path} of a relocated mod's shared (mod-only) files, without its
        PrimaryAssetLabels: cook metadata that does nothing in game, which two different mods of one
        author often share."""
        if mod['name'] in self._shared:
            return self._shared[mod['name']]
        labels, case = set(), {}
        for s in mod.get('slots', []):
            for v in s.get('variants', []):
                for p, c in (v.get('classes') or {}).items():
                    case.setdefault(p.lower(), p)
                    if is_label(c):
                        labels.add(p.lower())
        out = {}
        for p in mod.get('shared') or []:
            low = p.lower()
            if low not in labels:
                out[low] = case.get(low, p)
        self._shared[mod['name']] = out
        return out

    def _variant_keys(self, mod):
        """{(character, original path): class info} of a relocated mod's game overrides."""
        if mod['name'] in self._keys:
            return self._keys[mod['name']]
        out = self._keys[mod['name']] = {}
        for s in mod.get('slots', []):
            key = s.get('id', '').split('/', 1)[-1]
            sch = s.get('character') or character_of(key) or character_of(mod['name'])
            for v in s.get('variants', []):
                for old in (v.get('map') or {}):
                    c = (v.get('classes') or {}).get(old, {})
                    if not c.get('override', True):
                        continue
                    out[(sch or character_of(old) or '', old)] = c
        return out

    def overlaps(self, mod_id):
        """[{mod, text, files}]: other relocated mods that replace the same game files for the same
        character. files: those game paths."""
        mod = self.by_name.get(mod_id)
        if not mod:
            return []
        mine = self._variant_keys(mod)
        res = []
        for other in self.registry:
            if other['name'] == mod_id:
                continue
            theirs = self._variant_keys(other)
            common = {k for k in set(mine) & set(theirs) if not is_label(mine[k]) and not is_label(theirs[k])}
            if not common:
                continue
            chars = sorted({c for c, _p in common if c})
            who = ' and '.join(chars)
            pk = sorted({p for _c, p in common}, key=str.lower)
            meshes = sorted({k[1] for k in common if _cls(mine[k]) == 'SkeletalMesh' or is_skeletal_leaf(k[1])})
            if meshes:
                names = []
                for m in meshes:
                    n = outfit_name(m) or 'base body'
                    if n not in names:
                        names.append(n)
                what = (f"{who}'s " if who else 'the ') + ' and '.join(names) + (' outfit' if len(names) == 1 else ' outfits')
                text = f'Both replace {what}.'
            elif any(is_body_texture(p) for p in pk):
                text = f"Both change {who + chr(39) + 's' if who else 'the'} body textures: {names_of(pk)}."
            else:
                text = f"Both change {plural(len(pk), 'game file')}" + (f' of {who}' if who else '') + f': {names_of(pk)}.'
            res.append({'mod': other['name'], 'text': text + ' In game, the one picked last shows.', 'files': pk})
        return res

    # -- names of files that links point to but nobody has

    def missing_names(self, folder, rel, unresolved, cache=None):
        """{package: [paths]} of the files the links in `unresolved` ({package: count}) point to,
        read from the option's own paks (the zen package keeps the names of the packages it imports;
        retoc drops the ones it can't find). {} when they can't be read."""
        try:
            from . import assets
            return assets.missing_names(self, folder, os.path.join(folder, *rel.split('/')) if rel else folder,
                                        unresolved, cache)
        except Exception:
            return {}


def summary_of(d):
    """ModSummary from a describe() result."""
    rows = [r for r in d['rows'] if r['options']]
    return {'id': d['id'], 'name': d['name'], 'state': d['state'], 'characters': d['characters'],
            'replaces': d['replaces'], 'options': d['options'], 'rows': len(rows), 'size': d['size'],
            'swatches': d['_swatches'][:4], 'notes': len(d['notes']), 'skin': d['skin']['has'],
            'note_level': ('warn' if any(n['level'] == 'warn' for n in d['notes'])
                           else 'info' if d['notes'] else None)}


def list_mods(view):
    out = []
    for mid in view.mod_ids():
        d = view.describe(mid)
        if d:
            out.append(summary_of(d))
    return out


def mod_details(view, mod_id):
    d = view.describe(mod_id, names=True)
    if d is None:
        return None
    d = dict(d)
    d.pop('_swatches', None)
    return d
