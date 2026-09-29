#!/usr/bin/env python3
"""G4-2 B1+B2 judge (docs/G4_2_BATCH_PLAN.md 7): batches across brackets, segments inside a stream.
  judge_g42.py <dir with mb/mk sb/sk ob/ok pictures> <dir with many.log seg.log order.log>
MANY   300 textured triangles, one state: 2 batches (6300 + 60 words at 4068 a stream), stock-equal
SEG    the same 300, the state changing every 2: <= 3 batches, >= 147 segments, stock-equal
ORDER  card, software lines, card, glReadPixels, glTexSubImage2D, card, software points: the picture
       and the read block stock-equal; the flush table names lines, points, readpix, texupload
every scene: prevalidateRefused = lostAtFlush = unfinished = primNoSoftware = batchDesync = noSoftware = 0
"""
import os
import re
import sys
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


def kv(line):
    return {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)}


HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def bounds():
    """the words a submission may carry today (the kernel's page: osrdn_r7b.h) and the textured
    prologue's length (the generated table) -> textured triangles a batch, batches for 300"""
    h = open(os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_r7b.h')).read()
    t = open(os.path.join(PROJ, 'mesa', 'OSRDNMesaTriTable.h')).read()
    page = int(re.search(r'#define\s+OSRDN_R7B_WINDOW_BYTES\s+(\d+)', h).group(1)) // 4
    maxw = int(re.search(r'#define\s+OSRDN_R7B_MAX_WORDS\s+(\d+)', h).group(1))
    ver = int(re.search(r'#define\s+OSRDN_R7B_VERSION\s+(\d+)', h).group(1))
    # G4-4 K8: a version 2 kernel takes maxWords on the copyin path (the library's default);
    # version 1 refused past the page, and the library then bounded itself by the page
    bound = maxw if ver >= 2 else page
    tpro = int(re.search(r'#define\s+OSRDN_TEX_PROLOGUE_WORDS\s+(\d+)', t).group(1))
    vw = int(re.search(r'#define\s+OSRDN_TEX_VERTEX_WORDS\s+(\d+)', t).group(1))
    per = (bound - tpro - 2) // (3 * vw)
    return bound, per, -(-300 // per)


def main(pics, logs):
    fails = []
    page, per, many_batches = bounds()
    print('  --   a submission carries %d words (osrdn_r7b.h): %d textured triangles a batch, 300 in %d'
          % (page, per, many_batches))

    def picture(tag, a_name, s_name):
        try:
            a, s = load(os.path.join(pics, a_name)), load(os.path.join(pics, s_name))
        except IOError as e:
            fails.append('%s: picture missing (%s)' % (tag, e))
            return
        drawn_a, drawn_s = int((a != a[0, 0]).any(axis=2).sum()), int((s != s[0, 0]).any(axis=2).sum())
        big, unx = unexplained(a, s)
        print('  %-4s %-6s drawn px %6d vs %6d  >32 %5d  not any stock neighbour %5d'
              % ('ok' if unx == 0 else 'FAIL', tag, drawn_a, drawn_s, big, unx))
        if unx:
            fails.append('%s: differs from stock beyond a neighbour (%d px)' % (tag, unx))
        if drawn_s == 0:
            fails.append('%s: stock drew nothing, so equality proves nothing' % tag)

    def counters(tag, text):
        b1 = [l for l in text.splitlines() if ' b1: ' in l]
        b2 = [l for l in text.splitlines() if ' b2: ' in l]
        if not b1 or not b2:
            fails.append('%s: no b1/b2 counter lines' % tag)
            return {}, {}
        c1, c2 = kv(b1[0]), kv(b2[0])
        for k in ('refused', 'lost', 'unfinished', 'primNoSw', 'desync', 'noSw'):
            if c1.get(k, -1) != 0:
                fails.append('%s: %s = %s, want 0' % (tag, k, c1.get(k)))
        if c2.get('verifyRefused', -1) != 0 or c2.get('flushFailed', -1) != 0:
            fails.append('%s: verifyRefused %s / flushFailed %s, want 0 / 0' % (tag, c2.get('verifyRefused'), c2.get('flushFailed')))
        print('  ok   %-6s b1 %s' % (tag, ' '.join('%s=%d' % (k, c1[k]) for k in ('prevalidated', 'refused', 'prefix', 'lost', 'points', 'lines', 'delegated'))))
        print('  ok   %-6s b2 %s' % (tag, ' '.join('%s=%d' % (k, c2[k]) for k in ('segments', 'segWords', 'verifies', 'opens', 'flushes', 'submitted'))))
        return c1, c2

    # ---- MANY
    many = open(os.path.join(logs, 'many.log')).read()
    m = re.search(r'GHOST many: batches=(\d+) drawn=(\d+) delegated=(\d+)', many)
    if not m or (int(m.group(1)), int(m.group(2)), int(m.group(3))) != (many_batches, 300, 0):
        fails.append('MANY: 300 triangles took %s batches / drawn %s / delegated %s (want %d / 300 / 0)'
                     % ((m.group(1), m.group(2), m.group(3)) if m else ('?', '?', '?'), many_batches))
    else:
        print('  ok   MANY 300 triangles in %d batches (the bracket no longer closes a batch; boot 8: 5)' % many_batches)
    counters('MANY', many)
    picture('MANY', 'mb.many.ppm', 'mk.many.ppm')

    # ---- SEG
    seg = open(os.path.join(logs, 'seg.log')).read()
    m = re.search(r'GHOST seg: batches=(\d+) drawn=(\d+) delegated=(\d+)', seg)
    if not m or int(m.group(1)) > many_batches + 1 or (int(m.group(2)), int(m.group(3))) != (300, 0):
        fails.append('SEG: %s batches / drawn %s / delegated %s (want <= %d / 300 / 0)'
                     % ((m.group(1), m.group(2), m.group(3)) if m else ('?', '?', '?'), many_batches + 1))
    else:
        print('  ok   SEG 300 triangles with 150 state changes in %s batches' % m.group(1))
    c1, c2 = counters('SEG', seg)
    if c2 and m:
        want = 149 - (int(m.group(1)) - 1)       # every change is a segment unless it opened a new batch
        if c2.get('segments', 0) < want:
            fails.append('SEG: %d segments, want >= %d' % (c2.get('segments', 0), want))
        else:
            print('  ok   SEG %d segments (%d pair words) for 149 changes inside the streams' % (c2['segments'], c2['segWords']))
    picture('SEG', 'sb.seg.ppm', 'sk.seg.ppm')

    # ---- ORDER
    order = open(os.path.join(logs, 'order.log')).read()
    m = re.search(r'GHOST order: batches=(\d+) drawn=(\d+) delegated=(\d+)', order)
    if not m or (int(m.group(2)), int(m.group(3))) != (8, 0):
        fails.append('ORDER: drawn %s / delegated %s (want 8 / 0: four quads on the card)'
                     % ((m.group(2), m.group(3)) if m else ('?', '?')))
    counters('ORDER', order)
    why = [l for l in order.splitlines() if ' why:' in l]
    w = kv(why[0]) if why else {}
    # F8 fires at the drop (glTexSubImage2D invalidates the resident image) or at the upload
    # (the next draw puts the new texels in), whichever comes first with a batch in hand
    w['f8'] = w.get('texdrop', 0) + w.get('texupload', 0)
    for k in ('lines', 'points', 'readpix', 'f8'):
        if w.get(k, 0) < 1:
            fails.append('ORDER: the flush table has no %s (%s)' % (k, why[0].strip() if why else 'no line'))
    if why and all(w.get(k, 0) >= 1 for k in ('lines', 'points', 'readpix', 'f8')):
        print('  ok   ORDER flushes: %s' % why[0].split('why:')[1].strip())
    picture('ORDER', 'ob.order.ppm', 'ok.order.ppm')
    picture('READ', 'ob.read.ppm', 'ok.read.ppm')

    for f in fails:
        print('  FAIL ' + f)
    print('judge_g42: %s' % ('PASS' if not fails else 'FAIL (%d)' % len(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
