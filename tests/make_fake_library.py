"""Build a fake library with the folder layout of the multi-variant mod in tools/rules (dummy paks, valid tiny .utoc)."""
import os, struct, sys

TREE = {
 'Lace dress': {
  'Lune color': ['Lune_Lace-chic_black_P', 'Lune_Lace-chic_red_P'],
  'Lune outfit': ['Lace_lune-sleeveless-barefoot_P', 'Lace_lune-sleeveless-boots_P', 'Lace_lune-sleeves-barefoot_P', 'Lace_lune-sleeves-boots_P'],
  'Sciel color': ['Sciel-Lace-chic_red_P', 'Sciel_Lace-chic_black_P', 'Sciel_Lace-chic_blue_P'],
  'Sciel outfit': ['Lace_sciel-sleeveless-barefoot_P', 'Lace_sciel-sleeveless-boots_P', 'Lace_sciel-sleeves-barefoot_P', 'Lace_sciel-sleeves-boots_P'],
  None: ['_only Lune mod_fix_P']},
 'Non-Lace dress': {
  'Lune color': ['Lune_chic_33rd_P', 'Lune_chic_black_P', 'Lune_chic_blue_P', 'Lune_chic_fire_P', 'Lune_chic_galaxy_P', 'Lune_chic_gold_P', 'Lune_chic_painted_P', 'Lune_chic_red_P', 'Lune_chic_white_P'],
  'Lune outfit': ['chic_lune-sleeveless-barefoot_P', 'chic_lune-sleeveless-boots_P', 'chic_lune-sleeves-barefoot_P', 'chic_lune-sleeves-boots_P'],
  'Sciel color': ['Sciel_chic_33rd_P', 'Sciel_chic_black_P', 'Sciel_chic_blue_P', 'Sciel_chic_default_P', 'Sciel_chic_fire_P', 'Sciel_chic_galaxy_P', 'Sciel_chic_gold_P', 'Sciel_chic_painted_P', 'Sciel_chic_red_P', 'Sciel_chic_white_P'],
  'Sciel outfit': ['chic_sciel-sleeveless-barefoot_P', 'chic_sciel-sleeveless-boots_P', 'chic_sciel-sleeves-barefoot_P', 'chic_sciel-sleeves-boots_P'],
  None: ['_only Lune mod_fix_P', '_only Separate colors_P']},
}

def fstr(s):
    b = s.encode() + b'\0'
    return struct.pack('<i', len(b)) + b

def tiny_utoc(files):
    """Minimal indexed .utoc (v6, no chunks) whose directory index lists `files` under ../../../"""
    strings, dirs, fents = [], [], []
    def sid(s):
        if s not in strings: strings.append(s)
        return strings.index(s)
    NONE = 0xFFFFFFFF
    dirs.append([NONE, NONE, NONE, NONE])          # root
    def get_dir(parent, name):
        c = dirs[parent][1]
        while c != NONE:
            if strings[dirs[c][0]] == name: return c
            c = dirs[c][2]
        dirs.append([sid(name), NONE, dirs[parent][1], NONE]); dirs[parent][1] = len(dirs) - 1
        return len(dirs) - 1
    for f in files:
        parts = f.split('/'); d = 0
        for p in parts[:-1]: d = get_dir(d, p)
        fents.append([sid(parts[-1]), dirs[d][3], len(fents)]); dirs[d][3] = len(fents) - 1
    di = fstr('../../../') + struct.pack('<i', len(dirs)) + b''.join(struct.pack('<4I', *d) for d in dirs)
    di += struct.pack('<i', len(fents)) + b''.join(struct.pack('<3I', *e) for e in fents)
    di += struct.pack('<i', len(strings)) + b''.join(fstr(s) for s in strings)
    hdr = bytearray(144); hdr[:16] = b'-==--==--==--==-'; hdr[16] = 6
    struct.pack_into('<9I', hdr, 20, 144, 0, 0, 12, 0, 32, 0x10000, len(di), 1)
    hdr[80] = 8
    return bytes(hdr) + di

def build(root, mod='Cheekier Chic V331'):
    base = os.path.join(root, mod)
    for dress, groups in TREE.items():
        for grp, opts in groups.items():
            for o in opts:
                d = os.path.join(base, dress, *( [grp] if grp else [] ), o)
                os.makedirs(d, exist_ok=True)
                who = 'Lune' if 'lune' in o.lower() and 'sciel' not in o.lower() else ('Sciel' if 'sciel' in o.lower() else 'Shared')
                kind = 'Color' if 'color' in (grp or '').lower() else 'Mesh'
                pkg = f'Sandfall/Content/Characters/{who}/Chic/{kind}/{o}_asset.uasset'
                if 'outfit' in (grp or '').lower():
                    pkg = f'Sandfall/Content/Characters/{who}/Chic/SK_{who}_Chic.uasset'   # outfits of one char clash
                open(os.path.join(d, o + '.pak'), 'wb').write(b'PAK' + o.encode())
                open(os.path.join(d, o + '.ucas'), 'wb').write(b'UCAS' + o.encode())
                open(os.path.join(d, o + '.utoc'), 'wb').write(tiny_utoc([pkg]))
                # extra paks the real v3.3.1 folders carry (per the Nexus file preview)
                extra = None
                if (grp or '').endswith('outfit') and dress == 'Lace dress':
                    extra = f'{who.lower()}_lace_material_P'
                elif grp == 'Sciel outfit' and dress == 'Non-Lace dress':
                    extra = 'Sciel_separate_P'
                if extra:
                    for ext in ('.pak', '.ucas'):
                        open(os.path.join(d, extra + ext), 'wb').write(extra.encode())
                    open(os.path.join(d, extra + '.utoc'), 'wb').write(
                        tiny_utoc([f'Sandfall/Content/Characters/{who}/Chic/{extra}.uasset']))
    # a second, simple mod with no rules file to exercise the auto layout
    simple = os.path.join(root, 'Some Hair Mod')
    for o in ['Red_P', 'Blue_P']:
        d = os.path.join(simple, 'Colors', o); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, o + '.pak'), 'wb').write(b'x')
        open(os.path.join(d, o + '.utoc'), 'wb').write(tiny_utoc([f'Sandfall/Content/Characters/Lune/Hair/{o}.uasset']))
    d = os.path.join(simple, '_Optional fix_P'); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'HairFix_P.pak'), 'wb').write(b'x')

if __name__ == '__main__':
    build(sys.argv[1])
    print('fake library at', sys.argv[1])
