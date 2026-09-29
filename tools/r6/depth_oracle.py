#!/usr/bin/env python3
"""R6f oracle (docs/R6F_PLAN.md 3): depth VALUES -- the 16-bit format's placement, the
float z -> integer conversion, and the depth planes of z-sloped triangles.

  depth_oracle.py --self-test
  depth_oracle.py --c-tables        the C rows the driver carries (osrdn_cp.m)
  depth_oracle.py --separation      the anchors against the whole conversion space (slow, ~1 min)

Cases 60-81: K16a-d / K24a-d draw a grid of 16 constant-z cells (the 64 anchors), I1-I7 draw one
triangle with a z per vertex, once at 24 and once at 16 bits.  Colour is flat C1 (the coverage
map, R6d rule); the depth buffer is read back as planes (driver dsrc 1: 24-bit, mba_z32, lanes
0-2; dsrc 2: 16-bit, mba_z16, lanes 0-1).

The conversion space (plan 3-1, widened after codex Q3, plan 8): z pre-quantised to 2^-q
(none, 16, 20, 24, 32; floor / round) x scale {2^n - 1, 2^n} x {floor, round half up, half
even, ceil}; 16-bit also from a 24-bit value (>> 8, rounded >> 8) and a float32 product;
float intermediates with 10-22 mantissa bits, fixed intermediates 2^-8..2^-14, scale 2^n - 2,
and (24-bit) a 16-bit value expanded.  The 64 anchors separate every class of both spaces
(docs/R6F_PLAN.md 3-1; --separation re-proves it).
"""

import importlib.util
import math
import os
import random
import struct
import sys
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('gouraud_oracle', os.path.join(HERE, 'gouraud_oracle.py'))
go = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(go)
to = go.to
zo = to.zo
M32 = 0xffffffff

# ---- the conversion space ------------------------------------------------------------

def f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def fromhex(h):
    return struct.unpack('<f', struct.pack('<I', int(h, 16)))[0]


def tohex(z):
    return '%08x' % struct.unpack('<I', struct.pack('<f', float(z)))[0]


def rnd(v, m):
    f = math.floor(v)
    if m == 'floor':
        return f
    if m == 'up':
        return math.floor(v + Fr(1, 2))
    if m == 'even':
        return round(v)
    if m == 'ceil':
        return math.ceil(v)
    raise ValueError(m)


def _e(z):
    e = 0
    while Fr(2) ** e > z:
        e -= 1
    while Fr(2) ** (e + 1) <= z:
        e += 1
    return e


def _fq(z, mb, m):
    """z to a float with mb fraction bits (rounding m)"""
    z = Fr(z)
    if z == 0:
        return z
    s = Fr(2) ** (mb - _e(z))
    return Fr(rnd(z * s, m)) / s


def _space_base(bits):
    out = {}
    top = (1 << bits) - 1
    for q in (None, 16, 20, 24, 32):
        for qm in ('floor', 'up'):
            if q is None and qm == 'up':
                continue
            for scale in ('m1', 'p2'):
                for m in ('floor', 'up', 'even', 'ceil'):
                    def h(z, q=q, qm=qm, scale=scale, m=m):
                        zz = Fr(z) if q is None else Fr(rnd(Fr(z) * (1 << q), qm), 1 << q)
                        return max(0, min(top, rnd(zz * (top if scale == 'm1' else (1 << bits)), m)))
                    out[('q%s%s' % (q, qm if q else ''), scale, m)] = h
    if bits == 16:
        for k, h24 in _space_base(24).items():
            for sm in ('shift', 'up'):
                def h(z, h24=h24, sm=sm):
                    v = h24(z)
                    return v >> 8 if sm == 'shift' else min(0xffff, (v + 128) >> 8)
                out[('from24',) + k + (sm,)] = h
    for m in ('floor', 'up', 'even'):
        def h(z, m=m):
            return max(0, min(top, rnd(Fr(f32(z * top)), m)))
        out[('f32prod', m)] = h
    return out


def space(bits):
    """{name: function(float z) -> integer depth} -- docs/R6F_PLAN.md 3-1 and 8"""
    out = _space_base(bits)
    top = (1 << bits) - 1
    for mb in (10, 12, 14, 16, 18, 20, 22):
        for qm in ('floor', 'even'):
            for sc in ('m1', 'p2'):
                for m in ('floor', 'up', 'even'):
                    out[('fp', mb, qm, sc, m)] = (lambda z, mb=mb, qm=qm, sc=sc, m=m:
                        max(0, min(top, rnd(_fq(z, mb, qm) * (top if sc == 'm1' else (1 << bits)), m))))
    for q in (8, 10, 12, 14):
        for qm in ('floor', 'up', 'even'):
            for m in ('floor', 'up', 'even'):
                out[('fx', q, qm, m)] = (lambda z, q=q, qm=qm, m=m:
                    max(0, min(top, rnd(Fr(rnd(Fr(z) * (1 << q), qm), 1 << q) * top, m))))
    for m in ('floor', 'up', 'even'):
        out[('res1', m)] = lambda z, m=m: max(0, min(top, rnd(Fr(z) * (top - 1), m)))
    if bits == 24:
        for m1 in ('floor', 'even'):
            for m2 in ('floor', 'even'):
                out[('u16to24', m1, m2)] = (lambda z, m1=m1, m2=m2:
                    max(0, min(top, rnd(Fr(rnd(Fr(z) * 65535, m1)) * top / 65535, m2))))
    return out


# the 64 anchors (build/r6f/anchors.py): 50 separators of the space, then seed 62306
ANCHORS = [fromhex(h) for h in (
    '3cd54000 3f419601 3f0007ff 3cb63000 3ce990e9 3f08cd00 3f00c68a 3f102891 3ef0aef0 3ce981d2 3d95e095 3ec230c3 '
    '3cafffff 3ce99001 3f00d17f 3e746203 3ef942ff 3f000800 3ec1d5c2 3ef0aff1 3d56f8d7 3f72a873 3f732ef3 3cb00001 '
    '3cb40000 3cd00000 3e387002 3e42b9fd 3ee0ffff 3f00d180 3cb62fff 3ce99000 3ce991d2 3e746204 3ebe4ffe 3e56d6d7 '
    '3f5a7f3e 3cc076d0 3d086b37 3cf50000 3cc076d1 377f1dfb 38d00b9d 358401b3 3a11f203 3584473d 36ba0076 36e601b3 '
    '35dffc1a 36aaff66 3eccea02 3f07e348 3f25b44e 3e947a9f 3ec61708 3eac5920 3e5fb5ff 3dbc9d98 3ea9bf97 3e7dde01 '
    '3f6c8d12 3e96fc07 3e353f32 3dbe9294').split()]

# ---- the cases ---------------------------------------------------------------------

C1 = to.C1                                      # (0x12, 0x34, 0x56, 0x78): word 0x78563412, pixel 0x78123456
CELLS = [(2 + 8 * i, 2 + 8 * j) for j in range(4) for i in range(4)]
LEG = 3
ZCNTL = {24: 0x42227072, 16: 0x42227070}        # the precedent / its format field 16-bit (plan D2)
SE_CNTL_FLAT = 0x480055de
GEOM = {'T1z': to.T1, 'X3z': list(to.TRI['X3'][0][0]), 'S1z': go.GCASES['S1'][0],
        'V1z': go.GCASES['V1'][0], 'V4z': go.GCASES['V4'][0]}
TRI_ORDER = ['T1z', 'X3z', 'S1z', 'V1z', 'V4z']  # cpR6Tris rows 52 .. 56
TRI_FIRST = 52
ICASES = {                                      # name: (geometry, z per vertex as float32 hex)
    'I1': ('T1z', ('3e800000', '3f400000', '3e800000')),
    'I2': ('T1z', ('3e800000', '3e800000', '3f400000')),
    'I3': ('X3z', ('3f0f5455', '3ecd9065', '3f523f1a')),        # seed 62307
    'I4': ('S1z', ('3f48a4eb', '3f0d2317', '3dff6d84')),
    'I5': ('V1z', ('3f000000', '3f001000', '3effd000')),        # 0.5, 0.5 + 2^-12, 0.5 - 3 * 2^-13
    'I6': ('V4z', ('3cf5c28f', '3f7851ec', '3f000000')),        # 0.03, 0.97, 0.5
    'I7': ('V1z', ('3f0019eb', '3d8dc548', '3e1bf7f9')),
}
IORDER = ['I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7']
ORDER = (['K16a', 'K16b', 'K16c', 'K16d', 'K24a', 'K24b', 'K24c', 'K24d'] +
         [n + '_24' for n in IORDER] + [n + '_16' for n in IORDER])
FIRST = 60
CASE_NUM = dict((n, FIRST + k) for k, n in enumerate(ORDER))
LAST = FIRST + len(ORDER) - 1                   # 81 = CP_R6_CASES
WORDS_MAX = 4080                                 # CP_R6_WORDS: the biggest client submission
                                                 # (4068, G4-3 K4 / build/r7/design3.py) plus
                                                 # the driver's WAIT_UNTIL and tail (12), rounded to 16


def fmt_bits(case):
    return 16 if case.startswith('K16') or case.endswith('_16') else 24


def grid_index(case):
    """1 + the anchor row (cpR6GridZ), 0 for a triangle case"""
    return 'abcd'.index(case[3]) + 1 if case.startswith('K') else 0


def zrow_index(case):
    return IORDER.index(case[:2]) + 1 if case.startswith('I') else 0


def tri_index(case):
    return TRI_FIRST + TRI_ORDER.index(ICASES[case[:2]][0]) if case.startswith('I') else 0


def dsrc(case):
    return 2 if fmt_bits(case) == 16 else 1


def lanes(case):
    return 0x3 if fmt_bits(case) == 16 else 0x7


def cell_tri(x0, y0):
    return [(float(x0), float(y0)), (float(x0 + LEG), float(y0)), (float(x0), float(y0 + LEG))]


def triangles(case):
    """[(vertices, z per vertex (float))] in packet order"""
    if case.startswith('K'):
        zs = ANCHORS[16 * (grid_index(case) - 1):16 * grid_index(case)]
        return [(cell_tri(x0, y0), (z, z, z)) for (x0, y0), z in zip(CELLS, zs)]
    g, zh = ICASES[case[:2]]
    return [(GEOM[g], tuple(fromhex(h) for h in zh))]


def covered(case):
    """{(x, y)} the colour buffer covers (measured R6d rule), 32 x 32"""
    out = set()
    for pts, _ in triangles(case):
        out |= set(go.covered(pts))
    return out


# ---- the ring words ------------------------------------------------------------------

def draw_words(case, seed):
    """R6c F's state (SE_CNTL flat, ZSTENCILCNTL by format) and blend stage, the whole-buffer
    clip, one 3D_DRAW_IMMD_2 with every triangle (x, y, z, 1.0, C1), the tail"""
    fw = zo.draw_words('F', seed)
    state, pix, tail = fw[:26], fw[26:34], fw[-10:]
    assert state[8] == zo.p0(zo.V('RADEON_RB3D_ZSTENCILCNTL')) and state[9] == ZCNTL[24]
    assert state[14] == zo.p0(zo.V('RADEON_SE_CNTL')) and state[15] == SE_CNTL_FLAT
    state = state[:9] + [ZCNTL[fmt_bits(case)]] + state[10:]
    x1, y1, x2, y2 = to.CLIP
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]
    tris = triangles(case)
    body = [vf_cntl(case)]
    for pts, zs in tris:
        for (x, y), z in zip(pts, zs):
            body += [to.fbits(x), to.fbits(y), to.fbits(z), to.fbits(1.0), to.word(C1)]
    hdr = zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)
    return state + pix + clip + [hdr] + body + tail


def nverts(case):
    return 3 * len(triangles(case))


def vf_cntl(case):
    return (zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') | zo.M('R200_VF_COLOR_ORDER_RGBA') |
            (nverts(case) << 16))


def header(case):
    return zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), 5 * nverts(case))


# ---- the depth buffer ----------------------------------------------------------------

PITCH = 64


def _bit(v, b):
    return (v >> b) & 1


def mba_z16(x, y, pitch=PITCH):
    """Mesa 6.5.3 r200_span.c r200_mba_z16, depthHasSurface false"""
    b = ((y & 0x7ff) >> 4) * ((pitch & 0xfff) >> 6) + ((x & 0x7ff) >> 6)
    par = (b & 1) if (pitch & 0x40) else ((b & 1) ^ _bit(y, 4))
    return ((_bit(x, 0) << 1) | (_bit(y, 0) << 2) | (_bit(x, 1) << 3) | (_bit(y, 1) << 4) | (_bit(x, 2) << 5) |
            (_bit(x, 4) << 6) | (_bit(x, 5) << 7) | (_bit(x, 3) << 8) | (_bit(y, 2) << 9) | (_bit(y, 3) << 10) |
            (par << 11) | ((b >> 1) << 12))


def mba_z32(x, y, pitch=PITCH):
    return zo.mba_z32(pitch, x, y)


def pattern_block():
    """the depth buffer (4096 words, block words 0 ..) as ZPREP leaves it"""
    return [zo.pattern(i) for i in range(zo.BUF_BYTES // 4)]


def read_depth(block, x, y, bits):
    if bits == 24:
        return block[mba_z32(x, y) // 4] & 0xffffff
    a = mba_z16(x, y)
    return (block[a // 4] >> (16 * ((a >> 1) & 1))) & 0xffff


def put_depth(block, x, y, bits, v):
    if bits == 24:
        k = mba_z32(x, y) // 4
        block[k] = (block[k] & 0xff000000) | (v & 0xffffff)
    else:
        a = mba_z16(x, y)
        s = 16 * ((a >> 1) & 1)
        block[a // 4] = (block[a // 4] & ~(0xffff << s) & M32) | ((v & 0xffff) << s)


def block_from_values(values, bits):
    """{(x, y): depth} over the pattern"""
    b = pattern_block()
    for (x, y), v in values.items():
        put_depth(b, x, y, bits, v)
    return b


def plane_words(block, bits):
    """{lane: 256 words} the driver logs for a depth source: pixel i = y*32+x, byte i%4 of word i//4,
    lane l = byte l of the pixel's depth"""
    out = {}
    for l in range(3 if bits == 24 else 2):
        w = [0] * 256
        for y in range(32):
            for x in range(32):
                i = y * 32 + x
                w[i // 4] |= ((read_depth(block, x, y, bits) >> (8 * l)) & 0xff) << (8 * (i % 4))
        out[l] = w
    return out


def values_from_planes(planes, bits):
    """{(x, y): depth} for the 32 x 32 from logged planes {lane: 256 words}"""
    out = {}
    for y in range(32):
        for x in range(32):
            i = y * 32 + x
            out[(x, y)] = sum(((planes[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in planes)
    return out


def digest(block):
    return zo.digest(block, 0, len(block))


def cell_values(case, vals):
    """the grid's 16 cells: [(anchor z, [values of the cell's covered pixels])]"""
    zs = ANCHORS[16 * (grid_index(case) - 1):16 * grid_index(case)]
    return [(z, [vals[p] for p in sorted(go.covered(cell_tri(x0, y0)))]) for (x0, y0), z in zip(CELLS, zs)]


def classes(bits, zs=None):
    """{signature on zs (default the 64 anchors): [names]}"""
    zs = ANCHORS if zs is None else zs
    out = {}
    for k, h in space(bits).items():
        out.setdefault(tuple(h(z) for z in zs), []).append(k)
    return out


def name_conversion(bits, observed):
    """observed: the 64 anchor values (None where unread) -> (matching names, [(name, differing anchors)] nearest 3)"""
    sp = space(bits)
    hit, near = [], []
    for k, h in sp.items():
        d = sum(1 for z, v in zip(ANCHORS, observed) if v is not None and h(z) != v)
        (hit if d == 0 else near).append((k, d))
    near.sort(key=lambda t: t[1])
    return [k for k, _ in hit], near[:3]


# ---- R6g: the depth test (docs/R6G_PLAN.md 2, 6) -------------------------------------------

C2 = to.C2                                      # the second draw's colour (word 0x3cdebc9a, pixel 0x3c9abcde)
ZFUNC = {'NEVER': 0, 'LESS': 1, 'LEQUAL': 2, 'EQUAL': 3, 'GEQUAL': 4, 'GREATER': 5, 'NEQUAL': 6, 'ALWAYS': 7}
Z_WRITE = 1 << 30
RB3D_Z_ON = 0x1902                              # the precedent (Z_ENABLE, bit 8)
RB3D_Z_OFF = RB3D_Z_ON & ~(1 << 8)              # 0x1802
PF16 = (15360, 1024, 512)                       # the ramp: equality at (15, 4) for z 0.5 (plan E7)
PF24 = tuple(v * 256 for v in PF16)
PF75 = (49152, 0, 0)                            # a constant 0.75 (16-bit)
ZHALF = 0.5
ZFRAC = 0.5 + 2.0 ** -17                        # z * 2^16 = 32768.5 exactly (plan E8)


def zcntl(bits, func, write):
    return ZCNTL[bits] & ~0x70 & ~Z_WRITE | (ZFUNC[func] << 4) | (Z_WRITE if write else 0)


# name: (bits, func, write, rb3d, prefill or None, z (float or a triple), second draw or None)
# a second draw is (func, write, z, colour, wait)
RG = [
    ('GN',  16, 'NEVER',   1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GL',  16, 'LESS',    1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GLE', 16, 'LEQUAL',  1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GE',  16, 'EQUAL',   1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GGE', 16, 'GEQUAL',  1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GG',  16, 'GREATER', 1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GNE', 16, 'NEQUAL',  1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GA',  16, 'ALWAYS',  1, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GLW', 16, 'LESS',    0, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GAW', 16, 'ALWAYS',  0, RB3D_Z_ON,  PF16, ZHALF, None),
    ('GZE', 16, 'LESS',    1, RB3D_Z_OFF, PF16, ZHALF, None),
    ('GF',  16, 'EQUAL',   1, RB3D_Z_ON,  PF16, ZFRAC, None),
    ('GFG', 16, 'GREATER', 1, RB3D_Z_ON,  PF16, ZFRAC, None),
    ('GI',  16, 'LESS',    1, RB3D_Z_ON,  (32768, 0, 0), ('I1',), None),
    ('G24', 24, 'LESS',    1, RB3D_Z_ON,  PF24, ZHALF, None),
    ('GH1', 16, 'ALWAYS',  1, RB3D_Z_ON,  None, 0.9,   ('LESS', 1, ZHALF, C2, 0)),
    ('GH2', 16, 'LESS',    0, RB3D_Z_ON,  PF75, 0.25,  ('LESS', 1, ZHALF, C2, 0)),
    ('GH3', 16, 'ALWAYS',  1, RB3D_Z_ON,  None, ZFRAC, ('EQUAL', 1, ZFRAC, C2, 0)),
    ('GH4', 16, 'ALWAYS',  1, RB3D_Z_ON,  None, ('I1',), ('LESS', 1, ('I1r',), C2, 0)),
    ('GH1w',16, 'ALWAYS',  1, RB3D_Z_ON,  None, 0.9,   ('LESS', 1, ZHALF, C2, 1)),
]
GORDER = [r[0] for r in RG]
GFIRST = LAST + 1                               # 82
GCASE_NUM = dict((n, GFIRST + k) for k, n in enumerate(GORDER))
GLAST = GFIRST + len(GORDER) - 1                # 101
GZ = {'I1': ('3e800000', '3f400000', '3e800000'),        # the I1 slope (0.25 -> 0.75 in x)
      'I1r': ('3f400000', '3e800000', '3f400000')}       # reversed
GEOM_G = 'T1z'


def grow(case):
    return dict((r[0], r) for r in RG)[case]


def g_bits(case):
    return grow(case)[1]


def g_zvals(case, which):
    """the three vertex z (floats) of the first or second draw"""
    r = grow(case)
    z = r[6] if which == 1 else r[7][2]
    if isinstance(z, tuple):
        return tuple(fromhex(h) for h in GZ[z[0]])
    return (z, z, z)


def g_prefill(case):
    """{(x, y): stored depth} the CPU writes over the 32 x 32, or None (the ZPREP pattern stays)"""
    r = grow(case)
    if r[5] is None:
        return None
    A, B, C = r[5]
    top = (1 << r[1]) - 1
    return dict(((x, y), max(0, min(top, A + B * x + C * y))) for y in range(32) for x in range(32))


def g_stored(case):
    """the depth the first draw tests against, for every pixel of the 32 x 32"""
    pf = g_prefill(case)
    if pf is not None:
        return pf
    b = pattern_block()
    return dict(((x, y), read_depth(b, x, y, g_bits(case))) for y in range(32) for x in range(32))


def g_drawn(case, which, exact=False):
    """{(x, y): the depth the draw produces} on the covered pixels -- floored to the format (what is
    stored), or, with exact=True, the unfloored value (the other reading of what the test compares)"""
    bits = g_bits(case)
    pts = GEOM[GEOM_G]
    zs = g_zvals(case, which)
    pix = go.covered(pts)
    raw = [v * (1 << bits) for v in interp_exact(pts, zs, pix)]
    top = (1 << bits) - 1
    if exact:
        return dict(zip(pix, [max(0, min(top, v)) for v in raw]))
    return dict(zip(pix, [max(0, min(top, math.floor(v))) for v in raw]))


def zpass(func, new, old):
    return {'NEVER': False, 'LESS': new < old, 'LEQUAL': new <= old, 'EQUAL': new == old,
            'GEQUAL': new >= old, 'GREATER': new > old, 'NEQUAL': new != old, 'ALWAYS': True}[func]


def g_predict(case, ze_off='none', cmp='int'):
    """(colour {(x, y): pixel}, depth {(x, y): value}) over the 32 x 32.
    ze_off names what RB3D_CNTL.Z_ENABLE = 0 is taken to mean for the recorded case GZE:
    'none' (the bit does nothing), 'pass' (no test, but depth is written), 'off' (no test, no write).
    cmp: 'int' -- the test compares the floored value the buffer would hold; 'exact' -- it compares the
    value before flooring (the two readings the GF / GFG / H3 cases separate)"""
    r = grow(case)
    bits, func, write, rb3d, _, _, d2 = r[1], r[2], r[3], r[4], r[5], r[6], r[7]
    depth = dict(g_stored(case))
    colour = {}
    d1m, d2m = measured_drawn(case, 1), measured_drawn(case, 2)
    draws = [(func, write, d1m or g_drawn(case, 1), g_drawn(case, 1, True), to.pixel(C1))]
    if d2 is not None:
        draws.append((d2[0], d2[1], d2m or g_drawn(case, 2), g_drawn(case, 2, True), to.pixel(d2[3])))
    for k, (f, w, drawn, exact, px) in enumerate(draws):
        off = (rb3d & (1 << 8)) == 0
        for p, v in drawn.items():
            if off and ze_off != 'none':
                ok, wr = True, (ze_off == 'pass')
            else:
                ok, wr = zpass(f, exact[p] if cmp == 'exact' else v, depth[p]), w
            if ok:
                colour[p] = px
                if wr:
                    depth[p] = v
    return colour, depth


def g_block(case, ze_off='none', cmp='int'):
    """the 256 KiB block after ZPREP, the prefill and the draws"""
    colour, depth = g_predict(case, ze_off, cmp)
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    d = block_from_values(depth, g_bits(case))
    words[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(d)] = d
    for (x, y), px in colour.items():
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = px
    return words


def g_coverage_words(case, ze_off='none', cmp='int'):
    """the map the driver logs: code 1 = C1's pixel, code 2 = C2's pixel, 0 = the pattern"""
    colour, _ = g_predict(case, ze_off, cmp)
    w = [0] * 64
    for (x, y), px in colour.items():
        i = y * 32 + x
        w[i >> 4] |= (1 if px == to.pixel(C1) else 2) << (2 * (i & 15))
    return w


# The 16-bit depth the machine writes for the I1 slope over T1z, measured on boot e4d44687 (R6f,
# docs/R6F_PLAN.md 11) and unchanged on boot 04f45b10 with another build (docs/R6G_PLAN.md 10): the
# setup's rounding is not named yet (docs/R6F_PLAN.md 12), so the measurement is the oracle here.
MEASURED_I1_16 = (
    '42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa42aa47ff'
    '47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff47ff4d554d554d55'
    '4d554d554d554d554d554d554d554d554d554d554d554d554d554d554d554d554d554d5552aa52aa52aa52aa52aa52aa'
    '52aa52aa52aa52aa52aa52aa52aa52aa52aa52aa52aa52aa52aa52aa57ff57ff57ff57ff57ff57ff57ff57ff57ff57ff'
    '57ff57ff57ff57ff57ff57ff57ff57ff57ff5d555d555d555d555d555d555d555d555d555d555d555d555d555d555d55'
    '5d555d555d5562aa62aa62aa62aa62aa62aa62aa62aa62aa62aa62aa62aa62aa62aa62aa62aa62aa67ff67ff67ff67ff'
    '67ff67ff67ff67ff67ff67ff67ff67ff67ff67ff67ff67ff6d556d556d556d556d556d556d556d556d556d556d556d55'
    '6d556d556d5572aa72aa72aa72aa72aa72aa72aa72aa72aa72aa72aa72aa72aa72aa77ff77ff77ff77ff77ff77ff77ff'
    '77ff77ff77ff77ff77ff77ff7d557d557d557d557d557d557d557d557d557d557d557d5582aa82aa82aa82aa82aa82aa'
    '82aa82aa82aa82aa82aa87ff87ff87ff87ff87ff87ff87ff87ff87ff87ff8d558d558d558d558d558d558d558d558d55'
    '92aa92aa92aa92aa92aa92aa92aa92aa97ff97ff97ff97ff97ff97ff97ff9d559d559d559d559d559d55a2aaa2aaa2aa'
    'a2aaa2aaa7ffa7ffa7ffa7ffad55ad55ad55b2aab2aab7ff'
)


def measured_drawn(case, which):
    """{(x, y): depth} the machine writes for this draw, where a measurement stands in for the
    unnamed setup rounding -- the I1 slope at 16 bits; None when there is none"""
    r = grow(case)
    if which == 2 and r[7] is None:
        return None
    z = r[6] if which == 1 else r[7][2]
    if g_bits(case) != 16 or not (isinstance(z, tuple) and z[0] == 'I1'):
        return None
    pix = go.covered(GEOM[GEOM_G])
    h = MEASURED_I1_16
    return dict((p, int(h[4 * k:4 * k + 4], 16)) for k, p in enumerate(pix))


PURGE_DC, PURGE_ZC = zo.PURGE_DC, zo.PURGE_ZC
WAIT_3D_IDLECLEAN = 0x00020000                  # RADEON_WAIT_3D_IDLECLEAN (radeon_drv.h)


def g_vf():
    """R6g draws one triangle: TRIANGLES | WALK_RING | ORDER_RGBA | 3 vertices"""
    return (zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') |
            zo.M('R200_VF_COLOR_ORDER_RGBA') | (3 << 16))


def g_header():
    return zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), 15)


def g_draw_words(case, seed):
    """the ring words of an R6g case: the caches purged (a prefill case), R6c F's state with this
    case's RB3D_CNTL and ZSTENCILCNTL, the clip, the first draw, then -- for a two-draw case -- a
    new ZSTENCILCNTL (and optionally a WAIT_UNTIL) and the second draw; then the tail"""
    r = grow(case)
    bits, rb3d, pf, d2 = r[1], r[4], r[5], r[7]
    fw = zo.draw_words('F', seed)
    state, pix, tail = fw[:26], fw[26:34], fw[-10:]
    assert state[6] == zo.p0(zo.V('RADEON_RB3D_CNTL')) and state[7] == RB3D_Z_ON
    state = state[:7] + [rb3d] + state[8:9] + [zcntl(bits, r[2], r[3])] + state[10:]
    x1, y1, x2, y2 = to.CLIP
    head = []
    if pf is not None:                          # docs/R6G_PLAN.md 2-1: the precedent's purge order
        head = [zo.p0(zo.V('RADEON_RB3D_DSTCACHE_CTLSTAT')), PURGE_DC,
                zo.p0(zo.V('RADEON_RB3D_ZCACHE_CTLSTAT')), PURGE_ZC]
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]

    def draw(zs, colour):
        body = [g_vf()]
        for (x, y), z in zip(GEOM[GEOM_G], zs):
            body += [to.fbits(x), to.fbits(y), to.fbits(z), to.fbits(1.0), to.word(colour)]
        return [zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)] + body

    out = head + state + pix + clip + draw(g_zvals(case, 1), C1)
    if d2 is not None:
        out += [zo.p0(zo.V('RADEON_RB3D_ZSTENCILCNTL')), zcntl(bits, d2[0], d2[1])]
        if d2[4]:
            out += [zo.p0(zo.V('RADEON_WAIT_UNTIL')), WAIT_3D_IDLECLEAN]
        out += draw(g_zvals(case, 2), d2[3])
    return out + tail


def g_case_values(case):
    """the 30 values of an R6g case row (osrdn_cp.m cpR6Case, with rb3d and gidx)"""
    r = grow(case)
    bits = r[1]
    slope = isinstance(r[6], tuple)
    return [0, 0, 64, 64, 0, 0, 0, 0, 0 if slope else to.fbits(r[6]), 2,
            0x1000, 0xffffffff, 0x803, 0x10000, g_header(), g_vf(), 0, TRI_FIRST, to.pixel(C1), to.pixel(C2),
            SE_CNTL_FLAT, 0x3 if bits == 16 else 0x7, 0, 0,
            zcntl(bits, r[2], r[3]), 1 if slope else 0, 0, 2 if bits == 16 else 1,
            r[4], GORDER.index(case) + 1]


def g_table_values(case):
    """the 10 values of a cpR6G row: the prefill and the second draw"""
    r = grow(case)
    pf, d2 = r[5], r[7]
    A, B, C = pf if pf is not None else (0, 0, 0)
    if d2 is None:
        d2v = [0, 0, 0, 0, 0, 0]
    else:
        z = g_zvals(case, 2)
        d2v = [zcntl(r[1], d2[0], d2[1]), to.fbits(z[0]), to.fbits(z[1]), to.fbits(z[2]), to.word(d2[3]), d2[4]]
    return [0 if pf is None else 1, A & M32, B & M32, C & M32] + d2v


# ---- the simulator's model (tools/r5/sim/world5.c r6Tri / r6Conv) ------------------------

SIM_CONV = ('qNone', 'm1', 'up')                # round(z (2^n - 1)) half up, one rule of the space


def sim_values(case, conv=SIM_CONV):
    """{(x, y): depth} the model writes: each triangle's covered pixels get its FIRST vertex's z
    converted (the model does not interpolate)"""
    bits = fmt_bits(case)
    f = space(bits)[conv]
    out = {}
    for pts, zs in triangles(case):
        for p in go.covered(pts):
            out[p] = f(zs[0])
    return out


def full_block(case, conv=SIM_CONV):
    """the 256 KiB block (65536 words) after ZPREP then ZCLEAR <case> under the model: the depth
    region from sim_values, the colour buffer C1's pixel on the covered pixels"""
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    d = block_from_values(sim_values(case, conv), fmt_bits(case))
    words[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(d)] = d
    for x, y in covered(case):
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = to.pixel(C1)
    return words


def sim_g_predict(case):
    """what tools/r5/sim/world5.c's model does with an R6g case: the depth of a draw is its FIRST
    vertex's z converted (the model does not interpolate), the test is the case's, Z_ENABLE = 0 means
    no test and no depth write"""
    r = grow(case)
    bits, func, write, rb3d, d2 = r[1], r[2], r[3], r[4], r[7]
    conv = space(bits)[SIM_CONV]
    depth = dict(g_stored(case))
    colour = {}
    pix = go.covered(GEOM[GEOM_G])
    draws = [(func, write, conv(g_zvals(case, 1)[0]), to.pixel(C1))]
    if d2 is not None:
        draws.append((d2[0], d2[1], conv(g_zvals(case, 2)[0]), to.pixel(d2[3])))
    zen = (rb3d & (1 << 8)) != 0
    for f, w, v, px in draws:
        for p in pix:
            if zen and not zpass(f, v, depth[p]):
                continue
            colour[p] = px
            if zen and w:
                depth[p] = v
    return colour, depth


def sim_g_block(case):
    colour, depth = sim_g_predict(case)
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    d = block_from_values(depth, g_bits(case))
    words[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(d)] = d
    for (x, y), px in colour.items():
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = px
    return words


def sim_g_coverage_words(case):
    colour, _ = sim_g_predict(case)
    w = [0] * 64
    for (x, y), px in colour.items():
        i = y * 32 + x
        w[i >> 4] |= (1 if px == to.pixel(C1) else 2) << (2 * (i & 15))
    return w


def coverage_words(case):
    """the 64 map words the driver logs: code 1 (C1's pixel) on the covered pixels"""
    cov = covered(case)
    w = [0] * 64
    for y in range(32):
        for x in range(32):
            if (x, y) in cov:
                i = y * 32 + x
                w[i >> 4] |= 1 << (2 * (i & 15))
    return w


# ---- interpolation analysis (recorded, not gated: docs/R6F_PLAN.md 3-3) -----------------

def _verts(pts, p='t16'):
    return [(go.pos(x, p), go.pos(y, p)) for x, y in pts]


def _left(P):
    return min(range(3), key=lambda i: (P[i][0], P[i][1]))


def _rq(v, k, m):
    return Fr(rnd(v * (1 << k), m), 1 << k)


def interp_exact(pts, zs, pix, p='t16', wq=None):
    """exact barycentric at pixel + 1/2 (vertices 1/16-truncated); wq = (k, mode): rule B's weight
    quantisation (the two weights other than the leftmost vertex's to 2^-k)"""
    (x0, y0), (x1, y1), (x2, y2) = P = _verts(pts, p)
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    L = _left(P)
    z = [Fr(v) for v in zs]
    out = []
    for x, y in pix:
        sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        w = [1 - w1 - w2, w1, w2]
        if wq:
            for i in range(3):
                if i != L:
                    w[i] = _rq(w[i], wq[0], wq[1])
            w[L] = 1 - sum(w[i] for i in range(3) if i != L)
        out.append(sum(a * b for a, b in zip(w, z)))
    return out


def families():
    """{name: function(pts, zs, pix) -> [exact pre-conversion value]} -- the analysis families"""
    F = {('exact', 't16'): lambda p, z, x: interp_exact(p, z, x, 't16'),
         ('exact', 'exact'): lambda p, z, x: interp_exact(p, z, x, 'exact')}
    for k in (8, 10, 12, 14, 16, 20, 24):
        for m in ('up', 'even'):
            F[('wq', k, m)] = lambda p, z, x, k=k, m=m: interp_exact(p, z, x, 't16', (k, m))
    return F


def interp_report(case, vals, conv):
    """[(family, pixels differing)] under the conversion function conv, best first"""
    pts, zs = triangles(case)[0]
    pix = sorted(go.covered(pts))
    seen = [vals[p] for p in pix]
    f = space(fmt_bits(case))[conv]
    out = []
    for k, fn in families().items():
        d = sum(1 for v, s in zip(fn(pts, zs, pix), seen) if f(v) != s)
        out.append((k, d))
    out.sort(key=lambda t: t[1])
    return out


def conv_exact(name, v, bits):
    """a conversion from the space applied to an exact rational (not only a float32): the
    names whose function accepts a Fraction"""
    return space(bits)[name](v)


# ---- the C rows -------------------------------------------------------------------------

def c_tables():
    """the driver's tables: cells, grid z, vertex z, the five triangle rows, the case rows"""
    L = []
    L.append('static const unsigned long cpR6Cells[16][4] = {     /* x0, y0, x0 + 3, y0 + 3 (float32) */')
    L.append(',\n'.join('    { 0x%08xUL, 0x%08xUL, 0x%08xUL, 0x%08xUL }' % (
        to.fbits(x0), to.fbits(y0), to.fbits(x0 + LEG), to.fbits(y0 + LEG)) for x0, y0 in CELLS))
    L.append('};')
    L.append('static const unsigned long cpR6GridZ[4][16] = {       /* the 64 anchors (float32) */')
    L.append(',\n'.join('    { ' + ', '.join('0x%sUL' % tohex(z) for z in ANCHORS[16 * r:16 * r + 16]) + ' }'
                        for r in range(4)))
    L.append('};')
    L.append('static const unsigned long cpR6Zv[7][3] = {           /* I1-I7: z per vertex (float32) */')
    L.append(',\n'.join('    { ' + ', '.join('0x%sUL' % h for h in ICASES[n][1]) + ' }   /* %s */' % n for n in IORDER))
    L.append('};')
    L.append('/* R6f triangle rows (cpR6Tris %d .. %d) */' % (TRI_FIRST, TRI_FIRST + len(TRI_ORDER) - 1))
    for g in TRI_ORDER:
        L.append('    { 3UL, { ' + ', '.join('{ 0x%08xUL, 0x%08xUL, 0x%08xUL }' % (to.fbits(x), to.fbits(y), to.word(C1))
                                            for x, y in GEOM[g]) + ' } }   /* %s */,' % g)
    L.append('/* R6f case rows */')
    for n in ORDER:
        L.append(case_row(n))
    L.append('/* R6g (docs/R6G_PLAN.md 2, 6): the prefill and the second draw of each case */')
    L.append('static const unsigned long cpR6G[%d][10] = {   /* pf, A, B, C, d2 zcntl, d2 z0, z1, z2, colour, wait */'
             % len(GORDER))
    L.append('\n'.join(g_row_text(n) for n in GORDER).rstrip(','))
    L.append('};')
    L.append('/* R6g case rows */')
    for n in GORDER:
        L.append(g_case_row(n))
    return '\n'.join(L)


def case_values(case):
    """the 28 values of a case row (osrdn_cp.m cpR6Case)"""
    px = to.pixel(C1)
    return [0, 0, 64, 64, 0, 0, 0, 0, 0, 2,
            0x1000, 0xffffffff, 0x803, 0x10000, header(case), vf_cntl(case),
            to.word(C1) if case.startswith('K') else 0, tri_index(case), px, px,     # the grid's colour word (a triangle row carries its own)
            SE_CNTL_FLAT, lanes(case), 0, 0,
            ZCNTL[fmt_bits(case)], zrow_index(case), grid_index(case), dsrc(case),
            RB3D_Z_ON, 0]                       # R6g: RB3D_CNTL and no R6g row


def _row_text(case, v):
    return ('    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, %s, 2UL,     /* %s */\n' % (
                '0x%08xUL' % v[8] if v[8] else '0UL', case) +
            '      ' + ', '.join('0x%xUL' % x if x > 255 else '%dUL' % x for x in v[10:]) + ' },')


def case_row(case):
    return _row_text(case, case_values(case))


def g_case_row(case):
    return _row_text(case, g_case_values(case))


def g_row_text(case):
    v = g_table_values(case)
    return '    { ' + ', '.join('0x%xUL' % x if x > 255 else '%dUL' % x for x in v) + ' }   /* %s */,' % case


def words_needed(case):
    """ring words of the draw submission (the driver's cpR6Words must hold them)"""
    return len(draw_words(case, 1))


# ---- self-test -----------------------------------------------------------------------------

def self_test():
    bad = 0

    def expect(what, got, want):
        nonlocal bad
        ok = got == want
        bad += not ok
        print('  %s  %s%s' % ('ok  ' if ok else 'FAIL', what, '' if ok else ': got %s, want %s' % (got, want)))

    # codex Q3 (docs/R6F_PLAN.md 8): the five witnesses, each outside the first space
    s16, s24 = space(16), space(24)
    W = [(('fp', 10, 'even', 'm1', 'even'), 16, '3e99999a', 19664), (('fp', 16, 'even', 'm1', 'even'), 24, '3f612345', 14754687),
         (('fx', 12, 'even', 'even'), 16, '3e99999a', 19664), (('u16to24', 'even', 'even'), 24, '3dcccccd', 1677850),
         (('res1', 'even'), 16, '3f400000', 49150)]
    expect('codex Q3 witnesses reproduced', [ (s16 if b == 16 else s24)[k](fromhex(h)) for k, b, h, _ in W], [w for *_, w in W])
    base16 = _space_base(16)
    expect('the witnesses are outside the first space', [any(f(fromhex(h)) == w for f in (base16 if b == 16 else _space_base(24)).values())
                                                         for k, b, h, w in W], [False] * 5)
    expect('space sizes 348 / 202', (len(s16), len(s24)), (348, 202))
    # the anchors separate the classes a small random probe finds (the full proof: --separation)
    random.seed(4)
    probe = [f32(random.random()) for _ in range(300)] + [f32(2 ** random.uniform(-20, -5.6)) for _ in range(100)]
    for bits, sp in ((16, s16), (24, s24)):
        full = {}
        for k, h in sp.items():
            full.setdefault(tuple(h(z) for z in probe + ANCHORS), []).append(k)
        part = set(tuple(sp[v[0]](z) for z in ANCHORS) for v in full.values())
        expect('%d-bit: the anchors separate every class of a 400-z probe' % bits, len(part), len(full))
    expect('64 anchors, all distinct', (len(ANCHORS), len(set(ANCHORS))), (64, 64))
    # the grid: 3 pixels a cell, disjoint, 48 in all
    cov = [set(go.covered(cell_tri(x0, y0))) for x0, y0 in CELLS]
    expect('grid cells cover 3 pixels each, 48 disjoint', (set(map(len, cov)), len(set().union(*cov))), ({3}, 48))
    expect('each cell covers its corner pixel', all((x0, y0) in c for (x0, y0), c in zip(CELLS, cov)), True)
    # addressing (plan D5, D6)
    a16 = [mba_z16(x, y) for y in range(64) for x in range(64)]
    expect('mba_z16: 64 x 64 one to one onto 8 KiB of halfwords', sorted(a16), list(range(0, 8192, 2)))
    expect('mba_z16: the 32 x 32 lies below 0x1000', max(mba_z16(x, y) for y in range(32) for x in range(32)) < 0x1000, True)
    w16 = {}
    for y in range(32):
        for x in range(32):
            w16.setdefault(mba_z16(x, y) // 4, []).append((x, y))
    expect('mba_z16: every word the 32 x 32 touches holds two of its pixels', set(map(len, w16.values())), {2})
    expect('mba_z16 bit placement: (1,0) (0,1) (2,0) (8,0) (16,0) (32,0)',
           [mba_z16(1, 0), mba_z16(0, 1), mba_z16(2, 0), mba_z16(8, 0), mba_z16(16, 0), mba_z16(32, 0)],
           [2, 4, 8, 256, 64, 128])
    # the depth block round trip, both formats
    random.seed(8)
    for bits in (16, 24):
        vals = dict(((x, y), random.randrange(1 << bits)) for y in range(32) for x in range(32))
        b = block_from_values(vals, bits)
        expect('%d-bit: planes -> values round trip' % bits, values_from_planes(plane_words(b, bits), bits), vals)
        b2 = block_from_values(values_from_planes(plane_words(b, bits), bits), bits)
        expect('%d-bit: the rebuilt block has the same digest' % bits, digest(b2), digest(b))
        b3 = list(b)
        b3[3000] ^= 1                                          # one word outside the 32 x 32
        expect('%d-bit: one word changed outside the 32 x 32 changes the digest' % bits, digest(b3) != digest(b), True)
    b = block_from_values({(0, 0): 0x1234}, 16)
    expect('16-bit: a write keeps the other half of the word', b[0], (zo.pattern(0) & 0xffff0000) | 0x1234)
    b = block_from_values({(0, 0): 0x123456}, 24)
    expect('24-bit: a write keeps the stencil byte', b[0], (zo.pattern(0) & 0xff000000) | 0x123456)
    # the words
    expect('ZSTENCILCNTL 16-bit = the precedent with format 0', ZCNTL[16], ZCNTL[24] & ~0xf)
    expect('cases 60 .. 81', (FIRST, LAST, len(ORDER)), (60, 81, 22))
    expect('grid draw: 48 vertices, header count 240', (nverts('K16a'), (header('K16a') >> 16) & 0x3fff), (48, 240))
    expect('the largest submission fits 320 words', max(words_needed(n) for n in ORDER), 290)
    dw = draw_words('K24b', 7)
    expect('K24b: ZSTENCILCNTL word, VF, first cell, its z', (dw[9], dw[39], dw[40], dw[41], dw[42]),
           (ZCNTL[24], 0x300074, to.fbits(2.0), to.fbits(2.0), to.fbits(ANCHORS[16])))
    dw = draw_words('I5_16', 7)
    expect('I5_16: ZSTENCILCNTL and the three z', (dw[9], dw[42], dw[47], dw[52]),
           (ZCNTL[16], 0x3f000000, 0x3f001000, 0x3effd000))
    expect('interpolation cases cover 276 276 137 181 103 160 103',
           [len(covered(n + '_24')) for n in IORDER], [276, 276, 137, 181, 103, 160, 103])
    # naming: a synthetic observation under one rule is named by exactly its class
    for bits in (16, 24):
        sp = space(bits)
        want = ('qNone', 'm1', 'up')
        obs = [sp[want](z) for z in ANCHORS]
        names, near = name_conversion(bits, obs)
        expect('%d-bit: round(z (2^n - 1)) named with its class' % bits, want in names and all(
            all(sp[k](z) == v for z, v in zip(ANCHORS, obs)) for k in names), True)
        obs2 = list(obs)
        obs2[5] += 1
        expect('%d-bit: one anchor off by one names nothing' % bits, name_conversion(bits, obs2)[0], [])
    # interpolation analysis: exact values of a case reproduce under exact + the rule's conversion
    pts, zs = triangles('I1_24')[0]
    pix = sorted(go.covered(pts))
    ex = interp_exact(pts, zs, pix)
    vals = dict(zip(pix, [conv_exact(('qNone', 'm1', 'floor'), v, 24) for v in ex]))
    expect('I1: the exact family explains an exact-floor plane with 0 misses',
           dict(interp_report('I1_24', vals, ('qNone', 'm1', 'floor')))[('exact', 't16')], 0)
    # R6g (docs/R6G_PLAN.md 2-2, 6): the predictions the plan tabulates
    want = {'GN': 0, 'GL': 132, 'GLE': 144, 'GE': 12, 'GGE': 144, 'GG': 132, 'GNE': 264, 'GA': 276,
            'GLW': 132, 'GAW': 276, 'GZE': 132, 'GF': 12, 'GFG': 132, 'GI': 210, 'G24': 132}
    expect('R6g: the single-draw pass counts', dict((n, len(g_predict(n)[0])) for n in want), want)
    expect('R6g: GF / GFG / H3 separate the two comparison readings',
           [(len(g_predict(n)[0]), len(g_predict(n, cmp='exact')[0]),
             sum(1 for v in g_predict(n)[0].values() if v == to.pixel(C2)),
             sum(1 for v in g_predict(n, cmp='exact')[0].values() if v == to.pixel(C2))) for n in ('GF', 'GFG', 'GH3')],
           [(12, 0, 0, 0), (132, 144, 0, 0), (276, 276, 276, 0)])
    c, d = g_predict('GH1')
    stale = sum(1 for p, v in g_drawn('GH1', 2).items() if v < read_depth(pattern_block(), p[0], p[1], 16))
    expect('R6g: GH1 tells a fresh depth from a stale one (276 against 132)',
           (sum(1 for v in c.values() if v == to.pixel(C2)), stale), (276, 132))
    c2, d2_ = g_predict('GH2')
    expect('R6g: GH2 -- the masked first draw leaves 0.75, the second writes 0.5',
           (sum(1 for v in c2.values() if v == to.pixel(C2)), sorted(set(d2_[p] for p in g_drawn('GH2', 2)))), (276, [32768]))
    c4, _ = g_predict('GH4')
    expect('R6g: GH4 -- the two sloped surfaces cross (210 / 66)',
           (sum(1 for v in c4.values() if v == to.pixel(C1)), sum(1 for v in c4.values() if v == to.pixel(C2))), (210, 66))
    expect('R6g: every prefill stays inside its format',
           [max(g_prefill(n).values()) < (1 << g_bits(n)) and min(g_prefill(n).values()) >= 0
            for n in GORDER if g_prefill(n) is not None], [True] * 16)
    expect('R6g: ZSTENCILCNTL keeps the format bits and names the function',
           [zcntl(16, 'LESS', 1), zcntl(24, 'ALWAYS', 0), zcntl(16, 'EQUAL', 1) & 0x70],
           [0x42227010, 0x02227072, 0x30])
    expect('R6g: cases 82 .. 101, rows of 30 values and the table of 10',
           (GFIRST, GLAST, len(g_case_values('GN')), len(g_table_values('GH1'))), (82, 101, 30, 10))
    expect('R6g: the longest submission fits', max(len(g_draw_words(n, 1)) for n in GORDER) <= WORDS_MAX, True)
    b16 = g_block('GL')
    expect('R6g: the block rebuilds from its depth planes',
           digest(block_from_values(values_from_planes(plane_words(b16[:4096], 16), 16), 16)), digest(b16[:4096]))
    expect('R6g: the GH1w stream differs from GH1 only by the WAIT_UNTIL pair',
           (len(g_draw_words('GH1w', 3)) - len(g_draw_words('GH1', 3)),
            [hex(w) for w in g_draw_words('GH1w', 3) if w == WAIT_3D_IDLECLEAN]), (2, ['0x20000']))
    blk = full_block('K16a')
    vals = values_from_planes(plane_words(blk[:4096], 16), 16)
    expect('the model: K16a planes carry the model values on the 48 grid pixels',
           all(vals[p] == v for p, v in sim_values('K16a').items()) and len(sim_values('K16a')) == 48, True)
    expect('the model: coverage words count 48 grid pixels', sum(bin(w).count('1') for w in coverage_words('K24c')), 48)
    print('depth_oracle: %s' % ('PASS' if bad == 0 else 'FAIL %d' % bad))
    return bad == 0


def separation():
    """the anchors against the whole space on the design probe (docs/R6F_PLAN.md 3-1)"""
    random.seed(9)
    probe = [f32(random.random()) for _ in range(3000)]
    random.seed(5)
    probe += sorted(set(f32(2 ** random.uniform(-20, -5.6)) for _ in range(4000)))
    ok = True
    for bits in (16, 24):
        full, part = {}, {}
        sp = space(bits)
        for k, h in sp.items():
            full.setdefault(tuple(h(z) for z in probe + ANCHORS), []).append(k)
        for v in full.values():
            part.setdefault(tuple(sp[v[0]](z) for z in ANCHORS), []).append(v)
        print('%d-bit: %d hypotheses, %d classes, the anchors separate %d' % (bits, len(sp), len(full), len(part)))
        ok &= len(part) == len(full)
    print('separation: %s' % ('PASS' if ok else 'FAIL'))
    return ok


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(0 if self_test() else 1)
    if sys.argv[1:] == ['--c-tables']:
        print(c_tables())
        sys.exit(0)
    if sys.argv[1:] == ['--separation']:
        sys.exit(0 if separation() else 1)
    print(__doc__)
    sys.exit(2)
