"""Every thread of a freeze dump: where it is, its system call, the first modules on its stack, and
which add-ons (UE4SS, ReShade/relimiter, frame generation, ...) are on it (developer tool).

    pip install minidump
    python scripts/dump_threads.py <file.dmp> [<second.dmp>]

With two dumps of one freeze (ProcDump -n 2 -s 5), threads that are running (not in a system
call) at the same address in both are listed as "SPINNING": a busy loop. 15 Oct 2026 this found
the relimiter add-on spinning at relimiter.addon64+0x10d1f in both UE4SS 1176 freezes, with no
mod code on the game thread. scripts/analyze_dump.py names UE4SS's functions on the game thread.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_dump as ad  # noqa: E402

SYS = ('ntdll.dll', 'KERNELBASE.dll', 'kernel32.dll', 'win32u.dll', 'USER32.dll')
WATCH = ('UE4SS.dll', 'relimiter.addon64', 'dxgi.dll', 'renodx-clairobscur_expedition33.addon64', 'dsound.dll',
         'ClairObscurFix.asi', 'RTSSHooks64.dll', 'amd_fidelityfx_framegeneration_dx12.dll',
         'amd_fidelityfx_upscaler_dx12.dll', 'sl.interposer.dll', 'libxell.dll', 'main.dll')


def threads(path):
    mf = ad.load(path)
    mods = ad.modules(mf)
    out = {}
    for i, t in enumerate(mf.threads.threads):
        rip = t.ContextObject.Rip
        n, off = ad.where(mods, rip)
        sc = ad.syscall_number(mf, mods, rip) if n == 'ntdll.dll' else None
        data = ad.stack(mf, t, 0x6000)
        frames, flags = [], set()
        for k in range(0, len(data) - 7, 8):
            a = struct.unpack_from('<Q', data, k)[0]
            m, o = ad.where(mods, a)
            if m and m not in SYS and o > 0x1000:
                if m in WATCH:
                    flags.add(m)
                if len(frames) < 4:
                    frames.append(f'{m}+{o:#x}')
        out[t.ThreadId] = (i, f'{n}+{off:#x}', sc, frames, sorted(flags))
    return out


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0 if len(sys.argv) > 1 else 2
    a = threads(sys.argv[1])
    b = threads(sys.argv[2]) if len(sys.argv) > 2 else None
    for tid, (i, where, sc, frames, flags) in sorted(a.items(), key=lambda kv: kv[1][0]):
        mark = ''
        if b and tid in b and sc is None and b[tid][2] is None and b[tid][1] == where:
            mark = 'SPINNING '
        print(f'{mark}{i:3} tid {tid:6} {where} sc={sc} | {" ".join(frames)} | {",".join(flags)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
