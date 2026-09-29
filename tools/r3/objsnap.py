#!/usr/bin/env python3
"""Compile the bundle's units with the host toolchain and fingerprint their sections.

  objsnap.py <out.json> [--header H] [--src DIR]
                                       write {unit: {section: sha256}} for every unit;
                                       --src compiles the units of another tproj (e.g. one
                                       unpacked from an archived build tar), --header
                                       replaces osrdn_mode_expect.h in that copy
  objsnap.py --compare a.json b.json
  objsnap.py --r3-inert                R3a's claim that the R3 block compiled to
                                       nothing.  RETIRED at R3b-2, which turns the
                                       block on; kept for reading R3a's record.

docs/R3_MULTIMODE_PLAN.md 16-2 B8: R3a adds tables to the generated header
behind a guard no unit defines, so NOTHING the R2 driver compiles may change.
The reloc gate reads code only; this compares code AND data (.text, .data,
.rodata and their relocation-free bytes) of every unit, before and after.

Host gcc output is not the target's cc 2.7.2.1 output, so this proves only
that the preprocessed program the target will compile is unchanged -- which is
the property R3a claims.  Because gcc may drop an unused static table at any
optimisation level, equal sections alone would not show that; each unit's
preprocessed token stream (-E -P, whitespace collapsed) is hashed as well.

.bss holds no bytes in an object file, so `objcopy -O binary` gives an empty
file for it whatever it declares -- until 2026-09-17 its "hash" was the empty
hash for every unit and could never differ.  It is compared by SIZE
(`objdump -h`) instead.  Relocations are not compared; the token hash is what
catches a changed callee or global.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
WS = os.path.dirname(PROJ)
SRC = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
R = os.path.join(WS, 'ref', 'openstep', 'headers', 'NextDeveloper', 'Headers')
HOST = os.path.join(PROJ, 'tools', 'host')
UNITS = ['OSRDNDisplay.m', 'osrdn_record.m', 'osrdn_pll.m', 'osrdn_port.m', 'RDNR2aMMIO.m',
         'osrdn_snap.m', 'osrdn_mode.m', 'osrdn_modelog.m', 'osrdn_modesel.m']
SECTIONS = ['.text', '.data', '.rodata', '.bss', 'tokens']
HEADER = 'osrdn_mode_expect.h'


def flags(src):
    return ['gcc-12', '-m32', '-O0', '-nostdinc', '-fno-pic', '-ffreestanding', '-fno-builtin',
            '-I' + src, '-I' + os.path.join(HOST, 'hostshim'),
            '-isystem', R, '-isystem', os.path.join(R, 'ansi'), '-isystem', os.path.join(R, 'bsd'),
            '-isystem', os.path.join(R, 'mach'), '-isystem', os.path.join(R, 'kernserv'),
            '-isystem', os.path.join(R, 'architecture'),
            '-DKERNEL', '-DMACH_USER_API', '-DMACH', '-DNeXT=1', '-D__NeXT__', '-D_NEXT_SOURCE',
            '-Di386', '-D__ARCHITECTURE__="i386"', '-x', 'objective-c', '-fnext-runtime', '-fasm',
            '-w']


def section_bytes(obj, name, work):
    out = os.path.join(work, 'sec.bin')
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run(['objcopy', '-O', 'binary', '--only-section=' + name, obj, out],
                       capture_output=True)
    if r.returncode != 0 or not os.path.exists(out):
        return None
    return open(out, 'rb').read()


def section_size(obj, name):
    r = subprocess.run(['objdump', '-h', obj], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 3 and f[1] == name:
            return 'size:' + f[2]
    return 'size:absent'


def snap(header=None, srcdir=None):
    work = tempfile.mkdtemp(prefix='objsnap.')
    src = srcdir or SRC
    if header is not None:
        copy = os.path.join(work, 'src')
        shutil.copytree(src, copy)
        shutil.copyfile(header, os.path.join(copy, HEADER))
        src = copy
    result = {}
    for u in UNITS:
        obj = os.path.join(work, u + '.o')
        r = subprocess.run(flags(src) + ['-c', os.path.join(src, u), '-o', obj],
                           capture_output=True, text=True)
        e = subprocess.run(flags(src) + ['-E', '-P', os.path.join(src, u)],
                           capture_output=True, text=True)
        if r.returncode != 0 or e.returncode != 0:
            result[u] = {'error': (r.stderr + e.stderr)[-400:]}
            continue
        result[u] = {}
        for s in SECTIONS[:-1]:
            if s == '.bss':
                result[u][s] = section_size(obj, s)
                continue
            b = section_bytes(obj, s, work)
            result[u][s] = None if b is None else hashlib.sha256(b).hexdigest()
        toks = re.sub(r'\s+', ' ', e.stdout).strip()
        result[u]['tokens'] = hashlib.sha256(toks.encode()).hexdigest()
    shutil.rmtree(work, ignore_errors=True)
    return result


R3_MARK = '/* ---- R3: every resolution x every format'


def compare(a, b, tag='FAIL'):
    bad = 0
    for u in UNITS:
        for s in SECTIONS:
            x, y = a.get(u, {}).get(s), b.get(u, {}).get(s)
            if x != y or 'error' in a.get(u, {}) or 'error' in b.get(u, {}):
                print('  %-4s %s %s changed' % (tag, u, s))
                bad += 1
    if not bad:
        print('  ok   %d units x %d sections: code and data unchanged' % (len(UNITS), len(SECTIONS)))
    return bad


def r3_inert():
    text = open(os.path.join(SRC, HEADER), encoding='utf-8').read()
    if text.count(R3_MARK) != 1:
        print('  FAIL the R3 block marker occurs %d times' % text.count(R3_MARK))
        return 1
    work = tempfile.mkdtemp(prefix='objsnap-h.')
    stripped = os.path.join(work, HEADER)
    open(stripped, 'w', encoding='utf-8').write(text[:text.index(R3_MARK)])
    switched = os.path.join(work, 'switched.h')    # negative control: the block turned on
    open(switched, 'w', encoding='utf-8').write('#define OSRDN_MODE_TABLES_R3\n' + text)
    full, bare, on = snap(), snap(stripped), snap(switched)
    shutil.rmtree(work, ignore_errors=True)
    errs = [u for r in (full, bare, on) for u in r if 'error' in r[u]]
    for u in errs:
        print('  FAIL %s did not compile' % u)
    bad = compare(bare, full) + len(errs)
    print('  negative control (R3 guard defined):')
    if compare(bare, on, 'seen') == 0:
        print('  FAIL the comparison cannot see the R3 tables at all')
        bad += 1
    else:
        print('  ok   ... the comparison sees them')
    print('objsnap r3-inert: %s' % ('PASS' if not bad else 'FAIL'))
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ['--r3-inert']:
        return r3_inert()
    if len(argv) == 4 and argv[1] == '--compare':
        return 1 if compare(json.load(open(argv[2])), json.load(open(argv[3]))) else 0
    header = srcdir = None
    rest = argv[2:]
    while len(rest) >= 2 and rest[0] in ('--header', '--src'):
        if rest[0] == '--header':
            header = rest[1]
        else:
            srcdir = rest[1]
        rest = rest[2:]
    if rest:
        print(__doc__)
        return 2
    argv = argv[:2]
    if len(argv) == 2:
        res = snap(header, srcdir)
        json.dump(res, open(argv[1], 'w'), indent=1, sort_keys=True)
        errs = [u for u in res if 'error' in res[u]]
        for u in errs:
            print('  FAIL %s did not compile: %s' % (u, res[u]['error']))
        print('  wrote %s (%d units)' % (argv[1], len(res)))
        return 1 if errs else 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
