#!/usr/bin/env python3
"""M1g: a whole TEXTURED approval run, synthesised and judged (docs/M1G_PLAN.md 8).

  sim_texrun.py

The other M1g checks test the pieces: the prologue generator checks the stream,
sim_class the state, and judge_m1d --self-test the sampling rule.  None of them
runs the JUDGE over a TRANSCRIPT, and that is where a textured rung is most
likely to break in a way only hardware would show -- a counter the judge reads
and the test does not print, a vertex width the parser does not expect, a gate
that was written for five-word vertices.  Finding that on the target costs a
boot; finding it here costs a second.

So this builds a transcript of the shape the test prints, fills the picture with
the RECOUNT's implementation of the rule (build/m1d/indep_m1d.py), and judges it
with the JUDGE's (tools/mesa/judge_m1d.py).  A pass means two implementations
agreed through two parsers over a whole run.  Then one pixel is moved by one bit
and the judge must say so -- a judge that cannot fail is not a judge.
"""

import os
import shutil
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PROJ, 'build', 'm1d'))

import judge_m1d as J                                       # noqa: E402
import indep_m1d as I                                       # noqa: E402

W = H = 64
CLEAR = 0xffbf8040              # the clear colour M1f measured, in OSMesa's packing
PTS = [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]
# the ST the test sends: eight texels across twenty-four pixels, so every sample
# sits a sixth of a texel from the nearest boundary
ST = ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
ROWS = [[0xff550000 | ((v * 32) << 8) | (u * 32) for u in range(8)] for v in range(8)]
SEED = 1234567
RUN = 'simtexa'


def bits(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]


def step(name, inst, tri, deleg, notb, ent, sub, tsent, tup, tproj, dash, setup):
    """the four lines the test prints at every step"""
    return [
        'RDNTRI run=%s step=%s installs=%d leaves=0 triangles=%d delegated=%d '
        'nosw=0 notbound=%d slotsfull=0 caps=00000001 shade=1d00 '
        'tex=1 texup=%d texbad=0 texproj=%d'
        % (RUN, name, inst, tri, deleg, notb, tup, tproj),
        'RDNTRI run=%s step=%s-tri entered=%d submitted=%d maps=1 opens=%d '
        'words=57 seed=%d smoothsent=0 blendsent=0 texsent=%d why=0 at=0 '
        'word=00000000 status=0' % (RUN, name, ent, sub, sub, SEED, tsent),
        'RDNTRI run=%s step=%s-refused -=0 NO_ACCEL=0 NOT_RUNNING=0 NO_WINDOW=0 '
        'ARGS=0 IOCTL=0 REFUSED=0 NOT_DRAWN=0 BATCH_OPEN=0 SUM=0' % (RUN, name),
        # M1k's line.  This simulated run draws ONE triangle, so it is one
        # batch of one -- the "the batch happened" gate exempts a scene with a
        # single triangle by name, and this is that scene.
        'RDNTRI run=%s step=%s-batch adds=%d flushes=%d flushed=%d failed=0 '
        'replayed=0 outside=0 flushout=0 desync=0 rs=%d rf=%d rinst=%d '
        'tbatched=%d tflushes=%d tfailed=0'
        % (RUN, name, sub, sub, sub, sub + 1, sub + 1, 1 if inst else 0,
           sub, sub),
        'RDNTRI run=%s step=%s-why -=%d FORMAT=0 SMOOTH=0 STIPPLE=0 TEXTURE=0 '
        'RASTER=0 DEPTH_WIDTH=0 SHADE_MODEL=0 TRI_SETUP=%d BLEND_MODE=0'
        % (RUN, name, dash, setup),
    ]


def transcript(move=None):
    L = ['RDNTRI run=%s step=mode smooth=0 blend=0 tex=1' % RUN]
    L += step('before',  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    L += step('bind',    1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0)
    L += step('draw',    2, 1, 0, 0, 1, 1, 1, 1, 0, 2, 0)
    v = []
    for i in range(3):
        v += [bits(PTS[i][0]), bits(PTS[i][1]), bits(1.0), bits(1.0),
              0xffffffff, bits(ST[0][i]), bits(ST[1][i])]
    L.append('RDNTRI run=%s step=draw-sent n=1 kept=1 words=21' % RUN)
    L.append('RDNTRI run=%s tri 0%s' % (RUN, ''.join(' %08x' % w for w in v)))
    L.append('RDNTRI run=%s step=tex uploads=1 texels=64 readbad=0 first=%08x'
             % (RUN, ROWS[0][0]))
    for y in range(8):
        L.append('RDNTRI run=%s tex row=%d%s'
                 % (RUN, y, ''.join(' %08x' % w for w in ROWS[y])))
    L.append('RDNTRI run=%s step=grab-draw w=64 h=64' % RUN)
    L += step('cull',    2, 1, 0, 0, 1, 1, 1, 1, 0, 2, 1)
    L += step('unbound', 2, 3, 2, 2, 1, 1, 1, 1, 0, 2, 1)
    L += step('end',     2, 3, 2, 2, 1, 1, 1, 1, 0, 2, 1)
    L.append('RDNTRI run=%s step=end-sent n=1 kept=1 words=21' % RUN)
    L.append('RDNTRI run=%s tri 0%s' % (RUN, ''.join(' %08x' % w for w in v)))

    img = [CLEAR] * (W * H)
    for (x, y), word in I.texel_words(PTS, ST, (8, 8, ROWS)).items():
        img[y * W + x] = word
    if move is not None:
        img[move] ^= 0x00010000
    for tag in ('draw', 'cull'):
        L.append('RDNTRI run=%s step=pixels tag=%s n=%d' % (RUN, tag, W * H))
        for i in range(0, W * H, 8):
            L.append('RDNTRI px %s %05d%s'
                     % (tag, i, ''.join(' %08x' % w for w in img[i:i + 8])))
    L.append('RDNTRI run=%s step=done' % RUN)
    return '\n'.join(L) + '\n'


def judge_one(work, tag, move):
    d = os.path.join(work, tag)
    os.makedirs(d)
    open(os.path.join(d, 't-accel.out'), 'w').write(transcript(move))
    return J.judge(d)


def main():
    fails = 0
    work = tempfile.mkdtemp(prefix='simtexrun')
    try:
        ok, bad, note = judge_one(work, 'good', None)
        for s in note:
            print('  --   %s' % s)
        for s in bad:
            print('  FAIL %s' % s)
        if bad:
            fails += 1
        else:
            print('  ok   a whole textured run passes every gate (%d of them), with '
                  'the picture built by the recount and judged by the judge' % len(ok))

        covered = sorted(I.texel_words(PTS, ST, (8, 8, ROWS)))
        mx, my = covered[len(covered) // 2]
        _ok2, bad2, _n2 = judge_one(work, 'mutant', my * W + mx)
        if not bad2:
            print('  FAIL one wrong pixel at (%d,%d) is NOT caught' % (mx, my))
            fails += 1
        else:
            print('  ok   and one wrong pixel at (%d,%d) is caught' % (mx, my))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print('sim_texrun: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
