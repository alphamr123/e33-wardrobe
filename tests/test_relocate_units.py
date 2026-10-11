"""Small pure functions of the relocator (no game files, no retoc)."""
import os
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import e33_relocate  # noqa: E402


def main():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    # PC 2026-10-11: two mods by one author both ship /Game/chic_MyMod (a PrimaryAssetLabel)
    label = {'/Game/chic_MyMod': {'class': 'PrimaryAssetLabel', 'object': 'chic_MyMod'}}
    tex = {'/Game/Characters/Lune/Bikini/T_Shared': {'class': 'Texture2D', 'object': 'T_Shared'}}
    reg = [
        {'name': 'Mod A', 'shared': ['/game/chic_mymod', '/game/characters/lune/bikini/t_shared'],
         'slots': [{'variants': [{'classes': {**label, **tex}}]}]},
        {'name': 'Mod B', 'shared': ['/game/chic_mymod'], 'slots': [{'variants': [{'classes': dict(label)}]}]},
    ]
    check('a label asset in two mods\' shared paks is not a clash', e33_relocate.shared_clashes(reg) == {},
          e33_relocate.shared_clashes(reg))
    reg[1]['shared'].append('/game/characters/lune/bikini/t_shared')
    check('a texture in both still is', e33_relocate.shared_clashes(reg)
          == {'/game/characters/lune/bikini/t_shared': ['Mod A', 'Mod B']}, e33_relocate.shared_clashes(reg))
    # PC 2026-10-11: colour-only options (textures that replace the game's) showed no sizes: the
    # full texture read failed and nothing was recorded. The header alone still gives the size.
    tmp = tempfile.mkdtemp(prefix='e33units_')
    base = os.path.join(tmp, 'T_Colour')
    with open(base + '.uexp', 'wb') as f:          # platform data header only, no mips to follow
        f.write(struct.pack('<iiI', 2048, 1024, 0) + struct.pack('<i', 7) + b'PF_BC7\0' + b'\xff' * 8)
    entry, cands = {'object': 'T_Colour'}, []
    e33_relocate.texture_info(base, entry, cands)
    check('a texture the full read fails on still gets its size and format from the header',
          (entry.get('width'), entry.get('height'), entry.get('format')) == (2048, 1024, 'PF_BC7'), entry)
    check('  and the reason the full read failed is recorded', bool(entry.get('tex_error')), entry)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
