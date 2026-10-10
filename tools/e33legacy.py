"""Legacy (.uasset/.uexp) helpers for cooked UE5.4 packages, as produced by `retoc to-legacy`.

Two jobs:
  * read_package_info(): name map, imports and main export class, so tools know what an asset is.
  * relocate_tree(): move packages to new, SAME-LENGTH paths.
      - .uasset headers are rewritten structurally. Name entries whose whole string is a
        relocated path are renamed in place (export data that refers to them follows). Every
        header name reference (index + FName number) is then resolved to its full path; any
        reference that still needs the old string, or a numbered path such as
        '/Game/X/T_Body_1' (stored as entry '/Game/X/T_Body' + number 2), is pointed at an
        existing or newly appended entry (the header grows; later offsets are shifted).
        Limitation: a numbered reference inside export data to a vanilla sibling of a
        renamed entry would follow the rename - rare; headers are verified either way.
      - .uexp and shader asset-info JSON get a bounded byte replacement of whole paths;
        equal lengths keep every payload offset valid.
    The only consumer of these files is `retoc to-zen`, whose reader uses the header
    offsets, export SerialOffset - TotalHeaderSize, and the first
    NamesReferencedFromExportDataCount names.
"""
import hashlib
import os
import re
import struct

PKG_FILTER_EDITOR_ONLY = 0x80000000
ASSET_EXTS = ('.uasset', '.umap', '.uexp', '.ubulk', '.uptnl', '.m.ubulk')
HEADER_EXTS = ('.uasset', '.umap')
DATA_EXTS = ('.uexp',)


class LegacyError(Exception):
    pass


def _fstring(buf, pos):
    n = struct.unpack_from('<i', buf, pos)[0]
    pos += 4
    if n == 0:
        return '', pos
    if n > 0:
        return buf[pos:pos + n - 1].decode('utf-8', 'replace'), pos + n
    n = -n
    return buf[pos:pos + 2 * n - 2].decode('utf-16-le', 'replace'), pos + 2 * n


def _enc_fstring(s):
    if not s:
        return struct.pack('<i', 0)
    try:
        b = s.encode('ascii') + b'\0'
        return struct.pack('<i', len(b)) + b
    except UnicodeEncodeError:
        b = s.encode('utf-16-le') + b'\0\0'
        return struct.pack('<i', -(len(b) // 2)) + b


def split_number(name):
    """Unreal/retoc FName split: 'T_Body_1' -> ('T_Body', 2); 'T_04' -> ('T_04', 0)."""
    left, sep, right = name.rpartition('_')
    if sep and right.isdigit() and str(int(right)) == right and len(right) < 10:
        return left, int(right) + 1
    return name, 0


def join_number(base, number):
    return base if number == 0 else f'{base}_{number - 1}'


def read_summary(buf):
    """Parse FPackageFileSummary (UE5.0-5.4 cooked; unversioned = UE5.4) and record where
    every offset field lives, so a header can be grown. Returns a dict."""
    p = 0
    tag, legacy = struct.unpack_from('<Ii', buf, p); p += 8
    if tag != 0x9E2A83C1:
        raise LegacyError('not a legacy package (bad tag)')
    if legacy != -4:
        p += 4                                   # LegacyUE3Version
    ue4, = struct.unpack_from('<i', buf, p); p += 4
    ue5 = 0
    if legacy <= -8:
        ue5, = struct.unpack_from('<i', buf, p); p += 4
    p += 4                                       # licensee
    if legacy <= -9:
        raise LegacyError('UE5.5+ package summary not supported (E33 is UE5.4)')
    unversioned = ue4 == 0 and ue5 == 0
    v5 = 1013 if unversioned else ue5             # UE5.4 = up to ASSETREGISTRY_PACKAGEBUILDDEPENDENCIES
    if v5 >= 1014:
        raise LegacyError(f'package UE5 version {v5} (UE5.5+) not supported')
    ncustom, = struct.unpack_from('<i', buf, p); p += 4 + 20 * ncustom
    off = {}                                     # field -> (position, struct format)

    def field(name, fmt):
        nonlocal p
        off[name] = (p, fmt)
        v, = struct.unpack_from(fmt, buf, p)
        p += struct.calcsize(fmt)
        return v
    total_header = field('total_header', '<i')
    name_pos = p
    pkg_name, p = _fstring(buf, p)
    pkg_name_end = p
    flags, = struct.unpack_from('<I', buf, p); p += 4
    name_count = field('name_count', '<i')
    name_off = field('name_off', '<i')
    if v5 >= 1008:                               # ADD_SOFTOBJECTPATH_LIST
        soft_count = field('soft_count', '<i')
        field('soft_off', '<i')
    else:
        soft_count = 0
    if not (flags & PKG_FILTER_EDITOR_ONLY):
        _, p = _fstring(buf, p)                  # LocalizationId
    field('gather_count', '<i'); field('gather_off', '<i')
    export_count = field('export_count', '<i')
    export_off = field('export_off', '<i')
    import_count = field('import_count', '<i')
    import_off = field('import_off', '<i')
    depends_off = field('depends_off', '<i')
    softpkg_count = field('softpkg_count', '<i')
    field('softpkg_off', '<i')
    field('searchable_off', '<i')
    field('thumb_off', '<i')
    p += 16                                      # Guid
    if not (flags & PKG_FILTER_EDITOR_ONLY):
        p += 16                                  # PersistentGuid
    gens, = struct.unpack_from('<i', buf, p); p += 4 + 8 * gens
    for _ in range(2):                           # SavedBy / CompatibleWith engine version
        p += 10
        _, p = _fstring(buf, p)
    p += 4                                       # CompressionFlags
    chunks, = struct.unpack_from('<i', buf, p); p += 4 + 16 * chunks
    p += 4                                       # PackageSource
    extra, = struct.unpack_from('<i', buf, p); p += 4
    for _ in range(extra):
        _, p = _fstring(buf, p)
    if legacy > -7:
        p += 4                                   # NumTextureAllocations
    field('asset_registry_off', '<i')
    field('bulk_start', '<q')
    field('world_tile_off', '<i')
    nchunk, = struct.unpack_from('<i', buf, p); p += 4 + 4 * nchunk
    field('preload_count', '<i')
    field('preload_off', '<i')
    names_from_exports = field('names_from_exports', '<i') if v5 >= 1001 else name_count
    if v5 >= 1002:
        field('payload_toc_off', '<q')
    if v5 >= 1009:
        field('data_resource_off', '<i')
    import_size = 32 if v5 >= 1003 else 28
    if not (flags & PKG_FILTER_EDITOR_ONLY):
        import_size += 8
    return dict(legacy=legacy, ue5=v5, total_header=total_header, package_name=pkg_name,
                package_name_span=(name_pos, pkg_name_end), flags=flags, name_count=name_count,
                name_off=name_off, export_count=export_count, export_off=export_off,
                import_count=import_count, import_off=import_off, import_size=import_size,
                depends_off=depends_off, soft_count=soft_count, softpkg_count=softpkg_count,
                names_from_exports=names_from_exports, summary_end=p, fields=off)


def read_names(buf, s):
    """[(string, raw_entry_bytes)] for the name map."""
    names, p = [], s['name_off']
    for _ in range(s['name_count']):
        start = p
        n, p = _fstring(buf, p)
        p += 4                                   # two uint16 hashes (zero in cooked assets)
        names.append((n, buf[start:p]))
    return names, p


def _name_refs(buf, s):
    """Every name reference in the header that can be patched: list of (position, index, number)."""
    refs = []
    for i in range(s['import_count']):
        o = s['import_off'] + s['import_size'] * i
        for k in (0, 8, 20):                     # ClassPackage, ClassName, ObjectName
            idx, num = struct.unpack_from('<ii', buf, o + k)
            refs.append((o + k, idx, num))
    if s['export_count']:
        size = (s['depends_off'] - s['export_off']) // s['export_count']
        for i in range(s['export_count']):
            o = s['export_off'] + size * i + 16
            idx, num = struct.unpack_from('<ii', buf, o)
            refs.append((o, idx, num))
    if s['soft_count'] and 'soft_off' in s['fields']:
        p = struct.unpack_from('<i', buf, s['fields']['soft_off'][0])[0]
        for _ in range(s['soft_count']):
            for k in (0, 8):
                idx, num = struct.unpack_from('<ii', buf, p + k)
                refs.append((p + k, idx, num))
            _, p = _fstring(buf, p + 16)
    if s['softpkg_count']:
        p = struct.unpack_from('<i', buf, s['fields']['softpkg_off'][0])[0]
        for i in range(s['softpkg_count']):
            idx, num = struct.unpack_from('<ii', buf, p + 8 * i)
            refs.append((p + 8 * i, idx, num))
    return refs


def read_package_info(uasset_path=None, buf=None):
    if buf is None:
        buf = open(uasset_path, 'rb').read()
    s = read_summary(buf)
    entries, _ = read_names(buf, s)
    names = [n for n, _ in entries]

    def nm(idx, num=0):
        if not 0 <= idx < len(names):
            raise LegacyError(f'name index {idx} out of range')
        return join_number(names[idx], num)
    imports = []
    for i in range(s['import_count']):
        o = s['import_off'] + s['import_size'] * i
        cp, cpn, cn, cnn, outer, obj, objn = struct.unpack_from('<iiiiiii', buf, o)
        imports.append(dict(class_package=nm(cp, cpn), class_name=nm(cn, cnn), outer=outer, name=nm(obj, objn)))
    exports = []
    if s['export_count']:
        size = (s['depends_off'] - s['export_off']) // s['export_count']
        for i in range(s['export_count']):
            o = s['export_off'] + size * i
            cls, _sup, _tmpl, outer, obj, objn = struct.unpack_from('<iiiiii', buf, o)
            is_asset = struct.unpack_from('<i', buf, o + 68)[0] if size >= 72 else 0
            if cls < 0:
                cname = imports[-cls - 1]['name']
            elif cls > 0:
                ci, cn_ = struct.unpack_from('<ii', buf, s['export_off'] + size * (cls - 1) + 16)
                cname = 'export:' + nm(ci, cn_)
            else:
                cname = 'Class'
            exports.append(dict(name=nm(obj, objn), class_name=cname, outer=outer, is_asset=bool(is_asset)))
    main = next((e for e in exports if e['outer'] == 0 and e['is_asset']), None) or \
        next((e for e in exports if e['outer'] == 0), None)
    packages = [im['name'] for im in imports if im['class_name'] == 'Package' and im['outer'] == 0]
    return dict(summary=s, names=names, imports=imports, exports=exports, imported_packages=packages,
                main_class=main['class_name'] if main else None,
                main_name=main['name'] if main else None)


def rewrite_header(buf, mapping):
    """Redirect every package path in a .uasset header according to `mapping`
    ({old: new}, compared case-insensitively). Returns (new_bytes, stats)."""
    ci = {k.lower(): v for k, v in mapping.items()}
    s = read_summary(buf)
    entries, names_end = read_names(buf, s)
    names = [n for n, _ in entries]
    raw = [r for _, r in entries]
    refs = _name_refs(buf, s)
    # 1) in-place renames: entries whose whole string is a relocated path. Export data can only
    #    reference names below NamesReferencedFromExportDataCount; those references (unknown to
    #    us) keep following the entry, which matches the old whole-string behaviour.
    new_names = list(names)
    for i, n in enumerate(names):
        if n.lower() in ci:
            new_names[i] = ci[n.lower()]
    # 2) every header reference must resolve to its desired full name
    appended, patches, lookup = [], [], {}
    for i, n in enumerate(new_names):
        lookup.setdefault(n, i)
        lookup.setdefault(n.lower(), i)
    for pos, idx, num in refs:
        if not 0 <= idx < len(names):
            raise LegacyError(f'name index {idx} out of range at {pos}')
        full = join_number(names[idx], num)
        want = ci.get(full.lower(), full)
        if join_number(new_names[idx], num) == want:
            continue
        base, n2 = split_number(want)
        j = lookup.get(base, lookup.get(base.lower()))
        if j is None:
            j = len(new_names)
            new_names.append(base)
            appended.append(base)
            lookup[base] = lookup[base.lower()] = j
        patches.append((pos, j, n2))
    # 3) rebuild: summary (package name) + name map + rest, shifting offsets after the names
    old_pkg = s['package_name']
    new_pkg = ci.get(old_pkg.lower(), old_pkg)
    if len(new_pkg) != len(old_pkg):
        raise LegacyError('relocation must keep path length')
    out = bytearray(buf[:s['name_off']])
    a, b = s['package_name_span']
    out[a:b] = _enc_fstring(new_pkg)
    for i in range(len(names)):
        if new_names[i] != names[i]:
            if len(new_names[i]) != len(names[i]):
                raise LegacyError('in-place name rewrite must keep length')
            out += _enc_fstring(new_names[i]) + raw[i][-4:]
        else:
            out += raw[i]
    for n in appended:
        out += _enc_fstring(n) + b'\0\0\0\0'
    delta = len(out) - names_end
    rest = bytearray(buf[names_end:])
    out += rest
    if delta:
        for name, (pos, fmt) in s['fields'].items():
            if name.endswith('_off') or name in ('bulk_start', 'payload_toc_off', 'total_header',
                                                 'data_resource_off', 'asset_registry_off'):
                v, = struct.unpack_from(fmt, out, pos)
                if name == 'total_header' or v >= names_end:
                    struct.pack_into(fmt, out, pos, v + delta)
        struct.pack_into('<i', out, s['fields']['name_count'][0], len(new_names))
        s2 = read_summary(bytes(out))
        if s2['export_count']:
            size = (s2['depends_off'] - s2['export_off']) // s2['export_count']
            for i in range(s2['export_count']):
                o = s2['export_off'] + size * i + 36
                v, = struct.unpack_from('<q', out, o)
                struct.pack_into('<q', out, o, v + delta)
    for pos, j, n2 in patches:
        struct.pack_into('<ii', out, pos + (delta if pos >= names_end else 0), j, n2)
    return bytes(out), {'renamed_entries': sum(1 for i in range(len(names)) if new_names[i] != names[i]),
                        'appended_names': len(appended), 'patched_refs': len(patches), 'growth': delta}


def verify_rewrite(old_buf, new_buf, mapping):
    """Raise if any import/export/package name of the rewritten header is not what `mapping` implies."""
    ci = {k.lower(): v for k, v in mapping.items()}
    a = read_package_info(buf=old_buf)
    b = read_package_info(buf=new_buf)
    want_pkg = ci.get(a['summary']['package_name'].lower(), a['summary']['package_name'])
    if b['summary']['package_name'] != want_pkg:
        raise LegacyError(f'package name {b["summary"]["package_name"]!r} != {want_pkg!r}')
    if len(a['imports']) != len(b['imports']) or len(a['exports']) != len(b['exports']):
        raise LegacyError('import/export count changed')
    for x, y in zip(a['imports'], b['imports']):
        for k in ('class_package', 'class_name', 'name'):
            want = ci.get(x[k].lower(), x[k])
            if y[k] != want:
                raise LegacyError(f'import {x[k]!r} became {y[k]!r}, expected {want!r}')
    for x, y in zip(a['exports'], b['exports']):
        if y['name'] != ci.get(x['name'].lower(), x['name']):
            raise LegacyError(f'export {x["name"]!r} became {y["name"]!r}')
    if b['summary']['names_from_exports'] != a['summary']['names_from_exports']:
        raise LegacyError('NamesReferencedFromExportDataCount changed')
    return True


# ---------------------------------------------------------------------------- paths

def rel_to_package(rel):
    """'Sandfall/Content/A/B.uasset' -> ('/Game/A/B', '.uasset'). None if not under Content."""
    rel = rel.replace('\\', '/')
    for ext in sorted(ASSET_EXTS, key=len, reverse=True):
        if rel.lower().endswith(ext):
            stem, e = rel[:-len(ext)], rel[-len(ext):]
            break
    else:
        return None
    parts = stem.split('/')
    if len(parts) >= 3 and parts[1] == 'Content':
        return '/Game/' + '/'.join(parts[2:]), e
    return None


_SAFE_PKG = re.compile(r'/Game(/[^/\\:*?"<>|\x00-\x1f]+)+')


def safe_package(pkg):
    """A /Game/... package name that is safe to turn into a file path: no '.', '..' or empty
    segments and no characters Windows forbids (names come from files inside downloaded mods)."""
    return bool(pkg) and bool(_SAFE_PKG.fullmatch(pkg)) and \
        not any(seg in ('.', '..') for seg in pkg.split('/')[2:])


def package_to_rel(pkg, project='Sandfall'):
    if not safe_package(pkg):
        raise LegacyError(f'{pkg!r}: not a valid /Game/ package name')
    return f'{project}/Content/' + pkg[len('/Game/'):]


TOKEN_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
# Characters UE forbids in long package names (FPackageName::InvalidLongPackageCharacters)
# plus controls/space and NUL: a package path always ends right before one of these.
_INVALID = b'\\:*?"<>|\' ,.&!~@#'
_BOUND = rb'\x00-\x20' + b''.join(re.escape(bytes([c])) for c in _INVALID)


def _token(seed, length):
    """Deterministic folder token of any length: 'ZW' + base32-ish digest characters."""
    raw = hashlib.shake_256(seed.encode()).digest(max(length, 2))
    body = ''.join(TOKEN_ALPHABET[b % len(TOKEN_ALPHABET)] for b in raw)
    return ('ZW' + body)[:length] if length >= 4 else body[:length]


def plan_relocation(packages, variant_id, used=None):
    """Map each /Game/... package to a unique path of identical length.

    The longest directory segment is replaced by a token derived from variant_id, so
    the asset leaf names (and thus object names) stay untouched. `used` (lower-cased
    paths) should be shared across a whole run so different variants never collide.
    """
    used = set() if used is None else used
    mapping = {}
    for pkg in sorted(packages):
        if not pkg.isascii():
            raise LegacyError(f'{pkg}: non-ASCII package paths are not supported')
        if not safe_package(pkg):
            raise LegacyError(f'{pkg}: only /Game/ packages with a valid path can be relocated')
        parts = pkg.split('/')                   # ['', 'Game', d1, ..., leaf]
        dirs = list(range(2, len(parts) - 1))
        # A package directly under /Game ('/Game/chic_MyMod') has no folder to rename, so its
        # leaf gets the token instead. The object inside keeps its name; loads use the full
        # object path ('/Game/ZW....chic_MyMod'), which Unreal allows.
        seg = max(dirs, key=lambda i: (len(parts[i]), -i)) if dirs else len(parts) - 1
        if len(parts[seg]) < 3:
            raise LegacyError(f'{pkg}: no directory segment long enough (3+ chars) for a unique token')
        for salt in range(200):
            new = parts[:]
            new[seg] = _token(f'{variant_id}|{parts[seg]}|{seg}|{salt}', len(parts[seg]))
            newpkg = '/'.join(new)
            if newpkg.lower() not in used and newpkg.lower() != pkg.lower():
                break
        else:
            raise LegacyError(f'{pkg}: could not find a free relocation path')
        used.add(newpkg.lower())
        if len(newpkg) != len(pkg):
            raise LegacyError(f'internal error: relocation changed length of {pkg}')
        mapping[pkg] = newpkg
    return mapping


def _replace_paths(data, mapping):
    """Replace whole package paths (ASCII, case-insensitive like UE, and UTF-16).

    A match must not continue a path on the left ('x/Game/..') and must be followed by a
    character that cannot be part of a package path, so '/Game/A/T_Body' does not match
    inside '/Game/A/T_Body(1)', but does match in '(Mesh=/Game/A/T_Body.T_Body)'.
    Returns (data, count)."""
    total = 0
    for old, new in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        ob, nb = old.encode('ascii'), new.encode('ascii')
        pat = re.compile(rb'(?<![A-Za-z0-9_\-/])' + re.escape(ob) + rb'(?![^' + _BOUND + rb'])',
                         re.IGNORECASE)
        data, n = pat.subn(nb, data)
        total += n
        ob16, nb16 = old.encode('utf-16-le'), new.encode('utf-16-le')
        pat16 = re.compile(rb'(?<![A-Za-z0-9_\-/]\x00)' + re.escape(ob16) +
                           rb'(?=(?:[' + _BOUND + rb']\x00)|$)', re.IGNORECASE)
        data, n = pat16.subn(nb16, data)
        total += n
    return data, total


def relocate_tree(src_root, dst_root, mapping, project='Sandfall'):
    """Copy a legacy asset tree to dst_root, moving and rewriting packages in `mapping`.

    Every header (.uasset/.umap) in the tree is rewritten structurally and verified, so
    packages that are not relocated themselves still import the relocated paths. Export
    data (.uexp) and shader asset-info JSON get the bounded same-length byte rewrite.
    """
    report = {'moved': [], 'rewrites': 0, 'files': 0, 'appended_names': 0, 'patched_refs': 0}
    for dirpath, _dirs, files in os.walk(src_root):
        for fn in files:
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, src_root).replace(os.sep, '/')
            info = rel_to_package(rel)
            out_rel = rel
            if info and info[0] in mapping:
                out_rel = package_to_rel(mapping[info[0]], project) + info[1]
                report['moved'].append((rel, out_rel))
            data = open(src, 'rb').read()
            low = fn.lower()
            if low.endswith(HEADER_EXTS):
                new, st = rewrite_header(data, mapping)
                try:
                    verify_rewrite(data, new, mapping)
                except LegacyError as e:
                    raise LegacyError(f'{rel}: {e}') from None
                report['rewrites'] += st['renamed_entries'] + st['patched_refs']
                report['appended_names'] += st['appended_names']
                report['patched_refs'] += st['patched_refs']
                data = new
            elif low.endswith(DATA_EXTS) or low.endswith('.json') or 'shaderassetinfo' in low:
                data, n = _replace_paths(data, mapping)
                report['rewrites'] += n
            dst = os.path.join(dst_root, *out_rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(data)
            report['files'] += 1
    return report


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        info = read_package_info(p)
        s = info['summary']
        print(f"{p}\n  package={s['package_name']} names={s['name_count']} imports={s['import_count']} "
              f"exports={s['export_count']} main={info['main_name']} ({info['main_class']})")
