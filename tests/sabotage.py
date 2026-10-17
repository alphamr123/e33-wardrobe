"""Break one line of the code on purpose, run a test suite, put the line back: a test that never
fails can't be trusted. Judged by the suite's exit code.

    python tests/sabotage.py <suite> <file> <old text> <new text>
    python tests/sabotage.py test_lua_redesign lua/E33Wardrobe/Scripts/main.lua "B.broken[ch.ek] = true" ""

The old text must occur in the file; only its first occurrence is replaced. The file is restored
and compared byte for byte afterwards, also when the run is interrupted. Prints CAUGHT (the suite
failed) or NOT CAUGHT, and the first FAIL lines. Exit code 0 = caught.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    suite, rel, old, new = sys.argv[1:]
    path = os.path.join(ROOT, rel)
    src = open(path, 'rb').read()
    oldb, newb = old.encode('utf-8'), new.encode('utf-8')
    if oldb not in src:
        print(f'old text not in {rel}')
        return 2
    fd, backup = tempfile.mkstemp(prefix='sabotage_')
    os.close(fd)                # Windows can't delete a file that is still open
    shutil.copyfile(path, backup)
    try:
        open(path, 'wb').write(src.replace(oldb, newb, 1))
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', suite + '.py')], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    finally:
        shutil.copyfile(backup, path)
        os.remove(backup)
    assert open(path, 'rb').read() == src, 'file not restored!'
    fails = [x for x in p.stdout.splitlines() if x.startswith('FAIL')]
    caught = p.returncode != 0
    print(('CAUGHT' if caught else 'NOT CAUGHT') + f' (exit {p.returncode}, {len(fails)} FAIL line(s))')
    for x in fails[:3]:
        print('  ' + x[:200])
    if caught and not fails:
        print('  (no FAIL line: the suite crashed; check the change is a valid program)')
    return 0 if caught else 1


if __name__ == '__main__':
    sys.exit(main())
