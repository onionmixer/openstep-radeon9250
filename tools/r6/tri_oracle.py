#!/usr/bin/env python3
"""R6d oracle (docs/R6D_PLAN.md 10): flat-colour TRIANGLES -- the ring words, the
coverage every rasterization hypothesis predicts, the coverage map the driver logs
and the block digests, independent of the driver.

  tri_oracle.py --self-test

The rule the R200 uses to decide which pixels a triangle covers is in no reference
(docs/R6D_PLAN.md 1 D7), so the oracle carries 4032 hypotheses:
  snap    exact, or 1/2 1/4 1/8 1/16 1/256 pixel by trunc / round (half up) / even / odd
  sample  the pixel's point at (x + k/16, y + k/16), k = 0 .. 15
  tie     a sample exactly on an edge: top-left, top-right, bottom-left, bottom-right,
          all, none (memory y grows downward: "top" is the smaller y)
  wind    'n' ties classified on the positively oriented triangle (winding-blind),
          'w' ties classified by the submitted edge direction
All arithmetic is exact: float32 vertices >= 0.5 are multiples of 2^-24, so every
coordinate is an integer at scale 2^24 and edge products stay below 2^62.  Inside
one packet a later triangle overwrites an earlier one (Z is ALWAYS, write).

The stream pieces (state block, blend stage, prefix, tail) come from
tools/r6/zclear_oracle.py -- the R6c F state, measured on 058dc9a3 -- never copied.
"""

import os
import struct
import sys
import importlib.util

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('zclear_oracle', os.path.join(HERE, 'zclear_oracle.py'))
zo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(zo)
M32 = zo.M32

SH = 24
S = 1 << SH
MAPW = 32                       # the coverage map: the colour buffer's top-left 32 x 32
TIES = ('tl', 'tr', 'bl', 'br', 'all', 'none')
MODES = ('trunc', 'round', 'even', 'odd')
PRECS = (2, 4, 8, 16, 256)
HYPS = ([(None, 'trunc', o, t, w) for w in 'nw' for o in range(16) for t in TIES] +
        [(p, m, o, t, w) for w in 'nw' for p in PRECS for m in MODES for o in range(16) for t in TIES])
EXPECTED = (8, 'trunc', 8, 'tl', 'n')      # SE_CNTL: ROUND_MODE_TRUNC, ROUND_PREC_8TH_PIX, PIX_CENTER_OGL
MEASURED = (16, 'trunc', 8, 'tl', 'n')     # the rule the hardware follows (docs/R6D_PLAN.md 13, boot 0628ba86)

# colours (r, g, b, a): the alpha is never the pattern's 0xa5 (a write equal to the pattern is invisible)
C1 = (0x12, 0x34, 0x56, 0x78)
C2 = (0x9a, 0xbc, 0xde, 0x3c)
C3 = (0x11, 0x22, 0x33, 0x44)

T1 = [(4, 4), (28, 4), (4, 28)]
_SQ = [(8, 8), (24, 8), (24, 24), (8, 24)]      # a b c d


def _sh(t, d):
    return [(x + d, y + d) for x, y in t]


def _tri(pts, col):
    return (tuple(pts), (col, col, col))


# case: [(vertices, per-vertex colours)] in packet order -- docs/R6D_PLAN.md 10
TRI = {
    'T1': [_tri(T1, C1)],
    'T2': [_tri(_sh(T1, 0.5), C1)],
    'T3': [_tri([_SQ[0], _SQ[1], _SQ[3]], C1), _tri([_SQ[1], _SQ[2], _SQ[3]], C2)],
    'T4': [_tri(_sh([_SQ[0], _SQ[1], _SQ[3]], 0.5), C1), _tri(_sh([_SQ[1], _SQ[2], _SQ[3]], 0.5), C2)],
    'T5': [_tri([(3.3, 2.6), (29.45, 7.8), (10.1, 30.2)], C1)],
    'T6': [_tri([(4.06, 3.94), (27.19, 6.31), (9.44, 28.07)], C1)],
    'X1': [_tri([(27.375, 4.625), (4.3125, 3.0625), (10.4375, 27.75)], C1)],
    'X2': [_tri([(2.3125, 19.3125), (22.0, 7.25), (19.6875, 20.4375)], C1)],
    'X3': [_tri([(5.807, 6.869), (28.194, 13.23), (12.068, 21.055)], C1)],
    'X4': [_tri([(29.343, 15.937), (4.861, 19.402), (29.765, 9.319)], C1)],
    'X5': [_tri([(17.587, 11.027), (8.799, 22.999), (13.408, 27.396)], C1)],
    'X6': [_tri([(23.5, 10.0), (18.5, 25.0), (11.0625, 3.8125)], C1)],
    'X7': [_tri([(24.46875, 3.96875), (21.34375, 11.59375), (3.28125, 16.71875)], C1)],
    'X8': [_tri([(10.03125, 5.53125), (28.40625, 12.09375), (6.15625, 26.65625)], C1)],
    # vertices just below 1/8 and 1/16 boundaries: separates double rounding from the gated rules (11)
    'Y1': [_tri([(26.748046875, 12.998046875), (2.373046875, 20.498046875), (12.291, 11.4990234375)], C1)],
    'T7': [(tuple(T1), (C2, C3, C1))],          # flat shading: which vertex's colour (measured)
    'T1r': [_tri([T1[0], T1[2], T1[1]], C1)],   # T1 wound the other way (measured)
}
ORDER = ['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7', 'X8', 'Y1', 'T7', 'T1r']
CASE_NUM = dict((n, 9 + k) for k, n in enumerate(ORDER))
GATED = ORDER[:15]              # T1-T6, X1-X8, Y1: the equivalence class is judged on these
Z = 1.0
CLIP = (0, 0, 64, 64)           # the whole of both buffers, SCISSOR_ENABLE (rule H: TL applies)
MAP_CODES = {'T7': (C1, C2)}    # map code 1 / 2: T7's last and first vertex colours


def f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def fbits(x):
    return struct.unpack('<I', struct.pack('<f', float(x)))[0]


def word(c):
    """the vertex colour word, Mesa's r g b a bytes with COLOR_ORDER_RGBA (R6c)"""
    r, g, b, a = c
    return r | (g << 8) | (b << 16) | (a << 24)


def pixel(c):
    """the ARGB8888 pixel that colour leaves (measured on 058dc9a3)"""
    r, g, b, a = c
    return (a << 24) | (r << 16) | (g << 8) | b


def map_colours(case):
    """(pixel for code 1, pixel for code 2)"""
    if case in MAP_CODES:
        a, b = MAP_CODES[case]
        return pixel(a), pixel(b)
    cols = [t[1][2] for t in TRI[case]]
    return pixel(cols[0]), pixel(cols[1] if len(cols) > 1 else cols[0])


def nverts(case):
    return 3 * len(TRI[case])


# ---- the ring words ---------------------------------------------------------------

def vf_cntl(case):
    return (zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') | zo.M('R200_VF_COLOR_ORDER_RGBA') |
            (nverts(case) << 16))


def draw_words(case, seed):
    """R6c F's state and blend stage (zclear_oracle), the whole-buffer clip, one
    3D_DRAW_IMMD_2 with every triangle, the tail"""
    fw = zo.draw_words('F', seed)
    state, pix = fw[:26], fw[26:34]
    tail = fw[-10:]
    x1, y1, x2, y2 = CLIP
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]
    body = [vf_cntl(case)]
    for pts, cols in TRI[case]:
        for (x, y), c in zip(pts, cols):
            body += [fbits(x), fbits(y), fbits(Z), fbits(1.0), word(c)]
    hdr = zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)
    return state + pix + clip + [hdr] + body + tail


def prefix_words(win, seed):
    return zo.prefix_words(win, seed, 'F')


def prefix_expect(win):
    return zo.prefix_expect(win, 'F')


# ---- coverage -------------------------------------------------------------------

def fix(x):
    v = f32(x)
    assert v >= 0, v                    # R6k draws a box whose corner is the origin
    n = v * S
    assert n == int(n)
    return int(n)


def snap(n, prec, mode):
    if prec is None:
        return n
    u = S // prec
    q, r = divmod(n, u)
    if mode == 'trunc':
        k = q
    elif mode == 'round':
        k = q + (1 if 2 * r >= u else 0)
    elif 2 * r < u:
        k = q
    elif 2 * r > u:
        k = q + 1
    else:
        k = q if (q % 2 == (0 if mode == 'even' else 1)) else q + 1
    return k * u


_ys, _xs = np.mgrid[0:64, 0:64]


def cover(pts, h, w=64):
    """bool [y][x] over w x w: the pixels triangle pts covers under hypothesis h"""
    prec, mode, off, tie, wind = h
    p = [(snap(fix(x), prec, mode), snap(fix(y), prec, mode)) for x, y in pts]
    area = (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[2][0] - p[0][0]) * (p[1][1] - p[0][1])
    if area == 0:
        return np.zeros((w, w), bool)
    sgn = 1 if area > 0 else -1
    sx = _xs[:w, :w].astype(np.int64) * S + off * (S // 16)
    sy = _ys[:w, :w].astype(np.int64) * S + off * (S // 16)
    ok = np.ones((w, w), bool)
    for i in range(3):
        (ax, ay), (bx, by) = p[i], p[(i + 1) % 3]
        e = ((bx - ax) * (sy - ay) - (by - ay) * (sx - ax)) * sgn
        d = sgn if wind == 'n' else 1
        dx, dy = (bx - ax) * d, (by - ay) * d
        top, bottom, left, right = dy == 0 and dx > 0, dy == 0 and dx < 0, dy < 0, dy > 0
        inc = {'tl': top or left, 'tr': top or right, 'bl': bottom or left, 'br': bottom or right,
               'all': True, 'none': False}[tie]
        ok &= (e > 0) | ((e == 0) if inc else False)
    return ok


def cover_general(pts, snapf, ox, oy, tie, wind, w=64):
    """cover() with any vertex snapping function and separate x / y sample offsets (in
    1/16 pixel) -- the FAIL diagnostics' families outside the gated space"""
    p = [(snapf(fix(x)), snapf(fix(y))) for x, y in pts]
    area = (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[2][0] - p[0][0]) * (p[1][1] - p[0][1])
    if area == 0:
        return np.zeros((w, w), bool)
    sgn = 1 if area > 0 else -1
    sx = _xs[:w, :w].astype(np.int64) * S + ox * (S // 16)
    sy = _ys[:w, :w].astype(np.int64) * S + oy * (S // 16)
    ok = np.ones((w, w), bool)
    for i in range(3):
        (ax, ay), (bx, by) = p[i], p[(i + 1) % 3]
        e = ((bx - ax) * (sy - ay) - (by - ay) * (sx - ax)) * sgn
        d = sgn if wind == 'n' else 1
        dx, dy = (bx - ax) * d, (by - ay) * d
        top, bottom, left, right = dy == 0 and dx > 0, dy == 0 and dx < 0, dy < 0, dy > 0
        inc = {'tl': top or left, 'tr': top or right, 'bl': bottom or left, 'br': bottom or right,
               'all': True, 'none': False}[tie]
        ok &= (e > 0) | ((e == 0) if inc else False)
    return ok


def diagnostic_families():
    """[(name, label, snapf, ox, oy, tie, wind)] -- rules outside the 4032 hypotheses, part of
    the judge's named space since docs/R6D_PLAN.md 11: a double rounding (first to 1/16 or
    1/256 by round or even, then truncated to a coarser 1/8 or 1/16), and x and y samples
    at different offsets"""
    out = []
    for p1 in (16, 256):
        for m1 in ('round', 'even'):
            for p2 in (8, 16):
                if p2 >= p1:
                    continue
                f = (lambda a, b, c: (lambda n: snap(snap(n, a, b), c, 'trunc')))(p1, m1, p2)
                for o in range(16):
                    for t in TIES:
                        for w in 'nw':
                            out.append(('double rounding', '1/%d %s then 1/%d trunc, sample %d/16, %s, %s' % (p1, m1, p2, o, t, w),
                                        f, o, o, t, w))
    for prec, mode in ((None, 'trunc'), (8, 'trunc'), (16, 'trunc'), (8, 'round'), (16, 'round')):
        f = (lambda a, b: (lambda n: snap(n, a, b)))(prec, mode)
        for ox in range(16):
            for oy in range(16):
                if ox == oy:
                    continue
                for t in TIES:
                    out.append(('x/y samples apart', '%s %s, sample x %d/16 y %d/16, %s' % (prec, mode, ox, oy, t),
                                f, ox, oy, t, 'n'))
    return out


def diagnostic_map(case, fam):
    """the coverage map a diagnostic family member predicts"""
    _, _, f, ox, oy, t, w = fam
    out = np.full((MAPW, MAPW), -1, np.int64)
    for pts, cols in TRI[case]:
        out[cover_general(pts, f, ox, oy, t, w, MAPW)] = pixel(cols[2])
    return coverage_map(case, observed=out)


def signed_area(case):
    """the first triangle's signed area in float32 (negative: wound the other way)"""
    pts = [(f32(x), f32(y)) for x, y in TRI[case][0][0]]
    return (pts[1][0] - pts[0][0]) * (pts[2][1] - pts[0][1]) - (pts[2][0] - pts[0][0]) * (pts[1][1] - pts[0][1])


def named_rules():
    """every rule the judge can name (docs/R6D_PLAN.md 11): the 4032 gated hypotheses as
    ('gated', h) and the diagnostic families as (family, label); each with (snapf, ox, oy, tie, wind)"""
    out = []
    for h in HYPS:
        p, m, o, t, w = h
        out.append((('gated', h), (lambda a, b: (lambda n: snap(n, a, b)))(p, m), o, o, t, w))
    for f in diagnostic_families():
        out.append(((f[0], f[1]), f[2], f[3], f[4], f[5], f[6]))
    return out


def named_map(case, rule):
    out = np.full((MAPW, MAPW), -1, np.int64)
    for pts, cols in TRI[case]:
        out[cover_general(pts, rule[1], rule[2], rule[3], rule[4], rule[5], MAPW)] = pixel(cols[2])
    return tuple(coverage_map(case, observed=out))


def named_signatures(cases=None):
    """[(name, maps per case)] over every named rule"""
    cases = cases or GATED
    return [(r[0], tuple(named_map(c, r) for c in cases)) for r in named_rules()]


def pixels(case, h, w=64):
    """int64 [y][x]: the colour pixel each covered pixel ends with (later triangle wins,
    flat shading from the LAST vertex -- SE_CNTL FLAT_SHADE_VTX_LAST), -1 where uncovered"""
    out = np.full((w, w), -1, np.int64)
    for pts, cols in TRI[case]:
        out[cover(pts, h, w)] = pixel(cols[2])
    return out


def coverage_map(case, h=None, observed=None):
    """the 64 words the driver logs: 2 bits per pixel of the colour buffer's 32 x 32,
    pixel i = y*32 + x in word i // 16 at bit 2*(i % 16); 0 the pattern, 1 / 2 the
    case's two map colours, 3 anything else.  observed: a 32 x 32 array of pixels (-1 = pattern)"""
    px = np.asarray(pixels(case, h, MAPW) if observed is None else observed, np.int64)
    c1, c2 = map_colours(case)
    codes = np.where(px < 0, 0, np.where(px == c1, 1, np.where(px == c2, 2, 3))).astype(np.int64).reshape(-1, 16)
    return [int(w) for w in codes.dot(4 ** np.arange(16, dtype=np.int64))]


def decode_map(words):
    """code [y][x] from the 64 logged words"""
    w = np.asarray(words, np.int64).reshape(-1, 1)
    return ((w >> (2 * np.arange(16, dtype=np.int64))) & 3).reshape(MAPW, MAPW).astype(np.int8)


def map_distance(a, b):
    """pixels whose code differs between two 64-word maps"""
    n = 0
    for x, y in zip(a, b):
        d = x ^ y
        n += bin((d | (d >> 1)) & 0x55555555).count('1')
    return n


def expected_block(case, h, depth=0xffffff):
    """the 256 KiB block after ZPREP then ZCLEAR <case> under hypothesis h: the colour
    buffer linear (R6c), the depth buffer tiled (r200_mba_z32, R6a) with the stencil byte kept"""
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    px = pixels(case, h)
    ys, xs = np.nonzero(px >= 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        k = (zo.DEPTH_OFF + zo.mba_z32(zo.PITCH, x, y)) // 4
        words[k] = (words[k] & 0xff000000) | depth
        words[(zo.COLOR_OFF + zo.linear32(zo.PITCH, x, y)) // 4] = int(px[y][x]) & M32
    return words


def block_from_pixels(px, depth=0xffffff):
    """the block an observed 64 x 64 pixel array implies (depth where colour covered)"""
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    ys, xs = np.nonzero(px >= 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        k = (zo.DEPTH_OFF + zo.mba_z32(zo.PITCH, x, y)) // 4
        words[k] = (words[k] & 0xff000000) | depth
        words[(zo.COLOR_OFF + zo.linear32(zo.PITCH, x, y)) // 4] = int(px[y][x]) & M32
    return words


def signatures(cases=None):
    """{hypothesis: tuple of coverage-map words per case} -- what the judge matches"""
    cases = cases or GATED
    return dict((h, tuple(tuple(coverage_map(c, h)) for c in cases)) for h in HYPS)


def classes(cases=None):
    by = {}
    for h, s in signatures(cases).items():
        by.setdefault(s, []).append(h)
    return list(by.values())


def self_test():
    bad = 0

    def expect(label, got, want):
        nonlocal bad
        ok = got == want
        print('  %-4s %-72s %s' % ('ok' if ok else 'FAIL', label, '' if ok else 'got %r want %r' % (got, want)))
        bad += 0 if ok else 1

    expect('4032 hypotheses, all distinct', (len(HYPS), len(set(HYPS))), (4032, 4032))
    expect('17 triangle cases numbered 9 .. 25', [CASE_NUM[n] for n in ORDER], list(range(9, 26)))
    allpts = [c for n in ORDER for pts, _ in TRI[n] for c in pts]
    expect('every vertex inside [0.5, 31] (fix() exact, map holds all)', all(0.5 <= f32(v) <= 31 for p in allpts for v in p), True)
    expect('float32 3.3 is 3.2999999523...', f32(3.3), 3.299999952316284)
    expect('largest edge product < 2^62', (64 * S) ** 2 * 2 < 2 ** 62, True)
    expect('no colour alpha is the pattern\'s 0xa5', [c[3] for c in (C1, C2, C3) if c[3] == 0xa5], [])
    expect('every triangle but T7 has one colour', [n for n in ORDER if n != 'T7' and
                                                     any(len(set(cols)) != 1 for _, cols in TRI[n])], [])
    # rounding modes on a half: 2.5 units of 1/2 at 1/2 precision
    half = S // 4                   # 1/4 pixel: the midpoint of the 1/2 grid
    expect('snap 1/2: trunc round even odd of 0.25', [snap(half, 2, m) / S for m in MODES], [0.0, 0.5, 0.0, 0.5])
    expect('snap 1/2: trunc round even odd of 0.75', [snap(3 * half, 2, m) / S for m in MODES], [0.5, 1.0, 1.0, 0.5])
    # tie labels, y down: T1 = (4,4) (28,4) (4,28) under the expected rule; edge 0->1 is the top edge
    t1 = cover(T1, (None, 'trunc', 0, 'tl', 'n'), 32)
    expect('offset 0, tl: the top edge row y=4 is in, x=4 column is in', (bool(t1[4][10]), bool(t1[10][4])), (True, True))
    t1b = cover(T1, (None, 'trunc', 0, 'br', 'n'), 32)
    expect('offset 0, br: the top edge row y=4 is out, x=4 column is out', (bool(t1b[4][10]), bool(t1b[10][4])), (False, False))
    t1r = TRI['T1r'][0][0]
    expect('winding w on T1r: w-tl equals n-br', (cover(t1r, (8, 'trunc', 8, 'tl', 'w')) == cover(t1r, (8, 'trunc', 8, 'br', 'n'))).all(), True)
    expect('winding n: T1r covers what T1 covers', (cover(t1r, EXPECTED) == cover(T1, EXPECTED)).all(), True)
    # the plan's reference counts (1/8 trunc, 1/2, top-left)
    expect('reference counts T1 T2 T5 T6', [int((pixels(n, EXPECTED) >= 0).sum()) for n in ('T1', 'T2', 'T5', 'T6')],
           [276, 300, 343, 273])
    t3 = pixels('T3', EXPECTED)
    expect('T3: 120 + 136 = the 16 x 16 square', (int((t3 == pixel(C1)).sum()), int((t3 == pixel(C2)).sum())), (120, 136))
    # separation (docs/R6D_PLAN.md 10)
    cl = classes()
    expect('T1-T6, X1-X8, Y1 split the 4032 gated hypotheses into more than 1157 classes', len(cl) > 1157, True)
    mine = [c for c in cl if EXPECTED in c][0]
    expect('the expected rule is alone in its class', mine, [EXPECTED])
    expect('its winding twin too', [c for c in cl if (8, 'trunc', 8, 'tl', 'w') in c][0], [(8, 'trunc', 8, 'tl', 'w')])
    # the map round-trips
    m = coverage_map('T3', EXPECTED)
    d = decode_map(m)
    expect('map: 64 words, codes 1 and 2 counted 120 and 136', (len(m), int((d == 1).sum()), int((d == 2).sum())), (64, 120, 136))
    expect('T7 map: the last vertex colour is code 1', map_colours('T7')[0], pixel(C1))
    g = (None, lambda n: snap(n, 8, 'trunc'), 8, 8, 'tl', 'n')
    expect('cover_general reproduces cover for the expected rule',
           (cover_general(T1, g[1], 8, 8, 'tl', 'n') == cover(T1, EXPECTED)).all(), True)
    fams = diagnostic_families()
    expect('diagnostic families: both double rounding and x/y-apart members exist',
           (len(fams) > 0, any(f[0] == 'double rounding' for f in fams), any(f[0] == 'x/y samples apart' for f in fams)),
           (True, True, True))
    expect('signed areas: X1 and X5 negative, T1 positive', (signed_area('X1') < 0, signed_area('X5') < 0, signed_area('T1') > 0),
           (True, True, True))
    ns = named_signatures()
    byk = {}
    for name, sg in ns:
        byk.setdefault(sg, []).append(name)
    mixed = [v for v in byk.values() if any(n[0] == 'gated' for n in v) and any(n[0] != 'gated' for n in v)]
    expect('named rules: 12384, no class mixes a gated rule with a diagnostic one (11)', (len(ns), len(mixed)), (12384, 0))
    expect('named rules: the expected rule alone', [v for v in byk.values() if ('gated', EXPECTED) in v][0], [('gated', EXPECTED)])
    expect('named rules: named_map agrees with coverage_map for the gated rules',
           all(named_map(c, r) == tuple(coverage_map(c, r[0][1])) for r in named_rules()[:40] for c in ('T1', 'T3')), True)
    expect('map distance counts pixels, not bits', (map_distance([3], [0]), map_distance([0b1110], [0b0100])), (1, 2))
    # the stream
    for n in ORDER:
        dw = draw_words(n, 0x1234)
        nv = nverts(n)
        hdr = dw[38]
        ok = (hdr >> 16) & 0x3fff == 5 * nv and dw[39] == vf_cntl(n) and len(dw) == 26 + 8 + 4 + 1 + 1 + 5 * nv + 10
        expect('%s: header counts %d words, VF_CNTL %08x, %d words (<= 96)' % (n, 5 * nv, vf_cntl(n), len(dw)),
               (ok, len(dw) <= 96), (True, True))
    expect('VF_CNTL T1 0x00030074, T3 0x00060074', (vf_cntl('T1'), vf_cntl('T3')), (0x00030074, 0x00060074))
    expect('headers 0xc00f3500 and 0xc01e3500', (draw_words('T1', 1)[38], draw_words('T3', 1)[38]), (0xc00f3500, 0xc01e3500))
    fw = zo.draw_words('F', 1)
    tw = draw_words('T1', 1)
    expect('T1 state and blend = F\'s', tw[:34], fw[:34])
    expect('T1 clip (0,0)-(63,63)', tw[35:38:2], [0, (63 << 16) | 63])
    expect('prefix = F\'s (SE_VTX_STATE_CNTL 0x10000)', prefix_words(0x29e000, 5)[9], 0x10000)
    print('tri_oracle self-test: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(self_test())
    sys.exit(__doc__)
