"""Read the file list of an Unreal IoStore container (.utoc) without the game.

Only the table of contents and directory index are parsed - enough to know which
asset paths a mod overrides. Encrypted containers are reported, not read.
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
    """Return dict(mount_point, files=[relative paths], flags, version, container_id)."""
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
           'mount_point': '', 'files': [], 'encrypted': bool(flags & FLAG_ENCRYPTED)}
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
            fname, nxt, _user = files[fi]
            if fname < len(strings):
                out['files'].append(here + strings[fname])
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
