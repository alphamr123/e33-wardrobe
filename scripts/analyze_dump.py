"""Read a minidump of a frozen or crashed game: where the game thread is, the access violation on
its stack if there is one, and the UE4SS / Lua functions on that stack (developer tool).

    pip install minidump            (a pure-Python minidump reader)
    python scripts/analyze_dump.py <file.dmp> [--ue4ss <folder with UE4SS.dll and UE4SS.pdb>]

Dumps: ProcDump on the user's PC, e.g.
    procdump64.exe -accepteula -mm -n 2 -s 5 SandFall-Win64-Shipping.exe <folder>
(two small dumps 5 s apart: if the game thread is in the same place in both, it is blocked).

Symbols: the "zDEV" zip of the user's exact UE4SS build has UE4SS.pdb. The experimental builds are
in the GitHub release "experimental" of UE4SS-RE/RE-UE4SS (zDEV-UE4SS_v3.0.1-<n>-g<sha>.zip). The
build string is at the top of UE4SS.log ("Git SHA #..."). This script checks that the DLL's
timestamp matches the dump before naming anything. Naming uses llvm-symbolizer if it is on PATH,
else (Windows) the system's dbghelp.dll with the UE4SS.pdb next to UE4SS.dll.

Reading the result (from the freezes in 2026-10):
  * the game thread's instruction pointer in an ntdll system-call stub: the stub's "mov eax, N"
    is the call (8 = NtWriteFile, 4 = NtWaitForSingleObject, 0x34 = NtDelayExecution);
  * an ACCESS_VIOLATION record on the stack: the real cause; the frames under it are the call
    chain at the moment of the fault. Frames above it are the exception handlers (ReShade add-ons
    can hang there, which turns a crash into a freeze);
  * Lua interpreter frames (luaV_execute, luaD_precall, ...) under the fault mean Lua code was
    running; none means the mod's Lua was not on the stack.
The stack is read by scanning for return addresses, so stale values appear too: trust the order
below the exception record, and confirm with the second dump.
"""
import os
import shutil
import struct
import subprocess
import sys

CODES = {0xC0000005: 'ACCESS_VIOLATION', 0xE06D7363: 'C++ exception', 0xC00000FD: 'STACK_OVERFLOW',
         0xC0000374: 'HEAP_CORRUPTION', 0xC0000409: 'STACK_BUFFER_OVERRUN', 0x80000003: 'BREAKPOINT'}


def load(path):
    try:
        from minidump.minidumpfile import MinidumpFile
    except ImportError:
        sys.exit('needs: pip install minidump')
    return MinidumpFile.parse(path)


def modules(mf):
    return sorted((m.baseaddress, m.baseaddress + m.size, m.name.split('\\')[-1], m) for m in mf.modules.modules)


def where(mods, a):
    for b, e, n, _ in mods:
        if b <= a < e:
            return n, a - b
    return None, a


def stack(mf, thread, size=0x20000):
    r = mf.get_reader()
    rsp = thread.ContextObject.Rsp
    data = b''
    for k in range(0, size, 8):
        try:
            data += r.read(rsp + k, 8)
        except Exception:
            break
    return data


def syscall_number(mf, mods, rip):
    """The "mov eax, N" of the ntdll stub the thread is in (the stub starts 0x14 before the return)."""
    try:
        code = mf.get_reader().read(rip - 0x14, 8)
    except Exception:
        return None
    if code[:4] == bytes.fromhex('4c8bd1b8'):
        return struct.unpack_from('<I', code, 4)[0]
    return None


def dbghelp_namer(dll):
    """Windows without llvm: name UE4SS.dll offsets with the system's dbghelp.dll and the UE4SS.pdb
    next to the DLL (offline, no symbol server). Function name and source line, or None."""
    import ctypes
    import ctypes.wintypes as wt
    try:
        dbg = ctypes.WinDLL('dbghelp.dll')
    except (OSError, AttributeError):
        return None
    h = wt.HANDLE(0xE33)                                    # any unique value: no live process
    dbg.SymSetOptions(0x2 | 0x10 | 0x4)                     # UNDNAME | LOAD_LINES | DEFERRED_LOADS
    if not dbg.SymInitializeW(h, ctypes.c_wchar_p(os.path.dirname(dll)), False):
        return None
    base = 0x180000000
    dbg.SymLoadModuleExW.restype = ctypes.c_uint64
    dbg.SymLoadModuleExW.argtypes = [wt.HANDLE, wt.HANDLE, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint64,
                                     wt.DWORD, ctypes.c_void_p, wt.DWORD]
    if not dbg.SymLoadModuleExW(h, None, dll, None, base, os.path.getsize(dll), None, 0):
        return None

    class SYMBOL(ctypes.Structure):
        _fields_ = [('SizeOfStruct', wt.ULONG), ('TypeIndex', wt.ULONG), ('Reserved', ctypes.c_uint64 * 2),
                    ('Index', wt.ULONG), ('Size', wt.ULONG), ('ModBase', ctypes.c_uint64), ('Flags', wt.ULONG),
                    ('Value', ctypes.c_uint64), ('Address', ctypes.c_uint64), ('Register', wt.ULONG),
                    ('Scope', wt.ULONG), ('Tag', wt.ULONG), ('NameLen', wt.ULONG), ('MaxNameLen', wt.ULONG),
                    ('Name', ctypes.c_wchar * 512)]

    class LINE(ctypes.Structure):
        _fields_ = [('SizeOfStruct', wt.DWORD), ('Key', ctypes.c_void_p), ('LineNumber', wt.DWORD),
                    ('FileName', ctypes.c_wchar_p), ('Address', ctypes.c_uint64)]

    def name(rva):
        s = SYMBOL()
        s.SizeOfStruct, s.MaxNameLen = ctypes.sizeof(SYMBOL) - 512 * 2, 512
        disp = ctypes.c_uint64()
        if not dbg.SymFromAddrW(h, ctypes.c_uint64(base + rva), ctypes.byref(disp), ctypes.byref(s)):
            return ''
        ln, d2 = LINE(), wt.DWORD()
        ln.SizeOfStruct = ctypes.sizeof(LINE)
        at = ''
        if dbg.SymGetLineFromAddrW64(h, ctypes.c_uint64(base + rva), ctypes.byref(d2), ctypes.byref(ln)):
            at = f'  ({os.path.basename(ln.FileName or "")}:{ln.LineNumber})'
        return s.Name[:160] + at
    return name


def symbolizer(ue4ss_dir):
    if not ue4ss_dir:
        return None
    exe = shutil.which('llvm-symbolizer') or next((shutil.which(f'llvm-symbolizer-{v}') for v in range(20, 10, -1)
                                                   if shutil.which(f'llvm-symbolizer-{v}')), None)
    dll = os.path.join(ue4ss_dir, 'UE4SS.dll')
    if not exe:
        name = dbghelp_namer(dll) if os.name == 'nt' else None
        if name is None:
            print('(no llvm-symbolizer on PATH, no dbghelp: UE4SS frames stay as offsets)')
        return name

    def name(rva):
        p = subprocess.run([exe, f'--obj={dll}', '--relative-address', '--functions=short', '--demangle', hex(rva)],
                           capture_output=True, text=True)
        n = (p.stdout.splitlines() or ['?'])[0]
        return '' if n in ('??', '_tls_end') else n
    return name


def dll_timestamp(path):
    b = open(path, 'rb').read(4096)
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    return struct.unpack_from('<I', b, pe + 8)[0]


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith('-'):
        print(__doc__)
        return 2
    ue4ss_dir = None
    if '--ue4ss' in args:
        i = args.index('--ue4ss')
        ue4ss_dir = args[i + 1]
        del args[i:i + 2]
    mf = load(args[0])
    mods = modules(mf)
    ue = next((m for b, e, n, m in mods if n.lower() == 'ue4ss.dll'), None)
    name = None
    if ue is not None:
        print(f'UE4SS.dll in the dump: timestamp {ue.timestamp:#x}, size {ue.size:#x}')
        if ue4ss_dir:
            ts = dll_timestamp(os.path.join(ue4ss_dir, 'UE4SS.dll'))
            if ts != ue.timestamp:
                print(f'  the UE4SS.dll given has timestamp {ts:#x}: another build, names would be wrong; not used')
            else:
                name = symbolizer(ue4ss_dir)
    others = [n for b, e, n, m in mods if '\\Windows\\' not in m.name and 'WinSxS' not in m.name]
    print('non-Windows modules:', ', '.join(others))

    names = thread_names(args[0])
    fault = show_thread(mf, mods, name, 0, names)
    if fault is None:
        # PC 17 Oct: the game crashed on a worker ("Foreground Worker #0"); the game thread only waited
        for ti in range(1, len(mf.threads.threads)):
            if exception_records(mf, mods, name, ti, quiet=True):
                print('\n--- the exception is on another thread:')
                show_thread(mf, mods, name, ti, names)
                break
        else:
            print('\nno exception record on any thread\'s stack (a freeze, not a crash?)')
    return 0


def thread_names(path):
    """{thread id: name} from the dump's ThreadNameListStream (Windows 10+; Unreal names its threads)."""
    out = {}
    try:
        with open(path, 'rb') as f:
            head = f.read(32)
            n, rva = struct.unpack_from('<II', head, 8)
            f.seek(rva)
            dirs = f.read(12 * n)
            for i in range(n):
                typ, _size, r = struct.unpack_from('<III', dirs, 12 * i)
                if typ != 24:
                    continue
                f.seek(r)
                cnt = struct.unpack('<I', f.read(4))[0]
                entries = f.read(12 * cnt)
                for k in range(cnt):
                    tid, nrva = struct.unpack_from('<IQ', entries, 12 * k)
                    f.seek(nrva)
                    ln = struct.unpack('<I', f.read(4))[0]
                    out[tid] = f.read(ln).decode('utf-16-le', 'replace')
    except (OSError, struct.error):
        pass
    return out


def exception_records(mf, mods, name, ti, quiet=False):
    """Exception records found on thread ti's stack: [(stack offset, text)]."""
    data = stack(mf, mf.threads.threads[ti])
    found = []
    for o in range(0, len(data) - 0x98, 4):
        code = struct.unpack_from('<I', data, o)[0]
        if code in CODES and struct.unpack_from('<I', data, o + 4)[0] <= 0x100 \
                and struct.unpack_from('<I', data, o + 0x18)[0] <= 15:
            addr = struct.unpack_from('<Q', data, o + 0x10)[0]
            params = [struct.unpack_from('<Q', data, o + 0x20 + 8 * i)[0] for i in range(2)]
            m, a = where(mods, addr)
            if m is None:
                continue                                    # not an address in a module: not a record
            what = ''
            if code == 0xC0000005:
                what = f" ({'write' if params[0] == 1 else 'read'} of {params[1]:#x})"
            fn = f'  [{name(a)}]' if name and m == 'UE4SS.dll' and not quiet else ''
            found.append((o, f'{CODES[code]} at {m}+{a:#x}{what}{fn}  (record at stack +{o:#x})'))
    return found


def show_thread(mf, mods, name, ti, names):
    t = mf.threads.threads[ti]
    data = stack(mf, t)
    mod, off = where(mods, t.ContextObject.Rip)
    sc = syscall_number(mf, mods, t.ContextObject.Rip) if mod == 'ntdll.dll' else None
    label = names.get(t.ThreadId) or ('game thread' if ti == 0 else 'thread')
    print(f'\n{label} (thread {ti}, tid {t.ThreadId}): at {mod}+{off:#x}'
          + (f', system call {sc:#x}' if sc is not None else ''))
    recs = exception_records(mf, mods, name, ti)
    for _o, text in recs:
        print(text)
    fault_at = recs[0][0] if recs else None
    if fault_at is None:
        print('no exception record on this thread\'s stack')
    print('\nreturn addresses below the exception record (the call chain at the fault), oldest last:' if recs
          else '\nreturn addresses on the stack, newest first:')
    lua = shown = 0
    for o in range(fault_at or 0, len(data) - 8, 8):
        v = struct.unpack_from('<Q', data, o)[0]
        m, a = where(mods, v)
        if not m or a == 0:
            continue
        fn = name(a) if name and m == 'UE4SS.dll' else ''
        if fn.startswith('lua') or 'Lua' in fn:
            lua += 1
        if shown < 60:
            print(f'  +{o:05x} {m}+{a:#x} {fn}')
            shown += 1
    if name:
        print(f'\nLua-related UE4SS frames on that part of the stack: {lua}')
    return fault_at


if __name__ == '__main__':
    sys.exit(main())
