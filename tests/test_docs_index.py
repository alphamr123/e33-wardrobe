"""docs/index.md is generated from the code (scripts/gen_index.py) and must be current; every
source file starts with a header line saying what it is (run: python tests/test_docs_index.py).

The check itself is tested too: in a copy of the repository, a file without a header and a stale
index must both make `gen_index.py --check` fail.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GEN = os.path.join('scripts', 'gen_index.py')


def check_run(root):
    p = subprocess.run([sys.executable, '-I', os.path.join(root, GEN), '--check'], cwd=root,
                       capture_output=True, text=True, encoding='utf-8')
    return p.returncode, p.stdout + p.stderr


def main():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    rc, out = check_run(ROOT)
    check('docs/index.md is current and every file has a header (else: python scripts/gen_index.py)', rc == 0, out[-800:])

    tmp = tempfile.mkdtemp(prefix='e33index_')
    try:
        copy = os.path.join(tmp, 'repo')
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        import gen_index
        if shutil.which('git') and os.path.isdir(os.path.join(ROOT, '.git')):
            # on Windows a text-mode pipe sent CRLF and git matched nothing (handoff/ got indexed)
            got = gen_index.git_ignored(ROOT, ['handoff/a b.py', 'tools/e33common.py', 'handoff/x.py'])
            check('git-ignored files (handoff/, also with a space in the name) stay out of the index',
                  got == {'handoff/a b.py', 'handoff/x.py'}, got)
        local_only = {os.path.normcase(os.path.join(ROOT, *r.split('/')))
                      for r in gen_index.git_ignored(ROOT, gen_index.source_files_all(ROOT))}
        plain = shutil.ignore_patterns('.git', 'dist', 'release', 'bin', 'build_app', 'dist_app', '__pycache__', '*.zip')

        def skip(d, names):     # what git ignores stays out of the copy too (it has no .git)
            return set(plain(d, names)) | {n for n in names if os.path.normcase(os.path.join(d, n)) in local_only}
        shutil.copytree(ROOT, copy, ignore=skip)
        check('  (the copy passes the check before anything is changed)', check_run(copy)[0] == 0)

        with open(os.path.join(copy, 'tools', 'e33_new_helper.py'), 'w', encoding='utf-8') as f:
            f.write('import os\n\nX = 1\n')
        rc, out = check_run(copy)
        check('a new file without a header line fails the check, by name', rc == 1 and 'e33_new_helper.py' in out
              and 'NO HEADER' in out, out[-400:])

        with open(os.path.join(copy, 'tools', 'e33_new_helper.py'), 'w', encoding='utf-8') as f:
            f.write('"""A helper for the test."""\nX = 1\n')
        rc, out = check_run(copy)
        check('  with a header it still fails until the index is written again (stale index)',
              rc == 1 and 'out of date' in out, out[-400:])
        subprocess.run([sys.executable, '-I', os.path.join(copy, GEN)], cwd=copy, capture_output=True)
        rc, out = check_run(copy)
        check('  and passes after python scripts/gen_index.py', rc == 0, out[-400:])
        idx = open(os.path.join(copy, 'docs', 'index.md'), encoding='utf-8').read()
        check('  the index lists the file with its header line', '| `tools/e33_new_helper.py` | A helper for the test |' in idx)

        # a "header" with no words (PC review: main.lua's '--[[' alone on its line showed as "[[")
        with open(os.path.join(copy, 'tools', 'e33_new_helper.lua'), 'w', encoding='utf-8') as f:
            f.write('--[[\n]]\nreturn 1\n')
        rc, out = check_run(copy)
        check('a header without words ("--[[" alone) counts as no header', rc == 1 and 'e33_new_helper.lua' in out
              and 'NO HEADER' in out, out[-400:])
        with open(os.path.join(copy, 'tools', 'e33_new_helper.lua'), 'w', encoding='utf-8') as f:
            f.write('--[[\nA test helper for the index.\n]]\nreturn 1\n')
        subprocess.run([sys.executable, '-I', os.path.join(copy, GEN)], cwd=copy, capture_output=True)
        idx = open(os.path.join(copy, 'docs', 'index.md'), encoding='utf-8').read()
        check('  a --[[ block comment gives its first text line',
              '| `tools/e33_new_helper.lua` | A test helper for the index |' in idx)

        # an app API method missing from app/API.md is a problem too
        api = os.path.join(copy, 'app', 'API.md')
        text = open(api, encoding='utf-8').read()
        open(api, 'w', encoding='utf-8').write(text.replace('reconcile', 'recon_cile'))
        subprocess.run([sys.executable, '-I', os.path.join(copy, GEN)], cwd=copy, capture_output=True)
        rc, out = check_run(copy)
        check('an API method missing from app/API.md fails the check', rc == 1 and 'reconcile' in out, out[-400:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
