"""Preview tests: swatches from real cooked textures, saved looks, screenshot serving, VT tiles.

usage: python -I tests/test_previews.py <dir with global.utoc+ucas (script objects incl. Texture2D)>
                                        <legacy dir with Sandfall/Content/Tex/T_Test.* and T_pl01_001_body_D.*>
                                        <retoc>
"""
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import e33_mixer  # noqa: E402
import e33tex  # noqa: E402


def main():
    globdir, legacy, retoc = sys.argv[1:4]
    tmp = tempfile.mkdtemp(prefix='e33prev_')
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    paks = os.path.join(tmp, 'Paks')
    os.makedirs(os.path.join(paks, '~mods'))
    for ext in ('.utoc', '.ucas'):
        shutil.copy(os.path.join(globdir, 'global' + ext), paks)
    lib = os.path.join(tmp, 'Library')

    def option(rel, textures):
        leg = os.path.join(tmp, 'leg_' + rel.replace('/', '_'))
        for t in textures:
            for f in os.listdir(os.path.join(legacy, 'Sandfall', 'Content', 'Tex')):
                if f.startswith(t + '.'):
                    d = os.path.join(leg, 'Sandfall', 'Content', 'Mods', 'TexMod', f)
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    shutil.copy(os.path.join(legacy, 'Sandfall', 'Content', 'Tex', f), d)
        out = os.path.join(lib, 'TexMod', *rel.split('/'))
        os.makedirs(out)
        stem = rel.rsplit('/', 1)[1]
        p = subprocess.run([retoc, 'to-zen', '--version', 'UE5_4', leg, os.path.join(out, stem + '.utoc')],
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr

    option('Lune color/Red_P', ['T_Test'])
    option('Lune color/Body_P', ['T_pl01_001_body_D'])
    # an option without textures (copy only the .pak of another option -> no utoc textures)
    os.makedirs(os.path.join(lib, 'TexMod', 'Lune color', 'Plain_P'))
    open(os.path.join(lib, 'TexMod', 'Lune color', 'Plain_P', 'Plain_P.pak'), 'wb').write(b'x')

    shots = os.path.join(tmp, 'Shots')
    os.makedirs(shots)
    png = e33tex.png_bytes(2, 2, bytes([255, 0, 0, 255] * 4))
    open(os.path.join(shots, 'old.png'), 'wb').write(png)
    time.sleep(0.05)
    open(os.path.join(shots, 'new.png'), 'wb').write(png)
    cfg = {'library': lib, 'paks_dir': paks, 'rules_dirs': [], 'retoc': retoc, 'screenshot_dirs': [shots]}
    M = e33_mixer.Mixer(cfg)
    check('mod found', 'TexMod' in M.mods, list(M.mods))
    M.mod_state('TexMod')['enabled'] = True

    # ---- swatches
    M.start_swatches('TexMod')
    while M.swatch_job.state['running']:
        time.sleep(0.2)
    log = M.swatch_job.state['log']
    v = next(m for m in M.view()['mods'] if m['name'] == 'TexMod')
    store = M.previews
    rel = {os.path.basename(f): f for f in M.mods['TexMod'].folders()}     # option names after unwrapping
    RED, BODY, PLAIN = rel['Red_P'], rel['Body_P'], rel['Plain_P']
    red = store.swatches_for('TexMod', RED)
    body = store.swatches_for('TexMod', BODY)
    check('swatch built from a .ubulk mip (T_Test DXT1)', red and red[0]['format'] == 'PF_DXT1', (red, log))
    check('swatch built from inline mips (DXT5)', body and body[0]['format'] == 'PF_DXT5', (body, log))
    if red:
        data = open(store.file_path(red[0]['file']), 'rb').read()
        w, h = struct.unpack('>II', data[16:24])
        check('swatch is a small PNG', data[:8] == b'\x89PNG\r\n\x1a\n' and max(w, h) <= 96, (w, h))
    cid = next(c['id'] for c in v['choices'] if c['visible'])
    po = v['previews']['per_option'].get(cid, {})
    check('color option buttons get their swatch', po.get(RED, {}).get('swatch') == (red[0]['file'] if red else None), po)
    check('option without textures has no swatch', PLAIN not in po or not po[PLAIN].get('swatch'), po)
    t0 = os.path.getmtime(store.file_path(red[0]['file'])) if red else 0
    M.start_swatches('TexMod')
    while M.swatch_job.state['running']:
        time.sleep(0.2)
    check('unchanged options are not rebuilt', red and os.path.getmtime(store.file_path(red[0]['file'])) == t0)

    # ---- looks
    st = M.mod_state('TexMod')
    st['choices'] = {cid: RED}
    url = 'data:image/png;base64,' + base64.b64encode(png).decode()
    lid = M.save_look('TexMod', url)
    v = next(m for m in M.view()['mods'] if m['name'] == 'TexMod')
    check('look saved and shown for the exact combination', v['previews']['look_exact'] and v['previews']['look'].startswith('look_'))
    st['choices'] = {cid: BODY}
    v = next(m for m in M.view()['mods'] if m['name'] == 'TexMod')
    check('other combination: look shown as closest match, not exact', not v['previews']['look_exact'])
    check('the Red button shows that screenshot on hover', v['previews']['per_option'][cid][RED]['look'] == v['previews']['looks'][0]['file'])
    M.apply_look('TexMod', lid)
    check('clicking a saved look restores its choices', M.mod_state('TexMod')['choices'][cid] == RED)
    for bad in ('data:text/html;base64,PGI+', 'data:image/png;base64,' + base64.b64encode(b'<script>').decode()):
        try:
            M.save_look('TexMod', bad)
            check('rejects non-image data', False, bad[:30])
        except ValueError:
            check('rejects non-image data', True)

    # ---- HTTP: previews, screenshots, traversal
    hosts = set()
    srv = e33_mixer.ThreadingHTTPServer(('127.0.0.1', 0), e33_mixer.make_handler(M, 'tok', hosts))
    port = srv.server_address[1]
    hosts.update({f'127.0.0.1:{port}'})
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def get(path):
        try:
            r = urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10)
            return r.status, r.read(), r.headers.get('Content-Type')
        except urllib.error.HTTPError as e:
            return e.code, b'', None
    code, body_, ct = get('/previews/' + red[0]['file']) if red else (0, b'', None)
    check('swatch served as image/png', code == 200 and ct == 'image/png', (code, ct))
    check('path traversal refused', get('/previews/../.e33mixer_state.json')[0] == 404 and get('/previews/index.json%2F..')[0] == 404)
    code, body_, _ = get('/api/shots')
    shots_list = json.loads(body_)
    check('newest screenshot listed first', shots_list['shots'] and shots_list['shots'][0]['name'] == 'new.png', shots_list)
    code, body_, ct = get('/api/shot?id=0')
    check('screenshot served', code == 200 and body_[:8] == b'\x89PNG\r\n\x1a\n', (code, ct))
    check('unknown screenshot id refused', get('/api/shot?id=99')[0] == 404)
    srv.shutdown()

    M.previews.delete_look('TexMod', lid)
    check('look deleted with its file', not M.previews.mod('TexMod')['looks'] and not any(
        f.startswith('look_') for f in os.listdir(M.previews.root)))

    # ---- synthetic virtual texture: tiles assembled in Morton order, borders cropped
    vt_dir = os.path.join(tmp, 'vt')
    os.makedirs(vt_dir)
    src = os.path.join(legacy, 'Sandfall', 'Content', 'Tex', 'T_Test')
    shutil.copy(src + '.uasset', os.path.join(vt_dir, 'T_VT.uasset'))      # DR table: entry 0 -> .ubulk @0
    shutil.copy(src + '.ubulk', os.path.join(vt_dir, 'T_VT.ubulk'))
    tile, border = 128, 4
    phys = tile + 2 * border
    tsize = (phys // 4) * (phys // 4) * 8                                    # DXT1 tile bytes
    u = bytearray(16) + struct.pack('<iiI', 256, 256, 1)
    u += struct.pack('<i', 8) + b'PF_DXT1\x00' + struct.pack('<ii', 0, 0)     # first mip, no regular mips
    u += struct.pack('<I', 1)                                                # bIsVirtual
    u += struct.pack('<IIIIIII', 1, 1, 1, 1, tile, border, 1) + struct.pack('<I', tsize)  # bCooked..TileDataOffsetPerLayer
    u += struct.pack('<III', 1, 256, 256)                                    # NumMips, Width, Height
    u += struct.pack('<iI', 1, 0) + struct.pack('<iI', 1, 0)                 # ChunkIndexPerMip, BaseOffsetPerMip
    u += struct.pack('<i', 1) + struct.pack('<III', 2, 2, 4) + struct.pack('<iI', 1, 0) + struct.pack('<iI', 1, 0)
    u += struct.pack('<i', 0) * 3                                            # legacy tile arrays (empty)
    u += struct.pack('<i', 8) + b'PF_DXT1\x00' + b'\x00' * 16               # layer types + fallback color
    u += struct.pack('<i', 1) + b'\x00' * 20 + struct.pack('<II', 4 * tsize, 0) + struct.pack('<BI', 4, 0)
    u += struct.pack('<i', 0)                                                # chunk bulk -> DR entry 0
    open(os.path.join(vt_dir, 'T_VT.uexp'), 'wb').write(bytes(u))
    fmt, w, h, px = e33tex.decode_texture(os.path.join(vt_dir, 'T_VT'), 256)
    raw = open(src + '.ubulk', 'rb').read()
    ok = (w, h) == (256, 256)
    for addr, (tx, ty) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):       # Morton order
        ref = e33tex.decode('PF_DXT1', raw[addr * tsize:(addr + 1) * tsize], phys, phys)
        for yy in (0, 77, 127):
            a = px[((ty * tile + yy) * w + tx * tile) * 4:((ty * tile + yy) * w + tx * tile + tile) * 4]
            b = ref[((yy + border) * phys + border) * 4:((yy + border) * phys + border + tile) * 4]
            ok = ok and a == b
    check('virtual texture: tiles placed by Morton order with borders cropped', ok, (fmt, w, h))

    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
