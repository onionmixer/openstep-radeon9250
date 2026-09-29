#!/usr/bin/env python3
"""Store widths of the MMIO helpers in the target-built reloc (docs/R1C_R2A_IMPL_PLAN.md section 2-8).

  check_reloc.py <reloc> <sum> <blocks> [--marker DIR]
        check the file's BSD sum, parse the Mach-O, disassemble
        _rdnMmioRead32/_rdnMmioWrite8/_rdnMmioWrite32 and require one 8-bit
        store in Write8, one 32-bit store in Write32, none in Read32; on PASS
        write DIR/R2ARELOC_PASS holding "<sum> <blocks>"
  check_reloc.py --self-test

What this proves, and only this: the store width of the three helpers as the
target's cc 2.7.2.1 compiled them.  That no other store exists, the call
counts and the offsets are the source rules', the host objects' and the
simulator's (tools/r2a/check_r2a_src.py, sim_r2a.py).  kl_ld leaves no
relocation on a module-internal PC-relative call, so calls are not counted
here; relocations only patch address fields, so widths are read from the
bytes before relocation.

Mach-O (32-bit, little-endian, magic 0xfeedface, cputype 7): the __TEXT,__text
section from LC_SEGMENT, symbols from LC_SYMTAB.  A symbol opens a function
range if (n_type & N_STAB) == 0, (n_type & N_TYPE) == N_SECT and n_sect is
the __text ordinal; the range ends at the next such symbol with a strictly
greater address, or at the section end.  Stabs (N_SLINE, N_FUN, ...) are
ignored -- the same file holds thousands.

Two counts are printed per helper: stores whose base is not %esp/%ebp (the
rule), and stores through any base.  Code built without a frame pointer could
use %ebp as a general register; a store through it is then not counted by the
rule, which fails the helper rather than passing it, and the second count shows why.
"""

import importlib.util
import shutil
import atexit
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))

MH_MAGIC = 0xfeedface
CPU_TYPE_I386 = 7
LC_SEGMENT = 1
LC_SYMTAB = 2
N_STAB = 0xe0
N_TYPE = 0x0e
N_SECT = 0x0e
N_SLINE = 0x44

WANT = {'_rdnMmioRead32': [], '_rdnMmioWrite8': [8], '_rdnMmioWrite32': [32]}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


st = _load('stores', os.path.join(HERE, 'stores.py'))
pk = _load('pack_r1', os.path.join(PROJ, 'tools', 'r1', 'pack_probe.py'))


class MachOError(Exception):
    pass


def parse_macho(data):
    """Return (text section dict, [(name, n_type, n_sect, n_value)])."""
    if len(data) < 28:
        raise MachOError('file too short for a Mach-O header')
    magic, cputype, _, filetype, ncmds, sizeofcmds, _ = struct.unpack_from('<7I', data, 0)
    if magic != MH_MAGIC:
        raise MachOError('magic %08x is not 0xfeedface' % magic)
    if cputype != CPU_TYPE_I386:
        raise MachOError('cputype %d is not i386 (7)' % cputype)
    off = 28
    ordinal = 0
    text = None
    symtab = None
    for _ in range(ncmds):
        if off + 8 > len(data):
            raise MachOError('load command past the end')
        cmd, cmdsize = struct.unpack_from('<2I', data, off)
        if cmdsize < 8 or off + cmdsize > len(data):
            raise MachOError('bad load command size %d' % cmdsize)
        if cmd == LC_SEGMENT:
            nsects = struct.unpack_from('<I', data, off + 48)[0]
            so = off + 56
            for _ in range(nsects):
                ordinal += 1
                sectname = data[so:so + 16].split(b'\0')[0].decode('ascii', 'replace')
                segname = data[so + 16:so + 32].split(b'\0')[0].decode('ascii', 'replace')
                addr, size, foff = struct.unpack_from('<3I', data, so + 32)
                if sectname == '__text' and segname == '__TEXT':
                    if text is not None:
                        raise MachOError('two __TEXT,__text sections')
                    if foff + size > len(data):
                        raise MachOError('__text past the end of the file')
                    text = dict(ordinal=ordinal, addr=addr, size=size, offset=foff)
                so += 68
        elif cmd == LC_SYMTAB:
            symtab = struct.unpack_from('<4I', data, off + 8)
        off += cmdsize
    if text is None:
        raise MachOError('no __TEXT,__text section')
    if symtab is None:
        raise MachOError('no LC_SYMTAB')
    symoff, nsyms, stroff, strsize = symtab
    if symoff + 12 * nsyms > len(data) or stroff + strsize > len(data):
        raise MachOError('symbol table past the end')
    syms = []
    for i in range(nsyms):
        strx, ntype, nsect, _, value = struct.unpack_from('<IBBhI', data, symoff + 12 * i)
        name = ''
        if 0 < strx < strsize:
            end = data.find(b'\0', stroff + strx, stroff + strsize)
            name = data[stroff + strx:end if end >= 0 else stroff + strsize].decode('ascii', 'replace')
        syms.append((name, ntype, nsect, value))
    return text, syms


def function_ranges(text, syms):
    """{name: (start addr, end addr)} for code symbols in __text."""
    code = sorted((v, n) for n, t, s, v in syms
                  if (t & N_STAB) == 0 and (t & N_TYPE) == N_SECT and s == text['ordinal'])
    end_of_text = text['addr'] + text['size']
    out = {}
    for n_value, name in code:
        later = [v for v, _ in code if v > n_value]
        out[name] = (n_value, min(later) if later else end_of_text)
    return out


def disassemble(blob, vma):
    with tempfile.NamedTemporaryFile(suffix='.bin', dir=os.environ.get('TMPDIR')) as f:
        f.write(blob)
        f.flush()
        r = subprocess.run(['objdump', '-D', '-b', 'binary', '-m', 'i386', '--adjust-vma=0x%x' % vma,
                            '--no-show-raw-insn', f.name], capture_output=True, text=True)
    if r.returncode != 0:
        raise MachOError('objdump failed: %s' % r.stderr.strip()[:200])
    insns = []
    for line in r.stdout.splitlines():
        parts = line.split(':', 1)
        if len(parts) == 2 and parts[0].strip() and all(c in '0123456789abcdef' for c in parts[0].strip()):
            if parts[1].strip():
                insns.append((int(parts[0], 16), parts[1].strip()))
    return insns


def check(data):
    """Return (report lines, failures)."""
    out, fail = [], []
    try:
        text, syms = parse_macho(data)
    except (MachOError, struct.error) as e:
        return out, ['Mach-O: %s' % e]
    ranges = function_ranges(text, syms)
    nstab = sum(1 for _, t, _, _ in syms if t & N_STAB)
    out.append('__text addr %08x size %d file offset %d (section %d); %d symbols, %d stabs, %d code symbols'
               % (text['addr'], text['size'], text['offset'], text['ordinal'], len(syms), nstab, len(ranges)))
    for name, want in WANT.items():
        if name not in ranges:
            fail.append('%s not in the symbol table' % name)
            continue
        a, b = ranges[name]
        blob = data[text['offset'] + (a - text['addr']):text['offset'] + (b - text['addr'])]
        insns = disassemble(blob, a)
        stores = [(addr, i, st.classify(i)) for addr, i in insns]
        stores = [(addr, i, c) for addr, i, c in stores if c]
        nonstack = [c[0] for _, _, c in stores if not st.is_stack(c[1])]
        out.append('%s %08x-%08x (%d bytes, %d instructions): non-stack store widths %s; stores through any base: %s'
                   % (name, a, b, b - a, len(insns), nonstack, ['%d via %s' % c for _, _, c in stores]))
        for addr, i in insns:
            out.append('    %08x  %s' % (addr, i))
        if nonstack != want:
            fail.append('%s non-stack store widths %s, want %s' % (name, nonstack, want))
    out.append('proves: the store widths of the three helpers as the target compiled them, nothing else')
    return out, fail


# ---- self-test -------------------------------------------------------------

GOOD_ASM = """
.text
.globl w8
r32: push %ebp
 mov %esp,%ebp
 mov 0x8(%ebp),%eax
 add 0xc(%ebp),%eax
 mov (%eax),%eax
 leave
 ret
w8: push %ebp
 mov %esp,%ebp
 mov 0x10(%ebp),%edx
 mov %dl,-0x4(%ebp)
 mov 0x8(%ebp),%eax
 add 0xc(%ebp),%eax
 movb -0x4(%ebp),%dl
w8s: mov %dl,(%eax)
 leave
 ret
w32: push %ebp
 mov %esp,%ebp
 mov 0x8(%ebp),%eax
 add 0xc(%ebp),%eax
 mov 0x10(%ebp),%edx
 mov %edx,(%eax)
 leave
 ret
 .align 4, 0x90
tail: mov %eax,(%ebx)
 ret
"""


def assemble(src, work):
    s = os.path.join(work, 't.s')
    o = os.path.join(work, 't.o')
    b = os.path.join(work, 't.bin')
    open(s, 'w').write(src)
    subprocess.run(['as', '--32', '-o', o, s], check=True, capture_output=True)
    subprocess.run(['objcopy', '-O', 'binary', '-j', '.text', o, b], check=True, capture_output=True)
    nm = subprocess.run(['nm', o], check=True, capture_output=True, text=True).stdout
    labels = dict((l.split()[2], int(l.split()[0], 16)) for l in nm.splitlines() if len(l.split()) == 3)
    return open(b, 'rb').read(), labels


def macho(code, symbols, addr=0):
    """A minimal MH_OBJECT: one LC_SEGMENT with __TEXT,__text, one LC_SYMTAB.
    symbols: [(name, n_type, n_sect, value)]"""
    nsects = 1
    seg_size = 56 + 68 * nsects
    sym_size = 24
    header = 28
    text_off = header + seg_size + sym_size
    strtab = b'\0'
    nl = b''
    for name, t, s, v in symbols:
        nl += struct.pack('<IBBhI', len(strtab), t, s, 0, v)
        strtab += name.encode() + b'\0'
    symoff = text_off + len(code)
    stroff = symoff + len(nl)
    out = struct.pack('<7I', MH_MAGIC, CPU_TYPE_I386, 3, 1, 2, seg_size + sym_size, 0)
    out += struct.pack('<2I16s6I', LC_SEGMENT, seg_size, b'', addr, len(code), text_off, len(code), 7, 7) + \
        struct.pack('<2I', nsects, 0)
    out += struct.pack('<16s16s9I', b'__text', b'__TEXT', addr, len(code), text_off, 2, 0, 0, 0, 0, 0)
    out += struct.pack('<6I', LC_SYMTAB, sym_size, symoff, len(symbols), stroff, len(strtab))
    assert len(out) == text_off
    return out + code + nl + strtab


def self_test():
    failures = 0

    def expect(label, ok, detail=''):
        nonlocal failures
        print('%-4s %s%s' % ('ok' if ok else 'FAIL', label, '' if ok else ' -- ' + detail))
        failures += 0 if ok else 1

    work = tempfile.mkdtemp(prefix='check_reloc.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    code, lab = assemble(GOOD_ASM, work)

    def syms(extra=(), drop=None, lab=lab):
        s = [('_rdnMmioRead32', 0x0f, 1, lab['r32']), ('_rdnMmioWrite8', 0x0f, 1, lab['w8']),
             ('_rdnMmioWrite32', 0x0f, 1, lab['w32']), ('_tail', 0x0e, 1, lab['tail'])]
        s = [x for x in s if x[0] != drop] + list(extra)
        return s

    addr = 0x1000
    rs = lambda s: [(n, t, c, v + addr) for n, t, c, v in s]
    out, fail = check(macho(code, rs(syms()), addr))
    expect('good helpers pass', not fail, str(fail))
    expect('good: Write8 reported as one 8-bit store', any('_rdnMmioWrite8' in o and 'widths [8]' in o for o in out), '')
    # stabs inside the helper ranges (N_SLINE between two instructions,
    # N_FUN at the start) must not split the ranges
    stabs = [('', N_SLINE, 1, lab['w8'] + 3), ('', N_SLINE, 1, lab['w8'] + 9), ('_rdnMmioWrite8:F1', 0x24, 1, lab['w8'])]
    out, fail = check(macho(code, rs(syms(stabs)), addr))
    expect('N_SLINE inside a helper still passes', not fail, str(fail))
    # the same stab typed as a section symbol (no N_STAB bit) would split the
    # range: proves the filter is what keeps the good case whole
    out, fail = check(macho(code, rs(syms([('Lsplit', 0x0e, 1, lab['w8s'])])), addr))
    expect('a non-stab symbol inside Write8 splits it (and fails)', bool(fail), str(fail))
    out, fail = check(macho(code, rs(syms(drop='_rdnMmioWrite32')), addr))
    expect('missing helper symbol fails', any('not in the symbol table' in f for f in fail), str(fail))
    bad, lab2 = assemble(GOOD_ASM.replace('w8s: mov %dl,(%eax)\n', 'w8s: movl %edx,(%eax)\n'), work)
    out, fail = check(macho(bad, rs(syms(lab=lab2)), addr))
    expect('Write8 with a 32-bit store fails', any('_rdnMmioWrite8' in f for f in fail), str(fail))
    bad, lab2 = assemble(GOOD_ASM.replace(' mov %edx,(%eax)\n leave', ' mov %dx,(%eax)\n leave'), work)
    out, fail = check(macho(bad, rs(syms(lab=lab2)), addr))
    expect('Write32 with a 16-bit store fails', any('_rdnMmioWrite32' in f for f in fail), str(fail))
    bad, lab2 = assemble(GOOD_ASM.replace(' mov (%eax),%eax\n', ' mov (%eax),%eax\n mov %eax,(%ecx)\n'), work)
    out, fail = check(macho(bad, rs(syms(lab=lab2)), addr))
    expect('Read32 with a store fails', any('_rdnMmioRead32' in f for f in fail), str(fail))
    # frame pointer used as a general register: the store hides from the rule,
    # the helper fails, the any-base count shows it
    fp = GOOD_ASM.replace(' movb -0x4(%ebp),%dl\nw8s: mov %dl,(%eax)\n',
                          ' movb -0x4(%ebp),%dl\n mov %eax,%ebp\nw8s: mov %dl,(%ebp)\n')
    assert fp != GOOD_ASM
    bad, lab2 = assemble(fp, work)
    out, fail = check(macho(bad, rs(syms(lab=lab2)), addr))
    expect('store through %ebp fails and is shown in the any-base count',
           any('_rdnMmioWrite8' in f for f in fail) and any("'8 via ebp'" in o for o in out), str(fail))
    expect('not a Mach-O fails', bool(check(b'\x7fELF' + bytes(100))[1]))
    expect('truncated Mach-O fails without raising', bool(check(macho(code, rs(syms()), addr)[:60])[1]))
    # a real cc 2.7.2.1 reloc parses (no helper symbols: fails on those only)
    real = os.path.join(os.path.dirname(PROJ), 'openstep-mdh10', 'MDH10Disk', 'MDH10Disk.config', 'MDH10Disk_reloc')
    if os.path.exists(real):
        out, fail = check(open(real, 'rb').read())
        expect('real MDH10Disk_reloc parses, fails only on the missing helpers',
               len(fail) == 3 and all('not in the symbol table' in f for f in fail), str(fail) + ' ' + out[0])
        print('     ' + out[0])
    print('check_reloc self-test: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return failures == 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return 0 if self_test() else 1
    a = argv[1:]
    marker = None
    if '--marker' in a:
        i = a.index('--marker')
        marker = a[i + 1]
        a = a[:i] + a[i + 2:]
    if len(a) != 3:
        print(__doc__)
        return 2
    path, want_sum, want_blocks = a
    data = open(path, 'rb').read()
    got = pk.bsdsum(data)
    fail = []
    if not (want_sum.isdigit() and want_blocks.isdigit()) or \
            [int(x) for x in got.split()] != [int(want_sum), int(want_blocks)]:
        fail.append('BSD sum %s, the target reported %s %s' % (got, want_sum, want_blocks))
    out, f2 = check(data)
    fail += f2
    print('reloc %s: %d bytes, sum %s' % (path, len(data), got))
    for o in out:
        print(o)
    for f in fail:
        print('FAIL ' + f)
    ok = not fail
    if ok and marker:
        os.makedirs(marker, exist_ok=True)
        open(os.path.join(marker, 'R2ARELOC_PASS'), 'w').write('%s %s\n' % tuple(got.split()))
        print('marker %s' % os.path.join(marker, 'R2ARELOC_PASS'))
    print('check_reloc: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
