#!/usr/bin/env python3
"""R6e oracle (docs/R6E_PLAN.md 9-10): Gouraud-shaded TRIANGLES -- the ring words, the
byte planes every named interpolation rule predicts, and the equivalence classes the
judge matches, independent of the driver.

  gouraud_oracle.py --self-test

Coverage is the measured R6d rule (tri_oracle.MEASURED).  The colour interpolation
arithmetic is in no reference we have, so the oracle names rules:
  gated        setup position {exact, 1/16 trunc, 1/8 trunc} x sample (x+ox/16, y+oy/16),
               ox, oy in {0,4,8,12} x arithmetic {exact rational; slopes and intercept
               quantised to 2^-q (q 4 6 8 10 12 16, trunc = floor or round half up) and
               evaluated from an anchor (v0, top vertex, bbox origin, 8-pixel tile, each
               row's first covered sample = span stepping); float32 plane from v0, x term
               first} x input scale {c, c*256/255} x conversion {floor, round half up,
               half even, ceil}, clamped to 0..255              -- 23808 rules
  diagnostic   rules outside that space (codex 2nd review): q 5 7 9 11 13 14 15, toward-zero
               truncation, every 1/16 sample offset, rounded setup coordinates, float32
               y-first / FMA / float32 coefficients                -- 11176 rules
RGB planes and alpha planes are matched separately.  8-bit output cannot separate every
high-precision variant (exact, q >= 12, float32): those residual classes are a stated
measurement limit (docs/R6E_PLAN.md 9), not a pass under a wrong name.
"""

import hashlib
import importlib.util
import math
import os
import pickle
import sys
from fractions import Fraction as Fr

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location('tri_oracle', os.path.join(HERE, 'tri_oracle.py'))
to = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(to)
zo = to.zo
CACHE = os.path.join(PROJ, 'build', 'cache')

COV = to.MEASURED
POS = ('exact', 't16', 't8')
OFFS = [(ox, oy) for ox in (0, 4, 8, 12) for oy in (0, 4, 8, 12)]
ANCH = ('v0', 'top', 'bbox', 'tile8', 'row')
QS = (4, 6, 8, 10, 12, 16)
QM = ('trunc', 'round')
ARITH = [('exact',)] + [('q', q, m, a) for q in QS for m in QM for a in ANCH] + [('f32',)]
SCALE = ('c', 'c256')
FS = ('floor', 'round', 'even', 'ceil')
LANE_SHIFT = {'B': 0, 'G': 8, 'R': 16, 'A': 24}         # ARGB8888 (R6c, measured)
LANE_BIT = {'B': 1, 'G': 2, 'R': 4, 'A': 8}


def gated_rules():
    return [(p, o, a, sc, f) for p in POS for o in OFFS for a in ARITH for sc in SCALE for f in FS]


def diagnostic_rules():
    out = []
    for p in POS:
        for q in (5, 7, 9, 11, 13, 14, 15):
            for m in ('trunc', 'round', 'tz'):
                for a in ANCH:
                    for sc in SCALE:
                        for f in FS:
                            out.append((p, (8, 8), ('q', q, m, a), sc, f))
        for q in QS:
            for a in ANCH:
                for sc in SCALE:
                    for f in FS:
                        out.append((p, (8, 8), ('q', q, 'tz', a), sc, f))
        for ox in range(16):
            for oy in range(16):
                if (ox, oy) in OFFS:
                    continue
                for sc in SCALE:
                    for f in FS:
                        out.append((p, (ox, oy), ('exact',), sc, f))
        for var in ('yx', 'fma', 'c32'):
            for o in OFFS:
                for sc in SCALE:
                    for f in FS:
                        out.append((p, o, ('f32', var), sc, f))
    for p in ('r16', 'e16', 'r8', 'e8'):
        for o in OFFS:
            for a in (('exact',), ('f32',)):
                for sc in SCALE:
                    for f in FS:
                        out.append((p, o, a, sc, f))
    return out


ALL = gated_rules() + diagnostic_rules()
NG = len(gated_rules())


# ---- arithmetic -------------------------------------------------------------------

def pos(v, p):
    """setup coordinate: 'exact', or <t|r|e><prec> = trunc / round half up / even"""
    n = to.fix(v)
    if p != 'exact':
        n = to.snap(n, int(p[1:]), {'t': 'trunc', 'r': 'round', 'e': 'even'}[p[0]])
    return Fr(n, to.S)


def qz(v, q, m):
    """to 2^-q: trunc = floor (toward -inf), tz = toward zero, round = half up"""
    s = v * (1 << q)
    if m == 'trunc':
        k = math.floor(s)
    elif m == 'tz':
        k = math.floor(s) if s >= 0 else math.ceil(s)
    else:
        k = math.floor(s + Fr(1, 2))
    return Fr(k, 1 << q)


def conv(v, f):
    if f == 'floor':
        k = math.floor(v)
    elif f == 'ceil':
        k = math.ceil(v)
    elif f == 'round':
        k = math.floor(v + Fr(1, 2))
    else:
        k = round(v)                            # exact half to even on a Fraction
    return max(0, min(255, k))


def covered(pts):
    """the covered pixels in (x, y) order, measured rule, 32 x 32"""
    cov = to.cover(pts, COV, 32)
    return sorted((x, y) for y in range(32) for x in range(32) if cov[y][x])


def raw(pts, vals, r4):
    """{(x, y): exact interpolated value} for one channel under (pos, offset, arith, scale)"""
    p, o, a, sc = r4
    c = [Fr(v) if sc == 'c' else Fr(v * 256, 255) for v in vals]
    P = [(pos(x, p), pos(y, p)) for x, y in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    dx = ((c[1] - c[0]) * (y2 - y0) - (c[2] - c[0]) * (y1 - y0)) / A
    dy = ((c[2] - c[0]) * (x1 - x0) - (c[1] - c[0]) * (x2 - x0)) / A
    pix = covered(pts)
    smp = dict((xy, (Fr(16 * xy[0] + o[0], 16), Fr(16 * xy[1] + o[1], 16))) for xy in pix)
    out = {}
    if a[0] == 'exact':
        for xy in pix:
            sx, sy = smp[xy]
            out[xy] = c[0] + dx * (sx - x0) + dy * (sy - y0)
    elif a[0] == 'f32':
        f32 = np.float32
        var = a[1] if len(a) > 1 else 'xy'
        if var == 'c32':
            X = [f32(float(v[0])) for v in P]
            Y = [f32(float(v[1])) for v in P]
            C = [f32(float(v)) for v in c]
            A32 = f32(f32(f32(X[1] - X[0]) * f32(Y[2] - Y[0])) - f32(f32(X[2] - X[0]) * f32(Y[1] - Y[0])))
            dxf = f32(f32(f32(f32(C[1] - C[0]) * f32(Y[2] - Y[0])) - f32(f32(C[2] - C[0]) * f32(Y[1] - Y[0]))) / A32)
            dyf = f32(f32(f32(f32(C[2] - C[0]) * f32(X[1] - X[0])) - f32(f32(C[1] - C[0]) * f32(X[2] - X[0]))) / A32)
        else:
            dxf, dyf = f32(float(dx)), f32(float(dy))
        c0, x0f, y0f = f32(float(c[0])), f32(float(x0)), f32(float(y0))
        for xy in pix:
            sx, sy = smp[xy]
            tx = f32(f32(float(sx)) - x0f)
            ty = f32(f32(float(sy)) - y0f)
            if var == 'fma':
                v = f32(float(Fr(float(c0)) + Fr(float(dxf)) * Fr(float(tx)) + Fr(float(dyf)) * Fr(float(ty))))
            elif var == 'yx':
                v = f32(f32(c0 + f32(dyf * ty)) + f32(dxf * tx))
            else:
                v = f32(f32(c0 + f32(dxf * tx)) + f32(dyf * ty))
            out[xy] = Fr(float(v))
    else:
        _, q, m, an = a
        qx, qy = qz(dx, q, m), qz(dy, q, m)
        if an == 'row':
            rows = {}
            for xy in pix:
                rows.setdefault(xy[1], []).append(xy)
            for y, r in rows.items():
                sx0, sy0 = smp[min(r)]
                base = qz(c[0] + dx * (sx0 - x0) + dy * (sy0 - y0), q, m)
                for xy in r:
                    out[xy] = base + qx * (smp[xy][0] - sx0)
        else:
            if an == 'v0':
                ax, ay = x0, y0
            elif an == 'top':
                ax, ay = min(P, key=lambda v: (v[1], v[0]))
            elif an == 'bbox':
                ax, ay = min(v[0] for v in P), min(v[1] for v in P)
            else:
                ax = Fr(math.floor(min(v[0] for v in P) / 8) * 8)
                ay = Fr(math.floor(min(v[1] for v in P) / 8) * 8)
            base = qz(c[0] + dx * (ax - x0) + dy * (ay - y0), q, m)
            for xy in pix:
                sx, sy = smp[xy]
                out[xy] = base + qx * (sx - ax) + qy * (sy - ay)
    return out


def plane_bytes(pts, vals, rule):
    """the bytes over the covered pixels, in covered() order"""
    r = raw(pts, vals, rule[:4])
    return bytes(conv(r[xy], rule[4]) for xy in sorted(r))


# ---- the cases ------------------------------------------------------------------

T1 = to.T1
T1R = [T1[0], T1[2], T1[1]]
X3 = list(to.TRI['X3'][0][0])
T6 = list(to.TRI['T6'][0][0])
G0 = (0x9a, 0xbc, 0xde, 0x3c)
_S1 = [(28.774, 29.216), (25.137, 13.404), (5.137, 26.087)]
R_CASES = [                                  # (name, vertices, R = A triple)
    ('G1', T1, (0, 240, 0)), ('G2', T1, (0, 0, 240)), ('G3', X3, (17, 201, 90)),
    ('S1', _S1, (187, 206, 227)),
    ('S2', [(27.352, 13.0), (5.411, 29.556), (10.25, 2.826)], (122, 116, 117)),
    ('S3', [(2.213, 5.419), (26.542, 5.185), (29.784, 25.763)], (70, 245, 69)),
    ('S4', [(3.377, 27.818), (28.35, 19.944), (29.171, 3.522)], (220, 117, 0)),
    ('S5', [(4.233, 29.362), (7.131, 6.32), (22.141, 25.017)], (78, 69, 71)),
    ('S6', [(26.368, 24.337), (4.482, 3.261), (22.463, 2.605)], (71, 69, 67)),
    ('S7', [(28.922, 19.738), (4.82, 25.668), (9.534, 10.378)], (42, 40, 46)),
    ('S8', [(6.609, 28.504), (11.321, 4.188), (27.931, 3.654)], (94, 97, 98)),
    ('H1', T1, (0, 24, 0)), ('H2', T1, (0, 0, 24)),
    ('P1', [_S1[1], _S1[2], _S1[0]], (206, 227, 187)),
    ('M1', [(x - 1.5, y - 1.5) for x, y in _S1], (187, 206, 227)),
    ('E1', T1R, (200, 0, 56)), ('E2', T1R, (200, 80, 40)), ('E3', T1R, (248, 80, 0)), ('E4', T1R, (248, 40, 200)),
]
G7 = {'R': (13, 201, 77), 'G': (240, 5, 130), 'B': (60, 61, 250), 'A': (190, 30, 110)}
G7P = {'R': (240, 5, 130), 'G': (60, 61, 250), 'B': (190, 30, 110), 'A': (13, 201, 77)}


def _verts(tr):
    """per-vertex (r, g, b, a) from {lane: triple}"""
    return [tuple(tr[l][i] for l in 'RGBA') for i in range(3)]


GCASES = {}                                    # name: (vertices, [(r,g,b,a)] x3, logged lanes, varying lanes)
GCASES['G0'] = (T1, [G0] * 3, 'RGBA', '')
for _n, _p, _t in R_CASES:
    GCASES[_n] = (_p, _verts({'R': _t, 'G': (0x34,) * 3, 'B': (0x56,) * 3, 'A': _t}), 'RA', 'RA')
GCASES['G4'] = (X3, _verts({'R': (0x12,) * 3, 'G': (17, 201, 90), 'B': (0x56,) * 3, 'A': (0x78,) * 3}), 'G', 'G')
GCASES['G5'] = (X3, _verts({'R': (0x12,) * 3, 'G': (0x34,) * 3, 'B': (17, 201, 90), 'A': (0x78,) * 3}), 'B', 'B')
GCASES['G7'] = (T6, _verts(G7), 'RGBA', 'RGBA')
GCASES['G7p'] = (T6, _verts(G7P), 'RGBA', 'RGBA')
ORDER = ['G0'] + [n for n, _, _ in R_CASES] + ['G4', 'G5', 'G7', 'G7p']
FIRST = 26                                     # case numbers 26 .. 49 (after R6d's 9 .. 25)
CASE_NUM = dict((n, FIRST + k) for k, n in enumerate(ORDER))

# R6e-3 (docs/R6E_PLAN.md 18): the confirmation cases -- a separate list, so the r6e gate planes and
# their signature cache stay as they were
CONFIRM = [
    ('D1', [(26.375, 28.9375), (4.5, 25.875), (7.5, 8.375)], (175, 143, 164)),
    ('D2', [(5.9375, 12.6875), (17.1875, 13.3125), (5.9375, 28.6875)], (190, 11, 5)),
    ('V1', [(9.106, 9.367), (17.943, 26.739), (28.858, 24.81)], (14, 53, 199)),
    ('V2', [(24.364, 6.337), (15.942, 6.302), (25.224, 21.276)], (109, 97, 138)),
    ('V3', [(18.143, 5.064), (5.48, 8.217), (7.557, 20.637)], (61, 241, 217)),
    ('V4', [(29.138, 19.064), (10.096, 7.999), (4.773, 21.81)], (119, 25, 209)),
    ('V5', [(21.424, 29.0), (11.941, 28.027), (5.361, 4.752)], (155, 195, 101)),
    ('V6', [(10.759, 12.564), (22.977, 7.873), (29.018, 17.826)], (68, 219, 213)),
    ('V7', [(10.175, 26.275), (2.842, 15.669), (29.492, 29.646)], (154, 255, 206)),
]
for _n, _p, _t in CONFIRM:
    GCASES[_n] = (_p, _verts({'R': _t, 'G': (0x34,) * 3, 'B': (0x56,) * 3, 'A': _t}), 'RA', 'RA')
GCASES['V8'] = ([(16.976, 7.084), (3.534, 14.673), (2.293, 26.525)],
                _verts({'R': (238, 122, 16), 'G': (138, 253, 151), 'B': (31, 134, 196), 'A': (115, 53, 68)}), 'RGBA', 'RGBA')
ORDER3 = ['V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7', 'V8', 'D1', 'D2']
CASE_NUM.update(dict((n, 50 + k) for k, n in enumerate(ORDER3)))
ALL_ORDER = ORDER + ORDER3                      # case numbers 26 .. 59 in order
SE_CNTL_FLAT = 0x480055de


def se_cntl_gouraud():
    """the precedent's SE_CNTL with diffuse and alpha GOURAUD (Mesa macros) -- 0x48005ade"""
    m = zo.M
    return ((SE_CNTL_FLAT & ~(m('R200_DIFFUSE_SHADE_MASK') | m('R200_ALPHA_SHADE_MASK'))) |
            m('R200_DIFFUSE_SHADE_GOURAUD') | m('R200_ALPHA_SHADE_GOURAUD'))


def lane_triple(case, lane):
    return tuple(v['RGBA'.index(lane)] for v in GCASES[case][1])


def const_pixel(case):
    """the pixel's constant lanes (the varying ones zero) and the varying-lane mask"""
    verts, vary = GCASES[case][1], GCASES[case][3]
    px = 0
    for lane in 'RGBA':
        if lane not in vary:
            px |= verts[0]['RGBA'.index(lane)] << LANE_SHIFT[lane]
    return px, sum(LANE_BIT[l] for l in vary)


def lanes_mask(case):
    return sum(LANE_BIT[l] for l in GCASES[case][2])


def draw_words(case, seed):
    """R6d's triangle stream (tri_oracle) with SE_CNTL's value word GOURAUD and the case's
    per-vertex colours"""
    fw = zo.draw_words('F', seed)
    state, pix, tail = fw[:26], fw[26:34], fw[-10:]
    assert state[14] == zo.p0(zo.V('RADEON_SE_CNTL')) and state[15] == SE_CNTL_FLAT
    state = state[:15] + [se_cntl_gouraud()] + state[16:]
    x1, y1, x2, y2 = to.CLIP
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]
    pts, cols = GCASES[case][0], GCASES[case][1]
    body = [to.zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') | zo.M('R200_VF_COLOR_ORDER_RGBA') | (3 << 16)]
    for (x, y), c in zip(pts, cols):
        body += [to.fbits(x), to.fbits(y), to.fbits(to.Z), to.fbits(1.0), to.word(c)]
    hdr = zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)
    return state + pix + clip + [hdr] + body + tail


def rule_b(pts, vals, wmode='round'):
    """rule B (docs/R6E_PLAN.md 18, found on boot ff63a8c4's planes): vertices truncated to 1/16, sample at
    pixel + 1/2, exact barycentric weights; the two weights other than the leftmost vertex's (x ties: the
    upper, smaller y) rounded to 1/256 (wmode 'round' half up, 'even' half to even), the leftmost vertex's
    weight = 1 - those two; value = the exact weighted sum, floored, clamped -- bytes in covered() order"""
    P = [(pos(x, 't16'), pos(y, 't16')) for x, y in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    L = min(range(3), key=lambda i: (P[i][0], P[i][1]))
    out = []
    for x, y in covered(pts):
        sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        w = [1 - w1 - w2, w1, w2]
        for i in range(3):
            if i != L:
                z = w[i] * 256
                w[i] = Fr(math.floor(z + Fr(1, 2)) if wmode == 'round' else round(z), 256)
        w[L] = 1 - sum(w[i] for i in range(3) if i != L)
        out.append(max(0, min(255, math.floor(sum(wi * Fr(ci) for wi, ci in zip(w, vals))))))
    return bytes(out)


def plane_words(values):
    """the 256 words the driver logs for one lane: byte (x, y) of the 32 x 32 at word
    (y*32+x)//4, bits 8*((y*32+x)%4); uncovered pixels 0.  values: {(x, y): byte}"""
    w = [0] * 256
    for (x, y), b in values.items():
        i = y * 32 + x
        w[i // 4] |= (b & 0xff) << (8 * (i % 4))
    return w


def unpack_plane(words, pix):
    """the bytes of the covered pixels (covered() order) from the 256 logged words"""
    return bytes((words[(y * 32 + x) // 4] >> (8 * ((y * 32 + x) % 4))) & 0xff for x, y in pix)


def expected_values(case, lane, rule):
    pts = GCASES[case][0]
    b = plane_bytes(pts, lane_triple(case, lane), rule)
    return dict(zip(covered(pts), b))


def expected_block(case, rule_rgb, rule_a):
    """the 256 KiB block after ZPREP then ZCLEAR <case>: colour linear, depth tiled"""
    pts, cols = GCASES[case][0], GCASES[case][1]
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    px = dict((xy, 0) for xy in covered(pts))
    for lane in 'RGBA':
        tr = lane_triple(case, lane)
        vals = dict(zip(covered(pts), plane_bytes(pts, tr, rule_a if lane == 'A' else rule_rgb)))
        for xy in px:
            px[xy] |= vals[xy] << LANE_SHIFT[lane]
    for (x, y), v in px.items():
        k = (zo.DEPTH_OFF + zo.mba_z32(zo.PITCH, x, y)) // 4
        words[k] = (words[k] & 0xff000000) | 0xffffff
        words[(zo.COLOR_OFF + zo.linear32(zo.PITCH, x, y)) // 4] = v
    return words


# ---- the planes the gate matches, and their signatures ----------------------------

def gate_planes(kind):
    """[(case, lane)] for 'RGB' or 'A' -- every logged plane of that kind"""
    out = []
    for n in ORDER:
        for lane in GCASES[n][2]:
            if (lane == 'A') == (kind == 'A'):
                out.append((n, lane))
    return out


def _digest(b):
    return hashlib.blake2b(b, digest_size=8).digest()


def _plane_sig(key):
    pts, tr = key
    return [_digest(plane_bytes(pts, tr, r)) for r in ALL]


def _src_hash():
    h = hashlib.sha256()
    for f in ('gouraud_oracle.py', 'tri_oracle.py'):
        h.update(open(os.path.join(HERE, f), 'rb').read())
    return h.hexdigest()[:16]


def signatures(kind, procs=30):
    """{rule index: tuple of plane digests} over the gate planes of kind, cached on disk by
    the oracle's source hash"""
    planes = gate_planes(kind)
    keys = list(dict.fromkeys((tuple(GCASES[n][0]), lane_triple(n, l)) for n, l in planes))
    path = os.path.join(CACHE, 'gouraud-%s-%s.pkl' % (kind, _src_hash()))
    if os.path.exists(path):
        return pickle.load(open(path, 'rb'))
    # the oracles are loaded by path (importlib.util), so this module may not be in sys.modules --
    # Pool pickles _plane_sig by name and needs to find this very function there
    import types
    me = sys.modules.get(__name__)
    if getattr(me, '_plane_sig', None) is not _plane_sig:
        me = types.ModuleType(__name__)
        me.__dict__.update(globals())
        sys.modules[__name__] = me
    from multiprocessing import Pool
    with Pool(procs) as pool:
        cols = pool.map(_plane_sig, keys)
    per_key = dict(zip(keys, cols))
    sig = [tuple(per_key[(tuple(GCASES[n][0]), lane_triple(n, l))][k] for n, l in planes) for k in range(len(ALL))]
    os.makedirs(CACHE, exist_ok=True)
    pickle.dump((planes, sig), open(path, 'wb'))
    return planes, sig


def classes(kind):
    planes, sig = signatures(kind)
    by = {}
    for k, s in enumerate(sig):
        by.setdefault(s, []).append(k)
    return planes, sig, by


def observed_sig(planes, observed):
    """observed: {(case, lane): 256 words}"""
    return tuple(_digest(unpack_plane(observed[(n, l)], covered(GCASES[n][0]))) for n, l in planes)


def high_precision(rule):
    a = rule[2]
    return a[0] != 'q' or a[1] >= 10


def self_test():
    bad = 0

    def expect(label, got, want):
        nonlocal bad
        ok = got == want
        print('  %-4s %-74s %s' % ('ok' if ok else 'FAIL', label, '' if ok else 'got %r want %r' % (got, want)))
        bad += 0 if ok else 1

    expect('rule counts: 23808 gated + 11176 diagnostic, disjoint', (NG, len(ALL) - NG, len(set(ALL))), (23808, 11176, 34984))
    expect('coverage is the measured R6d rule (1/16 trunc, 1/2, tl, n)', COV, (16, 'trunc', 8, 'tl', 'n'))
    expect('covered pixels: T1 276, X3 137, T6 275', [len(covered(p)) for p in (T1, X3, T6)], [276, 137, 275])
    expect('SE_CNTL gouraud (diffuse + alpha) = 0x48005ade', se_cntl_gouraud(), 0x48005ade)
    expect('24 cases numbered 26 .. 49', [CASE_NUM[n] for n in ORDER], list(range(26, 50)))
    # pattern safety: equal to the pattern word needs alpha 0xa5 AND red 0 (pattern 0xa5000000 | i)
    unsafe = []
    for n in ORDER:
        r, a = lane_triple(n, 'R'), lane_triple(n, 'A')
        can_a = min(a) <= 0xa5 <= max(a)
        can_r = min(r) == 0
        same = r == a
        if can_a and can_r and not same:
            unsafe.append(n)
    expect('no case can leave a pixel equal to the pattern', unsafe, [])
    dup = []
    for n in ORDER:
        cl = [lane_triple(n, l)[0] for l in 'RGBA' if l not in GCASES[n][3]]
        if n != 'G0' and len(set(cl)) != len(cl):
            dup.append(n)
        if any(len(set(lane_triple(n, l))) != 1 for l in 'RGBA' if l not in GCASES[n][3]):
            dup.append(n + ' (a constant lane varies)')
    expect('every case: constant lanes hold distinct values and do not vary', dup, [])
    # arithmetic spot checks (docs/R6E_PLAN.md 7, 10): G1 integers, X3 slopes, E1 halves
    g1 = raw(T1, (0, 240, 0), ('t16', (8, 8), ('exact',), 'c'))
    expect('G1: every exact value is an integer (10(x-3.5))', all(v.denominator == 1 for v in g1.values()), True)
    e = [raw(T1R, t, ('t16', (8, 8), ('exact',), 'c')) for t in ((200, 0, 56), (200, 80, 40), (248, 80, 0), (248, 40, 200))]
    expect('E1..E4: 92 half, 92 half, 92 integer, 92 integer hits',
           [(sum(v.denominator == 1 for v in d.values()), sum(v.denominator == 2 for v in d.values())) for d in e],
           [(0, 92), (0, 92), (92, 0), (92, 0)])
    expect('H1: every value is x - 3.5 (a half)', all(v.denominator == 2 for v in raw(T1, (0, 24, 0), ('t16', (8, 8), ('exact',), 'c')).values()), True)
    expect('conversions of 5/2: floor round even ceil', [conv(Fr(5, 2), f) for f in FS], [2, 3, 2, 3])
    expect('clamp: 256 -> 255, -1 -> 0', (conv(Fr(256), 'floor'), conv(Fr(-1), 'floor')), (255, 0))
    expect('toward-zero vs floor of -3/2', (qz(Fr(-3, 2), 0, 'tz'), qz(Fr(-3, 2), 0, 'trunc')), (-1, -2))
    expect('M1 is S1 - 1.5 in float32', [to.fbits(x) for x, _ in GCASES['M1'][0]],
           [to.fbits(to.f32(to.f32(x) - 1.5)) for x, _ in _S1])
    w = plane_words({(1, 0): 0xab, (0, 1): 0xcd})
    expect('plane packing: (1,0) byte 1 of word 0, (0,1) byte 0 of word 8', (w[0], w[8]), (0xab00, 0xcd))
    # the stream
    dw = draw_words('S1', 0x1234)
    expect('S1: 65 words, header 0xc00f3500, SE_CNTL word 0x48005ade', (len(dw), dw[38], dw[15]), (65, 0xc00f3500, 0x48005ade))
    fw = to.draw_words('T1', 0x1234)
    expect('only the SE_CNTL word differs from R6d\'s stream (besides the vertices)',
           [k for k in range(38) if dw[k] != fw[k]], [15])
    expect('S1 vertex 0: R and A both carry 187 (colour word bytes r and a)',
           (to.word(GCASES['S1'][1][0]) & 0xff, to.word(GCASES['S1'][1][0]) >> 24), (187, 187))
    # the audit (docs/R6E_PLAN.md 9): cached after the first run
    for kind, want_cls in (('RGB', 26281), ('A', 26010)):
        planes, sig, by = classes(kind)
        mixed = [v for v in by.values() if any(k < NG for k in v) and any(k >= NG for k in v)]
        structural = [v for v in mixed if not all(high_precision(ALL[k]) for k in v)]
        expect('%s: %d planes, %d classes' % (kind, len(planes), want_cls), len(by), want_cls)
        expect('%s: no mixed class holds a low-precision (q < 10) rule' % kind, len(structural), 0)
        m = [v for v in by.values() if ALL.index(('t16', (8, 8), ('q', 8, 'trunc', 'v0'), 'c', 'floor')) in v][0]
        expect('%s: a low-precision rule (q8 trunc v0 floor) is alone' % kind, len(m), 1)
    # R6e-3 (docs/R6E_PLAN.md 18)
    expect('R6e-3: ten cases numbered 50 .. 59', [CASE_NUM[n] for n in ORDER3], list(range(50, 60)))
    expect('R6e-3: D1 D2 split half-up from even (3 and 14 bytes)',
           [sum(1 for a, b in zip(rule_b(GCASES[n][0], lane_triple(n, 'R'), 'round'),
                                  rule_b(GCASES[n][0], lane_triple(n, 'R'), 'even')) if a != b) for n in ('D1', 'D2')], [3, 14])
    expect('R6e-3: V8 red never 0 (pattern-safe with any alpha)', min(lane_triple('V8', 'R')) > 0, True)
    g1 = dict(zip(covered(T1), rule_b(T1, (0, 240, 0))))
    expect('rule B on G1 row y=4 = the measured 4 15 25 34 45 (boot ff63a8c4)', [g1[(x, 4)] for x in range(4, 9)], [4, 15, 25, 34, 45])
    print('gouraud_oracle self-test: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(self_test())
    sys.exit(__doc__)
