"""Read the file list of an Unreal IoStore container (.utoc) without the game.

Only the table of contents and directory index are parsed - enough to know which
asset paths a mod overrides. Encrypted containers are reported, not read. Also: the package
names a raw zen package chunk imports (from retoc unpack-raw), and fixing their letter case.
"""
import os
import struct

TOC_MAGIC = b'-==--==--==--==-'
FLAG_COMPRESSED, FLAG_ENCRYPTED, FLAG_SIGNED, FLAG_INDEXED = 1, 2, 4, 8


class UtocError(Exception):
    pass


def _fstring(buf, pos):
    n = struct.unpack_from('<i', buf, pos)[0]
    pos += 4
    if n == 0:
        return '', pos
    if n > 0:
        return buf[pos:pos + n - 1].decode('latin-1'), pos + n
    n = -n
    return buf[pos:pos + 2 * n - 2].decode('utf-16-le'), pos + 2 * n


def read_utoc(path):
    """Return dict(mount_point, files=[relative paths], chunks=[chunk id (hex) of each file], flags,
    version, container_id)."""
    with open(path, 'rb') as f:
        buf = f.read()
    if buf[:16] != TOC_MAGIC:
        raise UtocError(f'{path}: not a .utoc file')
    version = buf[16]
    (hdr_size, entry_count, block_count, block_entry_size, method_count, method_len,
     _block_size, dir_index_size, _partitions) = struct.unpack_from('<9I', buf, 20)
    container_id = struct.unpack_from('<Q', buf, 56)[0]
    flags = buf[80]
    seeds_count = struct.unpack_from('<I', buf, 84)[0]
    no_hash_count = struct.unpack_from('<I', buf, 96)[0]
    pos = hdr_size
    chunk_ids = buf[pos:pos + entry_count * 12]
    pos += entry_count * 12          # chunk ids
    pos += entry_count * 10          # offset/lengths
    if version >= 4:                 # PerfectHash
        pos += seeds_count * 4
    if version >= 5:                 # PerfectHashWithOverflow
        pos += no_hash_count * 4
    pos += block_count * block_entry_size
    pos += method_count * method_len
    if flags & FLAG_SIGNED:
        hash_size = struct.unpack_from('<i', buf, pos)[0]
        pos += 4 + 2 * hash_size + block_count * 20
    out = {'path': path, 'version': version, 'flags': flags, 'container_id': container_id,
           'mount_point': '', 'files': [], 'chunks': [], 'encrypted': bool(flags & FLAG_ENCRYPTED)}
    if not (flags & FLAG_INDEXED) or dir_index_size == 0 or out['encrypted']:
        return out
    d = buf[pos:pos + dir_index_size]
    p = 0
    mount, p = _fstring(d, p)
    n = struct.unpack_from('<i', d, p)[0]; p += 4
    dirs = [struct.unpack_from('<4I', d, p + 16 * i) for i in range(n)]; p += 16 * n
    n = struct.unpack_from('<i', d, p)[0]; p += 4
    files = [struct.unpack_from('<3I', d, p + 12 * i) for i in range(n)]; p += 12 * n
    n = struct.unpack_from('<i', d, p)[0]; p += 4
    strings = []
    for _ in range(n):
        s, p = _fstring(d, p)
        strings.append(s)
    NONE = 0xFFFFFFFF

    seen_dirs, seen_files = set(), set()

    def walk(di, prefix, depth=0):
        # a corrupt index can link entries in a cycle: every entry is visited at most once
        if di in seen_dirs or di >= len(dirs) or depth > 256:
            return
        seen_dirs.add(di)
        name, first_child, _sib, first_file = dirs[di]
        here = prefix + (strings[name] + '/' if name != NONE and name < len(strings) else '')
        fi = first_file
        while fi != NONE and fi < len(files) and fi not in seen_files:
            seen_files.add(fi)
            fname, nxt, user = files[fi]
            if fname < len(strings):
                out['files'].append(here + strings[fname])
                out['chunks'].append(chunk_ids[user * 12:user * 12 + 12].hex() if user < entry_count else '')
            fi = nxt
        c = first_child
        while c != NONE and c < len(dirs) and c not in seen_dirs:
            walk(c, here, depth + 1)
            c = dirs[c][2]
    if dirs:
        walk(0, '')
    out['mount_point'] = mount
    return out


def game_path(mount_point, rel):
    """'../../../' + 'Sandfall/Content/X/Y.uasset' -> '/Game/X/Y' (None for non-package files)."""
    full = (mount_point + rel).replace('\\', '/')
    while full.startswith('../'):
        full = full[3:]
    stem, ext = os.path.splitext(full)
    if ext.lower() not in ('.uasset', '.umap'):
        return None
    parts = stem.split('/')
    if parts[0] == 'Engine' and len(parts) > 2 and parts[1] == 'Content':
        return '/Engine/' + '/'.join(parts[2:])
    if 'Plugins' in parts and 'Content' in parts:
        i = parts.index('Content')
        return '/' + parts[i - 1] + '/' + '/'.join(parts[i + 1:])
    if len(parts) >= 3 and parts[1] == 'Content':
        return '/Game/' + '/'.join(parts[2:])
    return '/' + stem


def packages_in(utoc_path):
    info = read_utoc(utoc_path)
    pk = []
    for rel in info['files']:
        g = game_path(info['mount_point'], rel)
        if g:
            pk.append(g)
    return sorted(set(pk)), info


# ------------------------------------------------------------------------------ zen package headers

def _name_batch(buf, p):
    """An FNameBatch at p: ([(offset, length in bytes, wide, string)], end)."""
    n, = struct.unpack_from('<I', buf, p)
    p += 4
    if n == 0:
        return [], p
    nbytes, = struct.unpack_from('<I', buf, p)
    p += 4 + 8 + 8 * n                             # string bytes, hash version, hashes
    heads = struct.unpack_from(f'>{n}H', buf, p)
    p += 2 * n
    end, out = p + nbytes, []
    for h in heads:
        wide, ln = bool(h & 0x8000), h & 0x7FFF
        size = 2 * ln if wide else ln
        if p + size > end:
            raise UtocError('name batch runs past its end')
        # a lone UTF-16 surrogate must not lose the whole container's names (wide names are only read)
        out.append((p, size, wide, buf[p:p + size].decode('utf-16-le', 'surrogatepass') if wide
                    else buf[p:p + size].decode('latin-1')))
        p += size
    return out, end


def with_number(base, number):
    """An FName's text: number 0 is none, number n is '_<n-1>'."""
    return base if number == 0 else f'{base}_{number - 1}'


def _zen_summary(buf):
    """(header size, name map offset) of a UE5.4 zen package chunk, or UtocError."""
    if len(buf) < 52:
        raise UtocError('too short for a zen package header')
    has_ver, header_size = struct.unpack_from('<II', buf, 0)
    if has_ver not in (0, 1) or not 52 <= header_size <= len(buf):
        raise UtocError('not a zen package header')
    p = 52
    if has_ver:                                     # FZenPackageVersioningInfo
        p += 4 + 8 + 4                              # zen version, package file version, licensee
        n, = struct.unpack_from('<i', buf, p)
        if not 0 <= n < 1000:
            raise UtocError('bad versioning info')
        p += 4 + 20 * n                             # custom versions (guid, version)
    return header_size, p


def zen_package_name(buf):
    """The name a zen package chunk gives itself (FZenPackageSummary.Name, in its name map)."""
    try:
        header_size, p = _zen_summary(buf)
        index, number = struct.unpack_from('<II', buf, 8)
        names, end = _name_batch(buf, p)
    except struct.error as e:
        raise UtocError(f'malformed zen package header: {e}') from None
    index &= 0x3FFFFFFF                              # the top bits are the name's type
    if end > header_size or index >= len(names) or names[index][2]:
        raise UtocError('bad package name')
    return with_number(names[index][3], number)


def zen_imported_packages(buf):
    """[(offset, length, wide, base, number)] of the package names a UE5.4 zen package chunk
    imports (FZenPackageSummary.ImportedPackageNamesOffset: a name batch, then an int32 number per
    name). UtocError if the header isn't that layout."""
    try:
        header_size, _p = _zen_summary(buf)
        ipn_off, = struct.unpack_from('<i', buf, 48)
        if not 52 <= ipn_off < header_size:
            raise UtocError('no imported package names')
        names, end = _name_batch(buf, ipn_off)
        numbers = struct.unpack_from(f'<{len(names)}i', buf, end)
    except struct.error as e:
        raise UtocError(f'malformed zen package header: {e}') from None
    if end + 4 * len(names) > header_size:
        raise UtocError('imported package names run past the header')
    return [(off, size, wide, base, num) for (off, size, wide, base), num in zip(names, numbers)]


def fix_import_case(buf, real_names):
    """Give every imported package name that differs from a real package name only in letter case
    the real spelling. The game finds packages by an ID made from the lower-case name, so it
    resolves such links; retoc compares the names exactly and writes /Engine/UnknownPackage.
    real_names: {lower-case full name: real full name} - the packages' own names (the name in each
    package's header, which is what retoc compares with; a container's file index can be spelled
    differently). Only the base string is respelled, same length; UTF-16 names are left alone.
    Returns (new bytes, [(old, new)])."""
    out, changes = bytearray(buf), []
    for off, size, wide, base, number in zen_imported_packages(buf):
        full = with_number(base, number)
        real = real_names.get(full.lower())
        if wide or real is None or real == full or len(real) != len(full):
            continue
        suffix = full[len(base):]
        if real[len(base):] != suffix:
            continue
        try:
            new = real[:len(base)].encode('latin-1')
        except UnicodeEncodeError:
            continue
        if len(new) != size:
            continue
        out[off:off + size] = new
        changes.append((full, real))
    return bytes(out), changes


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        pk, info = packages_in(p)
        print(f'{p}: v{info["version"]} flags={info["flags"]} mount={info["mount_point"]!r} '
              f'{len(info["files"])} files')
        for f in info['files']:
            print('   ', f)
        for g in pk:
            print('  pkg', g)
