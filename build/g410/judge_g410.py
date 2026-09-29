#!/usr/bin/env python3
"""G4-10 (docs/G4_10_MIP_SUBSTITUTE_PLAN.md 3-4): scene D under the DEFAULT knob must come out of the card as
LEVEL SELECTION -- every 16 px square's G is one level's flat G (32 * level), never a blend between two --
with nothing delegated to Mesa.  Row 0 asked GL_NEAREST_MIPMAP_LINEAR (sent as NEAREST_MIPMAP_NEAREST), row 1
GL_LINEAR_MIPMAP_LINEAR (sent as LINEAR_MIPMAP_NEAREST).
  judge_g410.py <pics dir> <logs dir>
  judge_g410.py --self-test
"""
import os, re, sys, importlib.util
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('model', os.path.join(HERE, '..', 'g45', 'model.py'))
model = importlib.util.module_from_spec(spec); spec.loader.exec_module(model)


def block(img, x, y, n, inset=1):
    """scene coordinates have GL's origin (bottom-left); the PPM's rows start at the top (judge_g45.block)"""
    a = np.asarray(img)
    H = a.shape[0]
    return a[H - (y + n) + inset:H - y - inset, x + inset:x + n - inset].reshape(-1, 3)


def judge_pic(img):
    """[(row, k, mean G, spread, level chosen or None)] and the failures"""
    fails, rows = [], []
    for row in (0, 1):
        for r in model.scene_d():
            b = block(img, r['x'], r['y'] + row * 200, 16)
            g = b[:, 1]
            mean, sp = float(g.mean()), int(g.max() - g.min())
            level = None
            for lv in range(model.LEVELS):
                if abs(mean - model.level_g(lv)) <= 2:
                    level = lv
            rows.append((row, r['k'], mean, sp, level))
            if sp > 4:
                fails.append('row %d k=%d: spread %d (not flat)' % (row, r['k'], sp))
            elif level is None:
                fails.append('row %d k=%d: G %.1f is between levels (a blend?)' % (row, r['k'], mean))
            elif level not in (r['level'], min(r['level'] + 1, model.LEVELS - 1)):
                fails.append('row %d k=%d: level %d chosen, lambda %.3f allows %d or %d' % (row, r['k'], level, r['lam'], r['level'], r['level'] + 1))
    return rows, fails


def judge(pics, logs):
    fails = []
    log = open(os.path.join(logs, 'mipd.log')).read()
    m = re.search(r'GHOST mipd: batches=(\d+) drawn=(\d+) delegated=(\d+)', log)
    if not m:
        fails.append('no GHOST mipd counter line')
    elif int(m.group(3)) != 0 or int(m.group(2)) == 0:
        fails.append('D (default knob): drawn %s delegated %s, want drawn > 0 and delegated 0' % (m.group(2), m.group(3)))
    p = os.path.join(pics, 'qd.mipd.ppm')
    if not os.path.exists(p):
        fails.append('no card picture %s' % p)
        return fails
    rows, f2 = judge_pic(Image.open(p).convert('RGB'))
    fails += f2
    for row in (0, 1):
        print('  --   row %d: %s' % (row, ' '.join('%d:%s' % (k, lv if lv is not None else '?') for rw, k, _m, _s, lv in rows if rw == row)))
    return fails


def self_test():
    bad = 0
    img = np.zeros((400, 500, 3), dtype=np.uint8)
    for row in (0, 1):
        for r in model.scene_d():
            lv = round(r['lam'])
            y = 400 - (r['y'] + row * 200 + 16)
            img[y:y + 16, r['x']:r['x'] + 16, 1] = model.level_g(lv)
    ok = not judge_pic(Image.fromarray(img))[1]
    print('  %-4s a level-selected picture passes' % ('ok' if ok else 'FAIL')); bad += 0 if ok else 1
    blend = img.copy()
    r = model.scene_d()[3]
    y = 400 - (r['y'] + 16)
    blend[y:y + 16, r['x']:r['x'] + 16, 1] = int(r['g'])      # GL's blend value for k=3 (between levels)
    caught = bool(judge_pic(Image.fromarray(blend))[1])
    print('  %-4s a blended square is caught' % ('ok' if caught else 'FAIL')); bad += 0 if caught else 1
    wrong = img.copy()
    wrong[y:y + 16, r['x']:r['x'] + 16, 1] = model.level_g(7)
    caught = bool(judge_pic(Image.fromarray(wrong))[1])
    print('  %-4s a far-off level is caught' % ('ok' if caught else 'FAIL')); bad += 0 if caught else 1
    print('judge_g410 self-test: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return bad


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(1 if self_test() else 0)
    f = judge(sys.argv[1], sys.argv[2])
    for x in f:
        print('  FAIL ' + x)
    print('judge_g410: %s' % ('PASS' if not f else 'FAIL (%d)' % len(f)))
    sys.exit(1 if f else 0)
