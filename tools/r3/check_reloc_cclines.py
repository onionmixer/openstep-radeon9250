#!/usr/bin/env python3
"""H4 of docs/R3_MULTIMODE_PLAN.md 26-3: what adding the Configure inspector
did to the KERNEL driver's compile, read from the machine's own make log.

  check_reloc_cclines.py BASE NEW     BASE: the make log (or its cc lines) of
                                      the last build without the inspector;
                                      NEW: <nfs>/<runid>/make-cc.txt
  check_reloc_cclines.py --self-test  the rules on built-in lines, each shown to fail

The reloc's bytes cannot be compared: the build stamp is compiled into it.
What can be compared is how it is compiled.  For every reloc unit (a cc line
whose object goes to OSRDNDisplay_reloc.tproj):
  - the same units are compiled, no more, no fewer;
  - with the stamp masked, each line's tokens are the base line's plus at
    most the one token -I./compat -- the bundle's HEADER_PATHS, which
    common.make passes down as PROPOGATED_CFLAGS and which names no
    directory under the tproj (26-1 E2);
and the inspector's own line carries -I./compat, which proves the preamble's
HEADER_PATHS survived the command-line OTHER_CFLAGS (26-1 E1).
The reloc's cc lines also carry -I.. (the bundle directory), so a header the
bundle adds must not share a name with one of the reloc's: that is checked
on the source tree.
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
BUNDLE = os.path.join(PROJ, 'OSRDNDisplay')
TPROJ = os.path.join(BUNDLE, 'OSRDNDisplay_reloc.tproj')
STAMP = re.compile(r'-DOSRDN_BUILD=0x[0-9a-f]{8}\b')
ALLOWED_EXTRA = ['-I./compat']


def cc_lines(text):
    return [l for l in text.splitlines() if l.startswith('cc ')]


def unit_of(line):
    m = re.search(r' -c (\S+)', line)
    return os.path.basename(m.group(1)) if m else None


def reloc_units(lines):
    """{unit: tokens with the stamp masked} for lines building into the tproj."""
    out = {}
    for l in lines:
        if 'OSRDNDisplay_reloc.tproj' in l and unit_of(l):
            out[unit_of(l)] = STAMP.sub('-DOSRDN_BUILD=STAMP', l).split()
    return out


def extra_tokens(base, new):
    """Tokens of `new' left over after matching `base' in order, or None if a
    base token is missing."""
    extra, i = [], 0
    for tok in new:
        if i < len(base) and tok == base[i]:
            i += 1
        else:
            extra.append(tok)
    return extra if i == len(base) else None


def check(base_text, new_text, bundle_headers, reloc_headers):
    p = []
    base = reloc_units(cc_lines(base_text))
    new = reloc_units(cc_lines(new_text))
    if not base:
        p.append('the base log has no reloc compile line')
    if sorted(base) != sorted(new):
        p.append('reloc units differ: base %s, new %s' % (sorted(base), sorted(new)))
    for u in sorted(set(base) & set(new)):
        extra = extra_tokens(base[u], new[u])
        if extra is None:
            p.append('%s: a flag of the base build is gone' % u)
        elif extra not in ([], ALLOWED_EXTRA):
            p.append('%s: new flags %s (allowed: %s)' % (u, extra, ALLOWED_EXTRA))
    insp = [l for l in cc_lines(new_text) if unit_of(l) == 'OSRDNDisplayInspector.m']
    if len(insp) != 1:
        p.append('%d compile lines for OSRDNDisplayInspector.m, want 1' % len(insp))
    elif '-I./compat' not in insp[0].split():
        p.append('the inspector was compiled without -I./compat')
    clash = sorted(set(bundle_headers) & set(reloc_headers))
    if clash:
        p.append('bundle headers share a name with the reloc\'s (-I.. reaches them): %s' % clash)
    return p


def headers():
    return ([os.path.basename(h) for h in glob.glob(os.path.join(BUNDLE, '*.h'))],
            [os.path.basename(h) for h in glob.glob(os.path.join(TPROJ, '*.h'))])


# The shape of the machine's lines (build/r3d/h4-base-ae724459.log, 2026-09-18),
# shortened to the tokens that matter.
BASE = '''Making OSRDNDisplay_reloc.tproj
cc -static -nostdinc -I. -I.. -DKERNEL -DOSRDN_BUILD=0xae724459 -g -Wall -DOSRDN_BUILD=0xae724459 -O -I../sym -c OSRDNDisplay.m -o ../i386_obj/OSRDNDisplay_reloc.tproj/OSRDNDisplay.o
cc -static -nostdinc -I. -I.. -DKERNEL -DOSRDN_BUILD=0xae724459 -g -Wall -DOSRDN_BUILD=0xae724459 -O -I../sym -c osrdn_mode.m -o ../i386_obj/OSRDNDisplay_reloc.tproj/osrdn_mode.o
Warning: Building empty bundle.
'''
NEW = '''Making OSRDNDisplay_reloc.tproj
cc -static -nostdinc -I. -I.. -DKERNEL -I./compat -DOSRDN_BUILD=0x12345678 -g -Wall -DOSRDN_BUILD=0x12345678 -O -I../sym -c OSRDNDisplay.m -o ../i386_obj/OSRDNDisplay_reloc.tproj/OSRDNDisplay.o
cc -static -nostdinc -I. -I.. -DKERNEL -I./compat -DOSRDN_BUILD=0x12345678 -g -Wall -DOSRDN_BUILD=0x12345678 -O -I../sym -c osrdn_mode.m -o ../i386_obj/OSRDNDisplay_reloc.tproj/osrdn_mode.o
cc -static -I./compat -DOSRDN_BUILD=0x12345678 -g -Wall -O -c OSRDNDisplayInspector.m -o ./i386_obj/OSRDNDisplayInspector.o
'''


def self_test():
    fails = 0
    bh, rh = headers()
    base = check(BASE, NEW, bh, rh)
    for x in base:
        print('  FAIL %s' % x)
    print('  %-4s the real header sets and the built-in lines pass' % ('FAIL' if base else 'ok'))
    fails += len(base)
    extra_unit = NEW.replace('Making', 'cc -static -I. -c osrdn_extra.m -o ../i386_obj/OSRDNDisplay_reloc.tproj/x.o\nMaking')
    negatives = [
        ('a unit added to the reloc', BASE, extra_unit, bh, rh),
        ('another flag reaches the reloc', BASE, NEW.replace('-I./compat -DOSRDN', '-I./compat -DAPPKIT -DOSRDN', 1), bh, rh),
        ('a base flag dropped', BASE, NEW.replace(' -O -I../sym -c OSRDNDisplay.m', ' -I../sym -c OSRDNDisplay.m'), bh, rh),
        ('the inspector compiled without -I./compat', BASE,
         NEW.replace('cc -static -I./compat -DOSRDN_BUILD=0x12345678 -g', 'cc -static -DOSRDN_BUILD=0x12345678 -g'), bh, rh),
        ('the inspector not compiled', BASE, '\n'.join(l for l in NEW.splitlines() if 'Inspector' not in l), bh, rh),
        ('a bundle header named like a reloc header', BASE, NEW, bh + ['osrdn_mode.h'], rh),
        ('an empty base log', 'nothing\n', NEW, bh, rh),
    ]
    for label, b, n, x, y in negatives:
        caught = bool(check(b, n, x, y))
        print('  %-4s negative: %s' % ('ok' if caught else 'FAIL', label))
        fails += 0 if caught else 1
    print('check_reloc_cclines self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    bh, rh = headers()
    p = check(open(sys.argv[1]).read(), open(sys.argv[2]).read(), bh, rh)
    for x in p:
        print('  FAIL %s' % x)
    n = len(reloc_units(cc_lines(open(sys.argv[2]).read())))
    print('check_reloc_cclines: %s (%d reloc units)' % ('PASS' if not p else 'FAIL (%d)' % len(p), n))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main())
