#!/usr/bin/env python3
"""An independent recount of the M1d picture.

  indep_m1d.py <run dir>
  indep_m1d.py --self-test

tools/mesa/judge_m1d.py predicts the picture with tools/r6/tri_oracle.py's
cover(), which is numpy and shared with the whole R6 ladder.  If that oracle
were wrong in some way the ladder never exercised, the judge and the oracle
would agree with each other and with nothing else.

So this counts again, and shares NO code with either: plain integer arithmetic,
no numpy, the raster rule written out here from what R6d measured --

    vertices truncated to 1/16 of a pixel   (R6d: 1/16, truncate)
    the sample point is the pixel centre    (x + 1/2, y + 1/2)
    an edge pixel is in when it is on a top or a left edge
    winding does not matter

-- and the colour rule from R6c: a vertex word r | g<<8 | b<<16 | a<<24 leaves
the pixel a<<24 | r<<16 | g<<8 | b.

It reads the same transcript the judge does, but it reads it with its own
parser, and it prints a count the judge also prints so the two can be compared
by eye as well as by exit code.
"""

import os
import re
import struct
import sys
from fractions import Fraction as Fr

W = H = 64


def f32(u):
    return struct.unpack('<f', struct.pack('<I', u & 0xffffffff))[0]


def read(path):
    """(triangles, pixels, texture) -- a parser of its own, deliberately.

    A vertex is five words, or SEVEN when the triangle is textured, and the two
    extra are s and t.  This tells them apart by the length of the line, which
    is a different discriminator from the judge's (it reads the width off the
    -sent line); if the library ever logged a shape neither expects, the two
    would not fail in the same way."""
    blocks, tris, px, rows = [], None, {}, {}
    for ln in open(path, errors='replace'):
        f = ln.split()
        if len(f) >= 6 and f[0] == 'RDNTRI' and f[2].endswith('-sent'):
            if tris is not None:
                blocks.append(tris)
            tris = []
            continue
        if tris is None:
            tris = []
        if len(f) in (19, 25) and f[0] == 'RDNTRI' and f[2] == 'tri':
            w = [int(x, 16) for x in f[4:]]
            n = (len(f) - 4) // 3
            cols = tuple(w[i * n + 4] for i in range(3))
            st = None
            if n == 7:
                st = ([f32(w[i * 7 + 5]) for i in range(3)],
                      [f32(w[i * 7 + 6]) for i in range(3)])
            # M1i: word 2 is the vertex z (the constant 1.0 until M1h)
            zs = [f32(w[i * n + 2]) for i in range(3)]
            tris.append(([(f32(w[i * n]), f32(w[i * n + 1])) for i in range(3)],
                         cols[0] if cols[0] == cols[1] == cols[2] else cols, st, zs))
        elif len(f) >= 5 and f[0] == 'RDNTRI' and f[2] == 'tex' \
                and f[3].startswith('row='):
            rows[int(f[3][4:])] = [int(x, 16) for x in f[4:]]
        elif len(f) >= 4 and f[0] == 'RDNTRI' and f[1] == 'px':
            px.setdefault(f[2], []).extend(int(x, 16) for x in f[4:])
    if tris is not None:
        blocks.append(tris)
    tris = blocks[-1] if blocks else []
    tex = None
    if rows:
        h = max(rows) + 1
        if sorted(rows) != list(range(h)) or \
                len(set(len(r) for r in rows.values())) != 1:
            raise RuntimeError('the texture rows are ragged or not 0..%d' % (h - 1))
        tex = (len(rows[0]), h, [rows[v] for v in range(h)])
    return tris, px, tex


def snap16(v):
    """to 1/16 of a pixel, truncated -- toward minus infinity, as a fixed-point
    conversion does, not toward zero"""
    n = v * 16.0
    i = int(n)
    if n < 0.0 and float(i) != n:
        i -= 1
    return i


def covered(pts):
    """the set of (x, y) the measured rule fills.  Sixteenths throughout: the
    sample point x+1/2 is 8 sixteenths, which is exact."""
    p = [(snap16(x), snap16(y)) for x, y in pts]
    area = ((p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) -
            (p[2][0] - p[0][0]) * (p[1][1] - p[0][1]))
    if area == 0:
        return set()
    sgn = 1 if area > 0 else -1
    out = set()
    for y in range(H):
        sy = y * 16 + 8
        for x in range(W):
            sx = x * 16 + 8
            inside = True
            for i in range(3):
                ax, ay = p[i]
                bx, by = p[(i + 1) % 3]
                e = ((bx - ax) * (sy - ay) - (by - ay) * (sx - ax)) * sgn
                if e > 0:
                    continue
                if e < 0:
                    inside = False
                    break
                # on the edge: in only if it is a top or a left edge
                dx, dy = (bx - ax) * sgn, (by - ay) * sgn
                if not ((dy == 0 and dx > 0) or dy < 0):
                    inside = False
                    break
            if inside:
                out.add((x, y))
    return out


def gouraud_bytes(pts, vals):
    """rule B, written out here from what R6e-3 confirmed (docs/R6E_PLAN.md 20),
    NOT imported: vertices truncated to 1/16, sample at pixel + 1/2, exact
    barycentric weights; the two weights other than the LEFTMOST vertex's (x
    ties broken by the smaller y) rounded to 1/256 half-to-EVEN, the leftmost
    weight made 1 minus those two; the exact weighted sum floored and clamped.

    Returns {(x, y): byte}."""
    P = [(snap16(x), snap16(y)) for x, y in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if A == 0:
        return {}
    L = min(range(3), key=lambda i: (P[i][0], P[i][1]))
    out = {}
    for (x, y) in sorted(covered(pts)):
        # SIXTEENTHS, like P: the pixel centre x + 1/2 is x*16 + 8 of them, and
        # it is exact.  The first draft wrote the sample in PIXELS while the
        # vertices were in sixteenths and disagreed with the oracle in 1655 of
        # 2208 bytes -- units, not the rule.
        sx, sy = x * 16 + 8, y * 16 + 8
        w1 = Fr((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0), 1) / A
        w2 = Fr((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0), 1) / A
        w = [1 - w1 - w2, w1, w2]
        for i in range(3):
            if i != L:
                # half to even, on the 1/256 grid
                z = w[i] * 256
                fl = z.numerator // z.denominator
                rem = z - fl
                if rem > Fr(1, 2) or (rem == Fr(1, 2) and fl % 2):
                    fl += 1
                w[i] = Fr(fl, 256)
        w[L] = 1 - sum(w[i] for i in range(3) if i != L)
        t = sum(wi * Fr(ci) for wi, ci in zip(w, vals))
        out[(x, y)] = max(0, min(255, t.numerator // t.denominator))
    return out


TEX_EPS = Fr(1, 1024)       # R6h's "far from a texel boundary", written out here


def texel_words(pts, st, tex):
    """{(x, y): word} -- the NEAREST rule, written out here from R6h and R6i:

        s and t interpolated affinely over the 1/16-truncated vertices
        sampled at the PIXEL CENTRE (R6i: 1/2, NOT R6h's uncorrected corner)
        multiplied by the texture size and FLOORED
        wrapped modulo the size (GL_REPEAT, and the prologue's filter says wrap)
        the texel word IS the pixel word -- no byte swap, unlike a vertex colour

    Raises when a sample lands on a texel boundary: which side it falls is the
    hardware's fixed point talking, and nothing here can predict it."""
    w, h, rows = tex
    P = [(snap16(x), snap16(y)) for x, y in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if A == 0:
        return {}
    out = {}
    for (x, y) in sorted(covered(pts)):
        sx, sy = x * 16 + 8, y * 16 + 8
        w1 = Fr((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0), 1) / A
        w2 = Fr((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0), 1) / A
        lam = (1 - w1 - w2, w1, w2)
        fs = sum(l * Fr(v) for l, v in zip(lam, st[0])) * w
        ft = sum(l * Fr(v) for l, v in zip(lam, st[1])) * h
        for f in (fs, ft):
            k = f.numerator // f.denominator
            if f - k <= TEX_EPS or k + 1 - f <= TEX_EPS:
                raise RuntimeError('a sample at (%d,%d) is on a texel boundary '
                                   '(%s)' % (x, y, f))
        out[(x, y)] = rows[(ft.numerator // ft.denominator) % h][
            (fs.numerator // fs.denominator) % w]
    return out


def zvalue(pts, zs, x, y):
    """the integer depth R6f measured for pixel (x, y): the affine plane's
    floor, times 2^16, clamped.  Sixteenths throughout, like covered()."""
    P = [(snap16(a), snap16(b)) for a, b in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if A == 0:
        return 0xffff
    sx, sy = x * 16 + 8, y * 16 + 8
    w1 = Fr((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0), 1) / A
    w2 = Fr((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0), 1) / A
    z = (1 - w1 - w2) * Fr(zs[0]) + w1 * Fr(zs[1]) + w2 * Fr(zs[2])
    v = (z * 65536).numerator // (z * 65536).denominator
    return max(0, min(0xffff, v))


def blend_srcalpha(src, dst):
    """the measured blend, written out again: each term (colour * (F+1)) >> 8,
    truncated, sum clamped; F is the source alpha for the source term and
    255 - alpha for the destination one.  (r, g, b, a) in the card's order."""
    a = src[3]
    out = []
    for i in range(4):
        v = ((src[i] * (a + 1)) >> 8) + ((dst[i] * (256 - a)) >> 8)
        out.append(0 if v < 0 else (255 if v > 255 else v))
    return tuple(out)


def pixel_of(word):
    r, g, b, a = word & 0xff, (word >> 8) & 0xff, (word >> 16) & 0xff, (word >> 24) & 0xff
    return (a << 24) | (r << 16) | (g << 8) | b


def main():
    if '--self-test' in sys.argv:
        # the T1 triangle the R6 ladder measured covers 276 pixels
        n = len(covered([(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]))
        ok = (n == 276)
        print('  %-4s T1 covers %d pixels (the ladder measured 276)'
              % ('ok' if ok else 'FAIL', n))
        # and the colour rule round-trips the way the hook builds it
        want = 0xff0000ff
        vtx = (want & 0xff00ff00) | ((want & 0xff) << 16) | ((want >> 16) & 0xff)
        ok2 = (pixel_of(vtx) == want)
        print('  %-4s a vertex word built by the hook leaves the wanted pixel'
              % ('ok' if ok2 else 'FAIL'))
        # rule B, checked by properties rather than against the oracle: the
        # tool must stay importless on its judging path.
        pts = [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]
        g = gouraud_bytes(pts, (200, 200, 200))
        ok3 = (len(set(g.values())) == 1 and next(iter(g.values())) == 200)
        print('  %-4s three equal vertex values give that value everywhere'
              % ('ok' if ok3 else 'FAIL'))
        g = gouraud_bytes(pts, (255, 0, 0))
        ok4 = (len(g) == 276 and min(g.values()) < 20 and max(g.values()) > 235
               and len(set(g.values())) > 20)
        print('  %-4s a gradient spans the range (%d values, %d..%d)'
              % ('ok' if ok4 else 'FAIL', len(set(g.values())),
                 min(g.values()), max(g.values())))
        # the blend, by properties: alpha 255 is the identity, alpha 0 is the
        # destination, and something between is neither
        d0 = (64, 128, 191, 255)
        ok5 = (blend_srcalpha((255, 0, 0, 255), d0) == (255, 0, 0, 255))
        print('  %-4s source alpha 255 leaves the source untouched' % ('ok' if ok5 else 'FAIL'))
        b = blend_srcalpha((255, 0, 0, 128), d0)
        ok6 = (b != (255, 0, 0, 128) and b != d0)
        print('  %-4s source alpha 128 gives neither the source nor the '
              'destination (%s)' % ('ok' if ok6 else 'FAIL', str(b)))
        # the texture rule, by properties: a constant ST inside one texel gives
        # that texel everywhere; the XA ST spans the map; a boundary is refused
        rows = [[0xff000000 | ((u * 32) << 16) | ((v * 32) << 8) | 0x55
                 for u in range(8)] for v in range(8)]
        tex = (8, 8, rows)
        c = 3.5 / 8.0
        t7 = texel_words(pts, ([c] * 3, [c] * 3), tex)
        ok7 = (len(t7) == 276 and set(t7.values()) == set([rows[3][3]]))
        print('  %-4s a constant ST inside texel (3,3) samples only that texel'
              % ('ok' if ok7 else 'FAIL'))
        t8 = texel_words(pts, ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0]), tex)
        ok8 = (len(t8) == 276 and len(set(t8.values())) == 36 and
               t8[(4, 4)] == rows[0][0])
        print('  %-4s the XA ST spans %d texels and starts at (0,0)'
              % ('ok' if ok8 else 'FAIL', len(set(t8.values()))))
        try:
            texel_words(pts, ([0.125] * 3, [c] * 3), tex)
            ok9 = False
        except RuntimeError:
            ok9 = True
        print('  %-4s a sample on a texel boundary is refused' % ('ok' if ok9 else 'FAIL'))
        # and the texel is NOT byte-swapped, unlike a vertex colour
        ok10 = (pixel_of(rows[1][2]) != rows[1][2] and t7[(10, 10)] == rows[3][3])
        print('  %-4s the texel word goes through unswapped (a vertex colour '
              'would not)' % ('ok' if ok10 else 'FAIL'))
        good = (ok and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8
                and ok9 and ok10)
        print('indep_m1d self-test: %s' % ('PASS' if good else 'FAIL'))
        return 0 if good else 1

    if '--cross-check' in sys.argv:
        #
        # The ONE place this file is allowed to import the oracle.  Two
        # implementations of rule B, written from the same prose and sharing no
        # code, must give the same bytes; that agreement is what makes the
        # recount worth doing.  The judging path above never imports anything.
        #
        # It found a real difference the first time: the sample point was
        # written in pixels while the vertices were in sixteenths, and 1655 of
        # 2208 bytes disagreed.  A recount that had quietly used the oracle
        # would have agreed with itself and said nothing.
        #
        import importlib.util as I
        here = os.path.dirname(os.path.abspath(__file__))
        sp = I.spec_from_file_location(
            'gouraud_oracle', os.path.join(here, '..', '..', 'tools', 'r6',
                                           'gouraud_oracle.py'))
        go = I.module_from_spec(sp)
        sys.modules['gouraud_oracle'] = go
        sp.loader.exec_module(go)
        pts = [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]
        tot = bad = 0
        for vals in ((255, 16, 64), (64, 255, 32), (32, 128, 255), (255, 170, 85),
                     (0, 0, 0), (255, 255, 255), (1, 2, 3), (200, 7, 99)):
            a = go.rule_b(pts, vals, 'even')
            mine = gouraud_bytes(pts, vals)
            for (x, y), v in zip(go.covered(pts), a):
                tot += 1
                if mine[(x, y)] != v:
                    bad += 1
        print('  %-4s %d bytes of rule B, two independent implementations, %d differ'
              % ('ok' if bad == 0 else 'FAIL', tot, bad))

        # and the same for the NEAREST rule, against R6i's own oracle on the
        # cases R6i measured.  Three implementations of it now exist -- this
        # one, the judge's, and the oracle's -- and all three have to agree
        # before a textured picture is called right.
        sp = I.spec_from_file_location(
            'persp_oracle', os.path.join(here, '..', '..', 'tools', 'r6',
                                         'persp_oracle.py'))
        po = I.module_from_spec(sp)
        sys.modules['persp_oracle'] = po
        sp.loader.exec_module(po)
        tot2 = bad2 = 0
        for case in po.TEX_ORDER:
            w, h = po.tex_of(case)[0], po.tex_of(case)[1]
            rows = [[po.sampled(case, u, v) for u in range(w)] for v in range(h)]
            g = po.geom_of(case)
            try:
                mine = texel_words(g, po.st_of(case), (w, h, rows))
            except RuntimeError:
                continue            # the oracle's own DELTA throws these out too
            for p, (word, safe) in po.nearest_map(
                    case, ('A', po.MEASURED_OFF, None)).items():
                if not safe or p not in mine:
                    continue
                tot2 += 1
                if mine[p] != word:
                    bad2 += 1
        okt = (bad2 == 0 and tot2 > 200)
        print('  %-4s %d textured samples, this file against persp_oracle, %d differ'
              % ('ok' if okt else 'FAIL', tot2, bad2))
        good = (bad == 0 and okt)
        print('indep_m1d cross-check: %s' % ('PASS' if good else 'FAIL'))
        return 0 if good else 1

    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    d = sys.argv[1]
    blend = dmode = 0
    for ln in open(os.path.join(d, 't-accel.out'), errors='replace'):
        f = ln.split()
        if len(f) >= 4 and f[0] == 'RDNTRI' and f[2] == 'step=mode':
            for kv in f[3:]:
                if kv.startswith('blend='):
                    blend = int(kv.split('=')[1])
                elif kv.startswith('depth='):
                    dmode = int(kv.split('=')[1])
    tris, px, tex = read(os.path.join(d, 't-accel.out'))
    if not tris:
        print('indep_m1d: FAIL (no sent triangles in the transcript)')
        return 1
    got = px.get('draw', [])
    if len(got) != W * H:
        print('indep_m1d: FAIL (%d pixels, want %d)' % (len(got), W * H))
        return 1

    # the destination, read out of the picture where nothing was drawn
    dst = None
    if blend:
        allcov = set()
        for pts, _c, _st, _z in tris:
            allcov |= covered(pts)
        vals = set(got[y * W + x] for y in range(H) for x in range(W)
                   if (x, y) not in allcov)
        if len(vals) != 1:
            print('indep_m1d: FAIL (the uncovered pixels are %d colours, so the '
                  'destination cannot be read)' % len(vals))
            return 1
        w = vals.pop()
        dst = ((w >> 16) & 0xff, (w >> 8) & 0xff, w & 0xff, (w >> 24) & 0xff)
        print('  destination read from the picture: %08x' % w)

    #
    # BUILD THE PICTURE, THEN COMPARE ONCE.
    #
    # M1h draws triangles that OVERLAP, and the later one wins.  Comparing each
    # triangle against the buffer as it goes calls every overwritten pixel
    # wrong -- the first version did, and would have failed a correct run.
    #
    pred = {}
    zbuf = {}
    if dmode:
        for y in range(H):
            for x in range(W):
                zbuf[(x, y)] = 0xffff          # glClearDepth(1.0), R6f's floor rule
    bad = 0
    total = 0
    for pts, col, st, zs in tris:
        if dmode:
            # GL_LESS with the write on, written out here from R6f and R6g:
            # the buffer holds floor(z * 2^16) clamped, the compare is on that
            # integer, and a pixel that passes becomes the new value.
            keep = set()
            for (x, y) in covered(pts):
                v = zvalue(pts, zs, x, y)
                if v < zbuf[(x, y)]:
                    zbuf[(x, y)] = v
                    keep.add((x, y))
        else:
            keep = None
        if st is not None:
            # textured: the texel decides the pixel and the vertex colour never
            # reaches the buffer
            if tex is None:
                print('indep_m1d: FAIL (a textured triangle, but the transcript '
                      'carries no texture rows)')
                return 1
            try:
                tw = texel_words(pts, st, tex)
            except RuntimeError as e:
                print('indep_m1d: FAIL (%s)' % e)
                return 1
            for (x, y), word in sorted(tw.items()):
                if keep is not None and (x, y) not in keep:
                    continue
                if dst is not None:
                    rgba = ((word >> 16) & 0xff, (word >> 8) & 0xff,
                            word & 0xff, (word >> 24) & 0xff)
                    rgba = blend_srcalpha(rgba, dst)
                    word = ((rgba[3] << 24) | (rgba[0] << 16) |
                            (rgba[1] << 8) | rgba[2])
                pred[(x, y)] = word
            continue
        if isinstance(col, tuple):
            # Gouraud: each card channel on its own, then assembled the way a
            # flat pixel is (a<<24 | r<<16 | g<<8 | b)
            planes = [gouraud_bytes(pts, tuple((c >> sh) & 0xff for c in col))
                      for sh in (0, 8, 16, 24)]
            for (x, y) in sorted(covered(pts)):
                if keep is not None and (x, y) not in keep:
                    continue
                rgba = (planes[0][(x, y)], planes[1][(x, y)],
                        planes[2][(x, y)], planes[3][(x, y)])
                if dst is not None:
                    rgba = blend_srcalpha(rgba, dst)
                pred[(x, y)] = ((rgba[3] << 24) | (rgba[0] << 16) |
                                (rgba[1] << 8) | rgba[2])
            continue
        if dst is None:
            want = pixel_of(col)
        else:
            rgba = (col & 0xff, (col >> 8) & 0xff, (col >> 16) & 0xff,
                    (col >> 24) & 0xff)
            rgba = blend_srcalpha(rgba, dst)
            want = (rgba[3] << 24) | (rgba[0] << 16) | (rgba[1] << 8) | rgba[2]
        for (x, y) in covered(pts):
            if keep is not None and (x, y) not in keep:
                continue
            pred[(x, y)] = want
    # now, once, against the picture
    for (x, y) in sorted(pred):
        total += 1
        if got[y * W + x] != pred[(x, y)]:
            if bad < 3:
                print('  differs at (%d,%d): %08x, want %08x'
                      % (x, y, got[y * W + x], pred[(x, y)]))
            bad += 1
    #
    # M1k: THE BATCH, counted again from the transcript, with this file's own
    # parser.  The judge reads the same line; the point of doing it twice is
    # that neither reading can be the only one.
    #
    bat = {}
    sub = None
    for ln in open(os.path.join(d, 't-accel.out'), errors='replace'):
        f = ln.split()
        if len(f) < 4 or f[0] != 'RDNTRI':
            continue
        if f[2] == 'step=end-batch':
            for kv in f[3:]:
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    if v.isdigit():
                        bat[k] = int(v)
        elif f[2] == 'step=end-tri':
            for kv in f[3:]:
                if kv.startswith('submitted='):
                    sub = int(kv.split('=')[1])
    if not bat:
        print('indep_m1d: FAIL (the transcript has no end-batch line)')
        return 1
    bbad = 0
    if bat.get('adds') != bat.get('flushed', 0) + bat.get('replayed', 0):
        print('  batch: %s went in, %s came out and %s were replayed'
              % (bat.get('adds'), bat.get('flushed'), bat.get('replayed')))
        bbad += 1
    for k in ('desync', 'outside'):
        if bat.get(k, 1) != 0:
            print('  batch: %s = %s, want 0' % (k, bat.get(k)))
            bbad += 1
    if bat.get('flushes') != bat.get('tflushes'):
        print('  batch: the two sides counted %s and %s flushes'
              % (bat.get('flushes'), bat.get('tflushes')))
        bbad += 1
    if sub is not None and len(tris) > 1 and bat.get('flushes', 0) >= sub:
        print('  batch: %d triangles in %s submissions -- nothing was batched'
              % (sub, bat.get('flushes')))
        bbad += 1
    print('indep_m1d: batch %s adds, %s flushes, %s replayed -- %s'
          % (bat.get('adds'), bat.get('flushes'), bat.get('replayed'),
             'consistent' if bbad == 0 else '%d PROBLEM(S)' % bbad))

    print('indep_m1d: %d triangles, %d pixels recounted, %d differ'
          % (len(tris), total, bad))
    good = (bad == 0 and total > 50 and bbad == 0)
    print('indep_m1d: %s' % ('PASS' if good else 'FAIL'))
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(main())
