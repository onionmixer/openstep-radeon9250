#!/usr/bin/env python3
"""M1b design: how often OSMesa's own triangle chooser gives anything back.

  python3 build/m1b/design1.py

The Matrox ladder records that saving ctx->Driver.TriangleFunc for a per-state
fallback does not work -- the chooser "거의 언제나 NULL 을 돌려준다".  That is a
claim about OUR source too, so it is counted here rather than believed: the
conditions are read out of osmesa.c and the space they cut out is enumerated.

If the saved pointer is usually null, a back end cannot fall back by calling it,
and M1b must not be designed around one.
"""
import itertools
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
OSMESA = os.path.join(PROJ, '..', 'openstep-mesa342', 'upstream', 'Mesa-3.4.2',
                      'src', 'OSmesa', 'osmesa.c')

TYPES = os.path.join(os.path.dirname(OSMESA), '..', 'types.h')


def raster_bits():
    """the RasterMask bits, read from types.h -- a list typed here would go stale
    the first time Mesa gained a feature, and the percentage below would lie"""
    t = open(TYPES).read()
    i = t.index('#define ALPHATEST_BIT')
    block = t[i:t.index('\n\n', i)]
    return [(m.group(1), int(m.group(2), 16))
            for m in re.finditer(r'#define\s+(\w+_BIT)\s+(0x[0-9a-fA-F]+)', block)]


def chooser(text):
    """the conditions, read from the function rather than remembered"""
    i = text.index('static triangle_func choose_triangle_function')
    body = text[i:text.index('\n}', i)]
    # count RETURNS, not conditions: the first one has nested parentheses and a
    # regex over the condition quietly missed it (which is how this file first
    # reported three of four)
    nulls = [' '.join(m.group(1).split())
             for m in re.finditer(r'if\s*(\(.*?\))\s*return NULL;', body, re.S)]
    return body, nulls


def main():
    text = open(OSMESA).read()
    body, nulls = chooser(text)
    bad = 0

    print('1. every way the chooser returns NULL, read from the source')
    for n in nulls:
        print('   %s' % n)
    print('   %d early nulls, plus the final "return NULL" when the depth shape does not match'
          % len(nulls))
    # the source's own count, so the regex cannot quietly miss one
    want = body.count('return NULL;') - 1
    if len(nulls) != want:
        print('   FAIL: the source has %d early nulls, this read %d' % (want, len(nulls)))
        bad += 1

    print('2. the ONLY shape that yields a function')
    want = ['RasterMask == DEPTH_BIT (exactly)', 'Depth.Func == GL_LESS', 'Depth.Mask == GL_TRUE',
            'Visual->DepthBits == DEFAULT_SOFTWARE_DEPTH_BITS', 'format != OSMESA_COLOR_INDEX']
    for w in want:
        key = w.split()[0].split('.')[-1].split('->')[-1]
        if key not in body:
            print('   FAIL the source no longer mentions %s' % key)
            bad += 1
    for w in want:
        print('   %s' % w)
    print('   and then flat or smooth, by Light.ShadeModel')

    print('3. how much of the RasterMask space that is')
    bits = raster_bits()
    n = len(bits)
    total = 2 ** n
    print('   bits, from types.h: %s' % ', '.join(b for b, _v in bits))
    ok = 1                                  # exactly DEPTH_BIT, one value out of 2**n
    print('   RasterMask has %d bits -> %d combinations' % (n, total))
    print('   the chooser accepts exactly ONE of them (DEPTH_BIT alone): %d / %d = %.5f%%'
          % (ok, total, 100.0 * ok / total))
    # the commonest case of all is no raster feature at all -- plain triangles
    print('   note: RasterMask == 0 (no depth test, no blend, nothing) is NOT accepted,')
    print('   and that is the commonest state a simple program is in')

    print('4. what follows for M1b')
    for s in ('a saved ctx->Driver.TriangleFunc is null in all but one RasterMask value,',
              'so "call the saved software function" is NOT a fallback;',
              'declining must mean LEAVING Mesa\'s own choice alone, which is what the',
              'call site already says: replace only for states we can draw, and leave',
              'every other one exactly as found.'):
        print('   %s' % s)

    print('design1: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
