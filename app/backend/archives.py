"""Unpacking dropped mod archives (zip, 7z, rar) and folders into a mod folder for the library.

Nexus file names look like "<file name>-<mod id>-<version...>-<unix time>.7z". Several dropped
files of one Nexus mod become ONE mod with an option folder per file; its name comes from Nexus
(public GraphQL API, optional) or from the file names.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from . import paths

ARCHIVE_EXTS = ('.zip', '.7z', '.rar')
PAK_EXTS = ('.pak', '.utoc', '.ucas')
JUNK = {'__macosx', '.ds_store', 'thumbs.db', 'desktop.ini'}
GAME_PARTS = {'sandfall', 'content', 'paks', '~mods', 'mods'}      # folders of the game's layout
NEXUS_GAME = 'clairobscurexpedition33'
NEXUS_API = 'https://api.nexusmods.com/v2/graphql'
_NEXUS_RE = re.compile(r'^(?P<name>.*?\S)-(?P<modid>\d+)(?P<ver>(?:-[0-9A-Za-z.]+)+)-(?P<ts>\d{9,11})$')
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)} | {f'LPT{i}' for i in range(1, 10)}
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


class ArchiveError(Exception):
    """A plain sentence for the user."""


# ------------------------------------------------------------------------------ names

def split_ext(filename):
    low = filename.lower()
    for ext in ARCHIVE_EXTS:
        if low.endswith(ext):
            return filename[:-len(ext)], ext
    return filename, ''


def is_archive(path):
    return os.path.isfile(path) and split_ext(os.path.basename(path))[1] != ''


def parse_nexus_name(stem):
    """'840 Expedition 1 (Crop Top)-337-2-1-1750919736' -> ('840 Expedition 1 (Crop Top)', 337, '2-1',
    1750919736); None if the name has no Nexus suffix."""
    m = _NEXUS_RE.match(stem.strip())
    if not m:
        return None
    return m.group('name').strip(), int(m.group('modid')), m.group('ver')[1:], int(m.group('ts'))


def file_name_part(path):
    """The name of a dropped file or folder without extension and Nexus suffix."""
    stem = split_ext(os.path.basename(os.path.normpath(path)))[0]
    n = parse_nexus_name(stem)
    return n[0] if n else stem.strip()


def nexus_id(path):
    n = parse_nexus_name(split_ext(os.path.basename(os.path.normpath(path)))[0])
    return n[1] if n else None


def sanitize_name(s, maxlen=80):
    """A folder name Windows accepts (no reserved characters or names, no trailing dot or space)."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', s or '')
    s = re.sub(r'\s+', ' ', s).strip().lstrip('.').strip()
    s = s[:maxlen].rstrip('. ')
    while s.lower().endswith('.old'):
        s = s[:-4].rstrip('. ')
    if s.split('.')[0].strip().upper() in _RESERVED:
        s += '_'
    return s or 'Mod'


def common_words(names):
    """Longest common leading words of option names, without leading numbers and dashes:
    ['840 Expedition 1 (Crop Top)', '840 Expedition 2 ...'] -> 'Expedition'; '' if none."""
    split = [re.split(r'[\s_]+', n.strip()) for n in names if n and n.strip()]
    if not split:
        return ''
    common = []
    for words in zip(*split):
        if all(w.lower() == words[0].lower() for w in words):
            common.append(words[0])
        else:
            break
    while common and re.fullmatch(r'[\d\W]*', common[0]):       # leading numbers, '-', '.'
        common.pop(0)
    while common and re.fullmatch(r'\W*', common[-1]):
        common.pop()
    text = ' '.join(common).strip(' -_.,')
    return text if re.search(r'[^\W\d]', text) else ''


_NAME_CACHE = {}


def _graphql(query, timeout):
    req = urllib.request.Request(NEXUS_API, data=json.dumps({'query': query}).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'User-Agent': 'E33Wardrobe/' + paths.app_version()})
    with urllib.request.urlopen(req, timeout=timeout) as r:          # nosec - fixed https URL
        return json.loads(r.read().decode('utf-8'))


def nexus_mod_name(mod_id, timeout=5):
    """The mod's name on Nexus, or None (offline, E33_OFFLINE set, or any error). Cached."""
    if mod_id is None:
        return None
    key = str(mod_id)
    if key in _NAME_CACHE:
        return _NAME_CACHE[key]
    cache_file = os.path.join(paths.app_data_dir(), 'nexus_names.json')
    cache = paths.read_json(cache_file, {}) or {}
    if isinstance(cache, dict) and isinstance(cache.get(key), str):
        _NAME_CACHE[key] = cache[key]
        return cache[key]
    if os.environ.get('E33_OFFLINE'):
        return None
    q = ('{ legacyModsByDomain(ids:[{gameDomain:"%s", modId:%d}]) { nodes { name } } }' % (NEXUS_GAME, int(mod_id)))
    try:
        data = _graphql(q, timeout)
        name = data['data']['legacyModsByDomain']['nodes'][0]['name']
        if not isinstance(name, str) or not name.strip():
            return None
    except Exception:
        return None
    name = name.strip()
    _NAME_CACHE[key] = name
    try:
        if not isinstance(cache, dict):
            cache = {}
        cache[key] = name
        paths.write_json(cache_file, cache)
    except OSError:
        pass
    return name


# ------------------------------------------------------------------------------ planning drops

def has_paks(folder):
    for _dp, ds, fs in os.walk(paths.lp(folder)):
        ds[:] = [d for d in ds if not d.startswith('.')]
        if any(f.lower().endswith(PAK_EXTS) for f in fs):
            return True
    return False


def archives_in(folder, depth=2):
    out = []
    base = paths.lp(folder)
    for dp, ds, fs in os.walk(base):
        if dp[len(base):].count(os.sep) >= depth - 1:
            ds[:] = []
        out += [os.path.join(dp, f) for f in sorted(fs) if split_ext(f)[1]]
    return sorted(out)


def plan_items(items):
    """Group dropped paths into mods: [{'items': [path...], 'modid': id|None}], plus the paths
    that aren't archives or folders. Files of one Nexus mod form one group; a folder holding only
    archives counts as those archives."""
    flat, bad = [], []
    for p in items or []:
        if not isinstance(p, str) or not p.strip():
            continue
        p = os.path.abspath(p.strip().strip('"'))
        if os.path.isdir(p):
            inner = [] if has_paks(p) else archives_in(p)
            flat += inner if inner else [p]
        elif is_archive(p):
            flat.append(p)
        else:
            bad.append(p)
    groups, by_id = [], {}
    for p in flat:
        mid = nexus_id(p)
        if mid is not None:
            if mid not in by_id:
                by_id[mid] = {'items': [], 'modid': mid}
                groups.append(by_id[mid])
            if p not in by_id[mid]['items']:
                by_id[mid]['items'].append(p)
        else:
            groups.append({'items': [p], 'modid': None})
    for g in groups:
        g['items'].sort(key=lambda x: os.path.basename(x).lower())
    return groups, bad


def group_label(group):
    """Job name: the file name, or the first file's name and how many more."""
    first = os.path.basename(group['items'][0])
    n = len(group['items'])
    return first if n == 1 else f'{first} and {n - 1} more'


def group_size(group):
    total = 0
    for p in group['items']:
        if os.path.isdir(p):
            for dp, _ds, fs in os.walk(paths.lp(p)):
                for f in fs:
                    try:
                        total += os.path.getsize(os.path.join(dp, f))
                    except OSError:
                        pass
        else:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
    return total


# ------------------------------------------------------------------------------ extracting

def check_member(name, archive):
    """Path parts of an archive member; refuses absolute names and '..' (zip-slip)."""
    n = (name or '').replace('\\', '/')
    if n.startswith('/') or re.match(r'^[A-Za-z]:', n):
        raise ArchiveError(f'{os.path.basename(archive)} has a file with an absolute path ({name}). Not unpacked.')
    parts = [x for x in n.split('/') if x not in ('', '.')]
    if any(x == '..' for x in parts):
        raise ArchiveError(f'{os.path.basename(archive)} has a file that would land outside its folder ({name}). '
                           'Not unpacked.')
    return parts


def _extract_zip(path, dest):
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ArchiveError(f'{os.path.basename(path)} is damaged or not a zip file ({e}).')
    with zf:
        infos = zf.infolist()
        for info in infos:
            check_member(info.filename, path)
            if info.flag_bits & 0x1:
                raise ArchiveError(f'{os.path.basename(path)} is password-protected. Unpack it yourself and drop '
                                   'the folder.')
        for info in infos:
            parts = check_member(info.filename, path)
            if not parts:
                continue
            target = os.path.join(dest, *parts)
            if info.is_dir():
                os.makedirs(paths.lp(target), exist_ok=True)
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:      # a symlink: never followed
                continue
            os.makedirs(paths.lp(os.path.dirname(target)), exist_ok=True)
            try:
                with zf.open(info) as src, open(paths.lp(target), 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
            except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError) as e:
                raise ArchiveError(f'Could not unpack {info.filename} from {os.path.basename(path)}: {e}')


def _extract_7z(path, dest):
    try:
        import py7zr
    except ImportError:
        raise ArchiveError('7z files need py7zr, which is missing from this build.')
    try:
        with py7zr.SevenZipFile(path, 'r') as z:
            if z.needs_password():
                raise ArchiveError(f'{os.path.basename(path)} is password-protected. Unpack it yourself and drop '
                                   'the folder.')
            for info in z.list():
                check_member(info.filename, path)
                if getattr(info, 'is_symlink', False):
                    raise ArchiveError(f'{os.path.basename(path)} contains a link ({info.filename}). Not unpacked.')
            z.extractall(path=dest)
    except ArchiveError:
        raise
    except Exception as e:      # py7zr raises many kinds: Bad7zFile, PasswordRequired, CrcError, ...
        if type(e).__name__ == 'PasswordRequired':
            raise ArchiveError(f'{os.path.basename(path)} is password-protected. Unpack it yourself and drop '
                               'the folder.')
        raise ArchiveError(f'{os.path.basename(path)} could not be unpacked ({type(e).__name__}: {e}).')


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    out = (p.stdout + p.stderr).decode('utf-8', errors='replace')
    return p.returncode, out


def _last_line(out):
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    return lines[-1] if lines else 'no output'


def rar_tool():
    """('7z', path) or ('unrar', path) or None."""
    p = paths.find_7z()
    if p:
        return '7z', p
    p = paths.find_unrar()
    if p:
        return 'unrar', p
    return None


def _extract_rar(path, dest):
    tool = rar_tool()
    if not tool:
        raise ArchiveError('RAR needs 7-Zip. Install 7-Zip (7-zip.org) and try again, or unpack the file '
                           'yourself and drop the folder.')
    kind, exe = tool
    if kind == '7z':
        rc, out = _run([exe, 'l', '-slt', '-ba', '-pE33Wardrobe', '--', path])
        names = [ln[7:] for ln in out.splitlines() if ln.startswith('Path = ')]
        names = [n for n in names if os.path.normcase(n) != os.path.normcase(path)]
    else:
        rc, out = _run([exe, 'lb', '-p-', path])
        names = [ln for ln in out.splitlines() if ln.strip()]
    if rc != 0:
        if 'password' in out.lower() or 'encrypted' in out.lower():
            raise ArchiveError(f'{os.path.basename(path)} is password-protected. Unpack it yourself and drop '
                               'the folder.')
        raise ArchiveError(f'{os.path.basename(path)} could not be read: {_last_line(out)}')
    for n in names:
        check_member(n, path)
    if kind == '7z':
        rc, out = _run([exe, 'x', '-y', '-bd', '-pE33Wardrobe', '-o' + dest, '--', path])
    else:
        rc, out = _run([exe, 'x', '-y', '-o+', '-p-', path, dest + os.sep])
    if rc != 0:
        raise ArchiveError(f'{os.path.basename(path)} could not be unpacked: {_last_line(out)}')


def _plain(p):
    return p[4:] if p.startswith('\\\\?\\') else p


def _verify_tree(dest, archive):
    """Remove links and make sure nothing landed outside `dest`."""
    real = _plain(os.path.realpath(dest))
    for dp, ds, fs in os.walk(paths.lp(dest)):
        for n in ds + fs:
            p = os.path.join(dp, n)
            if os.path.islink(p):
                os.remove(p)
                continue
            if not paths.is_inside(_plain(os.path.realpath(p)), real):
                raise ArchiveError(f'{os.path.basename(archive)} has a file outside its folder. Not unpacked.')


def extract_archive(path, dest):
    """Unpack a zip, 7z or rar into `dest` (created). Raises ArchiveError with a plain sentence."""
    ext = split_ext(os.path.basename(path))[1]
    os.makedirs(dest, exist_ok=True)
    if ext == '.zip':
        _extract_zip(path, dest)
    elif ext == '.7z':
        _extract_7z(path, dest)
    elif ext == '.rar':
        _extract_rar(path, dest)
    else:
        raise ArchiveError(f'{os.path.basename(path)} is not a zip, 7z or rar file.')
    _verify_tree(dest, path)


def strip_wrapper(folder, wrapper=True, names=(), depth=8):
    """Descend through a folder that holds only one folder (and maybe a readme): the archive's own
    wrapper folder (`wrapper`), then only folders of the game's layout (Sandfall, Content, Paks,
    ~mods) or a repeat of the mod's name (`names`). 'Mod/Sandfall/Content/Paks/~mods/<paks>' ->
    the folder with the paks; 'Mod/Lune outfit/<options>' keeps 'Lune outfit' (a menu row)."""
    known = {n.lower() for n in names if n}
    for _ in range(depth):
        try:
            entries = [e for e in os.listdir(paths.lp(folder)) if e.lower() not in JUNK]
        except OSError:
            return folder
        dirs = [e for e in entries if os.path.isdir(os.path.join(paths.lp(folder), e))]
        files = [e for e in entries if e not in dirs]
        if len(dirs) != 1 or any(f.lower().endswith(PAK_EXTS + ARCHIVE_EXTS) for f in files) or len(files) > 3:
            return folder
        child = dirs[0]
        if not (wrapper or child.lower() in GAME_PARTS or child.lower() in known):
            return folder
        known.add(child.lower())
        wrapper = False
        folder = os.path.join(folder, child)
    return folder


def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(paths.lp(src), paths.lp(dst))


def _copy_tree(src, dst):
    shutil.copytree(paths.lp(src), paths.lp(dst), symlinks=False,
                    ignore=shutil.ignore_patterns('.git', '__MACOSX', 'Thumbs.db', 'desktop.ini'))


def _unique(name, taken):
    base, n = name, 2
    while name.lower() in taken:
        name = f'{base} {n}'
        n += 1
    taken.add(name.lower())
    return name


def _contents(item, work):
    """Unpack (archive) or locate (folder) one dropped item; returns (folder with its contents,
    copy_needed). Wrapper folders are stripped."""
    names = [file_name_part(item), os.path.basename(os.path.normpath(item))]
    if os.path.isdir(item):
        return strip_wrapper(item, wrapper=False, names=names), True
    dest = tempfile.mkdtemp(prefix='a', dir=work)
    extract_archive(item, dest)
    return strip_wrapper(dest, names=names), False


def unpack_group(group, work, library=None, lookup=None):
    """Turn one group of dropped items into a mod folder inside `work` (same drive as the
    library). Returns dict(name, folder, in_place, notes). `in_place`: a folder already in the
    library is used where it is. Raises ArchiveError."""
    items = group['items']
    lookup = lookup or nexus_mod_name
    notes = []
    os.makedirs(work, exist_ok=True)
    if len(items) == 1:
        item = items[0]
        name = file_name_part(item)
        if os.path.isdir(item) and library and os.path.normcase(os.path.dirname(os.path.abspath(item))) \
                == os.path.normcase(os.path.abspath(library)):
            return {'name': os.path.basename(item), 'folder': item, 'in_place': True, 'notes': notes}
        folder, copy = _contents(item, work)
        inner = [] if has_paks(folder) else archives_in(folder)
        if inner:                                 # an archive of archives (a "pack" download)
            sub = {'items': inner, 'modid': None}
            ids = {nexus_id(p) for p in inner}
            if len(ids) == 1 and None not in ids:
                sub['modid'] = ids.pop()
            res = _unpack_many(sub, work, lookup, fallback=name)
            res['notes'] = notes + res['notes']
            return res
        if copy:
            dst = os.path.join(work, 'mod')
            _copy_tree(folder, dst)
            folder = dst
        return {'name': sanitize_name(name), 'folder': folder, 'in_place': False, 'notes': notes}
    return _unpack_many(group, work, lookup)


def _unpack_many(group, work, lookup, fallback=None):
    items = group['items']
    names = [file_name_part(p) for p in items]
    name = lookup(group['modid']) if group.get('modid') is not None else None
    # offline: the files' shared words, else "Nexus mod 337" (better than the first file's name)
    name = (name or fallback or common_words(names)
            or (f'Nexus mod {group["modid"]}' if group.get('modid') is not None else names[0]))
    mod = os.path.join(work, 'mod')
    os.makedirs(mod, exist_ok=True)
    taken = set()
    notes = []
    for item, opt in zip(items, names):
        folder, copy = _contents(item, work)
        opt = _unique(sanitize_name(opt), taken)
        dst = os.path.join(mod, opt)
        if copy:
            _copy_tree(folder, dst)
        else:
            _move(folder, dst)
        if not has_paks(dst):
            notes.append(f'{os.path.basename(item)} has no game files (.utoc or .pak).')
    return {'name': sanitize_name(name), 'folder': mod, 'in_place': False, 'notes': notes}
