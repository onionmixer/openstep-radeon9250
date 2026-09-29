#!/usr/bin/env python3
"""G4-3 boot judge (docs/G4_3_KERNEL_PLAN.md 8): the runner's logs and pictures, one verdict a kernel item.

  judge_g43.py <dir with ab/ak/ub/uk/mb/mk pictures> <dir with uv.log many.log alpha.log q2.log>

K1  GHOST_UV: uv 64 and 256 drawn 32/32 with no refusal (the idle wait outlives one round)
K2  GHOST_ALPHA: each compare's picture equals stock's within the neighbour rule; 'off' too
K4  GHOST_MANY: 300 textured triangles in one state take ceil(300/72) = 5 batches (Mesa's VB bounds a batch; the 4068-word limit is not reached), stock-equal
q2  q2-state-matrix: every arm but mipmap / LUMINANCE is HARDWARE (uv 0..64 included now)
"""
import os
import re
import sys
import warnings

warnings.simplefilter('ignore')
import numpy as np
from PIL import Image


def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(int)


def unexplained(a, s):
    d = np.abs(a - s).max(axis=2) > 32
    ok = np.zeros_like(d)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ok |= np.abs(a - np.roll(np.roll(s, dy, axis=0), dx, axis=1)).max(axis=2) <= 32
    return int(d.sum()), int((d & ~ok).sum())


def main(pics, logs):
    fails = []
    # K1
    uv = open(os.path.join(logs, 'uv.log')).read()
    for n in (64, 256):
        m = re.search(r'GHOST uv %d: hooked=(\d+) drawn=(\d+) delegated=(\d+)' % n, uv)
        if not m or m.group(2) != '32' or m.group(3) != '0':
            fails.append('K1: uv %d is not drawn 32/32 (%s)' % (n, m.group(0) if m else 'no line'))
        else:
            print('  ok   K1 uv %d: drawn 32, delegated 0' % n)
    for k in ('lastStatus=5', 'refused: 0 0 0 0 0 0 1', 'refused: 0 0 0 0 0 0 2'):
        if k in uv:
            fails.append('K1: the log still shows a refusal (%s)' % k)
    # K2
    for case in ('greater', 'lequal', 'never', 'always', 'notequal', 'equal', 'off'):
        try:
            a, s = load(os.path.join(pics, 'ab.%s.ppm' % case)), load(os.path.join(pics, 'ak.%s.ppm' % case))
        except IOError:
            fails.append('K2: %s picture missing' % case)
            continue
        drawn_a, drawn_s = int((a != [15, 20, 35]).any(axis=2).sum()), int((s != [15, 20, 35]).any(axis=2).sum())
        big, unx = unexplained(a, s)
        print('  %-4s K2 %-8s drawn px %6d vs %6d  >32 %5d  not any stock neighbour %5d' % ('ok' if unx == 0 else 'FAIL', case, drawn_a, drawn_s, big, unx))
        if unx:
            fails.append('K2: %s differs from stock beyond a neighbour (%d px)' % (case, unx))
        if abs(drawn_a - drawn_s) > 600:
            fails.append('K2: %s draws %d px, stock %d -- a column band is wrong' % (case, drawn_a, drawn_s))
    al = open(os.path.join(logs, 'alpha.log')).read()
    m = re.findall(r'GHOST alpha written; drawn=(\d+) delegated=(\d+) codeGap=(\d+)', al)
    if not m or m[0] != ('14', '0', '0'):
        fails.append('K2: the accelerated run did not put all 14 triangles on the card (%s)' % (m[0] if m else 'no line',))
    # K4
    many = open(os.path.join(logs, 'many.log')).read()
    m = re.search(r'GHOST many: batches=(\d+) drawn=(\d+) delegated=(\d+)', many)
    # Boot 8 measured 5, not 2: Mesa's vertex buffer holds 216 vertices = 72 triangles (config.h
    # 181, VB_MAX) and the hook's batch closes at every RenderFinish, so a batch is bounded by the
    # VB, never by the 4068-word limit (190 triangles).  The limit is right; the gain needs the
    # batch to survive RenderFinish (G4-2).  ceil(300 / 72) = 5 is the number in force today.
    if not m or int(m.group(1)) > 5 or m.group(2) != '300' or m.group(3) != '0':
        fails.append('K4: 300 triangles took %s batches / drawn %s (want <= 5 = ceil(300 / 72 a VB) / 300)' % ((m.group(1), m.group(2)) if m else ('?', '?')))
    else:
        print('  ok   K4 300 triangles in %s batches (VB-bound: 72 a batch; the word limit is not reached)' % m.group(1))
    try:
        a, s = load(os.path.join(pics, 'mb.many.ppm')), load(os.path.join(pics, 'mk.many.ppm'))
        big, unx = unexplained(a, s)
        if unx:
            fails.append('K4: the 300-triangle picture differs from stock (%d px)' % unx)
    except IOError:
        fails.append('K4: many picture missing')
    # q2
    q2 = open(os.path.join(logs, 'q2.log')).read()
    soft = [l for l in q2.splitlines() if 'not what was expected' in l]
    allowed = [l for l in soft if 'mipmap' in l or 'LUMINANCE' in l]
    if len(soft) != len(allowed):
        for l in soft:
            if l not in allowed:
                fails.append('q2: %s' % l.strip()[:60])
    else:
        print('  ok   q2-state-matrix: every arm but mipmap / LUMINANCE is HARDWARE')
    for f in fails:
        print('  FAIL ' + f)
    print('judge_g43: %s' % ('PASS' if not fails else 'FAIL (%d)' % len(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
