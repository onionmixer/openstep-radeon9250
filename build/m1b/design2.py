#!/usr/bin/env python3
"""M1b: the numbers OSRDNMesaClass.c borrows from Mesa, checked against Mesa.

  python3 build/m1b/design2.py

The classifier compiles without Mesa's headers, which is what makes it testable
on the host -- but the price is that Mesa's constants are written out in it.  A
written-out constant is a constant that can go stale, so this reads the real
ones and compares.  If Mesa ever renumbers a format or moves DEPTH_BIT, this
fails rather than the classifier quietly deciding the wrong thing.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, '..', 'openstep-mesa342', 'upstream', 'Mesa-3.4.2')
CLS = os.path.join(PROJ, 'mesa', 'OSRDNMesaClass.c')


def defines(path, pat=r'#define\s+(\w+)\s+((?:0x)?[0-9a-fA-F]+)'):
    out = {}
    for m in re.finditer(pat, open(path).read()):
        try:
            out[m.group(1)] = int(m.group(2), 0)
        except ValueError:
            pass
    return out


def main():
    ours = defines(CLS)
    types = defines(os.path.join(MESA, 'src', 'types.h'))
    osm = defines(os.path.join(MESA, 'include', 'GL', 'osmesa.h'))
    gl = defines(os.path.join(MESA, 'include', 'GL', 'gl.h'))
    cfg = defines(os.path.join(MESA, 'src', 'config.h'))
    bad = 0

    print('1. the RasterMask bit')
    if ours.get('RM_DEPTH') != types.get('DEPTH_BIT'):
        print('   FAIL RM_DEPTH %r, types.h DEPTH_BIT %r' % (ours.get('RM_DEPTH'), types.get('DEPTH_BIT')))
        bad += 1
    else:
        print('   RM_DEPTH = DEPTH_BIT = %#x' % ours['RM_DEPTH'])
    # RM_KNOWN must be exactly the bits a rung has actually built.  M1b said
    # "DEPTH alone"; M1f added BLEND and the rung behind it.  The rule is not
    # relaxed -- it still refuses a bit with no rung, which is the thing it was
    # written to catch.
    if ours.get('RM_ALPHA') != types.get('ALPHATEST_BIT'):
        print('   FAIL RM_ALPHA %r, types.h ALPHATEST_BIT %r' % (ours.get('RM_ALPHA'), types.get('ALPHATEST_BIT')))
        bad += 1
    want_known = (ours.get('RM_DEPTH', 0) | ours.get('RM_BLEND', 0) |
                  ours.get('RM_TEXTURE', 0) | ours.get('RM_ALPHA', 0))
    if ours.get('RM_KNOWN') is not None and ours['RM_KNOWN'] != want_known:
        print('   FAIL RM_KNOWN is %#x, want %#x (DEPTH | BLEND | TEXTURE | ALPHA)'
              % (ours['RM_KNOWN'], want_known))
        bad += 1

    print('2. the colour question UpdateState can actually ask')
    # The OSMesa format lives in osmesa.c's private struct, so the hook cannot
    # see it; what it can see is RGBAflag.  This checks the field exists where
    # the classifier's comment says it does, rather than trusting the comment.
    types_src = open(os.path.join(MESA, 'src', 'types.h')).read()
    for field, what in (('RGBAflag', 'RGBA or colour index'),
                        ('DepthBits', 'the depth width'),
                        ('RasterMask', 'the raster features')):
        if not re.search(r'\b%s\s*;' % field, types_src):
            print('   FAIL types.h no longer has %s' % field)
            bad += 1
        else:
            print('   ctx has %-11s (%s)' % (field, what))
    # and the classifier must NOT pretend to know the packing
    src0 = open(CLS).read()
    if re.search(r'OSMESA_|FMT_RGBA|FMT_BGRA|FMT_ARGB', src0):
        print('   FAIL the classifier names an OSMesa format it cannot see')
        bad += 1
    else:
        print('   the classifier names no OSMesa format: the packing is a Buffer-time question')

    print('3. the software depth width')
    if ours.get('SOFTWARE_DEPTH_BITS') != cfg.get('DEFAULT_SOFTWARE_DEPTH_BITS'):
        print('   FAIL %r vs config.h %r' % (ours.get('SOFTWARE_DEPTH_BITS'),
                                             cfg.get('DEFAULT_SOFTWARE_DEPTH_BITS')))
        bad += 1
    else:
        print('   SOFTWARE_DEPTH_BITS = %d' % ours['SOFTWARE_DEPTH_BITS'])

    print('4. the accepted raster set is exactly the bits a rung has built')
    src1 = open(CLS).read()
    # each name here must have a rung behind it; adding one without a rung is
    # exactly the silent acceptance this check exists to stop
    RUNGS = {'RM_DEPTH': 'M1b measured it; the width is still checked separately',
             'RM_BLEND': 'M1f: the blend MODE is checked too (OSRDN_WHY_BLEND_MODE)',
             'RM_TEXTURE': 'M1g: Mesa sets the bit for ANY texture (state.c 817), so '
                           'WHICH texture is checked separately, and the bit and the '
                           'field must agree',
             'RM_ALPHA': 'G4-3 K2: the alpha test (docs/G4_3_KERNEL_PLAN.md 3) -- the bit and '
                         'Color.AlphaEnabled must agree, and the compare must have a code '
                         '(OSRDN_WHY_ALPHA_MODE)'}
    m = re.search(r'#define\s+RM_KNOWN\s+\(?([^)\n]*)\)?', src1)
    names = sorted(re.findall(r'RM_\w+', m.group(1))) if m else []
    if names != sorted(RUNGS):
        print('   FAIL RM_KNOWN is %r, want exactly %r' % (names, sorted(RUNGS)))
        bad += 1
    else:
        for n in names:
            print('   RM_KNOWN has %-9s -- %s' % (n, RUNGS[n]))

    print('design2: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
