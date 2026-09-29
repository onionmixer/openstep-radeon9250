#!/usr/bin/env python3
"""M1a design: the hook contract, taken from osmesa.c rather than typed here.

  python3 build/m1a/design1.py

The ten hooks are declared inside `#ifdef OPENSTEP_MESA_ACCEL_HOOK` in the Mesa
port's osmesa.c.  Everything M1a must supply follows from those declarations, so
this reads them and states what an implementation owes, instead of a list someone
keeps in step by hand.  It also settles the two questions M1a has to answer before
any code: what a DECLINING implementation of each hook is, and which hooks a
decline-only build must still be seen to call.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
OSMESA = os.path.join(PROJ, '..', 'openstep-mesa342', 'upstream', 'Mesa-3.4.2',
                      'src', 'OSmesa', 'osmesa.c')

# What "decline" means for each return type: the value the DECLARATION's own
# comment says leaves the caller as it was.  Stated here, checked against the
# comments below.
DECLINE = {'void': '(nothing)', 'void *': 'null -- leave the caller\'s buffer alone',
           'int': '0 -- declined', 'unsigned long': '0'}


def hooks(text):
    """(return type, name, [parameter types]) for every declaration in the ifdef"""
    i = text.index('#ifdef OPENSTEP_MESA_ACCEL_HOOK')
    block = text[i:text.index('#endif', i)]
    out = []
    for m in re.finditer(r'extern\s+(.+?)\s*\bOpenStepMesaAccel(\w+)\s*\(([^;]*?)\)\s*;',
                         block, re.S):
        ret = ' '.join(m.group(1).split())
        params = [' '.join(p.split()) for p in m.group(3).split(',')]
        # drop the parameter NAME, keep the type
        types = []
        for p in params:
            p = p.strip()
            if p in ('void', ''):
                types.append('void')
                continue
            types.append(re.sub(r'\s*\b\w+$', '', p).strip() if not p.endswith('*')
                         else re.sub(r'\s*\*\s*\w+$', ' *', p).strip())
        # the comment that documents a hook PRECEDES it: take everything since the
        # previous declaration ended, which is where "null to leave the caller's
        # alone" and "Returns zero when it declines" actually live
        start = out[-1][4] if out else 0
        out.append((ret, m.group(2), types, block[start:m.end()], m.end()))
    return [(r, n, t, d) for r, n, t, d, _e in out], block


def main():
    text = open(OSMESA).read()
    hs, block = hooks(text)
    bad = 0

    print('1. the hooks, read from osmesa.c')
    for ret, name, types, _ in hs:
        print('   %-14s %-13s (%s)' % (ret, name, ', '.join(types)))
    print('   %d hooks' % len(hs))
    if len(hs) != 10:
        print('   FAIL: the plan and every checker say ten')
        bad += 1

    print('2. what declining is, per hook')
    for ret, name, _t, _d in hs:
        if ret not in DECLINE:
            print('   FAIL %s returns %r, which this file has no decline value for' % (name, ret))
            bad += 1
            continue
        print('   %-13s -> %s' % (name, DECLINE[ret]))

    print('3. the ones a decline-only build must still be SEEN to call')
    # A hook that returns nothing cannot decline: it is called and does nothing.
    # Those are the ones whose counters prove the build is wired at all -- a gate
    # that only checks "the picture is the same" would pass with the hooks never
    # called, which is a gate that verifies nothing (PLAN.md 188).
    voids = [n for r, n, _t, _d in hs if r == 'void']
    print('   %s' % ', '.join(voids))
    print('   plus the value-returning ones, whose counters must also be non-zero')
    if not voids:
        print('   FAIL: no void hook to anchor the wiring proof')
        bad += 1

    print('4. the decline values are what the declarations say')
    for _r, name, _t, decl in hs:
        say = re.search(r'null to leave|Returns zero when it declines|or null\b', decl)
        if name in ('Buffer', 'DepthBuffer') and not say:
            print('   FAIL %s: the declaration does not say null means "leave it alone"' % name)
            bad += 1
        if name == 'CopyDepth' and 'Returns zero when it declines' not in decl:
            print('   FAIL CopyDepth: the declaration does not say zero means declined')
            bad += 1
    print('   checked against the comments in the ifdef, not against memory')

    print('5. the split V8 asked for is in the contract already')
    if 'not the same as owning it' in block:
        print('   BoundTo\'s own comment: binding is NOT ownership -- a refused rebind')
        print('   leaves the owner set while Mesa goes back to the application buffer.')
        print('   So bufCtx (ownership) and BoundTo (binding) are two fields from day one.')
    else:
        print('   FAIL: the contract no longer says it; re-read before relying on V8')
        bad += 1

    print('design1: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
