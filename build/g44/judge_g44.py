#!/usr/bin/env python3
"""G4-4 K5 judge: the mip qualification probe (docs/G4_4_KERNEL_PLAN.md 4-2).
  judge_g44.py <dir with pb.mip.ppm pb.mipclamp.ppm pk.mip.ppm pk.mipclamp.ppm> <dir with mip.log>
Scene A: square i (lambda i) must be level i's flat colour, >= 95 % of its pixels, on the card AND in
stock; scene B (GL_TEXTURE_MAX_LEVEL 4): squares 5..7 must be level 4's colour.  A square that comes
out another level's colour names which memory the card fetched that level from -- the probe's finding.
Counters: every square on the card (delegated 0), chains >= 1, refused = lost = 0.
"""
import os
import re
import sys
import numpy as np
from PIL import Image


def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(int)


def main(pics, logs):
    fails = []
    log = open(os.path.join(logs, 'mip.log')).read()
    colours = {int(m.group(1)): tuple(int(m.group(2)[k:k + 2], 16) for k in (0, 2, 4))
               for m in re.finditer(r'GHOST mip level (\d) \d+x\d+ colour ([0-9a-f]{6})', log)}
    squares = {}
    for m in re.finditer(r'GHOST mip scene (\d) square (\d) at (\d+),(\d+) side (\d+) texcoord (\S+)', log):
        squares.setdefault(int(m.group(1)), {})[int(m.group(2))] = (int(m.group(3)), int(m.group(4)), int(m.group(5)))
    if len(colours) != 8 or len(squares.get(0, {})) != 8 or len(squares.get(1, {})) != 8:
        fails.append('the log does not describe 8 levels and 8 squares a scene (%d levels, %s)' % (len(colours), {k: len(v) for k, v in squares.items()}))
    by_colour = {v: k for k, v in colours.items()}
    H = 600

    def dominant(img, x0, y0, n):
        blk = img[H - (y0 + n):H - y0, x0:x0 + n].reshape(-1, 3)   # rows are top-down in the PPM
        cols, counts = np.unique(blk, axis=0, return_counts=True)
        k = int(counts.argmax())
        return tuple(int(c) for c in cols[k]), counts[k] / float(len(blk))

    for scene, name, expect in ((0, 'mip', lambda i: i), (1, 'mipclamp', lambda i: min(i, 4))):
        for who, pic in (('card', 'pb.%s.ppm' % name), ('stock', 'pk.%s.ppm' % name)):
            try:
                img = load(os.path.join(pics, pic))
            except IOError:
                fails.append('%s: picture %s missing' % (name, pic))
                continue
            for sq, (x0, y0, n) in sorted(squares.get(scene, {}).items()):
                col, share = dominant(img, x0, y0, n)
                want = colours.get(expect(sq))
                got_level = by_colour.get(col, '?')
                ok = (col == want and share >= 0.95)
                # stock Mesa 3.4.2 computes lambda from rho^2 = r1 + r2, the SUM of the two axes'
                # squared derivatives (triangle.c 1061-1076, "used to be MAX2"), not GL's max --
                # measured on boot 9: its 8 px squares with texcoords 0..2 and 0..4 came out one
                # level higher (the card came out at GL's level).  Stock is the control for the
                # card's layout, not the judge of its LOD, so it is allowed one level up.
                if who == 'stock' and not ok and isinstance(got_level, int) and got_level == min(expect(sq) + 1, 7 if scene == 0 else 4) and share >= 0.95:
                    ok = True
                print('  %-4s scene %d %-5s square %d (%3d px, lambda %d): %s %3d%% -> level %s, want level %d'
                      % ('ok' if ok else 'FAIL', scene, who, sq, n, sq, '%02x%02x%02x' % col, int(share * 100), got_level, expect(sq)))
                if not ok:
                    fails.append('%s %s square %d came out level %s (%s, %d%%), want level %d'
                                 % (name, who, sq, got_level, '%02x%02x%02x' % col, int(share * 100), expect(sq)))
    for scene, name in ((0, 'mip'), (1, 'mipclamp')):
        m = re.search(r'GHOST mip scene %d: batches=(\d+) drawn=(\d+) delegated=(\d+) chains=(\d+)' % scene, log)
        if not m:
            fails.append('%s: no counter line' % name)
            continue
        drawn, deleg, chains = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if deleg != 0 or chains < 1:
            fails.append('%s: delegated %d (want 0), chains %d (want >= 1) -- the mip path did not run on the card' % (name, deleg, chains))
        else:
            print('  ok   %-8s drawn=%d delegated=0 chains=%d' % (name, drawn, chains))
        b1 = [l for l in log.splitlines() if ('GHOST %s b1:' % name) in l]
        if b1:
            c1 = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', b1[0])}
            for k in ('refused', 'lost', 'primNoSw', 'desync', 'noSw'):
                if c1.get(k, -1) != 0:
                    fails.append('%s: %s = %s, want 0' % (name, k, c1.get(k)))
    for f in fails:
        print('  FAIL ' + f)
    print('judge_g44: %s' % ('PASS' if not fails else 'FAIL (%d)' % len(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
