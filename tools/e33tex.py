"""Read a cooked UE5 texture (legacy .uasset/.uexp/.ubulk as written by `retoc to-legacy`)
and decode a small mip to RGBA - pure Python, no dependencies. Used for the mixer's swatches.

Handles regular mip chains and UE5 virtual textures (tiles in chunks, Morton-ordered), and
BC1/BC2/BC3/BC4/BC5/BC7 plus 8-bit uncompressed formats, checked on real cooked UE5 textures.

Portions (parse_texture, parse_vt, _tile_offset, decode_vt) are adapted from CUE4Parse
(https://github.com/FabianFG/CUE4Parse, Apache License 2.0): translated from C# to Python and
modified. See THIRD_PARTY_NOTICES.md and LICENSES/Apache-2.0.txt. The rest of this file is MIT.

  python e33tex.py <file.uasset> <out.png> [max_size]
"""
import os
import struct
import zlib

from e33legacy import read_summary

# --------------------------------------------------------------------------- BC7 tables
# BC7 partition shapes (subset index per pixel) and anchor pixels, derived from bcdec
# (https://github.com/iOrange/bcdec, MIT or Unlicense; used under the Unlicense) - they are the
# BC7 specification tables.
BC7_P2 = (
    '0011001100110011', '0001000100010001', '0111011101110111', '0001001100110111',
    '0000000100010011', '0011011101111111', '0001001101111111', '0000000100110111',
    '0000000000010011', '0011011111111111', '0000000101111111', '0000000000010111',
    '0001011111111111', '0000000011111111', '0000111111111111', '0000000000001111',
    '0000100011101111', '0111000100000000', '0000000010001110', '0111001100010000',
    '0011000100000000', '0000100011001110', '0000000010001100', '0111001100110001',
    '0011000100010000', '0000100010001100', '0110011001100110', '0011011001101100',
    '0001011111101000', '0000111111110000', '0111000110001110', '0011100110011100',
    '0101010101010101', '0000111100001111', '0101101001011010', '0011001111001100',
    '0011110000111100', '0101010110101010', '0110100101101001', '0101101010100101',
    '0111001111001110', '0001001111001000', '0011001001001100', '0011101111011100',
    '0110100110010110', '0011110011000011', '0110011010011001', '0000011001100000',
    '0100111001000000', '0010011100100000', '0000001001110010', '0000010011100100',
    '0110110010010011', '0011011011001001', '0110001110011100', '0011100111000110',
    '0110110011001001', '0110001100111001', '0111111010000001', '0001100011100111',
    '0000111100110011', '0011001111110000', '0010001011101110', '0100010001110111')
BC7_P3 = (
    '0011001102212222', '0001001122112221', '0000200122112211', '0222002200110111',
    '0000000011221122', '0011001100220022', '0022002211111111', '0011001122112211',
    '0000000011112222', '0000111111112222', '0000111122222222', '0012001200120012',
    '0112011201120112', '0122012201220122', '0011011211221222', '0011200122002220',
    '0001001101121122', '0111001120012200', '0000112211221122', '0022002200221111',
    '0111011102220222', '0001000122212221', '0000001101220122', '0000110022102210',
    '0122012200110000', '0012001211222222', '0110122112210110', '0000011012211221',
    '0022110211020022', '0110011020022222', '0011012201220011', '0000200022112221',
    '0000000211221222', '0222002200120011', '0011001200220222', '0120012001200120',
    '0000111122220000', '0120120120120120', '0120201212010120', '0011220011220011',
    '0011112222000011', '0101010122222222', '0000000021212121', '0022112200221122',
    '0022001100220011', '0220122102201221', '0101222222220101', '0000212121212121',
    '0101010101012222', '0222011102220111', '0002111200021112', '0000211221122112',
    '0222011101110222', '0002111211120002', '0110011001102222', '0000000021122112',
    '0110011022222222', '0022001100110022', '0022112211220022', '0000000000002112',
    '0002000100020001', '0222122202221222', '0101222222222222', '0111201122012220')
BC7_A2 = (15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 2, 8, 2, 2, 8, 8, 15, 2, 8, 2, 2, 8, 8, 2, 2, 15, 15, 6, 8, 2, 8, 15, 15, 2, 8, 2, 2, 2, 15, 15, 6, 6, 2, 6, 8, 15, 15, 2, 2, 15, 15, 15, 15, 15, 2, 2, 15)
BC7_A3A = (3, 3, 15, 15, 8, 3, 15, 15, 8, 8, 6, 6, 6, 5, 3, 3, 3, 3, 8, 15, 3, 3, 6, 10, 5, 8, 8, 6, 8, 5, 15, 15, 8, 15, 3, 5, 6, 10, 8, 15, 15, 3, 15, 5, 15, 15, 15, 15, 3, 15, 5, 5, 5, 8, 5, 10, 5, 10, 8, 13, 15, 12, 3, 3)
BC7_A3B = (15, 8, 8, 3, 15, 15, 3, 8, 15, 15, 15, 15, 15, 15, 15, 8, 15, 8, 15, 3, 15, 8, 15, 8, 3, 15, 6, 10, 15, 15, 10, 8, 15, 3, 15, 10, 10, 8, 9, 10, 6, 15, 8, 15, 3, 6, 6, 8, 15, 3, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 3, 15, 15, 8)

BULK_UNUSED, BULK_SEPARATE, BULK_OPTIONAL, BULK_MEMMAPPED, BULK_SIZE64 = 0x20, 0x100, 0x800, 0x1000, 0x2000
HAS_OPT_DATA, HAS_CPU_COPY = 1 << 30, 1 << 29
# pixel format -> (block width, block height, bytes per block)
FORMATS = {
    'PF_DXT1': (4, 4, 8), 'PF_BC1': (4, 4, 8), 'PF_DXT3': (4, 4, 16), 'PF_DXT5': (4, 4, 16),
    'PF_BC4': (4, 4, 8), 'PF_BC5': (4, 4, 16), 'PF_BC7': (4, 4, 16),
    'PF_B8G8R8A8': (1, 1, 4), 'PF_R8G8B8A8': (1, 1, 4), 'PF_A8R8G8B8': (1, 1, 4),
    'PF_G8': (1, 1, 1), 'PF_A8': (1, 1, 1), 'PF_R8': (1, 1, 1),
}


class TexError(Exception):
    pass


# --------------------------------------------------------------------------- reading helpers

class Reader:
    def __init__(self, buf, pos=0):
        self.b, self.p = buf, pos

    def u(self, fmt):
        v = struct.unpack_from('<' + fmt, self.b, self.p)
        self.p += struct.calcsize('<' + fmt)
        return v[0] if len(v) == 1 else v

    def arr(self, fmt):
        n = self.u('i')
        if not 0 <= n < 1_000_000:
            raise TexError(f'bad array length {n}')
        return [self.u(fmt) for _ in range(n)]

    def fstring(self):
        n = self.u('i')
        if n == 0:
            return ''
        if n > 0:
            s = self.b[self.p:self.p + n - 1].decode('latin-1')
            self.p += n
            return s
        s = self.b[self.p:self.p - 2 * n - 2].decode('utf-16-le')
        self.p += -2 * n
        return s


def data_resources(uasset):
    s = read_summary(uasset)
    if 'data_resource_off' not in s['fields']:
        return None
    off = struct.unpack_from('<i', uasset, s['fields']['data_resource_off'][0])[0]
    if off <= 0:
        return None
    r = Reader(uasset, off)
    version, count = r.u('I'), r.u('i')
    out = []
    for _ in range(count):
        flags = r.u('I')
        if version >= 2:
            r.u('B')                                     # cooked index
        so, _dup, size, _raw, _outer, legacy = r.u('qqqqiI')
        out.append({'flags': legacy, 'offset': so, 'size': size})
    return out


class Bulk:
    """Locates bulk payloads of one package: inline (.uexp) or in .ubulk/.uptnl/.m.ubulk."""
    def __init__(self, base_path):
        self.base = base_path                              # path without extension
        self.uexp = open(base_path + '.uexp', 'rb').read()
        self.res = data_resources(open(base_path + '.uasset', 'rb').read())
        self._files = {}

    def _file(self, ext):
        if ext not in self._files:
            p = self.base + ext
            self._files[ext] = open(p, 'rb').read() if os.path.isfile(p) else None
        return self._files[ext]

    def read_ref(self, r):
        """Read a bulk reference from the export stream at reader r; returns a descriptor."""
        if self.res is not None:
            idx = r.u('i')
            if not 0 <= idx < len(self.res):
                raise TexError(f'bulk index {idx} out of range')
            d = dict(self.res[idx])
            if not d['flags'] & (BULK_SEPARATE | BULK_UNUSED) and d['size'] > 0:
                d['offset'] = r.p                          # inline payload follows the reference
                r.p += d['size']
            return d
        flags = r.u('I')
        if flags & BULK_SIZE64:
            _count, size = r.u('qq')
        else:
            _count, size = r.u('ii')
        offset = r.u('q')
        d = {'flags': flags, 'offset': offset, 'size': size}
        if not flags & (BULK_SEPARATE | BULK_UNUSED):
            d['offset'] = r.p                              # old format: payload follows inline
            r.p += size
        return d

    def payload(self, d):
        if d['flags'] & BULK_UNUSED or d['size'] <= 0:
            return None
        if d['flags'] & BULK_SEPARATE:
            ext = '.uptnl' if d['flags'] & BULK_OPTIONAL else ('.m.ubulk' if d['flags'] & BULK_MEMMAPPED else '.ubulk')
            data = self._file(ext)
        else:
            data = self.uexp
        if data is None or d['offset'] < 0 or d['offset'] + d['size'] > len(data):
            return None
        return data[d['offset']:d['offset'] + d['size']]


# --------------------------------------------------------------------------- platform data

def find_platform_data(uexp):
    """Position of the platform data's pixel-format FString ('PF_...') with plausible sizes before it."""
    start = 0
    while True:
        i = uexp.find(b'PF_', start)
        if i < 0:
            raise TexError('no texture platform data found')
        start = i + 1
        if i < 16:
            continue
        n = struct.unpack_from('<i', uexp, i - 4)[0]
        if not 4 < n < 40 or uexp[i + n - 1] != 0:
            continue
        sx, sy, packed = struct.unpack_from('<iiI', uexp, i - 16)
        if 0 < sx <= 32768 and 0 < sy <= 32768:
            return i - 4, sx, sy, packed


def parse_texture(base_path):
    """Return dict(format, width, height, mips=[(w, h, descriptor)], vt=None|dict, bulk=Bulk)."""
    bulk = Bulk(base_path)
    fs_pos, sx, sy, packed = find_platform_data(bulk.uexp)
    r = Reader(bulk.uexp, fs_pos)
    fmt = r.fstring()
    if packed & HAS_OPT_DATA:
        r.u('II')
    if packed & HAS_CPU_COPY:
        raise TexError('textures with a CPU copy are not supported')
    first_mip, nmips = r.u('ii')
    if not 0 <= nmips <= 20:
        raise TexError(f'implausible mip count {nmips}')
    mips = []
    for _ in range(nmips):
        d = bulk.read_ref(r)
        w, h, _z = r.u('iii')
        mips.append((w, h, d))
    for a, b in zip(mips, mips[1:]):                       # sanity: sizes shrink
        if b[0] > a[0] or b[1] > a[1]:
            raise TexError('mip sizes inconsistent')
    vt = None
    if r.p + 4 <= len(bulk.uexp) and r.u('I'):
        vt = parse_vt(r, bulk)
    return {'format': fmt, 'width': sx, 'height': sy, 'mips': mips, 'vt': vt, 'bulk': bulk}


def texture_header(base_path):
    """(width, height, pixel format) from the platform data header alone: works where
    parse_texture() can't follow the mips (an unsupported layout, bulk data elsewhere)."""
    with open(base_path + '.uexp', 'rb') as f:
        uexp = f.read()
    pos, sx, sy, _packed = find_platform_data(uexp)
    n = struct.unpack_from('<i', uexp, pos)[0]
    return sx, sy, uexp[pos + 4:pos + 3 + n].decode('latin-1')


def parse_vt(r, bulk):
    """FVirtualTextureBuiltData (UE5 layout)."""
    vt = {}
    r.u('I')                                               # bCooked
    vt['layers'] = r.u('I')
    if not 1 <= vt['layers'] <= 8:
        raise TexError('bad VT layer count')
    vt['wblocks'], vt['hblocks'], vt['tile'], vt['border'] = r.u('IIII')
    vt['layer_offsets'] = r.arr('I')
    vt['nmips'], vt['width'], vt['height'] = r.u('III')
    vt['chunk_per_mip'] = r.arr('I')
    vt['base_per_mip'] = r.arr('I')
    tod = []
    for _ in range(r.u('i')):
        w, h, maxa = r.u('III')
        tod.append({'w': w, 'h': h, 'max': maxa, 'addr': r.arr('I'), 'offs': r.arr('I')})
    vt['tile_offset_data'] = tod
    vt['tile_index_per_chunk'] = r.arr('I')
    vt['tile_index_per_mip'] = r.arr('I')
    vt['tile_offset_in_chunk'] = r.arr('I')
    vt['layer_types'] = [r.fstring() for _ in range(vt['layers'])]
    r.p += 16 * vt['layers']                               # fallback colors
    chunks = []
    for _ in range(r.u('i')):
        r.p += 20                                          # SHA hash
        size, _payload = r.u('II')
        codecs = []
        for _ in range(vt['layers']):
            codec, _poff = r.u('BI')
            codecs.append(codec)
        chunks.append({'size': size, 'codecs': codecs, 'bulk': bulk.read_ref(r)})
    vt['chunks'] = chunks
    return vt


def _unmorton(x):
    x &= 0x55555555
    x = (x | (x >> 1)) & 0x33333333
    x = (x | (x >> 2)) & 0x0F0F0F0F
    x = (x | (x >> 4)) & 0x00FF00FF
    x = (x | (x >> 8)) & 0x0000FFFF
    return x


def _tile_offset(t, addr):
    a, o = t['addr'], t['offs']
    if not a:
        return 0xFFFFFFFF
    k = 0
    for i in range(len(a)):
        if a[i] > addr:
            k = i - 1
            break
        k = i
    if o[k] == 0xFFFFFFFF:
        return 0xFFFFFFFF
    return o[k] + (addr - a[k])


def decode_vt(tex, max_size=256):
    """Decode the VT level closest to max_size (layer 0) into (w, h, rgba)."""
    vt, bulk = tex['vt'], tex['bulk']
    if vt['tile_offset_in_chunk']:
        raise TexError('legacy (UE4) virtual texture layout not supported')
    fmt = vt['layer_types'][0]
    if fmt not in FORMATS:
        raise TexError(f'unsupported VT pixel format {fmt}')
    bw, bh, bb = FORMATS[fmt]
    tile, border = vt['tile'], vt['border']
    phys = tile + 2 * border
    packed_size = -(-phys // bw) * -(-phys // bh) * bb
    tile_data_size = vt['layer_offsets'][-1] if vt['layer_offsets'] else packed_size
    levels = range(len(vt['tile_offset_data']))
    level = next((lv for lv in levels if vt['tile_offset_data'][lv]['w'] * tile <= max_size), levels[-1])
    t = vt['tile_offset_data'][level]
    chunk = vt['chunks'][vt['chunk_per_mip'][level]]
    data = bulk.payload(chunk['bulk'])
    if data is None:
        raise TexError('VT chunk data missing')
    codec = chunk['codecs'][0]
    W, H = t['w'] * tile, t['h'] * tile
    out = bytearray(W * H * 4)
    base = vt['base_per_mip'][level]
    for addr in range(max(t['max'], 1)):
        x, y = _unmorton(addr), _unmorton(addr >> 1)
        if x >= t['w'] or y >= t['h']:
            continue
        toff = _tile_offset(t, addr)
        if base == 0xFFFFFFFF or toff == 0xFFFFFFFF:
            continue
        off = base + toff * tile_data_size
        if codec == 4:                                     # RawGPU
            raw = data[off:off + packed_size]
        elif codec == 5:                                   # ZippedGPU
            raw = zlib.decompress(data[off:off + tile_data_size])[:packed_size]
        elif codec in (0, 1, 2, 3):
            col = {0: (0, 0, 0, 0), 1: (0, 0, 0, 255), 2: (255, 255, 255, 255), 3: (128, 125, 255, 255)}[codec]
            for yy in range(tile):
                for xx in range(tile):
                    o = ((y * tile + yy) * W + x * tile + xx) * 4
                    out[o:o + 4] = bytes(col)
            continue
        else:
            raise TexError(f'unsupported VT codec {codec}')
        if len(raw) < packed_size:
            raise TexError('VT tile truncated')
        px = decode(fmt, raw, phys, phys)
        for yy in range(tile):
            src = ((yy + border) * phys + border) * 4
            dst = ((y * tile + yy) * W + x * tile) * 4
            out[dst:dst + tile * 4] = px[src:src + tile * 4]
    return W, H, bytes(out)


def decode_texture(base_path, max_size=256):
    """Best small image of a texture: (format, w, h, rgba)."""
    tex = parse_texture(base_path)
    if tex['vt'] is not None and not any(tex['bulk'].payload(d) for _w, _h, d in tex['mips']):
        w, h, px = decode_vt(tex, max_size)
        return tex['vt']['layer_types'][0], w, h, px
    fmt = tex['format']
    if fmt not in FORMATS:
        raise TexError(f'unsupported pixel format {fmt}')
    avail = [(w, h, tex['bulk'].payload(d)) for w, h, d in tex['mips']]
    avail = [(w, h, p) for w, h, p in avail if p]
    if not avail:
        raise TexError('no mip data available')
    small = [a for a in avail if max(a[0], a[1]) <= max_size]
    w, h, payload = small[0] if small else avail[-1]
    return fmt, w, h, decode(fmt, payload, w, h)


# --------------------------------------------------------------------------- block decoders

def _rgb565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _bc1_colors(block, off, force4=False):
    c0, c1 = struct.unpack_from('<HH', block, off)
    a, b = _rgb565(c0), _rgb565(c1)
    if c0 > c1 or force4:
        c2 = tuple((2 * x + y) // 3 for x, y in zip(a, b))
        c3 = tuple((x + 2 * y) // 3 for x, y in zip(a, b))
        cols = [a + (255,), b + (255,), c2 + (255,), c3 + (255,)]
    else:
        c2 = tuple((x + y) // 2 for x, y in zip(a, b))
        cols = [a + (255,), b + (255,), c2 + (255,), (0, 0, 0, 0)]
    idx = struct.unpack_from('<I', block, off + 4)[0]
    return [cols[(idx >> (2 * i)) & 3] for i in range(16)]


def _bc4_values(block, off):
    a0, a1 = block[off], block[off + 1]
    if a0 > a1:
        pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        pal = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
    bits = int.from_bytes(block[off + 2:off + 8], 'little')
    return [pal[(bits >> (3 * i)) & 7] for i in range(16)]


def _bc7_block(blk):
    bits = int.from_bytes(blk, 'little')
    pos = 0

    def take(n):
        nonlocal pos
        v = (bits >> pos) & ((1 << n) - 1)
        pos += n
        return v
    mode = 0
    while mode < 8 and not (bits >> mode) & 1:
        mode += 1
    if mode == 8:
        return [(0, 0, 0, 0)] * 16
    pos = mode + 1
    ns, pb, rb, isb, cb, ab, epb, spb, ib, ib2 = (
        (3, 4, 0, 0, 4, 0, 1, 0, 3, 0), (2, 6, 0, 0, 6, 0, 0, 1, 3, 0), (3, 6, 0, 0, 5, 0, 0, 0, 2, 0),
        (2, 6, 0, 0, 7, 0, 1, 0, 2, 0), (1, 0, 2, 1, 5, 6, 0, 0, 2, 3), (1, 0, 2, 0, 7, 8, 0, 0, 2, 2),
        (1, 0, 0, 0, 7, 7, 1, 0, 4, 0), (2, 6, 0, 0, 5, 5, 1, 0, 2, 0))[mode]
    part = take(pb)
    rot = take(rb)
    sel = take(isb)
    ne = ns * 2
    ep = [[0, 0, 0, 255] for _ in range(ne)]
    for ch in range(3):
        for e in range(ne):
            ep[e][ch] = take(cb)
    if ab:
        for e in range(ne):
            ep[e][3] = take(ab)
    cbits, abits = cb, ab
    if epb:
        for e in range(ne):
            p = take(1)
            for ch in range(4 if ab else 3):
                ep[e][ch] = (ep[e][ch] << 1) | p
        cbits += 1
        abits += 1 if ab else 0
    elif spb:
        for s in range(ns):
            p = take(1)
            for e in (2 * s, 2 * s + 1):
                for ch in range(3):
                    ep[e][ch] = (ep[e][ch] << 1) | p
        cbits += 1
    for e in range(ne):
        for ch in range(3):
            v = ep[e][ch] << (8 - cbits)
            ep[e][ch] = v | (v >> cbits)
        if ab:
            v = ep[e][3] << (8 - abits)
            ep[e][3] = v | (v >> abits)
    if ns == 1:
        subset = '0' * 16
        anchors = {0}
    elif ns == 2:
        subset = BC7_P2[part]
        anchors = {0, BC7_A2[part]}
    else:
        subset = BC7_P3[part]
        anchors = {0, BC7_A3A[part], BC7_A3B[part]}
    idx = [take(ib - 1 if i in anchors else ib) for i in range(16)]
    idx2 = [take(ib2 - 1 if i == 0 else ib2) for i in range(16)] if ib2 else None
    wt = {2: (0, 21, 43, 64), 3: (0, 9, 18, 27, 37, 46, 55, 64),
          4: (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64)}
    out = []
    for i in range(16):
        s = int(subset[i])
        e0, e1 = ep[2 * s], ep[2 * s + 1]
        if idx2 is None:
            wc = wa = wt[ib][idx[i]]
        elif sel:
            wc, wa = wt[ib2][idx2[i]], wt[ib][idx[i]]
        else:
            wc, wa = wt[ib][idx[i]], wt[ib2][idx2[i]]
        px = [((64 - wc) * e0[ch] + wc * e1[ch] + 32) >> 6 for ch in range(3)]
        px.append(((64 - wa) * e0[3] + wa * e1[3] + 32) >> 6)
        if rot:
            px[rot - 1], px[3] = px[3], px[rot - 1]
        out.append(tuple(px))
    return out


def decode(fmt, data, w, h):
    """Decode a whole mip to RGBA bytes."""
    if fmt not in FORMATS:
        raise TexError(f'unsupported pixel format {fmt}')
    bw, bh, bb = FORMATS[fmt]
    out = bytearray(w * h * 4)
    if bw == 1:
        n = w * h
        if len(data) < n * bb:
            raise TexError('mip data truncated')
        if fmt == 'PF_B8G8R8A8':
            for i in range(n):
                b, g, r, a = data[4 * i:4 * i + 4]
                out[4 * i:4 * i + 4] = bytes((r, g, b, a))
        elif fmt == 'PF_A8R8G8B8':
            for i in range(n):
                a, r, g, b = data[4 * i:4 * i + 4]
                out[4 * i:4 * i + 4] = bytes((r, g, b, a))
        elif bb == 4:
            out[:] = data[:4 * n]
        else:
            for i in range(n):
                v = data[i]
                out[4 * i:4 * i + 4] = bytes((v, v, v, 255))
        return bytes(out)
    bx, by = -(-w // 4), -(-h // 4)
    if len(data) < bx * by * bb:
        raise TexError('mip data truncated')
    for j in range(by):
        for i in range(bx):
            off = (j * bx + i) * bb
            if fmt in ('PF_DXT1', 'PF_BC1'):
                px = _bc1_colors(data, off)
            elif fmt == 'PF_DXT3':
                cols = _bc1_colors(data, off + 8, True)
                al = int.from_bytes(data[off:off + 8], 'little')
                px = [c[:3] + (((al >> (4 * k)) & 15) * 17,) for k, c in enumerate(cols)]
            elif fmt == 'PF_DXT5':
                alpha = _bc4_values(data, off)
                px = [c[:3] + (alpha[k],) for k, c in enumerate(_bc1_colors(data, off + 8, True))]
            elif fmt == 'PF_BC4':
                px = [(v, v, v, 255) for v in _bc4_values(data, off)]
            elif fmt == 'PF_BC5':
                rr, gg = _bc4_values(data, off), _bc4_values(data, off + 8)
                px = [(rr[k], gg[k], 0, 255) for k in range(16)]
            else:
                px = _bc7_block(data[off:off + 16])
            for k in range(16):
                x, y = i * 4 + (k & 3), j * 4 + (k >> 2)
                if x < w and y < h:
                    o = (y * w + x) * 4
                    out[o:o + 4] = bytes(px[k])
    return bytes(out)


# --------------------------------------------------------------------------- images

def downscale(w, h, px, max_size):
    """Box-filter RGBA down so the longer side is <= max_size."""
    f = 1
    while max(w, h) // f > max_size:
        f *= 2
    if f == 1:
        return w, h, px
    nw, nh = max(1, w // f), max(1, h // f)
    out = bytearray(nw * nh * 4)
    n = f * f
    for y in range(nh):
        for x in range(nw):
            acc = [0, 0, 0, 0]
            for yy in range(y * f, y * f + f):
                row = yy * w
                for xx in range(x * f, x * f + f):
                    o = (row + xx) * 4
                    acc[0] += px[o]; acc[1] += px[o + 1]; acc[2] += px[o + 2]; acc[3] += px[o + 3]
            o = (y * nw + x) * 4
            out[o:o + 4] = bytes(v // n for v in acc)
    return nw, nh, bytes(out)


def png_bytes(w, h, rgba, opaque=True, level=9):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        row = rgba[y * w * 4:(y + 1) * w * 4]
        if opaque:
            row = bytearray(row)
            row[3::4] = b'\xff' * w
        raw += row

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), level)) + chunk(b'IEND', b''))


# --------------------------------------------------------------------------- choosing textures

COLOR_HINTS = ('basecolor', 'base_color', 'albedo', 'diffuse', 'color', '_d', '_bc', '_c', 'col')
SKIP_HINTS = ('normal', '_n', 'nrm', '_orm', 'orm', 'mask', '_m', 'rough', 'metal', '_ao', 'height', 'opacity', '_r')


def color_score(name, fmt):
    """Higher = more likely a base-color texture worth showing (normal maps etc. score < 0)."""
    n = name.lower()
    if fmt in ('PF_BC5',):
        return -10                                         # two-channel: normal map
    if fmt in ('PF_BC4', 'PF_G8', 'PF_A8', 'PF_R8'):
        return -5                                          # single channel: masks
    score = 0
    tail = '_' + n.rsplit('_', 1)[-1] if '_' in n else n
    if any(n.endswith(h) or tail == h for h in ('_d', '_bc', '_c', '_basecolor', '_albedo', '_diffuse', '_color', '_col')):
        score += 5
    elif any(h in n for h in ('basecolor', 'albedo', 'diffuse', 'color')):
        score += 3
    if any(n.endswith(h) or tail == h for h in ('_n', '_nrm', '_normal', '_orm', '_m', '_mask', '_r', '_ao', '_h')):
        score -= 6
    return score


if __name__ == '__main__':
    import sys
    p, out = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    base = p[:-7] if p.endswith('.uasset') else p
    fmt, w, h, px = decode_texture(base, max(size, 256))
    w, h, px = downscale(w, h, px, size)
    open(out, 'wb').write(png_bytes(w, h, px))
    print(f'{fmt} -> {w}x{h} {out}')
