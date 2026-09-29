#!/usr/bin/env python3
"""Which triangle function actually runs, and who culls -- computed, not argued.

  sim_trifunc.py            print the table docs/M1D_PLAN.md 3b/3c assert
  sim_trifunc.py --self-test

docs/M1D_PLAN.md reasons about five files at once (state.c, vbrender.c,
triangle.c, vbcull.c, tritemp.h) to answer two questions: does OUR function get
called, and does anything cull the back faces before it.  Reasoning about five
files in prose is how the first draft of 3b got the answer backwards -- it read
render_triangle as a bypass when its last line calls us.

So the decision is modelled here instead, and the DD_* constants are READ OUT OF
types.h rather than typed in: a renumbered bit changes this table instead of
silently invalidating it.

Modelled, with the line each step comes from:

  state.c 1092    IndirectTriangles = TriangleCaps & ~Driver.TriangleCaps
  state.c 1093    IndirectTriangles |= DD_SW_RASTERIZE
  state.c 1100    Driver.TriangleFunc = NULL
  state.c 1111    Driver.UpdateState -> osmesa 1997, then OUR HOOK
  state.c 1121    if (IndirectTriangles & DD_SW_RASTERIZE)      -- always true
  state.c 1124      gl_set_triangle_function  (triangle.c 1527-1688)
  state.c 1127      if all of TRI_SW_RASTERIZE|QUAD_SW_RASTERIZE|TRI_CULL
  state.c 1130        IndirectTriangles &= ~DD_TRI_CULL
  vbrender.c 758  TriangleFunc = Driver.TriangleFunc, then the DD_SW_SETUP latch
  vbcull.c 819    the VB cull stage runs only when IndirectTriangles & DD_ANY_CULL
  tritemp.h 151   the software rasteriser culls: if (area * bf < 0.0) return
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MESA = os.path.join(HERE, '..', '..', '..', 'openstep-mesa342', 'upstream', 'Mesa-3.4.2')


def dd_constants():
    """Every DD_* macro from src/types.h, expanded.  Typing the values here
    instead would make this table agree with itself rather than with Mesa."""
    src = open(os.path.join(MESA, 'src', 'types.h'), errors='replace').read()
    src = re.sub(r'\\\s*\n', ' ', src)           # join macro continuations
    raw, order = {}, []
    for m in re.finditer(r'^#define\s+(DD_\w+)\s+(.+)$', src, re.M):
        raw[m.group(1)] = m.group(2).split('/*')[0].strip()
        order.append(m.group(1))

    out = {}

    def ev(name, seen=()):
        if name in out:
            return out[name]
        if name in seen:
            raise RuntimeError('cycle through %s' % name)
        e = re.sub(r'\bDD_\w+\b', lambda m: '(%d)' % ev(m.group(0), seen + (name,)),
                   raw[name])
        out[name] = eval(e)
        return out[name]

    for n in order:
        ev(n)
    return out


DD = dd_constants()


def decide(triangleCaps=0, driverTriangleCaps=0, renderMode='GL_RENDER',
           noRaster=False, smoothFlag=False, weInstall=False):
    """Return (what ctx->TriangleFunc ends up as, who culls back faces)."""
    ind = (triangleCaps & ~driverTriangleCaps) | DD['DD_SW_RASTERIZE']

    # state.c 1100: cleared every time, so an install must happen every UpdateState
    driverFunc = None
    if weInstall:                                   # our hook, state.c 1111
        driverFunc = 'ours'

    if ind & DD['DD_SW_RASTERIZE']:                 # state.c 1121 -- always
        # triangle.c 1527-1688, in source order
        if renderMode == 'GL_RENDER':
            if noRaster:                            # 1528, BEFORE the driver test
                driverFunc = 'null_triangle'
            elif driverFunc is not None:            # 1532 -- the hook point
                pass                                # kept
            elif smoothFlag:                        # 1539
                driverFunc = 'aa_triangle'
            else:
                driverFunc = 'sw_triangle'          # 1655-1678 and the rest
        elif renderMode == 'GL_FEEDBACK':           # 1683, outside GL_RENDER
            driverFunc = 'gl_feedback_triangle'
        else:                                       # 1687
            driverFunc = 'gl_select_triangle'

        need = DD['DD_TRI_SW_RASTERIZE'] | DD['DD_QUAD_SW_RASTERIZE'] | DD['DD_TRI_CULL']
        if (ind & need) == need:                    # state.c 1127
            ind &= ~DD['DD_TRI_CULL']               # 1130

    # vbrender.c 758-776
    triFunc = driverFunc
    if ind & DD['DD_SW_SETUP']:
        if ind & (DD['DD_SW_SETUP'] & ~DD['DD_TRI_CULL']):
            if ind & DD['DD_TRI_CULL_FRONT_BACK']:
                triFunc = 'null_triangle'
            elif triangleCaps & DD['DD_TRI_UNFILLED']:
                # vbrender.c 317-318: render_triangle diverts to unfilled_polygon
                # INSTEAD of calling Driver.TriangleFunc (the else at 320-321).
                # Leaving this out made the table say '-> ours' while the label
                # next to it said we were left out -- the model agreed with the
                # prose rather than with the source.
                triFunc = 'render_triangle -> unfilled_polygon'
            else:
                triFunc = 'render_triangle -> ' + str(driverFunc)

    # who culls?  vbcull.c 819 runs only if the bit SURVIVED state.c 1130
    if triangleCaps & DD['DD_TRI_CULL']:
        if ind & DD['DD_ANY_CULL']:
            culler = 'vbcull.c'
        elif 'render_triangle' in str(triFunc):
            culler = 'render_triangle'              # vbrender.c 292
        elif driverFunc == 'sw_triangle':
            culler = 'tritemp.h'                    # 151
        else:
            culler = 'NOBODY'
        return triFunc, culler
    return triFunc, '-'


CASES = [
    ('아무 상태도 안 켬',                    dict()),
    ('컬링만(GL_CULL_FACE)',                 dict(triangleCaps=DD['DD_TRI_CULL'])),
    ('폴리곤 오프셋',                        dict(triangleCaps=DD['DD_TRI_OFFSET'])),
    ('양면 조명',                            dict(triangleCaps=DD['DD_TRI_LIGHT_TWOSIDE'])),
    ('비채움(glPolygonMode)',                dict(triangleCaps=DD['DD_TRI_UNFILLED'])),
    ('앞뒤 모두 컬링',                       dict(triangleCaps=DD['DD_TRI_CULL_FRONT_BACK'])),
    ('NoRaster',                             dict(noRaster=True)),
    ('GL_FEEDBACK',                          dict(renderMode='GL_FEEDBACK')),
    ('GL_SELECT',                            dict(renderMode='GL_SELECT')),
    ('안티앨리어싱(GL_POLYGON_SMOOTH)',      dict(smoothFlag=True)),
]


def table():
    print('DD_SW_SETUP = %#010x   DD_SW_RASTERIZE = %#010x   교집합 = %#x'
          % (DD['DD_SW_SETUP'], DD['DD_SW_RASTERIZE'],
             DD['DD_SW_SETUP'] & DD['DD_SW_RASTERIZE']))
    print()
    print('%-30s | %-34s | %-34s | %s'
          % ('앱 상태', '설치 안 함 → TriangleFunc', '설치함 → TriangleFunc', '누가 자르나'))
    print('-' * 125)
    for label, kw in CASES:
        off, _ = decide(**kw)
        on, culler = decide(weInstall=True, **kw)
        print('%-30s | %-34s | %-34s | %s' % (label, off, on, culler))


def self_test():
    """Each assertion is a sentence docs/M1D_PLAN.md makes."""
    fails = 0

    def one(label, cond):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', label))

    one('D9: DD_SW_RASTERIZE does not intersect DD_SW_SETUP',
        (DD['DD_SW_SETUP'] & DD['DD_SW_RASTERIZE']) == 0)
    one('D8: DD_SW_SETUP is the five setup bits',
        DD['DD_SW_SETUP'] == (DD['DD_TRI_CULL'] | DD['DD_TRI_CULL_FRONT_BACK'] |
                              DD['DD_TRI_OFFSET'] | DD['DD_TRI_LIGHT_TWOSIDE'] |
                              DD['DD_TRI_UNFILLED']))
    one('D14: with nothing set, our function is what runs',
        decide(weInstall=True)[0] == 'ours')
    one('D14: and without us Mesa picks a software one',
        decide()[0] == 'sw_triangle')
    one('D10: polygon offset wraps us, it does not replace us',
        decide(weInstall=True, triangleCaps=DD['DD_TRI_OFFSET'])[0]
        == 'render_triangle -> ours')
    one('D11: unfilled leaves us out -- unfilled_polygon draws it instead',
        decide(weInstall=True, triangleCaps=DD['DD_TRI_UNFILLED'])[0]
        == 'render_triangle -> unfilled_polygon')
    one('D11: and it leaves the SOFTWARE triangle function out too, so that '
        'is not a difference we introduce',
        decide(triangleCaps=DD['DD_TRI_UNFILLED'])[0]
        == 'render_triangle -> unfilled_polygon')
    one('D11: front-and-back culling draws nothing at all',
        decide(weInstall=True, triangleCaps=DD['DD_TRI_CULL_FRONT_BACK'])[0]
        == 'null_triangle')
    one('D15: NoRaster replaces us for free',
        decide(weInstall=True, noRaster=True)[0] == 'null_triangle')
    one('D15: GL_FEEDBACK replaces us for free',
        decide(weInstall=True, renderMode='GL_FEEDBACK')[0] == 'gl_feedback_triangle')
    one('D15: GL_SELECT replaces us for free',
        decide(weInstall=True, renderMode='GL_SELECT')[0] == 'gl_select_triangle')
    one('D16: antialiasing does NOT replace us -- we must decline it',
        decide(weInstall=True, smoothFlag=True)[0] == 'ours')
    one('D16: and without us it would have been the AA rasteriser',
        decide(smoothFlag=True)[0] == 'aa_triangle')

    # the one this whole section exists for
    one('D12: with culling on and us installed, NOBODY culls',
        decide(weInstall=True, triangleCaps=DD['DD_TRI_CULL'])[1] == 'NOBODY')
    one('D12: without us, the software rasteriser culls',
        decide(triangleCaps=DD['DD_TRI_CULL'])[1] == 'tritemp.h')
    one('D19: the VB cull stage never runs in either case (1130 cleared the bit)',
        decide(weInstall=True, triangleCaps=DD['DD_TRI_CULL'])[1] != 'vbcull.c' and
        decide(triangleCaps=DD['DD_TRI_CULL'])[1] != 'vbcull.c')
    one('D20: TriangleCaps still shows the cull that IndirectTriangles lost',
        (DD['DD_TRI_CULL'] & DD['DD_SW_SETUP']) != 0)

    # and the decision the plan makes: one condition covers every unsafe case
    unsafe = []
    for label, kw in CASES:
        f, culler = decide(weInstall=True, **kw)
        bad = (culler == 'NOBODY') or (f == 'ours' and kw.get('smoothFlag')) \
              or f == 'render_triangle -> unfilled_polygon'
        declined = (kw.get('triangleCaps', 0) & DD['DD_SW_SETUP']) != 0 or kw.get('smoothFlag')
        if bad and not declined:
            unsafe.append(label)
    one('the plan\'s decline rule (TriangleCaps & DD_SW_SETUP, plus smooth) '
        'covers every unsafe case', not unsafe)
    if unsafe:
        print('       uncovered: %s' % ', '.join(unsafe))

    print('sim_trifunc self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


def main():
    if '--self-test' in sys.argv:
        return 1 if self_test() else 0
    table()
    return 0


if __name__ == '__main__':
    sys.exit(main())
