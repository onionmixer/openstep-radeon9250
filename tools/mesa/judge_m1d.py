#!/usr/bin/env python3
"""The triangle path's approval run, judged as one transcript (M1d, and M1e).

  judge_m1d.py <build dir>       expects t-accel.out and t-stock.out
  judge_m1d.py --self-test

Two things are judged, and they are different in kind.

THE COUNTERS say whether the right thing happened: our function went in for the
one state M1d takes, stayed out of the three it does not, was actually CALLED
when it went in, and handed every triangle it could not send to the software
function it saved.  These are read as CHANGES between steps, because absolute
counts break whenever a step is added while the property they stand for still
holds (the lesson M1c's judge records).

THE PICTURE is judged against tools/r6/tri_oracle.py's cover(pts, MEASURED) --
the rasterisation rule the R6 ladder measured -- and NOT against the software
picture.  M1c could demand pixel identity because it only moved where software
drew; M1d replaces the rasteriser, and the card's fill rule (1/16 truncation,
sample at pixel centre, top-left) has no reason to agree with tritemp.h's at the
edges.  Demanding identity there would report a working run as a failure.  The
difference from software is measured and reported instead, and only an INSIDE
pixel differing is an error.

The vertices are read out of the transcript -- what the library actually sent --
rather than taken from what the test meant to draw: the window coordinates come
out of a Mesa transform this side does not reproduce.
"""

import shutil
import atexit
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.join(HERE, '..', '..')

W = H = 64


def _load(name, rel):
    import importlib.util as I
    sp = I.spec_from_file_location(name, os.path.join(PROJ, *rel))
    m = I.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


def oracle():
    return _load('tri_oracle', ('tools', 'r6', 'tri_oracle.py'))


def persp():
    """R6i's oracle.  M1g needs one number out of it, MEASURED_OFF, and needs it
    from HERE rather than from tex_oracle: R6h could not separate the sample
    position (an affine ST only moves the texel at a boundary, and those pixels
    are the unsafe ones), so tex_oracle.MEASURED still carries the corner it
    guessed.  R6i put a perspective divide on the same triangle, which does
    separate them, and measured the PIXEL CENTRE (docs/R6I_PLAN.md 199, boot
    ff78c18a).  Reading the superseded constant would move every sample half a
    pixel -- and on a slow ST that is invisible until it is not."""
    return _load('persp_oracle', ('tools', 'r6', 'persp_oracle.py'))


def depth_oracle():
    """R6f's oracle.  M1i needs two things from it: the z -> integer conversion
    (floor(z * 2^n), NOT Mesa's d * 0xffff -- the two differ and using Mesa's
    would mispredict every tie) and the fact that interpolation is the floor of
    the affine plane."""
    return _load('depth_oracle', ('tools', 'r6', 'depth_oracle.py'))


def gouraud():
    """R6e's oracle.  rule_b with 'even' is the rule boot fecbb2af confirmed over
    3310 bytes (docs/R6E_PLAN.md 20); M1e does not re-measure it, it checks that
    the card still follows it when Mesa is the one choosing the colours."""
    return _load('gouraud_oracle', ('tools', 'r6', 'gouraud_oracle.py'))


def f32(u):
    """the float those 32 bits are"""
    return struct.unpack('<f', struct.pack('<I', u & 0xffffffff))[0]


def lines(path):
    return open(path, errors='replace').read().split('\n')


def counters(path):
    """{step: {...}} from the three per-step lines"""
    out = {}
    order = []
    for ln in lines(path):
        m = re.match(r'RDNTRI run=\S+ step=(\S+) installs=(\d+) leaves=(\d+) triangles=(\d+) '
                     r'delegated=(\d+) nosw=(\d+) notbound=(\d+) slotsfull=(\d+) '
                     r'caps=([0-9a-f]+) shade=([0-9a-f]+)'
                     r'(?: tex=(\d+) texup=(\d+) texbad=(\d+) texproj=(\d+))?'
                     r'(?: rmask=([0-9a-f]+))?'
                     r'(?: zclear=(\d+) zclearbad=(\d+))?'
                     r'(?: cli=(\d+) clc=(\d+) clp=(\d+))?', ln)
        if m:
            step = m.group(1)
            out.setdefault(step, {}).update(
                installs=int(m.group(2)), leaves=int(m.group(3)),
                triangles=int(m.group(4)), delegated=int(m.group(5)),
                nosw=int(m.group(6)), notbound=int(m.group(7)),
                slotsfull=int(m.group(8)),
                caps=int(m.group(9), 16), shade=int(m.group(10), 16))
            if m.group(11) is not None:
                out[step].update(tex=int(m.group(11)), texup=int(m.group(12)),
                                 texbad=int(m.group(13)),
                                 texproj=int(m.group(14)))
            if m.group(15) is not None:
                out[step]['rmask'] = int(m.group(15), 16)
            if m.group(16) is not None:
                out[step].update(zclear=int(m.group(16)),
                                 zclearbad=int(m.group(17)))
            if m.group(18) is not None:
                out[step].update(cli=int(m.group(18)), clc=int(m.group(19)),
                                 clp=int(m.group(20)))
            if step not in order:
                order.append(step)
            continue
        m = re.match(r'RDNTRI run=\S+ step=(\S+)-tri entered=(\d+) submitted=(\d+) maps=(\d+) '
                     r'opens=(\d+) words=(\d+) seed=(\d+) smoothsent=(\d+) '
                     r'blendsent=(\d+)(?: texsent=(\d+))?(?: depthsent=(\d+))? '
                     r'why=(\d+) at=(\d+) word=([0-9a-f]+) status=(\d+)', ln)
        if m:
            out.setdefault(m.group(1), {}).update(
                entered=int(m.group(2)), submitted=int(m.group(3)), maps=int(m.group(4)),
                opens=int(m.group(5)), words=int(m.group(6)), seed=int(m.group(7)),
                smoothsent=int(m.group(8)), blendsent=int(m.group(9)),
                why=int(m.group(12)), at=int(m.group(13)),
                word=int(m.group(14), 16), status=int(m.group(15)))
            if m.group(10) is not None:
                out[m.group(1)]['texsent'] = int(m.group(10))
            if m.group(11) is not None:
                out[m.group(1)]['depthsent'] = int(m.group(11))
            continue
        # M1k's own line.  Its own shape on purpose: folding these into the -tri
        # line would have made a judge written for the old shape stop matching
        # it, and a judge that matches nothing reports nothing.
        m = re.match(r'RDNTRI run=\S+ step=(\S+)-batch adds=(\d+) flushes=(\d+) '
                     r'flushed=(\d+) failed=(\d+) replayed=(\d+) outside=(\d+) '
                     r'flushout=(\d+) desync=(\d+) rs=(\d+) rf=(\d+) rinst=(\d+) '
                     r'tbatched=(\d+) tflushes=(\d+) tfailed=(\d+)', ln)
        if m:
            out.setdefault(m.group(1), {}).update(
                badds=int(m.group(2)), bflushes=int(m.group(3)),
                bflushed=int(m.group(4)), bfailed=int(m.group(5)),
                breplayed=int(m.group(6)), boutside=int(m.group(7)),
                bflushout=int(m.group(8)), bdesync=int(m.group(9)),
                brs=int(m.group(10)), brf=int(m.group(11)),
                brinst=int(m.group(12)), tbatched=int(m.group(13)),
                tflushes=int(m.group(14)), tfailed=int(m.group(15)))
            continue
        # the refusal line ends in SUM=, which is what makes it distinguishable
        # from the counter line of the same step (the bug M1c's judge had)
        m = re.match(r'RDNTRI run=\S+ step=(\S+)-refused (.*) SUM=(\d+)\s*$', ln)
        if m:
            out.setdefault(m.group(1), {})['sum'] = int(m.group(3))
            out[m.group(1)]['refused'] = dict(
                (kv.split('=')[0], int(kv.split('=')[1])) for kv in m.group(2).split())
            continue
        m = re.match(r'RDNTRI run=\S+ step=(\S+)-why (.*)$', ln)
        if m:
            out.setdefault(m.group(1), {})['whyname'] = dict(
                (kv.split('=')[0], int(kv.split('=')[1])) for kv in m.group(2).split())
    return out, order


def sent(path):
    """[(k, pts, cols, st)] for each triangle the library reported sending.

    Five words a vertex normally; SEVEN when a texture is on, and the two extra
    are s and t.  The log line carries the widest shape with the unused words
    zeroed, and the `words=` field of the -sent line says which it is -- reading
    the width from the LINE rather than assuming it is what keeps a textured
    triangle from being decoded as one and a half plain ones."""
    #
    # THE RING IS DUMPED MORE THAN ONCE (at `draw` and again at `end`) and it is
    # CUMULATIVE, so the two blocks hold the same triangles.  M1d could ignore
    # that -- one triangle twice predicts the same picture -- but M1h counts
    # them, and six would not be three.  Only the LAST block is returned, and
    # with it the library's own total `n`, which is what `submitted` is compared
    # against.
    #
    blocks, cur, vw, nsent = [], None, 15, 0
    for ln in lines(path):
        m = re.match(r'RDNTRI run=\S+ step=\S+-sent n=(\d+) kept=\d+ words=(\d+)', ln)
        if m:
            if cur is not None:
                blocks.append((cur, nsent))
            cur, nsent, vw = [], int(m.group(1)), int(m.group(2))
            continue
        out = cur if cur is not None else None
        if out is None:
            continue
        m = re.match(r'RDNTRI run=\S+ tri (\d+)((?: [0-9a-f]{8})+)\s*$', ln)
        if m:
            w = [int(x, 16) for x in m.group(2).split()]
            n = vw // 3
            if n not in (5, 7) or len(w) < 3 * n:
                continue
            pts = [(f32(w[i * n]), f32(w[i * n + 1])) for i in range(3)]
            # M1i: word 2 is the vertex z.  It was the constant 1.0 up to M1h --
            # depth was off and it could not matter -- and it is read here now
            # so the judge predicts from what was SENT, not from the mode flag.
            zs = [f32(w[i * n + 2]) for i in range(3)]
            cols = [w[i * n + 4] for i in range(3)]
            st = None
            if n == 7:
                st = ([f32(w[i * 7 + 5]) for i in range(3)],
                      [f32(w[i * 7 + 6]) for i in range(3)])
            out.append((int(m.group(1)), pts, cols, st, zs))
    if cur is not None:
        blocks.append((cur, nsent))
    if not blocks:
        return [], 0
    return blocks[-1]


def pixels(path):
    out = {}
    for ln in lines(path):
        m = re.match(r'RDNTRI px (\w+) (\d+)((?: [0-9a-f]{8})+)\s*$', ln)
        if m:
            out.setdefault(m.group(1), []).extend(int(x, 16) for x in m.group(3).split())
    return out


def tex_image(path):
    """(w, h, rows) of the texture the test says it uploaded, or None.

    The texels are NOT in the CP stream -- they go into the window by store, so
    the only way to judge the picture against them is for the test to say what
    it wrote.  It prints the image back out of its own array AFTER the upload
    unit read it back from the card, so a row that never reached video memory
    cannot be the row this predicts with."""
    rows, w = {}, None
    for ln in lines(path):
        m = re.match(r'RDNTRI run=\S+ tex row=(\d+)((?: [0-9a-f]{8})+)\s*$', ln)
        if m:
            r = [int(x, 16) for x in m.group(2).split()]
            if w is None:
                w = len(r)
            elif len(r) != w:
                raise RuntimeError('texture row %s is %d words, row 0 was %d'
                                   % (m.group(1), len(r), w))
            rows[int(m.group(1))] = r
    if not rows:
        return None
    h = max(rows) + 1
    if sorted(rows) != list(range(h)):
        raise RuntimeError('the texture rows in the transcript are %s, not 0..%d'
                           % (sorted(rows), h - 1))
    return (w, h, [rows[v] for v in range(h)])


def texel_at(go, po, pts, st, tex, cov):
    """{(x, y): (pixel word, margin)} -- R6h/R6i's NEAREST rule on one triangle.

    s and t are interpolated affinely (w = 1 everywhere this rung) over the
    1/16-truncated vertices, sampled at pixel + MEASURED_OFF, scaled by the
    texture size, floored, and wrapped.  The texel word IS the pixel word: R6h
    measured zero byte swaps on this path, unlike the vertex colour, which the
    interpolator hands back with bytes 0 and 2 exchanged (M1d).

    `margin` is how far the sample is from the nearest texel boundary, in
    texels; the caller decides what it is willing to predict."""
    from fractions import Fraction as Fr
    import math
    off = po.MEASURED_OFF
    if off != Fr(1, 2):
        raise RuntimeError('persp_oracle.MEASURED_OFF is %s, not 1/2 -- the '
                           'measured sample position changed and this rung was '
                           'written against the pixel centre' % off)
    w, h, rows = tex
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if A == 0:
        raise RuntimeError('the textured triangle %s is degenerate' % (pts,))
    ss = [Fr(v) for v in st[0]]
    tt = [Fr(v) for v in st[1]]
    out = {}
    for y in range(H):
        for x in range(W):
            if not cov[y][x]:
                continue
            sx, sy = Fr(x) + off, Fr(y) + off
            l1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
            l2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
            l0 = 1 - l1 - l2
            fs = (l0 * ss[0] + l1 * ss[1] + l2 * ss[2]) * w
            ft = (l0 * tt[0] + l1 * tt[1] + l2 * tt[2]) * h
            m = min(fs - math.floor(fs), math.floor(fs) + 1 - fs,
                    ft - math.floor(ft), math.floor(ft) + 1 - ft)
            u, v = math.floor(fs) % w, math.floor(ft) % h
            out[(x, y)] = (rows[v][u], m)
    return out


def blend_over(src, dst):
    """R6j's measured blend, SRC_ALPHA / ONE_MINUS_SRC_ALPHA / ADD_CLAMP:
    each term is (colour * (factor + 1)) >> 8, TRUNCATED, and the sum is
    clamped ([[r200-blend-factor-plus-one]], docs/R6J_PLAN.md).  src and dst are
    (r, g, b, a) in the CARD's channel order."""
    a = src[3]
    return tuple(max(0, min(255, ((src[i] * (a + 1)) >> 8) +
                                 ((dst[i] * ((255 - a) + 1)) >> 8)))
                 for i in range(4))


def depth_at(go, do, pts, zs):
    """{(x, y): integer depth} -- R6f's rule on one triangle.

    The z of each vertex is interpolated affinely over the 1/16-truncated
    vertices at the pixel centre, and the buffer value is floor(z * 2^16)
    clamped.  R6f measured BOTH halves: the conversion (the anchors separated
    148 equivalence classes) and that the interpolation is the plane's floor."""
    from fractions import Fraction as Fr
    import math
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if A == 0:
        return {}
    out = {}
    for y in range(H):
        for x in range(W):
            sx, sy = Fr(x) + Fr(1, 2), Fr(y) + Fr(1, 2)
            w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
            w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
            z = (1 - w1 - w2) * Fr(zs[0]) + w1 * Fr(zs[1]) + w2 * Fr(zs[2])
            v = int(math.floor(z * 65536))
            out[(x, y)] = max(0, min(0xffff, v))
    return out


def predict(to, tris, dstWord=None, tex=None, dmode=0, zfar=0xffff):
    """(picture, margin) -- what the MEASURED rules say those triangles leave.

    -1 is a pixel no triangle covered.  `margin` is None unless a texture was
    sampled, and then it is the closest any sample came to a texel boundary, in
    texels: the caller needs it to know whether SOFTWARE had to agree.

    Flat and Gouraud are told apart by the DATA, not by a flag: three equal
    vertex colours can only be flat, and three unequal ones can only be smooth.
    Reading it from the words that were sent means a wrongly-labelled run cannot
    be judged against the rule it claimed rather than the one it used."""
    import numpy as np
    img = np.full((H, W), -1, np.int64)
    go = po = None
    margin = None
    #
    # M1i.  The depth buffer the card tests against, as the prediction sees it:
    # cleared to `zfar`, then written where a triangle passes.  Kept HERE rather
    # than per triangle because that is the whole point of the rung -- what one
    # submission wrote, the next one must see.
    #
    zbuf = np.full((H, W), zfar, np.int64) if dmode else None
    zdo = depth_oracle() if dmode else None
    # M1f: when blending is on, the destination is whatever was already in the
    # surface -- the software clear.  It is READ OUT OF THE PICTURE (a pixel the
    # triangle does not cover), not assumed, so a clear that did not happen
    # shows up as a wrong prediction rather than as a lucky one.
    dst = None
    if dstWord is not None:
        dst = ((dstWord >> 16) & 0xff, (dstWord >> 8) & 0xff,
               dstWord & 0xff, (dstWord >> 24) & 0xff)
    for _k, pts, cols, st, zs in tris:
        cov = to.cover(pts, to.MEASURED, W)
        if dmode:
            # GL_LESS with the write on: a pixel is drawn when its depth is
            # strictly less than what is there, and then it becomes what is
            # there.  The compare is on the INTEGER that lands in the buffer
            # (R6g measured that, with z * 2^16 = 32768.5 as the separator).
            if go is None:
                go = gouraud()
            zt = depth_at(go, zdo, pts, zs)
            passed = np.zeros((H, W), bool)
            for (x, y), v in zt.items():
                if cov[y][x] and v < zbuf[y][x]:
                    passed[y][x] = True
                    zbuf[y][x] = v
            cov = cov & passed
        if st is not None:
            # M1g.  The texture decides the pixel on its own: the prologue's
            # stage 0 is out = R0 * (1 - 0) + 0 (tex_oracle.blend_texture), so
            # the vertex colour does not reach the buffer and the flat/Gouraud
            # question below does not arise.  Keyed on the ST being THERE rather
            # than on a flag, for the same reason as the colours: what was sent
            # decides what it is judged as.
            if tex is None:
                raise RuntimeError('a textured triangle was sent but the transcript '
                                   'carries no texture rows to predict it with')
            if go is None:
                go = gouraud()
            if po is None:
                po = persp()
            for (x, y), (word, m) in texel_at(go, po, pts, st, tex, cov).items():
                if margin is None or m < margin:
                    margin = m
                rgba = ((word >> 16) & 0xff, (word >> 8) & 0xff,
                        word & 0xff, (word >> 24) & 0xff)
                if dst is not None:
                    r, g, b, a = blend_over(rgba, dst)
                    word = (a << 24) | (r << 16) | (g << 8) | b
                img[y][x] = word
            continue
        if cols[0] == cols[1] == cols[2]:
            # R6c: a vertex word r | g<<8 | b<<16 | a<<24 leaves a<<24|r<<16|g<<8|b
            c = cols[0]
            rgba = (c & 0xff, (c >> 8) & 0xff, (c >> 16) & 0xff, (c >> 24) & 0xff)
            if dst is not None:
                rgba = blend_over(rgba, dst)
            img = np.where(cov, to.pixel(rgba), img)
            continue
        # Gouraud: each channel interpolated on its own by R6e's rule B, then
        # assembled the same way a flat pixel is.
        if go is None:
            go = gouraud()
        #
        # R6e's oracle only ever looked at the colour buffer's top-left 32 x 32
        # (gouraud_oracle.covered is hard-wired to 32, tri_oracle.MAPW), so its
        # rule_b returns bytes for THAT window and no other.  A triangle poking
        # outside it would be predicted over the wrong pixel set -- measured:
        # for (34,36)(58,40)(38,59) the two oracles say 268 pixels and 0.
        # Refuse loudly rather than judge a picture against a mask that is not
        # the one it was drawn under.
        #
        where = go.covered(pts)
        outside = [(int(x), int(y)) for y in range(H) for x in range(W)
                   if cov[y][x] and (x >= 32 or y >= 32)]
        if outside or set(where) != set((int(x), int(y)) for y in range(32)
                                        for x in range(32) if cov[y][x]):
            raise RuntimeError('the Gouraud triangle %s reaches outside the 32 x 32 '
                               'window R6e measured (%d pixels outside); the oracle '
                               'cannot predict it' % (pts, len(outside)))
        planes = []
        for sh in (0, 8, 16, 24):            # card r, g, b, a
            planes.append(go.rule_b(pts, tuple((c >> sh) & 0xff for c in cols), 'even'))
        for j, (x, y) in enumerate(where):
            rgba = (planes[0][j], planes[1][j], planes[2][j], planes[3][j])
            if dst is not None:
                rgba = blend_over(rgba, dst)
            r, g, b, a = rgba
            img[y][x] = (a << 24) | (r << 16) | (g << 8) | b
    if margin is not None:
        # R6h judged only the samples it could place: within DELTA of a texel
        # boundary the hardware's own fixed point decides which side, and the
        # exact rational here does not know.  The test picks an ST that keeps
        # clear of them, so a small margin is a broken TEST, not a soft pass --
        # say so instead of predicting.
        from fractions import Fraction as Fr
        if margin <= po.DELTA:
            raise RuntimeError('a textured sample lands %s of a texel from a '
                               'boundary (the oracle needs more than %s); the '
                               'test\'s ST is not judgeable'
                               % (margin, po.DELTA))
    return img, margin


def judge(d):
    ok, bad, note = [], [], []
    ap = os.path.join(d, 't-accel.out')
    sp = os.path.join(d, 't-stock.out')
    if not os.path.exists(ap):
        return [], ['no t-accel.out in %s' % d], []

    c, order = counters(ap)
    tris, nsent = sent(ap)
    px = pixels(ap)
    mode = None
    bmode = tmode = dmode = 0
    want_tris = None
    for ln in lines(ap):
        m = re.match(r'RDNTRI run=\S+ step=mode smooth=(\d+)(?: blend=(\d+))?'
                     r'(?: tex=(\d+))?(?: multi=\d+ tris=(\d+))?'
                     r'(?: depth=(\d+))?', ln)
        if m:
            mode = int(m.group(1))
            bmode = int(m.group(2)) if m.group(2) else 0
            tmode = int(m.group(3)) if m.group(3) else 0
            if m.group(4) is not None:
                want_tris = int(m.group(4))
            if m.group(5) is not None:
                dmode = int(m.group(5))
    if mode is None:
        bad.append('the transcript does not say which mode it ran')

    def delta(step, field):
        if step not in order:
            return None
        i = order.index(step)
        prev = c[order[i - 1]].get(field, 0) if i > 0 else 0
        return c[step].get(field, 0) - prev

    # ---- 1. the state M1d takes
    for field, what in (('installs', 'our triangle function went in'),
                        ('triangles', 'and was actually CALLED'),
                        ('submitted', 'and a triangle reached the ring')):
        v = delta('draw', field)
        if v is None:
            bad.append('the transcript has no "draw" step')
        elif v < 1:
            bad.append('draw: %s did not change (%s)' % (field, what))
        else:
            ok.append('draw %-10s +%d -- %s' % (field, v, what))
    # A seed of 1 means the environment never reached the library, and the
    # kernel refuses a repeat -- so the run would work once per boot and then
    # look like an unexplained refusal (measured, boot ed7bef6a).
    sd = c.get('draw', {}).get('seed')
    if sd is not None and sd <= 1:
        bad.append('the seed was %s: RDNMesaSeed did not reach the library, and a '
                   'repeat is refused with no reason the library can see' % sd)
    elif sd is not None:
        ok.append('the seed was %d, from the environment' % sd)

    #
    # HOW MANY REACHED THE RING.
    #
    # M1d could only claim ONE: the driver refused a client submission with no
    # ZPREP since the last, and the runner can issue a ZPREP only before the
    # process starts.  M1h lifted that (docs/M1H_PLAN.md 7), so the claim is no
    # longer a constant -- it is an EQUALITY: every triangle the library says it
    # sent reached the ring, and no others did.
    #
    # `nsent` is the library's own count, off the last -sent line.  Comparing the
    # driver's counter against the library's own number is the point: a run where
    # the card took some and dropped some is exactly what this rung could break.
    #
    v = delta('draw', 'submitted')
    if v is None or nsent == 0:
        pass
    elif v != nsent:
        bad.append('draw: %d triangles reached the ring, but the library says it sent '
                   '%d -- the difference never drew' % (v, nsent))
    else:
        ok.append('submitted +%d == the %d the library sent' % (v, nsent))
    #
    # AND THE NUMBER THE TEST MEANT TO DRAW.  Without this the chain proves only
    # that the library and the driver agree with EACH OTHER: a scene whose third
    # triangle never reached the library at all would satisfy both and lose a
    # triangle silently.  The test prints what it drew; this closes the loop.
    #
    if want_tris is not None and nsent:
        if nsent != want_tris:
            bad.append('the test drew %d triangles but the library sent %d'
                       % (want_tris, nsent))
        else:
            ok.append('the test drew %d and the library sent %d -- the scene, the '
                      'library and the driver all agree' % (want_tris, nsent))
    #
    # M1k: AND THEY RODE TOGETHER.
    #
    # Every gate above is satisfied by a library that batches nothing: one
    # triangle per submission still makes submitted == sent == drawn.  This is
    # the one that is not -- for a scene with more than one triangle, the
    # submissions must be FEWER than the triangles, or this rung did nothing.
    #
    fl = delta('draw', 'bflushes')
    sub = delta('draw', 'submitted')
    if want_tris is None or fl is None or sub is None:
        pass
    elif want_tris < 2:
        ok.append('one triangle in this scene -- nothing to batch, so no claim')
    elif fl >= sub:
        bad.append('%d triangles went to the card in %d submissions: the batch '
                   'did not happen' % (sub, fl))
    else:
        ok.append('%d triangles went to the card in %d submission(s) -- the batch '
                  'happened' % (sub, fl))
    v = delta('draw', 'delegated')
    if v is None:
        pass
    elif v != 0:
        bad.append('draw: %d triangles were delegated -- the state this mode is '
                   'about should not need the fallback' % v)
    else:
        ok.append('draw delegated +0 -- nothing had to fall back')

    # M1e: the shade value that went out matches the mode the run was told
    sm = delta('draw', 'smoothsent')
    if sm is None or mode is None:
        pass
    elif mode and sm != 1:
        bad.append('smooth mode, but %d submissions carried the Gouraud shade value; '
                   'the card would have flat-shaded it' % sm)
    elif not mode and sm != 0:
        bad.append('flat mode, but %d submissions carried the Gouraud shade value' % sm)
    else:
        ok.append('mode=%s and smoothSent +%d -- the shade control matches the run'
                  % ('smooth' if mode else 'flat', sm))

    # M1f: the blend unit that went out matches the mode the run was told
    bs = delta('draw', 'blendsent')
    if bs is None:
        pass
    elif bmode and bs != 1:
        bad.append('blend mode, but %d submissions switched the blend unit on' % bs)
    elif not bmode and bs != 0:
        bad.append('no-blend mode, but %d submissions switched the blend unit on' % bs)
    else:
        ok.append('blend=%d and blendSent +%d -- the blend unit matches the run'
                  % (bmode, bs))

    # M1g: the texture unit, the same way -- what went out against what the run
    # was told to do, and the upload against the read-back the unit did itself
    ts = delta('draw', 'texsent')
    if ts is None:
        if tmode:
            bad.append('texture mode, but the transcript has no texsent counter; '
                       'this is an older build than the run claims')
    elif tmode and ts != 1:
        bad.append('texture mode, but %d submissions switched the texture unit on' % ts)
    elif not tmode and ts != 0:
        bad.append('no-texture mode, but %d submissions switched the texture unit '
                   'on' % ts)
    else:
        ok.append('tex=%d and texSent +%d -- the texture unit matches the run'
                  % (tmode, ts))
    if tmode:
        u = c.get('draw', {}).get('texup')
        ub = c.get('draw', {}).get('texbad')
        if u is None:
            bad.append('texture mode, but the transcript does not report any upload')
        elif u != 1 or ub:
            bad.append('the texels were uploaded %s time(s) with %s failure(s); '
                       'exactly one clean upload is what the picture is predicted '
                       'from' % (u, ub))
        else:
            ok.append('one texture upload, read back out of video memory by the '
                      'unit that wrote it, 0 words wrong')

    # M1i: the depth unit, the same way -- what went out against what the run
    # was told, and the CLEAR against the read-back the unit did itself
    ds = delta('draw', 'depthsent')
    if ds is None:
        if dmode:
            bad.append('depth mode, but the transcript has no depthsent counter; '
                       'this is an older build than the run claims')
    elif dmode and ds != want_tris:
        bad.append('depth mode, but %d of %s submissions carried the depth test'
                   % (ds, want_tris))
    elif not dmode and ds != 0:
        bad.append('no-depth mode, but %d submissions carried the depth test' % ds)
    else:
        ok.append('depth=%d and depthSent +%d -- the depth test matches the run'
                  % (dmode, ds))
    if dmode:
        #
        # M1j: the clear is glClear's now, not the install's.  The chain is the
        # gate: our Clear was installed ONCE, it was called, and every call
        # either handled the depth bit or passed something on -- "handled plus
        # passed equals asked" is the shape M1d used for triangles.
        #
        cli = c.get('draw', {}).get('cli')
        clc = c.get('draw', {}).get('clc')
        if cli is None:
            bad.append('depth mode, but the transcript has no Clear counters; '
                       'this is an older build than the run claims')
        elif cli < 1:
            bad.append('our Clear was never installed')
        elif not clc:
            bad.append('our Clear was installed but never called')
        else:
            ok.append('our Clear installed %d time(s) and called %d time(s) -- '
                      'osmesa_update_state puts Mesa\'s back every time '
                      '(osmesa.c 1991), so re-installing is the contract'
                      % (cli, clc))
        zc = c.get('draw', {}).get('zclear')
        zb = c.get('draw', {}).get('zclearbad')
        if zc is None:
            bad.append('depth mode, but the transcript does not report a clear')
        elif zc != 1 or zb:
            bad.append('the depth buffer was cleared %s time(s) with %s failure(s); '
                       'exactly one clean clear is what the picture is predicted '
                       'from' % (zc, zb))
        else:
            ok.append('one depth clear, read back out of video memory by the unit '
                      'that wrote it, 0 pixels wrong')

    # ---- 2. the three states it declines: installed is not the same as called
    # M1e accepted GL_SMOOTH, so the only declined state left in this run is
    # culling.  SHADE_MODEL is still a reason (sim_class proves it fires); it
    # just has no case a GL program can reach any more.
    for step, reason in (('cull', 'TRI_SETUP'),):
        v = delta(step, 'triangles')
        if v is None:
            bad.append('the transcript has no "%s" step' % step)
            continue
        if v != 0:
            bad.append('%s: our function was called %d times in a state we decline' % (step, v))
        else:
            ok.append('%-6s triangles +0 -- declined, so Mesa drew it' % step)
        got = c[step].get('whyname', {})
        if got.get(reason, 0) < 1:
            bad.append('%s: no %s in the reasons (%s)' % (step, reason, got))
        else:
            ok.append('%-6s declined for %s' % (step, reason))

    # ---- 3. the fallback is real
    v, g = delta('unbound', 'triangles'), delta('unbound', 'delegated')
    if v is None:
        bad.append('the transcript has no "unbound" step')
    elif v < 1:
        bad.append('unbound: our function was not called at all, so the fallback '
                   'was never exercised')
    elif v != g:
        bad.append('unbound: called %d times but delegated %d -- %d triangles are '
                   'unaccounted for' % (v, g, v - g))
    else:
        ok.append('unbound triangles +%d == delegated +%d -- every one fell back' % (v, g))
    s = delta('unbound', 'submitted')
    if s is not None and s != 0:
        bad.append('unbound: %d triangles were still sent to the card with no surface '
                   'held' % s)
    elif s is not None:
        ok.append('unbound submitted +0 -- nothing was drawn into a surface we do not hold')

    # ---- 4. the invariants, at the end
    last = c.get('end', {})
    if last.get('nosw', 1) != 0:
        bad.append('%d triangles were neither sent nor drawn (nosw) -- LOST' % last.get('nosw'))
    else:
        ok.append('nosw = 0 -- no triangle was lost')
    if last.get('slotsfull', 1) != 0:
        note.append('slotsFull = %d: a context went un-remembered' % last['slotsfull'])
    if 'maps' not in last:
        bad.append('the end step has no counter line the judge could read -- the '
                   'transcript and this judge disagree about its shape')
    elif last['maps'] > 1:
        bad.append('the batch window was mapped %d times' % last['maps'])
    else:
        ok.append('the batch window was mapped %d time(s)' % last['maps'])
    # Every delegation is either a refusal the tri unit counted, or a triangle
    # the hook never offered it because the surface was not ours.  The first
    # version left the second term out and reported 2 against 4 -- a judge's
    # arithmetic, not a lost triangle.
    #
    # M1k REFINES this, it does not relax it.  Before batching every refusal the
    # tri unit counted was one triangle the hook then drew.  A refused FLUSH is
    # still one refusal, but it hands back as many triangles as the batch held,
    # and those are drawn on the replay path instead of the delegation path.  So
    # the failed flushes come out of the left side and their triangles are
    # accounted separately, just below.
    #
    if last.get('sum') is not None and last.get('delegated') is not None:
        ff = last.get('tfailed', 0)
        acc = (last['sum'] - ff + last.get('notbound', 0) + last.get('texproj', 0))
        if acc != last['delegated']:
            bad.append('refused %d - failed flushes %d + not-bound %d + projective '
                       '%d = %d, but the hook delegated %d -- the difference is '
                       'unaccounted for'
                       % (last['sum'], ff, last.get('notbound', 0),
                          last.get('texproj', 0), acc, last['delegated']))
        else:
            ok.append('refused %d - failed flushes %d + not-bound %d + projective '
                      '%d == delegated %d -- every triangle the card did not take '
                      'was drawn' % (last['sum'], ff, last.get('notbound', 0),
                                     last.get('texproj', 0), acc))

    #
    # ---- 4b. M1k: THE BATCH.
    #
    if 'badds' not in last:
        bad.append('the end step has no -batch line: this transcript was made by '
                   'a library from before M1k, or the judge and it disagree about '
                   'the shape')
    else:
        # Nothing may fall between "taken into a batch" and "drawn, one way or
        # the other".  This is the promise M1d made, counted.
        if last['badds'] != last['bflushed'] + last['breplayed']:
            bad.append('%d triangles went into a batch but %d were delivered and '
                       '%d replayed -- %d fell between'
                       % (last['badds'], last['bflushed'], last['breplayed'],
                          last['badds'] - last['bflushed'] - last['breplayed']))
        else:
            ok.append('batched %d == delivered %d + replayed %d -- nothing fell '
                      'out of a batch' % (last['badds'], last['bflushed'],
                                          last['breplayed']))
        # The two sides keep their own count of what is waiting.  A disagreement
        # means words went into the window without this file knowing, which is
        # how a batch draws a triangle twice.
        if last['bdesync'] != 0:
            bad.append('the hook and the tri unit disagreed about the batch %d '
                       'time(s)' % last['bdesync'])
        else:
            ok.append('the hook and the tri unit never disagreed about the batch')
        # Batching is only safe inside Mesa's render bracket.  Outside it a
        # triangle is sent alone -- correct, but it means there is a path into
        # the triangle function that the reading did not find.
        if last['boutside'] != 0:
            bad.append('%d triangles arrived OUTSIDE RenderStart/RenderFinish -- '
                       'they were sent alone, so nothing is wrong with the '
                       'picture, but docs/M1K_PLAN.md 8 says there is no such '
                       'path and there is' % last['boutside'])
        else:
            ok.append('every triangle arrived inside the render bracket '
                      '(%d starts, %d finishes)' % (last['brs'], last['brf']))
        if last['bflushout'] != 0:
            note.append('%d flush(es) came from a hook other than RenderFinish'
                        % last['bflushout'])
        # the hook's count of batches and the unit's must be the same number
        if last['bflushes'] != last.get('tflushes', -1):
            bad.append('the hook counted %d flushes and the unit %d'
                       % (last['bflushes'], last.get('tflushes')))
        if last['badds'] != last.get('tbatched', -1):
            bad.append('the hook batched %d and the unit %d'
                       % (last['badds'], last.get('tbatched')))

    # ---- 5. the picture, against the MEASURED rule
    if not tris:
        bad.append('the transcript records no sent triangles, so the picture cannot '
                   'be predicted')
    elif 'draw' not in px:
        bad.append('no drawn pixels in the transcript')
    else:
        import numpy as np
        to = oracle()
        got = np.asarray(px['draw'][:W * H], np.int64).reshape(H, W)
        tex = tex_image(ap)
        if tex is not None:
            ok.append('the transcript carries the %dx%d texture the test uploaded, '
                      'first texel %08x' % (tex[0], tex[1], tex[2][0][0]))
        dstWord = None
        if bmode:
            # the destination the card blended over: read it out of the picture
            # at the pixels the triangle does NOT cover.  If those are not all
            # one value the software clear did not do what this assumes, and
            # saying so is better than predicting against a guess.
            covAll = np.zeros((H, W), bool)
            for _k, pp, _c, _s, _z in tris:
                covAll |= to.cover(pp, to.MEASURED, W)
            outside = got[~covAll]
            vals = set(int(v) for v in outside.ravel())
            if len(vals) != 1:
                bad.append('blending: the uncovered pixels are not one colour (%d '
                           'distinct), so the destination cannot be read from them'
                           % len(vals))
            else:
                dstWord = vals.pop()
                ok.append('the destination the card blended over is %08x, read from '
                          'the %d pixels the triangle does not cover'
                          % (dstWord, int((~covAll).sum())))
        try:
            want, texMargin = predict(to, tris, dstWord, tex, dmode)
        except RuntimeError as e:
            # REFUSING to predict is a failure of this run, not an exception out
            # of the judge: a traceback prints no verdict, and a rung that ends
            # without a verdict tends to get read as one that passed.
            bad.append('the picture cannot be predicted: %s' % e)
            return ok, bad, note
        touched = want >= 0
        wrong = int(((got != want) & touched).sum())
        if len(px['draw']) != W * H:
            bad.append('the picture is %d pixels, want %d' % (len(px['draw']), W * H))
        elif int(touched.sum()) < 50:
            bad.append('the prediction covers only %d pixels -- too few for a match to '
                       'mean anything' % int(touched.sum()))
        elif wrong:
            ys, xs = np.where((got != want) & touched)
            bad.append('%d of %d predicted pixels are wrong, first at (%d,%d): '
                       'got %08x want %08x'
                       % (wrong, int(touched.sum()), int(xs[0]), int(ys[0]),
                          int(got[ys[0]][xs[0]]), int(want[ys[0]][xs[0]])))
        else:
            ok.append('%d pixels match the MEASURED rasterisation rule exactly'
                      % int(touched.sum()))

        # THE DIFFERENCE FROM SOFTWARE, as one measured rule.
        #
        # The card and Mesa reach the same pixel by different arithmetic, and
        # each stage that rounds can disagree by one:
        #
        #     Gouraud   the card weights barycentrically and rounds the weights
        #               to 1/256 (R6e rule B); Mesa steps a fixed-point span
        #     blending  the card computes (c * (F+1)) >> 8 per term (R6j); Mesa
        #               blends its own way
        #
        # so the bound is ONE PER ROUNDING STAGE.  Measured on boot ed7bef6a,
        # over the 276 covered pixels of each of the four runs:
        #
        #     flat, no blend    0      smooth, no blend   1
        #     flat, blend       1      smooth, blend      2
        #
        # exactly the formula.  This is a bound, not equality: demanding
        # equality failed three correct runs in a row, once per rung, because
        # the plan called it a measurement and the code called it a rule.
        #
        # It is applied to INTERIOR pixels only.  At an edge the two can differ by a
        # whole colour for a reason that is not rounding at all -- one of them
        # covered the pixel and the other did not -- and that is what the
        # separate coverage comparison above is for.
        #
        # A TEXTURE adds no rounding stage of its own: the card copies the texel
        # word into the buffer (R6h, zero byte swaps) and Mesa's NEAREST fetch
        # copies the same texel -- PROVIDED both pick the same one.  That holds
        # while the sample is far from a texel boundary, so the bound below is
        # only claimed when the measured margin is comfortable; otherwise the
        # comparison is skipped with a note rather than passed by assumption.
        smoothTri = any(c[0] != c[1] or c[1] != c[2]
                        for _k, _p, c, _s, _z in tris if _s is None)
        allowed = (1 if smoothTri else 0) + (1 if bmode else 0)
        from fractions import Fraction as Fr
        texSkip = texMargin is not None and texMargin <= Fr(1, 16)
        if texMargin is not None:
            note.append('the closest a texture sample came to a texel boundary is '
                        '%s of a texel' % texMargin)
        if texSkip:
            note.append('within 1/16 of a texel the two need not fetch the same '
                        'texel, so software is not compared on this run')
        elif os.path.exists(sp):
            spx = pixels(sp)
            if len(spx.get('draw', [])) == W * H:
                sw = np.asarray(spx['draw'], np.int64).reshape(H, W)
                diff = int((sw != got).sum())
                inside = _erode(touched)
                worst = 0
                tot = 0
                for sh in (0, 8, 16, 24):
                    d8 = np.abs(((got >> sh) & 0xff) - ((sw >> sh) & 0xff)) * inside
                    worst = max(worst, int(d8.max()))
                    tot += int(d8.sum())
                note.append('software differs in %d pixels; inside the triangle every '
                            'channel is within %d (mean %.2f), and %d rounding '
                            'stage(s) allow %d'
                            % (diff, worst, tot / float(4 * max(1, int(inside.sum()))),
                               allowed, allowed))
                if worst > allowed:
                    bad.append('an interior channel differs from software by %d, but '
                               'this run has %d rounding stage(s) and so may differ '
                               'by at most %d' % (worst, allowed, allowed))
    return ok, bad, note


def _erode(mask):
    """the covered pixels whose four neighbours are covered too -- the inside"""
    import numpy as np
    m = mask.copy()
    m[1:, :] &= mask[:-1, :]
    m[:-1, :] &= mask[1:, :]
    m[:, 1:] &= mask[:, :-1]
    m[:, :-1] &= mask[:, 1:]
    return m


def self_test():
    import tempfile
    fails = 0

    def one(label, cond):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', label))

    t = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, t, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    p = os.path.join(t, 'x')
    open(p, 'w').write(
        'RDNTRI run=1 step=draw-refused -=0 NO_ACCEL=0 NOT_RUNNING=0 NO_WINDOW=0 '
        'ARGS=0 IOCTL=0 REFUSED=0 NOT_DRAWN=0 SUM=0\n')
    c, _o = counters(p)
    one('the refusal line is read for its own step', c.get('draw', {}).get('sum') == 0)
    open(p, 'w').write('RDNTRI run=1 step=draw installs=1 leaves=0 triangles=2 '
                       'delegated=0 nosw=0 notbound=0 slotsfull=0 caps=00000000 '
                       'shade=1d00\n')
    c, _o = counters(p)
    one('and the counter line is not mistaken for one',
        'sum' not in c.get('draw', {}) and c['draw']['triangles'] == 2)

    # ---- M1k: the batch line, and that it is nobody else's line
    BL = ('RDNTRI run=1 step=draw-batch adds=9 flushes=3 flushed=9 failed=0 '
          'replayed=0 outside=0 flushout=0 desync=0 rs=3 rf=3 rinst=1 '
          'tbatched=9 tflushes=3 tfailed=0\n')
    open(p, 'w').write(BL)
    c, _o = counters(p)
    one('the batch line is read for its own step',
        c.get('draw', {}).get('badds') == 9 and c['draw']['bflushes'] == 3 and
        c['draw']['brf'] == 3)
    one('and it is not mistaken for the counter line or the refusal line',
        'triangles' not in c.get('draw', {}) and 'sum' not in c.get('draw', {}))
    open(p, 'w').write('RDNTRI run=1 step=draw installs=1 leaves=0 triangles=2 '
                       'delegated=0 nosw=0 notbound=0 slotsfull=0 caps=00000000 '
                       'shade=1d00\n' + BL)
    c, _o = counters(p)
    one('and the two lines of one step land in one place',
        c['draw']['triangles'] == 2 and c['draw']['badds'] == 9)

    one('a float comes back out of its bits', abs(f32(0x40800000) - 4.0) < 1e-6)
    one('and so does 1.0', abs(f32(0x3f800000) - 1.0) < 1e-6)

    # the prediction agrees with the oracle's own T1, which is the same rule
    to = oracle()
    import numpy as np
    img, _ = predict(to, [(0, [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)],
                           [to.word((0x12, 0x34, 0x56, 0x78))] * 3, None, [1.0] * 3)])
    ref = np.asarray(to.pixels('T1', to.MEASURED, W), np.int64)
    one('predict() reproduces the oracle\'s own T1 picture (%d pixels)'
        % int((img >= 0).sum()), (img == ref).all())

    m = np.zeros((5, 5), bool)
    m[1:4, 1:4] = True
    one('_erode keeps only the inside (1 of 9)', int(_erode(m).sum()) == 1)

    # ---- M1e: the Gouraud branch
    tri = [(0, [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)],
            [0xff4020ff, 0x10ff80aa, 0x4020ff55], None, [1.0] * 3)]
    gimg, _ = predict(to, tri)
    vals = [int(v) for v in gimg.ravel() if v >= 0]
    one('a Gouraud triangle predicts %d pixels with %d distinct colours (a flat '
        'one would give 1)' % (len(vals), len(set(vals))),
        len(vals) == 276 and len(set(vals)) > 50)
    # three EQUAL colours must give exactly the flat answer, through the flat branch
    flat, _ = predict(to, [(0, tri[0][1], [0x78563412] * 3, None, [1.0] * 3)])
    fv = set(int(v) for v in flat.ravel() if v >= 0)
    one('three equal vertex colours give one colour (the flat branch)', len(fv) == 1)
    # and the guard fires for a triangle the Gouraud oracle cannot see
    try:
        predict(to, [(0, [(34.0, 36.0), (58.0, 40.0), (38.0, 59.0)],
                      [0xff0000ff, 0x00ff00ff, 0x0000ffff], None, [1.0] * 3)])
        one('a triangle outside the 32 x 32 window is REFUSED, not mispredicted', False)
    except RuntimeError:
        one('a triangle outside the 32 x 32 window is REFUSED, not mispredicted', True)

    # ---- M1g: the texture branch
    from fractions import Fraction as Fr
    import math
    po = persp()
    go = gouraud()
    one('the sample position this rung predicts with is the PIXEL CENTRE '
        '(persp_oracle.MEASURED_OFF = %s)' % po.MEASURED_OFF,
        po.MEASURED_OFF == Fr(1, 2))
    te = _load('tex_oracle', ('tools', 'r6', 'tex_oracle.py'))
    one('and it is NOT tex_oracle.MEASURED[0] = %s, the corner R6h could not '
        'separate and R6i corrected' % te.MEASURED[0],
        te.MEASURED[0] != po.MEASURED_OFF)

    # tex_image: rows in, rows out, and a ragged transcript refused
    with tempfile.NamedTemporaryFile('w', suffix='.out', delete=False) as f:
        for v in range(4):
            f.write('RDNTRI run=z tex row=%d%s\n'
                    % (v, ''.join(' %08x' % (0xff000000 | (v << 8) | u)
                                  for u in range(4))))
        tp = f.name
    ti = tex_image(tp)
    one('tex_image reads the uploaded image back (%dx%d, [2][3] = %08x)'
        % (ti[0], ti[1], ti[2][2][3]), ti == (4, 4, [[0xff000000 | (v << 8) | u
                                                      for u in range(4)]
                                                     for v in range(4)]))
    open(tp, 'a').write('RDNTRI run=z tex row=4 ffffffff\n')
    try:
        tex_image(tp)
        one('a short texture row is refused, not padded', False)
    except RuntimeError:
        one('a short texture row is refused, not padded', True)
    os.unlink(tp)

    # THE CROSS-CHECK.  R6i's own oracle already knows what an affine ST samples
    # at the pixel centre; texel_at must agree with it word for word on the very
    # cases R6i measured.  Written twice, from two directions, so a wrong wrap or
    # a transposed row cannot pass both.
    agree = disagree = 0
    for case in po.TEX_ORDER:
        w, h = po.tex_of(case)[0], po.tex_of(case)[1]
        rows = [[po.sampled(case, u, v) for u in range(w)] for v in range(h)]
        pts = po.geom_of(case)
        st = po.st_of(case)
        cov = to.cover(pts, to.MEASURED, W)
        mine = texel_at(go, po, pts, st, (w, h, rows), cov)
        theirs = po.nearest_map(case, ('A', po.MEASURED_OFF, None))
        for p, (word, safe) in theirs.items():
            if p not in mine or not safe:
                continue
            # only where wrap and the case's own clamp cannot differ
            sx, sy = p
            if mine[p][1] <= po.DELTA:
                continue
            if mine[p][0] == word:
                agree += 1
            else:
                disagree += 1
    one('texel_at agrees with persp_oracle.nearest_map on %d safe samples across '
        '%d R6i cases, 0 differ' % (agree, len(po.TEX_ORDER)),
        agree > 200 and disagree == 0)

    # and a textured triangle predicts the texels, not the vertex colour
    trows = [[0xff000000 | (u * 32 << 16) | (v * 32 << 8) | 0x55
              for u in range(8)] for v in range(8)]
    tpts = [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]
    tst = ([0.0625, 0.9375, 0.0625], [0.0625, 0.0625, 0.9375])
    timg, tm = predict(to, [(0, tpts, [0x000000ff] * 3, tst, [1.0] * 3)], None,
                       (8, 8, trows))
    tvals = set(int(v) for v in timg.ravel() if v >= 0)
    one('a textured triangle predicts %d pixels in %d texel colours, none of them '
        'the vertex colour' % (int((timg >= 0).sum()), len(tvals)),
        int((timg >= 0).sum()) == 276 and 1 < len(tvals) <= 64 and
        tvals <= set(x for r in trows for x in r))
    one('and it reports how close the closest sample came to a boundary (%s)' % tm,
        tm is not None and tm > po.DELTA)
    # a sample ON a boundary is refused rather than guessed
    try:
        # s = 1/8 at every vertex is exactly texel boundary 1, everywhere
        predict(to, [(0, tpts, [0] * 3, ([0.125] * 3, [0.0625, 0.0625, 0.9375]), [1.0] * 3)],
                None, (8, 8, trows))
        one('an ST that lands a sample on a texel boundary is REFUSED', False)
    except RuntimeError:
        one('an ST that lands a sample on a texel boundary is REFUSED', True)

    print('judge_m1d self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


def main():
    if '--self-test' in sys.argv:
        return 1 if self_test() else 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ok, bad, note = judge(sys.argv[1])
    for x in ok:
        print('  ok   %s' % x)
    for x in note:
        print('  --   %s' % x)
    for x in bad:
        print('  FAIL %s' % x)
    print('judge_m1d: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
