"""Relocation tests on real cooked legacy assets.

usage: python -I tests/test_relocation.py <legacy_root containing Sandfall/Content/...> <retoc>

Scenarios (each verified by e33legacy.verify_rewrite on every header, then `retoc to-zen`):
  numbered   relocate one package whose path ends in _N (stored as base name + FName number)
  base-only  relocate a base path '/X/P' while '/X/P_1' etc. stay vanilla
  all        relocate every package in the tree
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import e33legacy as L  # noqa: E402


def packages(root):
    out = {}
    for dp, _ds, fs in os.walk(root):
        for f in fs:
            info = L.rel_to_package(os.path.relpath(os.path.join(dp, f), root))
            if info and info[1] in ('.uasset', '.umap'):
                out[info[0]] = os.path.join(dp, f)
    return out


def main():
    src, retoc = sys.argv[1], sys.argv[2]
    pk = packages(src)
    infos = {p: L.read_package_info(f) for p, f in pk.items()}
    importers = {}
    for p, i in infos.items():
        for imp in i['imported_packages']:
            importers.setdefault(imp, set()).add(p)
    numbered = sorted(p for p in importers if L.split_number(p.rsplit('/', 1)[1])[1] and p in pk)
    numbered_any = sorted(p for p in importers if L.split_number(p.rsplit('/', 1)[1])[1])
    print(f'{len(pk)} packages; {len(numbered_any)} imported paths end in _N ({len(numbered)} of them are in the tree)')
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    def run_case(name, keys):
        tmp = tempfile.mkdtemp(prefix='e33reloc_')
        try:
            mapping = L.plan_relocation(keys, 'test|' + name)
            try:
                rep = L.relocate_tree(src, os.path.join(tmp, 'out'), mapping)
            except L.LegacyError as e:
                check(f'{name}: rewrite + verify', False, e)
                return None
            check(f'{name}: rewrite + verify ({rep["files"]} files, {rep["appended_names"]} names appended, '
                  f'{rep["patched_refs"]} refs repointed)', True)
            out_pk = packages(os.path.join(tmp, 'out'))
            for old, new in mapping.items():
                if old in pk and new not in out_pk:
                    check(f'{name}: {old} moved', False, new)
            # every importer now imports the mapped path, and nothing else changed
            bad = []
            for p, i in infos.items():
                np_ = mapping.get(p, p)
                if np_ not in out_pk:
                    continue
                got = L.read_package_info(out_pk[np_])['imported_packages']
                want = [mapping.get(x, x) for x in i['imported_packages']]
                if got != want:
                    bad.append((p, [(a, b) for a, b in zip(got, want) if a != b][:2]))
            check(f'{name}: all importers follow the mapping', not bad, bad[:3])
            z = subprocess.run([retoc, 'to-zen', '--version', 'UE5_4', os.path.join(tmp, 'out'),
                                os.path.join(tmp, 'Z_P.utoc')], capture_output=True, text=True)
            check(f'{name}: retoc to-zen', z.returncode == 0, (z.stdout + z.stderr)[-400:])
            lst = subprocess.run([retoc, 'list', '--path', os.path.join(tmp, 'Z_P.utoc')], capture_output=True, text=True).stdout
            missing = [n for o, n in mapping.items() if o in pk and n.split('/Game/', 1)[1] + '.uasset' not in lst]
            stale = [o for o in mapping if o in pk and o.split('/Game/', 1)[1] + '.uasset' in lst]
            check(f'{name}: old paths gone from the container', not stale, stale[:3])
            check(f'{name}: container lists the new paths', not missing, missing[:3])
            return mapping
        finally:
            if os.environ.get('KEEP_RELOC'):
                print('   kept', tmp)
            else:
                shutil.rmtree(tmp, ignore_errors=True)

    if numbered_any:                                  # imported '/X/P_N' paths, relocated (file not needed)
        run_case('numbered', numbered_any[:5])
    bases = sorted({L.split_number(p.rsplit('/', 1)[1])[0] for p in numbered_any})
    if numbered_any:
        p = numbered_any[0]
        base = p.rsplit('/', 1)[0] + '/' + L.split_number(p.rsplit('/', 1)[1])[0]
        run_case('base-only', [base])                 # e.g. '/X/DA_Item' while '/X/DA_Item_10' stays
    run_case('all', sorted(pk))
    # header growth must keep export payload offsets consistent: re-read every grown header
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
