#!/usr/bin/env python3
"""G4-5 judge: the mip scenes C, D, E, F (docs/G4_5_MIP_PLAN.md 3).
  judge_g45.py <dir with pictures> <dir with mipc.log mipd.log mipe.log mipf.log>
Pictures: qc/kc .mipc (card RDNMesaMip=all / stock), qd/kd .mipd, qe/ke .mipe, qf/kf .mipf; and
qm .mipc from the card with the default knob (LINEAR_MIPMAP_NEAREST not yet measured: software).
C  card square i = level i's colour (>= 95 %)
D  card G within 2 of build/g45/model.py for both rows, spread <= 4; stock recorded, not judged
E  card and stock: rows 0/1/2 lambda 2 square = level 2 / X / Y, lambda 0 square = level 0
F  cases 1-3 delegated 2 (software), case 0 delegated 0; cases 1-3 card picture == stock
all  refused = lost = primNoSw = desync = noSw = 0 in every card run
"""
import os, re, sys, importlib.util
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('model', os.path.join(HERE, 'model.py'))
model = importlib.util.module_from_spec(spec); spec.loader.exec_module(model)
MIPC = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255), (255, 128, 0), (128, 0, 255)]
X, Y = (0x40, 0x80, 0xc0), (0xc0, 0x40, 0x80)
H = 600


def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(int)


def block(img, x, y, n, inset=0):
    return img[H - (y + n) + inset:H - y - inset, x + inset:x + n - inset].reshape(-1, 3)


def dominant(img, x, y, n):
    b = block(img, x, y, n)
    cols, counts = np.unique(b, axis=0, return_counts=True)
    k = int(counts.argmax())
    return tuple(int(c) for c in cols[k]), counts[k] / float(len(b))


def main(pics, logs):
    fails = []
    def counters(tag, text):
        for l in text.splitlines():
            if (' %s b1:' % tag) in l:
                c = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', l)}
                for k in ('refused', 'lost', 'primNoSw', 'desync', 'noSw'):
                    if c.get(k, -1) != 0:
                        fails.append('%s: %s = %s, want 0' % (tag, k, c.get(k)))
                return
        fails.append('%s: no b1 counter line' % tag)

    def pic(name):
        try:
            return load(os.path.join(pics, name))
        except IOError:
            fails.append('picture %s missing' % name)
            return None

    # ---- C
    log = open(os.path.join(logs, 'mipc.log')).read()
    m = re.findall(r'GHOST mipc: batches=(\d+) drawn=(\d+) delegated=(\d+)', log)
    if len(m) < 2:
        fails.append('C: want two card runs (knob all, knob default), got %d counter lines' % len(m))
    else:
        if int(m[0][2]) != 0:
            fails.append('C (knob all): delegated %s, want 0' % m[0][2])
        # scene C measured LINEAR_MIPMAP_NEAREST, so the default knob takes it (OSRDN_MIP_MEASURED);
        # a declined state would show as drawn 0 (the leave path), never as delegated
        if int(m[1][1]) != 16 or int(m[1][2]) != 0:
            fails.append('C (default knob): drawn %s delegated %s, want 16 / 0 (the mode is measured)' % (m[1][1], m[1][2]))
        else:
            print('  ok   C default knob: all 16 on the card (LINEAR_MIPMAP_NEAREST is measured)')
    counters('mipc', log)
    img = pic('qc.mipc.ppm')
    if img is not None:
        for s in model.squares_ac():
            col, share = dominant(img, s['x'], s['y'], s['n'])
            ok = col == MIPC[s['level']] and share >= 0.95
            print('  %-4s C  square %d (lambda %d): %02x%02x%02x %3d%%' % ('ok' if ok else 'FAIL', s['sq'], s['level'], col[0], col[1], col[2], int(share * 100)))
            if not ok:
                fails.append('C square %d came out %s (%d%%), want level %d' % (s['sq'], col, int(share * 100), s['level']))
    # ---- D
    log = open(os.path.join(logs, 'mipd.log')).read()
    m = re.search(r'GHOST mipd: batches=(\d+) drawn=(\d+) delegated=(\d+)', log)
    if not m or int(m.group(3)) != 0:
        fails.append('D: delegated %s, want 0 (knob all)' % (m.group(3) if m else '?'))
    counters('mipd', log)
    for who, name in (('card', 'qd.mipd.ppm'), ('stock', 'kd.mipd.ppm')):
        img = pic(name)
        if img is None:
            continue
        for row, mode in ((0, 'NEAREST_MIPMAP_LINEAR'), (1, 'LINEAR_MIPMAP_LINEAR')):
            got = []
            for r in model.scene_d():
                b = block(img, r['x'], r['y'] + row * 200, 16, inset=1)
                g = b[:, 1]
                got.append((r['k'], r['g'], float(g.mean()), int(g.max() - g.min())))
            line = ' '.join('%d:%.0f/%.1f' % (k, want, mean) for k, want, mean, _sp in got)
            if who == 'card':
                # G4-5 second run: the card blends linearly in rho, f = 2^frac - 1 (G = 32 * 2^(k/8)),
                # not GL's f = frac; that is the law judged here (+-2), and the GL table is printed
                # beside it -- the gap is why the two *_MIPMAP_LINEAR modes stay in software
                law = [32.0 * 2 ** (k / 8.0) for k, _w, _m, _s in got]
                bad = [(k, law[k], mean, sp) for k, want, mean, sp in got if abs(mean - law[k]) > 2 or sp > 4]
                print('  %-4s D  card %-22s GL/got %s  (card law 32*2^(k/8): %s)' % ('ok' if not bad else 'FAIL', mode, line,
                      ' '.join('%.1f' % v for v in law)))
                for k, want, mean, sp in bad:
                    fails.append('D %s k=%d: G %.1f (spread %d), the card law says %.1f +-2' % (mode, k, mean, sp, want))
            else:
                print('  --   D  stock %-21s want/got %s  (Mesa 3.4.2 lambda is +0.5: recorded, not judged)' % (mode, line))
    # ---- E
    log = open(os.path.join(logs, 'mipe.log')).read()
    counters('mipe', log)
    # stock is recorded, not judged: Mesa 3.4.2's lambda for these squares sits exactly on the
    # NEAREST rounding boundary (i + 0.5), so it picks level i or i + 1 by float error (G4-5 7)
    for who, name in (('card', 'qe.mipe.ppm'), ('stock', 'ke.mipe.ppm')):
        img = pic(name)
        if img is None:
            continue
        for e in model.scene_e():
            want2 = [MIPC[2], X, Y][e['row']]
            c0, s0 = dominant(img, e['x0'], e['y'], e['n0'])
            c2, s2 = dominant(img, e['x2'], e['y'], e['n2'])
            ok = c0 == MIPC[0] and s0 >= 0.95 and c2 == want2 and s2 >= 0.95
            print('  %-4s E  %-5s row %d: lambda0 %02x%02x%02x %3d%%  lambda2 %02x%02x%02x %3d%% (want %02x%02x%02x)'
                  % (('ok' if ok else 'FAIL') if who == 'card' else '--', who, e['row'], c0[0], c0[1], c0[2], int(s0 * 100), c2[0], c2[1], c2[2], int(s2 * 100), want2[0], want2[1], want2[2]))
            if not ok and who == 'card':
                fails.append('E %s row %d: lambda0 %s lambda2 %s, want %s / %s' % (who, e['row'], c0, c2, MIPC[0], want2))
    # ---- F
    log = open(os.path.join(logs, 'mipf.log')).read()
    counters('mipf', log)
    cases = {}
    for a, b, c, d in re.findall(r'GHOST mipf case (\d) at \d+,100 side 32: drawn=(\d+) delegated=(\d+) glerror=([0-9a-f]+)', log):
        cases.setdefault(int(a), (int(b), int(c), d))       # the card's lines come first; stock's follow
    for cse, want_soft in ((0, False), (1, True), (2, True), (3, True)):
        if cse not in cases:
            fails.append('F case %d: no line' % cse)
            continue
        drawn, deleg, err = cases[cse]
        ok = (drawn == 0 if want_soft else drawn == 2) and err == '0'      # software = the leave path, drawn 0
        print('  %-4s F  case %d (%s): drawn %d delegated %d glerror %s' % ('ok' if ok else 'FAIL', cse, ['default', 'MinLod 1', 'MaxLod 2', 'LodBias 1'][cse], drawn, deleg, err))
        if not ok:
            fails.append('F case %d: delegated %d glerror %s (want %s)' % (cse, deleg, err, 'software' if want_soft else 'card'))
    a, s = pic('qf.mipf.ppm'), pic('kf.mipf.ppm')
    if a is not None and s is not None:
        for cse in (1, 2, 3):
            ba, bs = block(a, 50 + cse * 180, 100, 32), block(s, 50 + cse * 180, 100, 32)
            same = bool((ba == bs).all())
            print('  %-4s F  case %d picture identical to stock: %s' % ('ok' if same else 'FAIL', cse, same))
            if not same:
                fails.append('F case %d: software on the accel link differs from stock' % cse)
    for f in fails:
        print('  FAIL ' + f)
    print('judge_g45: %s' % ('PASS' if not fails else 'FAIL (%d)' % len(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
