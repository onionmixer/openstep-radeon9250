#!/usr/bin/env python3
"""Every unit in mesa/ is compiled AND linked by the target build script.

  check_units.py

M1g added mesa/OSRDNMesaTex.c and the build script's hand-written list did not
grow with it.  Nothing on the host noticed: the units compile fine one by one,
and the failure would have been an undefined symbol at the final link on the
target -- a round trip spent to learn that a file was never named.

Two lists have to agree with the directory: the `for u in ...` loop that
compiles them, and the `ld -r` line that puts them in one object.  A unit in the
first and not the second compiles into nothing.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')
BUILD = os.path.join(PROJ, 'tools', 'mesa', 'target-build-mesa.sh')

# The hook unit is compiled by a line of its own, because it is the only one
# that needs Mesa's headers.  It is named here so that "not in the loop" cannot
# quietly become the normal case.
APART = ('OSRDNMesaHook',)


def units_on_disk():
    return sorted(os.path.basename(f)[:-2] for f in os.listdir(MESA)
                  if f.endswith('.c'))


def loop_units(src):
    m = re.search(r'for u in ((?:[A-Za-z0-9_ ]|\\\n\s*)+); do', src)
    if not m:
        return None
    return sorted(m.group(1).replace('\\\n', ' ').split())


def linked_units(src):
    m = re.search(r'ld -r -o "\$TMP/osrdnaccel\.o"(.*?)>', src, re.S)
    if not m:
        return None
    return sorted(set(re.findall(r'\$TMP/([A-Za-z0-9_]+)\.o', m.group(1))))


# The test source is built TWICE: against our archive, and against the stock
# libGL with test/osrdn-mesa-nocount.c standing in for everything of ours.  A
# function the test calls that nocount.c does not define breaks the STOCK link
# only -- on the target, several minutes in.  It has happened twice (M1g's
# OSRDN_TEX_H, M1i's osrdn_depth_get), and both times the symptom was a build
# that died at step 11 with a compiler message about the other link.
TEST_SRC = os.path.join(PROJ, 'test', 'osrdn-mesa-tri.c')
STUBS = os.path.join(PROJ, 'test', 'osrdn-mesa-nocount.c')


def stock_link(st=None):
    """[name] -- ours that the test calls and the stub file does not define"""
    try:
        t = open(TEST_SRC).read()
        if st is None:
            st = open(STUBS).read()
    except OSError as e:
        return ['cannot read the test sources: %s' % e]
    called = set(re.findall(r'\b(OSRDNMesa\w+|osrdn_\w+)\s*\(', t))
    # a definition in the stub file: the name at the start of a line, or after a
    # return type on the same line
    defined = set(re.findall(r'^(?:\w[\w \t*]*?)?\b(OSRDNMesa\w+|osrdn_\w+)\s*\('
                             r'[^;]*\)\s*(?:\{|$)', st, re.M))
    miss = sorted(n for n in called if n not in defined)
    return ['%s is called by the test and not defined in %s'
            % (n, os.path.basename(STUBS)) for n in miss]


def check(src):
    p = []
    disk = units_on_disk()
    want = sorted(u for u in disk if u not in APART)
    loop = loop_units(src)
    link = linked_units(src)
    if loop is None:
        p.append('the build script has no `for u in ...; do` compile loop')
    elif loop != want:
        p.append('compiled %s, but mesa/ holds %s (apart: %s)'
                 % (loop, want, list(APART)))
    if link is None:
        p.append('the build script has no `ld -r -o "$TMP/osrdnaccel.o"` line')
    elif link != disk:
        p.append('linked %s, but mesa/ holds %s' % (link, disk))
    for u in APART:
        if u + '.c' not in os.listdir(MESA):
            p.append('%s is named apart but is not in mesa/' % u)
    return p


MUTATIONS = [
    ('a unit is dropped from the compile loop',
     'OSRDNMesaTri OSRDNMesaTex OSRDNMesaTexArena OSRDNMesaVerify OSRDNMesaDepth OSRDNMesaPresent \\', 'OSRDNMesaTri OSRDNMesaTex OSRDNMesaTexArena OSRDNMesaVerify OSRDNMesaPresent \\'),
    ('the newest unit is dropped from the compile loop (G5-4)',
     '         OSRDNMesaTime OSRDNMesaWindow OSRDNMesaReadPix; do', '         OSRDNMesaTime OSRDNMesaWindow; do'),
    ('a unit is dropped from the ld -r line',
     '"$TMP/OSRDNMesaVerify.o" "$TMP/OSRDNMesaDepth.o" "$TMP/OSRDNMesaPresent.o"', '"$TMP/OSRDNMesaVerify.o" "$TMP/OSRDNMesaPresent.o"'),
    ('the hook itself falls out of the link',
     'ld -r -o "$TMP/osrdnaccel.o" "$TMP/OSRDNMesaHook.o"',
     'ld -r -o "$TMP/osrdnaccel.o"'),
]


def main():
    src = open(BUILD).read()
    bad = check(src) + stock_link()
    for s in bad:
        print('  FAIL %s' % s)
    if not bad:
        print('  ok   all %d units in mesa/ are compiled and linked'
              % len(units_on_disk()))
    fails = 1 if bad else 0
    for label, old, new in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL mutation %-44s anchor found %d times'
                  % (label, src.count(old)))
            fails += 1
            continue
        caught = bool(check(src.replace(old, new, 1)))
        print('  %-4s mutation %-44s %s' % ('ok' if caught else 'FAIL', label,
                                            'caught' if caught else 'NOT CAUGHT'))
        if not caught:
            fails += 1
    # and the stub file's own mutation: take a definition away and the stock
    # link would break on the target, several minutes into a build
    stub = open(STUBS).read()
    for label, old in (('a stub the stock link needs is gone',
                        'long osrdn_depth_get(int x, int y) '
                        '{ (void)x; (void)y; return -1L; }'),
                       ('the counter stub is gone',
                        'const osrdn_tex_counts *OSRDNMesaTexCounts(void) '
                        '{ return &noneTex; }')):
        if stub.count(old) != 1:
            print('  FAIL mutation %-44s anchor found %d times'
                  % (label, stub.count(old)))
            fails += 1
            continue
        caught = bool(stock_link(stub.replace(old, '', 1)))
        print('  %-4s mutation %-44s %s' % ('ok' if caught else 'FAIL', label,
                                            'caught' if caught else 'NOT CAUGHT'))
        if not caught:
            fails += 1
    print('check_units: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
