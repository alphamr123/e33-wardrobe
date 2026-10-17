"""Run every test suite:  python tests/run_suites.py   (or: pytest)

Each test_*.py is a script that prints PASS / FAIL lines and exits non-zero after a failure.
This runner starts each one in its own process. The Lua suites need lupa
(pip install -r requirements-dev.txt) and are skipped without it. Three suites need game-format
fixtures that can't be shipped (see docs/DEVELOPMENT.md); they run only when these are set:

  E33_RETOC                                 retoc executable (all three)
  E33_E2E_PAKS, E33_E2E_BASE                test_relocate_e2e.py: fake Paks dir, base legacy dir
  E33_PREVIEW_GLOBAL, E33_PREVIEW_LEGACY    test_previews.py: script objects dir, texture legacy dir
  E33_RELOC_SRC                             test_relocation.py: a legacy package tree to relocate

test_app_backend.py always runs; with E33_E2E_PAKS, E33_E2E_BASE and E33_RETOC set it also runs a full
add job through the app's Api, and E33_SAMPLE_MOD (option folders of a real outfit mod) checks sorting.
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

LUA = ['test_lua_mock', 'test_lua_mock_real', 'test_lua_switching', 'test_lua_coverage',
       'test_lua_dispatch', 'test_lua_menu', 'test_lua_outfit_whole', 'test_lua_clean', 'test_lua_redesign']
PLAIN = ['test_mixer', 'test_relocate_units', 'test_app_monitor', 'test_app_backend', 'test_docs_index',
         'test_collect_crash']
DATA = {
    'test_app_ui': ('E33_E2E_PAKS', 'E33_RETOC', 'E33_SAMPLE_ARCHIVES', 'E33_E2E_BASE'),
    'test_relocate_e2e': ('E33_E2E_PAKS', 'E33_E2E_BASE', 'E33_RETOC'),
    'test_previews': ('E33_PREVIEW_GLOBAL', 'E33_PREVIEW_LEGACY', 'E33_RETOC'),
    'test_relocation': ('E33_RELOC_SRC', 'E33_RETOC'),
}


def plan():
    """(suite, arguments, why it is skipped or None)"""
    lupa = importlib.util.find_spec('lupa') is not None
    out = [(n, [], None if lupa else 'needs lupa (pip install -r requirements-dev.txt)') for n in LUA]
    out += [(n, [], None) for n in PLAIN]
    for n, names in DATA.items():
        missing = [e for e in names if not os.environ.get(e)]
        out.append((n, [os.environ.get(e, '') for e in names], 'set ' + ', '.join(missing) if missing else None))
    return out


def run(name, args):
    p = subprocess.run([sys.executable, os.path.join(HERE, name + '.py'), *args], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', cwd=os.path.dirname(HERE),
                       env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
    out = p.stdout + p.stderr
    passed = sum(1 for line in out.splitlines() if line.startswith('PASS'))
    failed = [line for line in out.splitlines() if line.startswith('FAIL')]
    return p.returncode, passed, failed, out


try:
    import pytest
except ImportError:
    pytest = None

if pytest:
    @pytest.mark.parametrize('name,args,skip', plan(), ids=[p[0] for p in plan()])
    def test_suite(name, args, skip):
        if skip:
            pytest.skip(skip)
        code, _passed, failed, out = run(name, args)
        assert code == 0, '\n'.join(failed) or out[-3000:]


def main():
    bad = 0
    for name, args, skip in plan():
        if skip:
            print(f'SKIP {name}: {skip}')
            continue
        code, passed, failed, out = run(name, args)
        if code == 0:
            print(f'ok   {name}: {passed} checks')
        else:
            bad += 1
            print(f'FAIL {name}: exit {code}, {len(failed)} failed check(s)')
            for line in failed or out.splitlines()[-15:]:
                print('       ' + line)
    print(f'\n{bad} suite(s) failed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
