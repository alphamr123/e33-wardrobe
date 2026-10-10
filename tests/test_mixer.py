"""Scenario tests for e33_mixer on a fake library (run: python -I tests/test_mixer.py)."""
import json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools')); sys.path.insert(0, HERE)
import e33_mixer, make_fake_library

tmp = tempfile.mkdtemp(prefix='e33mix_')
lib, paks = os.path.join(tmp, 'Library'), os.path.join(tmp, 'Paks')
os.makedirs(os.path.join(paks, '~mods'))
open(os.path.join(paks, 'global.utoc'), 'wb').write(b'\0')   # marks the game's Paks folder
open(os.path.join(paks, '~mods', 'MyOtherMod_P.pak'), 'w').write('hand installed')
make_fake_library.build(lib)
cfg = {'library': lib, 'paks_dir': paks, 'rules_dirs': [os.path.join(HERE, '..', 'tools', 'rules')]}
M = e33_mixer.Mixer(cfg)
CC = 'Cheekier Chic V331'
fails = 0

def check(name, cond, extra=''):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'  -> {extra}'))
    fails += (not cond)

def resolve(**choices):
    st = M.mod_state(CC); st['choices'] = dict(choices); st['enabled'] = True
    return M.resolve_all()[CC]

r = resolve(lune_dress='lace', lune_sleeves='sleeveless', lune_feet='barefoot', lune_color='Lace dress/Lune color/Lune_Lace-chic_red_P', sciel_dress='vanilla')
check('lace lune + vanilla sciel', r['paks'] == ['Lace dress/Lune outfit/Lace_lune-sleeveless-barefoot_P', 'Lace dress/Lune color/Lune_Lace-chic_red_P', 'Lace dress/_only Lune mod_fix_P'], r['paks'])
check('  no errors', not [m for m in r['messages'] if m['level'] == 'error'], r['messages'])

r = resolve(lune_dress='vanilla', sciel_dress='vanilla', lune_color='Non-Lace dress/Lune color/Lune_chic_galaxy_P')
check('colors only (separate colors mode)', r['paks'] == ['Non-Lace dress/Lune color/Lune_chic_galaxy_P', 'Non-Lace dress/_only Separate colors_P', 'Non-Lace dress/Sciel color/Sciel_chic_default_P'], r['paks'])

r = resolve(lune_dress='vanilla', sciel_dress='vanilla')
check('fully vanilla installs nothing', r['paks'] == [], r['paks'])

r = resolve(lune_dress='vanilla', sciel_dress='lace', sciel_sleeves='sleeves', sciel_feet='boots')
check('lace sciel gets a lace color automatically', r['paks'] == ['Lace dress/Sciel outfit/Lace_sciel-sleeves-boots_P', 'Lace dress/Sciel color/Sciel-Lace-chic_red_P'], r['paks'])

r = resolve(lune_dress='lace', lune_color='Non-Lace dress/Lune color/Lune_chic_gold_P')
check('non-lace color is not allowed on lace dress', 'Non-Lace dress/Lune color/Lune_chic_gold_P' not in r['paks'], r['paks'])

r = resolve(lune_dress='nonlace', sciel_dress='nonlace', sciel_color='none')
check('modded sciel cannot have no color', 'Non-Lace dress/Sciel color/Sciel_chic_default_P' in r['paks'], r['paks'])
check('  no fix pak when both modded', not any('_only' in p for p in r['paks']), r['paks'])

r = resolve(lune_dress='lace', sciel_dress='nonlace', sciel_color='Non-Lace dress/Sciel color/Sciel_chic_fire_P')
check('mixed lace lune + non-lace sciel (Lace outfit brings its own material, color optional)',
      set(r['paks']) == {'Lace dress/Lune outfit/Lace_lune-sleeves-boots_P', 'Non-Lace dress/Sciel outfit/chic_sciel-sleeves-boots_P', 'Non-Lace dress/Sciel color/Sciel_chic_fire_P'}, r['paks'])

# apply / switch / off
res = M.apply()
target = os.path.join(paks, '~mods', '_E33Mixer', '50 ' + CC)
got = sorted(os.listdir(target))
check('apply places pak triplets into a priority folder (with each outfit\'s extra paks)',
      res['ok'] and len(got) == 15 and 'Sciel_chic_fire_P.utoc' in got and 'lune_lace_material_P.utoc' in got
      and 'Sciel_separate_P.utoc' in got, (res, got))
check('  hardlinked, not copied', os.stat(os.path.join(target, 'Sciel_chic_fire_P.pak')).st_ino == os.stat(os.path.join(lib, CC, 'Non-Lace dress/Sciel color/Sciel_chic_fire_P/Sciel_chic_fire_P.pak')).st_ino)
M.preset_save('Lace Lune + Fire Sciel')
resolve(lune_dress='vanilla', sciel_dress='vanilla', lune_color='Non-Lace dress/Lune color/Lune_chic_white_P')
res = M.apply(); got = sorted(os.listdir(target))
check('switching removes old files', 'Sciel_chic_fire_P.pak' not in got and 'Lune_chic_white_P.pak' in got, got)
M.preset_load('Lace Lune + Fire Sciel'); res = M.apply(); got = sorted(os.listdir(target))
check('preset restores combination', 'Sciel_chic_fire_P.pak' in got and 'Lune_chic_white_P.pak' not in got, got)
check('hand-installed mod untouched', open(os.path.join(paks, '~mods', 'MyOtherMod_P.pak')).read() == 'hand installed')
again = M.apply()
check('re-apply is a no-op', again['ok'] and again['log'] == [], again['log'])

# cross-mod conflict: make the hair mod override the same mesh as Lune's outfit
hair = os.path.join(lib, 'Some Hair Mod', 'Colors', 'Red_P', 'Red_P.utoc')
open(hair, 'wb').write(make_fake_library.tiny_utoc(['Sandfall/Content/Characters/Lune/Chic/SK_Lune_Chic.uasset']))
M.mod_state('Some Hair Mod').update(enabled=True, choices={'c2': 'Colors/Red_P'})
M.rescan(); v = M.view()
hm = next(m for m in v['mods'] if m['name'] == 'Some Hair Mod')
check('detects two mods overriding one asset', any('SK_Lune_Chic' in m['text'] for m in hm['messages']), hm['messages'])

# loose duplicate detection
os.makedirs(os.path.join(paks, 'Mods'), exist_ok=True)       # #673 installs into Paks\Mods
open(os.path.join(paks, 'Mods', 'Sciel_chic_fire_P.pak'), 'w').write('dup')
check('warns about hand-installed duplicate (any Paks subfolder)', any(d.endswith('Sciel_chic_fire_P.pak') for d in M.view()['loose_duplicates']), M.view()['loose_duplicates'])
os.remove(os.path.join(paks, 'Mods', 'Sciel_chic_fire_P.pak'))

res = M.off()
check('off removes managed files', res['ok'] and not os.path.exists(target), os.listdir(os.path.join(paks, '~mods', '_E33Mixer')))
check('off keeps manifest + hand mods', os.path.exists(os.path.join(paks, '~mods', 'MyOtherMod_P.pak')))
st = json.load(open(os.path.join(lib, '.e33mixer_state.json')))
check('state persisted with presets', 'Lace Lune + Fire Sciel' in st['presets'])
# --- regressions from code review -------------------------------------------------
# same-named, same-size, same-mtime files from two variants must still be swapped
a = os.path.join(lib, CC, 'Non-Lace dress/Lune color/Lune_chic_red_P')
b = os.path.join(lib, CC, 'Non-Lace dress/Lune color/Lune_chic_blue_P')
for f in os.listdir(b):
    os.remove(os.path.join(b, f))
for f in os.listdir(a):                      # B gets files named like A's, same size+mtime, other bytes
    data = open(os.path.join(a, f), 'rb').read()
    open(os.path.join(b, f), 'wb').write(bytes(x ^ 1 for x in data))
    st = os.stat(os.path.join(a, f)); os.utime(os.path.join(b, f), (st.st_atime, st.st_mtime))
M.rescan()
M.mod_state('Some Hair Mod')['enabled'] = False
resolve(lune_dress='nonlace', sciel_dress='nonlace', lune_color='Non-Lace dress/Lune color/Lune_chic_red_P'); M.apply()
resolve(lune_dress='nonlace', sciel_dress='nonlace', lune_color='Non-Lace dress/Lune color/Lune_chic_blue_P'); M.apply()
inst = os.path.join(paks, '~mods', '_E33Mixer', '50 ' + CC, 'Lune_chic_red_P.ucas')
check('variant switch with identical names/sizes/mtimes replaces bytes',
      open(inst, 'rb').read() == open(os.path.join(b, 'Lune_chic_red_P.ucas'), 'rb').read())

# refuse to apply while the game runs
orig = e33_mixer.game_running
e33_mixer.game_running = lambda *a, **k: True
r = M.apply()
check('apply refused while game runs', not r['ok'] and 'running' in r['errors'][0], r)
e33_mixer.game_running = orig

# a file that cannot be removed stays tracked, so "Disable all" can retry later
real_remove = os.remove
def locked(p):
    if p.endswith('Lune_chic_red_P.ucas'):
        raise PermissionError('locked')
    real_remove(p)
os.remove = locked
r = M.off()
os.remove = real_remove
man = json.load(open(os.path.join(paks, '~mods', '_E33Mixer', '.e33mixer_manifest.json')))['files']
check('failed removal kept in manifest', not r['ok'] and any(k.endswith('Lune_chic_red_P.ucas') for k in man), (r, man))
r = M.off()
check('  and removed on the next try', r['ok'] and not any('Lune_chic' in k for k in json.load(open(os.path.join(paks, '~mods', '_E33Mixer', '.e33mixer_manifest.json')))['files']), r)

# a broken mod (brace in folder name, truncated utoc) must not break the others
bad = os.path.join(lib, 'Broken {Mod')
os.makedirs(os.path.join(bad, 'Opt {1}_P'))
open(os.path.join(bad, 'Opt {1}_P', 'x_P.pak'), 'wb').write(b'x')
open(os.path.join(bad, 'Opt {1}_P', 'x_P.utoc'), 'wb').write(b'-==--==--==--==-' + b'\x06' + b'\x00' * 10)
M.rescan()
M.mod_state('Broken {Mod').update(enabled=True, choices={'c1': 'on'})
try:
    v = M.view(); okv = True
except Exception as e:
    okv, v = False, str(e)
check('broken mod does not break the view', okv, v)
if okv:
    bm = next(m for m in v['mods'] if m['name'] == 'Broken {Mod')
    check('  brace folder resolves', bm['paks'] == ['Opt {1}_P'], bm)
    check('  truncated utoc reported as warning', any('Could not read' in m['text'] for m in bm['messages']), bm['messages'])

# web server: token + Host checks
import threading, urllib.request
srv_holder = {}
def serve():
    import secrets
    from http.server import ThreadingHTTPServer
    hosts = set()
    srv = ThreadingHTTPServer(('127.0.0.1', 0), e33_mixer.make_handler(M, 'tok', hosts))
    hosts.update({f'127.0.0.1:{srv.server_address[1]}', f'localhost:{srv.server_address[1]}'})
    srv_holder['srv'] = srv
    srv.serve_forever()
threading.Thread(target=serve, daemon=True).start()
import time; time.sleep(0.5)
port = srv_holder['srv'].server_address[1]
def req(path, host=None, token=None, body=None):
    r = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=body, method='POST' if body is not None else 'GET')
    if host: r.add_header('Host', host)
    if token: r.add_header('X-Token', token)
    try:
        return urllib.request.urlopen(r, timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code
check('page served on localhost', req('/') == 200)
check('rebinding host rejected', req('/', host=f'evil.example:{port}') == 403)
check('POST without token rejected', req('/api/rescan', body=b'{}') == 403)
check('POST with token accepted', req('/api/rescan', token='tok', body=b'{}') == 200)
srv_holder['srv'].shutdown()

# --- second audit round -------------------------------------------------------------
# priority folders: lower number wins ties; the conflict message names the winner
M.mod_state('Broken {Mod')['enabled'] = False
M.mod_state('Some Hair Mod').update(enabled=True, choices={'c2': 'Colors/Red_P'}, priority=10)
resolve(lune_dress='nonlace', sciel_dress='nonlace')
v = M.view()
hm = next(m for m in v['mods'] if m['name'] == 'Some Hair Mod')
msg = next((m['text'] for m in hm['messages'] if 'wins' in m['text']), '')
check('conflict message says which mod wins in game', 'Some Hair Mod' in msg.split('wins')[0].split('In game')[-1], msg)
r = M.apply()
check('priority folders on disk', os.path.isdir(os.path.join(paks, '~mods', '_E33Mixer', '10 Some Hair Mod')), os.listdir(os.path.join(paks, '~mods', '_E33Mixer')))

# self-healing: anything in _E33Mixer that isn't wanted is removed, even without a manifest entry
stray = os.path.join(paks, '~mods', '_E33Mixer', '50 ' + CC, 'stray_P.pak')
open(stray, 'w').write('x')
os.remove(os.path.join(paks, '~mods', '_E33Mixer', '.e33mixer_manifest.json'))
r = M.apply()
check('stray file removed and missing manifest rebuilt', r['ok'] and not os.path.exists(stray) and
      os.path.exists(os.path.join(paks, '~mods', '_E33Mixer', '.e33mixer_manifest.json')), r)

# corrupt manifest / state are set aside instead of breaking everything
open(os.path.join(paks, '~mods', '_E33Mixer', '.e33mixer_manifest.json'), 'w').write('{broken')
r = M.apply()
check('corrupt manifest tolerated', r['ok'], r)
open(os.path.join(lib, '.e33mixer_state.json'), 'w').write('not json')
M2 = e33_mixer.Mixer(cfg)
check('corrupt state tolerated and reported', any('damaged' in w for w in M2.view()['warnings']))

# wrapper folder from "extract to <archive name>\" still matches the rules
wrapped = os.path.join(lib, 'Cheekier Chic v3.3.1-685-3-3-1')
os.makedirs(wrapped)
shutil.move(os.path.join(lib, CC), os.path.join(wrapped, CC))
M3 = e33_mixer.Mixer(cfg)
wm = next(m for m in M3.view()['mods'] if m['name'] == 'Cheekier Chic v3.3.1-685-3-3-1')
check('wrapper folder unwrapped, rules still apply', wm['rules_name'] == 'Cheekier Chic (v3.3.1)', wm['rules_name'])
shutil.move(os.path.join(wrapped, CC), os.path.join(lib, CC)); os.rmdir(wrapped)

# Thin Sciel add-on dropped into the mod folder: a 'Sciel body' choice appears and is used
thin = os.path.join(lib, CC, 'Thin Sciel - Non-Lace', 'chic_sciel-thin-sleeveless-boots_P')
os.makedirs(thin)
for f in ('chic_sciel-thin-sleeveless-boots_P', 'Sciel_separate_P'):
    for ext in ('.pak', '.utoc', '.ucas'):
        open(os.path.join(thin, f + ext), 'wb').write(b'x')
M4 = e33_mixer.Mixer(cfg)
st = M4.mod_state(CC); st['choices'] = dict(lune_dress='nonlace', sciel_dress='nonlace', sciel_sleeves='sleeveless', sciel_feet='boots', sciel_body='thin'); st['enabled'] = True
r4 = M4.resolve_all()[CC]
body = next(c for c in r4['choices'] if c['id'] == 'sciel_body')
check('Sciel body choice visible with the add-on', body['visible'] and body['value'] == 'thin', body)
check('thin outfit replaces the normal one', any('thin' in p for p in r4['paks']) and not any(p.endswith('chic_sciel-sleeveless-boots_P') for p in r4['paks']), r4['paks'])
st['choices']['sciel_sleeves'] = 'sleeves'
r4 = M4.resolve_all()[CC]
check('thin hidden for combinations it was not made for', not next(c for c in r4['choices'] if c['id'] == 'sciel_body')['visible'])
shutil.rmtree(os.path.join(lib, CC, 'Thin Sciel - Non-Lace'))

# LogicMods / UE4SS parts are not installed into ~mods, and the user is told
lm = os.path.join(lib, 'Logic Mod', 'LogicMods')
os.makedirs(lm); open(os.path.join(lm, 'Thing_P.pak'), 'wb').write(b'x')
os.makedirs(os.path.join(lib, 'Logic Mod', 'Paks_P')); open(os.path.join(lib, 'Logic Mod', 'Paks_P', 'Asset_P.pak'), 'wb').write(b'x')
M5 = e33_mixer.Mixer(cfg)
lmv = next(m for m in M5.view()['mods'] if m['name'] == 'Logic Mod')
check('LogicMods folder not offered as a pak option', not any('LogicMods' in (c['label'] or '') for c in lmv['choices']), lmv['choices'])
check('LogicMods part reported', any('LogicMods' in m['text'] for m in lmv['messages']), lmv['messages'])

# --- final audit round -------------------------------------------------------------
# wrapper folder holding the mod AND a Thin Sciel download next to it: rules still match
wrapped = os.path.join(lib, 'CC-685-wrapper')
os.makedirs(wrapped)
shutil.move(os.path.join(lib, CC), os.path.join(wrapped, CC))
thin2 = os.path.join(wrapped, 'Thin Sciel - Lace', 'Lace_sciel-thin-sleeveless-boots_P')
os.makedirs(thin2)
for f in ('Lace_sciel-thin-sleeveless-boots_P', 'sciel_lace_material_P'):
    for ext in ('.pak', '.utoc', '.ucas'):
        open(os.path.join(thin2, f + ext), 'wb').write(b'x')
M6 = e33_mixer.Mixer(cfg)
st = M6.mod_state('CC-685-wrapper'); st['enabled'] = True
st['choices'] = dict(lune_dress='vanilla', sciel_dress='lace', sciel_sleeves='sleeveless', sciel_feet='boots', sciel_body='thin')
r6 = M6.resolve_all()['CC-685-wrapper']
check('wrapper + add-on next to the mod: smart rules still used', M6.mods['CC-685-wrapper'].rules.get('name') == 'Cheekier Chic (v3.3.1)', M6.mods['CC-685-wrapper'].rules.get('name'))
check('  thin add-on found and paths prefixed', 'Thin Sciel - Lace/Lace_sciel-thin-sleeveless-boots_P' in r6['paks']
      and any(p.startswith(CC + '/Lace dress/Sciel color/') for p in r6['paks']), r6['paks'])
check('  no missing-path errors', not [m for m in r6['messages'] if m['level'] == 'error'], r6['messages'])
M6.mod_state('CC-685-wrapper')['enabled'] = False; M6.save()
shutil.rmtree(os.path.join(wrapped, 'Thin Sciel - Lace'))
shutil.move(os.path.join(wrapped, CC), os.path.join(lib, CC)); os.rmdir(wrapped)

# Unreal treats '_p' case-insensitively when ranking paks
check('lowercase _p ranks like _P', e33_mixer.pak_priority('mod_p') == e33_mixer.pak_priority('Mod_P') == 100
      and e33_mixer.pak_priority('x_3_p') == 400)
check('conflict winner: _P beats no suffix even if alphabetically later',
      e33_mixer.winner([('A', '~mods/a_mod.utoc'), ('B', '~mods/b_mod_p.utoc')]) == 'B')

# a mod updated in the library (same file names, new content) is shown as pending and re-installed
M7 = e33_mixer.Mixer(cfg)
M7.mod_state(CC)['enabled'] = True; M7.save(); M7.apply()
desired, _ = M7.plan(M7.resolve_all())
rel, src = sorted(desired.items())[0]
check('after Apply the page says the game folder matches', not M7.view()['pending'])
os.remove(src); open(src, 'w').write('new version of this pak, longer than before')
check('a mod updated in the library with the same file names is pending (it said "matches" before)',
      M7.view()['pending'])
M7.apply()
dst = os.path.join(paks, '~mods', '_E33Mixer', *rel.split('/'))
check('  and Apply installs the new content', open(dst).read() == 'new version of this pak, longer than before'
      and not M7.view()['pending'])

# copies (library on another drive) go to a .tmp first and are renamed; a stale .tmp is removed
real_link = os.link
def no_link(*a, **k):
    raise OSError('cross-device link')
e33_mixer.os.link = no_link
try:
    open(os.path.join(os.path.dirname(dst), 'left_over.ucas.tmp'), 'w').write('half a copy')
    os.remove(src); open(src, 'w').write('third version')
    r = M7.apply()
    left = [f for dp, _d, fs in os.walk(os.path.join(paks, '~mods', '_E33Mixer')) for f in fs if f.endswith('.tmp')]
    check('a copy lands complete under its name, with no .tmp left (a killed copy never looks installed)',
          open(dst).read() == 'third version' and not left and any(l.startswith('copied') for l in r['log']), (left, r['log']))
finally:
    e33_mixer.os.link = real_link
M7.off()

# a folder without global.utoc is not the game's Paks folder: Apply is refused, the page warns
wrong = os.path.join(tmp, 'NotPaks'); os.makedirs(wrong)
Mw = e33_mixer.Mixer({**cfg, 'paks_dir': wrong})
Mw.mod_state(CC)['enabled'] = True
r = Mw.apply()
check('Apply refuses a Paks folder without global.utoc (it installed where the game never looks before)',
      not r['ok'] and 'global.utoc' in ' '.join(r['errors']) and not os.path.exists(os.path.join(wrong, '~mods')), r)
check('  and the page warns', any('global.utoc' in w for w in Mw.view()['warnings']))
Mw.mod_state(CC)['enabled'] = False; Mw.save()

# a symlink planted inside _E33Mixer is not followed: files outside are never deleted
outside = os.path.join(tmp, 'outside'); os.makedirs(outside)
open(os.path.join(outside, 'keep.txt'), 'w').write('keep')
os.makedirs(os.path.join(paks, '~mods', '_E33Mixer'), exist_ok=True)
try:
    os.symlink(outside, os.path.join(paks, '~mods', '_E33Mixer', 'linked'))
except (OSError, NotImplementedError):      # Windows without admin rights / Developer Mode
    print('SKIP link check (creating symlinks needs admin rights or Developer Mode on Windows)')
else:
    r = e33_mixer.Mixer(cfg).off()
    check('link inside _E33Mixer not followed', os.path.exists(os.path.join(outside, 'keep.txt')), r)

shutil.rmtree(tmp)
print(f'\n{fails} failure(s)'); sys.exit(1 if fails else 0)
