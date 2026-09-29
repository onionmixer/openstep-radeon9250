#!/usr/bin/env python3
"""Count the calls a function makes IN THE BUILT RELOC, by name.

  python3 tools/r5/calls_in.py <reloc> <symbol> [<symbol> ...]

Source says what was written; this says what the target's cc emitted.  M1y
turned cpCheckBlock's one word loop into four region loops so that the
expectation is carried in the loop instead of fetched through cpBlockWord();
whether that actually removed the calls is a question about the shipped bytes,
and this answers it:

    _cpCheckBlock     436 B   calls: 1   ['_cpRing']

A NAME IN THE LIST IS ONLY TRUSTWORTHY FOR A LOCAL FUNCTION.  A call to a symbol
the KERNEL defines -- IOGetTimestamp, IOLog, IODelay -- is an unrelocated
displacement until kl_ld patches it, and this tool resolves that raw target
against the local symbol table, so it prints whatever local happens to sit
there.  On the M1z reloc the two IOGetTimestamp calls around cpFence both print
as `_rdnDevOpen`, and cpTMark -- which certainly calls IOGetTimestamp -- prints
the same name.  Read such entries as "an external call", and count them rather
than believe the name.

THREE TRAPS THIS FILE IS WRITTEN AROUND, the first two of which gave a confident
wrong answer first:
  * the symbol table carries STAB (debug) entries at the same addresses, so
    "the next symbol" is not the next function.  Only n_type without N_STAB
    (0xe0), in the __text section's ordinal, is a real boundary.
  * objdump's stderr was being thrown away, so a failed run printed NOTHING and
    the count came out 0 for every function -- including ones that plainly do
    call.  An empty result is not evidence ([[grep-silently-skips-nonutf8-source]]).
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
N_STAB = 0xe0


def load(path):
    spec = importlib.util.spec_from_file_location(
        'cr', os.path.join(PROJ, 'tools', 'r2a', 'check_reloc.py'))
    cr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cr)
    data = open(path, 'rb').read()
    text, syms = cr.parse_macho(data)
    return data, text, syms


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    data, text, syms = load(argv[1])
    addr, foff, size, ordn = text['addr'], text['offset'], text['size'], text['ordinal']
    real = sorted({(v, n) for n, t, s, v in syms
                   if not (t & N_STAB) and s == ordn and addr <= v < addr + size})
    addrs = sorted({v for v, _ in real})
    name_at = {}
    for v, n in real:
        name_at.setdefault(v, n)
    bad = 0
    for target in argv[2:]:
        hit = [v for v, n in real if n == target]
        if not hit:
            print('%-20s NOT FOUND in the reloc' % target)
            bad += 1
            continue
        s0 = hit[0]
        s1 = next((v for v in addrs if v > s0), addr + size)
        fd, path = tempfile.mkstemp()
        os.write(fd, data[foff + (s0 - addr):foff + (s1 - addr)])
        os.close(fd)
        r = subprocess.run(['objdump', '-D', '-b', 'binary', '-m', 'i386',
                            '--adjust-vma=0x%x' % s0, path],
                           capture_output=True, text=True)
        os.unlink(path)
        if r.returncode != 0:          # never let a failure read as "no calls"
            print('%-20s objdump FAILED: %s' % (target, r.stderr.strip()[:120]))
            bad += 1
            continue
        names = []
        for ln in r.stdout.split('\n'):
            if not re.search(r'\bcall\b', ln):
                continue
            m = re.search(r'call\s+\*?(?:0x)?([0-9a-f]+)', ln)
            names.append(name_at.get(int(m.group(1), 16), '0x' + m.group(1)) if m else '(indirect)')
        print('%-20s 0x%06x  %5d B   calls: %-3d %s' % (target, s0, s1 - s0, len(names), names))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
