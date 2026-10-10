"""Minimal .usmap reader (versions 0-4, none/zstd compression). Used to look up E33 struct layouts."""
import struct, sys

TYPES = ['ByteProperty','BoolProperty','IntProperty','FloatProperty','ObjectProperty','NameProperty',
 'DelegateProperty','DoubleProperty','ArrayProperty','StructProperty','StrProperty','TextProperty',
 'InterfaceProperty','MulticastDelegateProperty','WeakObjectProperty','LazyObjectProperty',
 'AssetObjectProperty','SoftObjectProperty','UInt64Property','UInt32Property','UInt16Property',
 'Int64Property','Int16Property','Int8Property','MapProperty','SetProperty','EnumProperty',
 'FieldPathProperty','OptionalProperty','Utf8StrProperty','AnsiStrProperty']

class R:
    def __init__(s, b): s.b, s.p = b, 0
    def u(s, fmt):
        v = struct.unpack_from('<' + fmt, s.b, s.p); s.p += struct.calcsize(fmt); return v[0]

def load(path):
    raw = open(path, 'rb').read()
    r = R(raw)
    assert r.u('H') == 0x30C4, 'bad magic'
    ver = r.u('B')
    if ver >= 1 and r.u('i'):
        r.u('i'); r.u('i'); n = r.u('i'); r.p += n * 20; r.u('I')  # versioning block
    comp, csize, dsize = r.u('B'), r.u('I'), r.u('I')
    data = raw[r.p:r.p + csize]
    if comp == 3:
        import zstandard; data = zstandard.ZstdDecompressor().decompress(data, max_output_size=dsize)
    elif comp != 0:
        raise SystemExit(f'compression {comp} unsupported')
    r = R(data)
    names = []
    for _ in range(r.u('I')):
        n = r.u('H') if ver >= 2 else r.u('B'); names.append(data[r.p:r.p + n].decode('utf-8', 'replace')); r.p += n
    enums = {}
    for _ in range(r.u('I')):
        en = names[r.u('I')]; cnt = r.u('H') if ver >= 3 else r.u('B'); vals = []
        for _ in range(cnt):
            if ver >= 4: r.u('Q')
            vals.append(names[r.u('I')])
        enums[en] = vals
    def ptype():
        t = TYPES[r.u('B')]
        if t == 'EnumProperty': inner = ptype(); return f'Enum<{names[r.u("I")]}:{inner}>'
        if t == 'StructProperty': return f'Struct<{names[r.u("I")]}>'
        if t in ('ArrayProperty', 'SetProperty', 'OptionalProperty'): return f'{t[:-8]}<{ptype()}>'
        if t == 'MapProperty': k = ptype(); v = ptype(); return f'Map<{k},{v}>'
        return t
    structs = {}
    for _ in range(r.u('I')):
        sn = names[r.u('I')]; si = r.u('I'); sup = None if si == 0xFFFFFFFF else names[si]
        r.u('H'); sc = r.u('H'); props = []
        for _ in range(sc):
            idx = r.u('H'); arr = r.u('B'); pn = names[r.u('I')]; props.append((idx, arr, pn, ptype()))
        structs[sn] = (sup, props)
    return enums, structs

def show(structs, name, depth=0, seen=None):
    seen = seen or set()
    if name not in structs or name in seen: return
    seen.add(name); sup, props = structs[name]
    print('  ' * depth + f'{name}' + (f' : {sup}' if sup else ''))
    for idx, arr, pn, t in props:
        print('  ' * depth + f'  [{idx}] {pn}: {t}' + (f' x{arr}' if arr > 1 else ''))
    if sup: show(structs, sup, depth + 1, seen)

if __name__ == '__main__':
    enums, structs = load(sys.argv[1])
    print(len(enums), 'enums', len(structs), 'structs')
    import re
    for pat in sys.argv[2:]:
        for k in structs:
            if re.search(pat, k): show(structs, k)
        for k in enums:
            if re.search(pat, k): print('enum', k, enums[k][:40])
