#!/usr/bin/env python3
"""R6i oracle (docs/R6I_PLAN.md 2): perspective (W != 1) and bilinear filtering -- the texels and
weights every named rule predicts, the ring words, and the C rows the driver carries.

  persp_oracle.py --self-test
  persp_oracle.py --c-tables

Cases 109-124 draw the R6h triangle T1z (PE the Gouraud triangle V8, PZ the R6f I1 z ramp) with a
per-vertex W and/or a linear-filtered texture, and read the colour (PZ: the 24-bit depth) back as
byte planes.  Two rule spaces:

  nearest  (model, sample offset, divide precision):  u = clamp/wrap(floor(s * w))
           model A  = affine, Pq = perspective with q = W0, Pw = perspective with q = 1/W0
  bilinear (model, sample offset, texel offset a, fraction quantum, its rounding, final rounding)

A pixel is RISKY when a tap index sits within 2^-10 of a texel boundary; the judge records those
instead of gating on them.
"""

import importlib.util
import math
import os
import sys
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


to_ = _load('tex_oracle')
do, go, to, zo = to_.do, to_.go, to_.to, to_.zo
M32 = 0xffffffff
DELTA = Fr(1, 1024)                             # "far from a texel boundary" (plan 2-3)
TEX_OFF, TEX_BYTES = to_.TEX_OFF, to_.TEX_BYTES

FIRST = to_.LAST + 1                            # 109
RE_SCISSOR = 2                                  # every triangle case carries it (osrdn_cp.m case rows)
RE_PERSP = RE_SCISSOR | 8                       # + R200_PERSPECTIVE_ENABLE (plan Y1)
VTE_BASE = 0x300                                # XY_FMT | Z_FMT (plan Y2)
VTE_W0 = VTE_BASE | 0x400                       # + VTX_W0_FMT (plan Y3): 0x700
TEXCOORD_PROJ = 3 << 16                         # PP_TXFORMAT_X (plan Y7)

W1 = (Fr(1), Fr(1), Fr(1))
WB = (Fr(1), Fr(1, 8), Fr(1, 2))                # the separating triple (plan 2-2)
WC = (Fr(1), Fr(1, 4), Fr(1, 4))
WF = (Fr(1), Fr(8), Fr(2))                      # PF: the reciprocals of WB, with VTX_W0_FMT set

# ---- the texel patterns -----------------------------------------------------------------------


def texel(pat, u, v):
    """pat 0: R6h's (u, v) ramp; 1: the four corners of a 2x2 told apart; 2: R alternates with u and
    G with v, so one channel carries one axis' weight.  Alpha is 0xff in all three: never a pattern word"""
    if pat == 0:
        return to_.texel(u, v)
    if pat == 1:
        return 0xff000000 | ((255 * (u & 1)) << 16) | ((255 * (v & 1)) << 8) | (255 * (u & 1) * (v & 1))
    if pat == 3:                                # R6i-3: pattern 2 transposed -- R follows v, G follows u
        return 0xff000000 | ((255 * (v & 1)) << 16) | ((255 * (u & 1)) << 8) | 0x55
    return 0xff000000 | ((255 * (u & 1)) << 16) | ((255 * (v & 1)) << 8) | 0x55


# ---- the cases ---------------------------------------------------------------------------------

GEOM_Q = [(4.0, 4.0), (20.0, 4.0), (4.0, 20.0)]   # R6i-2: 16-pixel spans, doubled area 256 --
                                                  # every setup division is by a power of two
SH = Fr(1, 512 * 8)                               # 1/512 texel, so a sample can land on a cell's half
ST_Q1 = ((Fr(1, 8) + SH, Fr(1, 4) + SH, Fr(17, 128) + SH), (Fr(3, 16),) * 3)      # fv = 0
ST_Q2 = ((Fr(1, 8) + SH, Fr(1, 4) + SH, Fr(17, 128) + SH), (Fr(1, 4),) * 3)       # fv = 1/2
ST_Q3 = ((Fr(5, 16),) * 3, (Fr(3, 16) + SH, Fr(3, 16) + Fr(1, 128) + SH, Fr(3, 16) + Fr(1, 8) + SH))
# R6i-3 (docs/R6I3_PLAN.md 2-2): each sweep stays inside ONE texel with an EVEN tap index, which is
# the branch (a = 0, b = 255) where the mix's rounding constant shows in the byte
ST_N1 = ((Fr(257, 4096), Fr(737, 4096), Fr(289, 4096)), (Fr(3, 16),) * 3)          # u sweeps texel 0
ST_N2 = ((Fr(5, 16),) * 3, (Fr(257, 4096), Fr(289, 4096), Fr(737, 4096)))          # v sweeps texel 0
ST_N3 = ((Fr(1281, 4096), Fr(1761, 4096), Fr(1313, 4096)), (Fr(3, 16),) * 3)       # u sweeps texel 2
ST_N4 = ((Fr(5, 16),) * 3, (Fr(1281, 4096), Fr(1313, 4096), Fr(1761, 4096)))       # v sweeps texel 2
PP_CNTL_FILTER_ROUND = 0x400                      # R200_FILTER_ROUND_MODE_MASK (plan Z6)

ST_XA = ((0, 1, 0), (0, 0, 1))
ST_LD = ((Fr(1, 8), Fr(2, 8), Fr(1, 8)), (Fr(1, 8), Fr(1, 8), Fr(2, 8)))
ST_LF = ((Fr(1, 8), Fr(2, 8), Fr(1, 8) + Fr(3, 256)), (Fr(5, 32), Fr(5, 32), Fr(5, 32)))

# name: (kind, texture (w, h, pat), clamp, filter, ST, W, RE_CNTL, VTE, PP_TXFORMAT_X, geometry, PP_CNTL extra)
CASES = {
    'PA': ('tex', (8, 8, 0), 'clamp', 'nearest', ST_XA, W1, RE_PERSP, VTE_BASE, 0, 'T1z', 0),
    'PB': ('tex', (8, 8, 0), 'clamp', 'nearest', ST_XA, WB, RE_PERSP, VTE_BASE, 0, 'T1z', 0),
    'PC': ('tex', (8, 8, 0), 'clamp', 'nearest', ST_XA, WC, RE_PERSP, VTE_BASE, 0, 'T1z', 0),
    'PD': ('tex', (8, 8, 0), 'clamp', 'nearest', ST_XA, WB, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
    'PF': ('tex', (8, 8, 0), 'clamp', 'nearest', ST_XA, WF, RE_PERSP, VTE_W0, 0, 'T1z', 0),
    'PH': ('tex', (8, 8, 0), 'clamp', 'nearest', ST_XA, W1, RE_SCISSOR, VTE_BASE, TEXCOORD_PROJ, 'T1z', 0),
    'PE': ('gouraud', None, None, None, None, WB, RE_PERSP, VTE_BASE, None, 'V8', 0),
    'LA': ('tex', (2, 2, 1), 'clamp', 'linear', ST_XA, W1, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
    'LB': ('tex', (2, 2, 1), 'clamp', 'nearest', ST_XA, W1, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
    'LC': ('tex', (2, 2, 1), 'wrap', 'linear', ST_XA, W1, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
    'LD': ('tex', (8, 8, 2), 'clamp', 'linear', ST_LD, W1, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
    'LE': ('tex', (8, 8, 2), 'clamp', 'nearest', ST_LD, W1, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
    'LF': ('tex', (8, 8, 2), 'clamp', 'linear', ST_LF, W1, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
    'PL': ('tex', (8, 8, 2), 'clamp', 'linear', ST_LD, WB, RE_PERSP, VTE_BASE, 0, 'T1z', 0),
    'PZ': ('depth', None, None, None, None, WB, RE_PERSP, VTE_BASE, None, 'T1z', 0),
    # R6i-2 (docs/R6I2_PLAN.md 2-2): the dyadic-gradient sweep on the 16 x 16 triangle
    'Q0': ('tex', (8, 8, 0), 'clamp', 'nearest', ST_XA, W1, RE_SCISSOR, VTE_BASE, 0, 'Q', 0),
    'Q1': ('tex', (8, 8, 2), 'clamp', 'linear', ST_Q1, W1, RE_SCISSOR, VTE_BASE, 0, 'Q', 0),
    'Q2': ('tex', (8, 8, 2), 'clamp', 'linear', ST_Q2, W1, RE_SCISSOR, VTE_BASE, 0, 'Q', 0),
    'Q3': ('tex', (8, 8, 2), 'clamp', 'linear', ST_Q3, W1, RE_SCISSOR, VTE_BASE, 0, 'Q', 0),
    'Q4': ('tex', (8, 8, 2), 'clamp', 'linear', ST_Q1, WB, RE_PERSP, VTE_BASE, 0, 'Q', 0),
    'Q5': ('tex', (8, 8, 2), 'clamp', 'linear', ST_Q1, W1, RE_SCISSOR, VTE_BASE, 0, 'Q',
           PP_CNTL_FILTER_ROUND),
    # R6i-3: the transposed pattern tells "the constant follows the axis" from "it follows the
    # channel"; N3 and N4 pin the constants with FILTER_ROUND_MODE set, N5 is the bit-clear control
    'N1': ('tex', (8, 8, 3), 'clamp', 'linear', ST_N1, W1, RE_SCISSOR, VTE_BASE, 0, 'Q', 0),
    'N2': ('tex', (8, 8, 3), 'clamp', 'linear', ST_N2, W1, RE_SCISSOR, VTE_BASE, 0, 'Q', 0),
    'N3': ('tex', (8, 8, 2), 'clamp', 'linear', ST_N3, W1, RE_SCISSOR, VTE_BASE, 0, 'Q',
           PP_CNTL_FILTER_ROUND),
    'N4': ('tex', (8, 8, 2), 'clamp', 'linear', ST_N4, W1, RE_SCISSOR, VTE_BASE, 0, 'Q',
           PP_CNTL_FILTER_ROUND),
    'N5': ('tex', (8, 8, 2), 'clamp', 'linear', ST_N3, W1, RE_SCISSOR, VTE_BASE, 0, 'Q', 0),
    # R6j (docs/R6J_PLAN.md 2-2): a Gouraud destination, then a flat source through the blend unit
    'J1': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J2': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J3': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J4': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J5': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J6': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J7': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J8': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J9': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'J0': ('blend', None, None, None, None, W1, RE_SCISSOR, VTE_BASE, None, 'Q', 0),
    'LN': ('tex', (2, 8, 0), 'clamp', 'nearest', ST_XA, W1, RE_SCISSOR, VTE_BASE, 0, 'T1z', 0),
}
ORDER1 = ['PA', 'PB', 'PC', 'PD', 'PF', 'PH', 'PE', 'LA', 'LB', 'LC', 'LD', 'LE', 'LF', 'PL', 'PZ', 'LN']
ORDER2 = ['Q0', 'Q1', 'Q2', 'Q3', 'Q4', 'Q5']       # R6i-2 (docs/R6I2_PLAN.md 2-2)
ORDER3 = ['N1', 'N2', 'N3', 'N4', 'N5']             # R6i-3 (docs/R6I3_PLAN.md 2-2)
ORDER4 = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6', 'J7', 'J8', 'J9', 'J0']    # R6j (docs/R6J_PLAN.md 2-2)
ORDER = ORDER1 + ORDER2 + ORDER3 + ORDER4
CASE_NUM = dict((n, FIRST + k) for k, n in enumerate(ORDER))
LAST = FIRST + len(ORDER) - 1                   # 124
TEX_ORDER = [n for n in ORDER if CASES[n][0] == 'tex']          # the cpR6T rows this rung appends
W_ORDER = ['WB', 'WC', 'WF']                                    # the cpR6W rows
WROW = {'WB': WB, 'WC': WC, 'WF': WF}
CONTROLS = {'PE': 57, 'PZ': 68}                 # the affine cases re-run in the same boot (plan 3)

GEOM_T = do.GEOM['T1z']
GEOM_V8 = go.GCASES['V8'][0]
Z_I1 = [Fr(do.fromhex(h)) for h in do.ICASES['I1'][1]]        # (0.25, 0.75, 0.25)


def kind(case):
    return CASES[case][0]


def tex_of(case):
    w, h, pat = CASES[case][1]
    return w, h, to_.row_stride(w), pat


def clamp_of(case):
    return CASES[case][2]


def filter_of(case):
    return CASES[case][3]


def st_of(case):
    return CASES[case][4]


def w_of(case):
    return CASES[case][5]


def recntl_of(case):
    return CASES[case][6]


def vte_of(case):
    return CASES[case][7]


def fmtx_of(case):
    return CASES[case][8]


def ppcntl_of(case):
    return to_.PP_CNTL_TEX | CASES[case][10]


GEOMS = {'T1z': None, 'Q': GEOM_Q, 'V8': None}      # filled below


def geom_of(case):
    g = CASES[case][9]
    return GEOM_V8 if g == 'V8' else GEOM_Q if g == 'Q' else GEOM_T


def tri_row(case):
    """the cpR6Tris row this case draws: T1z is the R6f one, Q is this rung's new row"""
    return TRI_Q if CASES[case][9] == 'Q' else 49 if CASES[case][9] == 'V8' else do.TRI_FIRST


TRI_Q = 57                                          # the row the driver appends (CP_R6_TRIS 57)


# ---- the texture in memory ----------------------------------------------------------------------

_tw = {}


def texture_words(case):
    if case in _tw:
        return _tw[case]
    w, h, stride, pat = tex_of(case)
    out = [zo.pattern((TEX_OFF // 4) + i) for i in range(TEX_BYTES // 4)]
    for v in range(h):
        for u in range(w):
            out[(v * stride) // 4 + u] = texel(pat, u, v)
    _tw[case] = out
    return out


def sampled(case, u, v, wh=None):
    """the texel word at (u, v); wh overrides the (width, height) the sampler is assumed to use"""
    w, h, stride, _ = tex_of(case)
    if wh is not None:
        w, h = wh
        stride = to_.row_stride(w)
    return texture_words(case)[(v * stride) // 4 + u]


# ---- interpolation -------------------------------------------------------------------------------

_bary = {}


def bary(case, off):
    """{(x, y): (l0, l1, l2)} -- exact affine barycentrics at pixel + off, vertices truncated to 1/16"""
    key = (tuple(map(tuple, geom_of(case))), off)
    if key in _bary:
        return _bary[key]
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in geom_of(case)]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    out = {}
    for x, y in go.covered(geom_of(case)):
        sx, sy = Fr(x) + off, Fr(y) + off
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        out[(x, y)] = (1 - w1 - w2, w1, w2)
    _bary[key] = out
    return out


def qtriple(case, model):
    """the per-vertex q the model interpolates with (None: plain affine weights)"""
    if model == 'A':
        return None
    W = w_of(case)
    return W if model == 'Pq' else tuple(1 / v for v in W)


def trunc_recip(den, prec):
    """1/den, truncated to a multiple of 2^-prec (None: exact)"""
    if prec is None:
        return 1 / den
    return Fr(math.floor(Fr(1 << prec) / den), 1 << prec)


def weights(case, model, off, prec=None):
    """{(x, y): (w0, w1, w2)} -- the weights the model gives each vertex"""
    out = {}
    q = qtriple(case, model)
    for p, l in bary(case, off).items():
        if q is None:
            out[p] = l
        else:
            n = [l[i] * q[i] for i in range(3)]
            r = trunc_recip(sum(n), prec)
            out[p] = tuple(v * r for v in n)
    return out


def coord(case, vals, model, off, prec=None):
    return dict((p, sum(w[i] * Fr(vals[i]) for i in range(3)))
                for p, w in weights(case, model, off, prec).items())


# ---- the nearest rule space ----------------------------------------------------------------------

MODELS = ('A', 'Pq', 'Pw')
# the sample position inside the pixel: R6h could not separate these (an affine ST moves the texel
# only at a boundary, and those pixels are the risky ones); the R6i perspective cases can, and they
# name 1/2 -- the pixel centre, the same point coverage, colour and depth use (docs/R6I_PLAN.md 8)
OFFS = (Fr(0), Fr(1, 8), Fr(1, 4), Fr(5, 16), Fr(3, 8), Fr(7, 16), Fr(1, 2))
PRECS = (None, 24, 20, 16)
NRULES = [(m, o, pr) for m in MODELS for o in OFFS for pr in PRECS]
MEASURED_OFF = Fr(1, 2)                         # measured on boot ff78c18a (PB, PC, PF fit only here)


def _index(f, n, c):
    t = math.floor(f)
    if c == 'clamp':
        return max(0, min(n - 1, t))
    return t % n


_nm = {}


def nearest_map(case, rule, wh=None):
    """{(x, y): (pixel word, safe)} the nearest rule predicts"""
    key = (case, rule, wh)
    if key in _nm:
        return _nm[key]
    model, off, prec = rule
    w, h, _, _ = tex_of(case)
    if wh is not None:
        w, h = wh
    st, tt = st_of(case)
    s, t = coord(case, st, model, off, prec), coord(case, tt, model, off, prec)
    c = clamp_of(case)
    out = {}
    for p in s:
        fs, ft = s[p] * w, t[p] * h
        safe = min(fs - math.floor(fs), math.floor(fs) + 1 - fs) > DELTA and \
               min(ft - math.floor(ft), math.floor(ft) + 1 - ft) > DELTA
        out[p] = (sampled(case, _index(fs, w, c), _index(ft, h, c), wh), safe)
    _nm[key] = out
    return out


# ---- the bilinear rule space ----------------------------------------------------------------------

AOFF = (Fr(0), Fr(-1, 2))
QUANTA = (None, 16, 32, 64, 128, 256)
QROUND = ('floor', 'round', 'even')
FINAL = ('floor', 'round')
BRULES = [(m, o, a, q, qr, f) for m in MODELS for o in OFFS for a in AOFF
          for q in QUANTA for qr in QROUND for f in FINAL
          if not (q is None and qr != 'floor')]      # with no quantum the rounding axis is empty


def quantise(f, q, qr):
    if q is None:
        return f
    z = f * q
    if qr == 'floor':
        k = math.floor(z)
    elif qr == 'round':
        k = math.floor(z + Fr(1, 2))
    else:
        k = round(z)                                  # half to even
    return Fr(k, q)


_bm = {}


def bilinear_map(case, rule):
    """{(x, y): (pixel word, safe)} the bilinear rule predicts, channel by channel"""
    key = (case, rule)
    if key in _bm:
        return _bm[key]
    model, off, a, q, qr, fin = rule
    w, h, _, pat = tex_of(case)
    st, tt = st_of(case)
    s, t = coord(case, st, model, off), coord(case, tt, model, off)
    c = clamp_of(case)
    out = {}
    for p in s:
        fs, ft = s[p] * w + a, t[p] * h + a
        i0, j0 = math.floor(fs), math.floor(ft)
        fu, fv = quantise(fs - i0, q, qr), quantise(ft - j0, q, qr)
        safe = min(fs - i0, i0 + 1 - fs) > DELTA and min(ft - j0, j0 + 1 - ft) > DELTA
        word = 0
        for lane in range(4):
            acc = 0
            for du, wu in ((0, 1 - fu), (1, fu)):
                for dv, wv in ((0, 1 - fv), (1, fv)):
                    tx = sampled(case, _index(i0 + du, w, c), _index(j0 + dv, h, c))
                    acc += wu * wv * ((tx >> (8 * lane)) & 0xff)
            v = math.floor(acc) if fin == 'floor' else math.floor(acc + Fr(1, 2))
            word |= max(0, min(255, v)) << (8 * lane)
        out[p] = (word, safe)
    _bm[key] = out
    return out


def predict(case, rule, wh=None):
    """the case's map under a rule of its own space"""
    return bilinear_map(case, rule) if filter_of(case) == 'linear' else nearest_map(case, rule, wh)


def rules_of(case):
    return BRULES if filter_of(case) == 'linear' else NRULES


# ---- R6j: the blend unit (docs/R6J_PLAN.md 2) ----------------------------------------------------

BLEND_DST_V = ((0x10, 0x20, 0xf0, 0x40), (0xe0, 0x90, 0x30, 0xc0), (0x70, 0xf0, 0x80, 0x20))
BLEND_SRC = (0xc1, 0x2a, 0x9b, 0x37)            # (r, g, b, a) of the flat second draw
TRI_J = 58                                      # the cpR6Tris row the first draw uses
RB3D_BLEND = do.RB3D_Z_ON | 1                   # ALPHA_BLEND_ENABLE on top of our usual value
RB3D_BLEND_ROUND = RB3D_BLEND | 8               # + ROUND_ENABLE (plan J3)
GLF = {'ZERO': 32, 'ONE': 33, 'SRC_COLOR': 34, 'ONE_MINUS_SRC_COLOR': 35, 'DST_COLOR': 36,
       'ONE_MINUS_DST_COLOR': 37, 'SRC_ALPHA': 38, 'ONE_MINUS_SRC_ALPHA': 39, 'DST_ALPHA': 40,
       'ONE_MINUS_DST_ALPHA': 41}
COMB = {'ADD_CLAMP': 0 << 12, 'ADD_NOCLAMP': 1 << 12, 'SUB_CLAMP': 2 << 12, 'SUB_NOCLAMP': 3 << 12,
        'MIN': 4 << 12, 'MAX': 5 << 12, 'RSUB_CLAMP': 6 << 12, 'RSUB_NOCLAMP': 7 << 12}
# name: (source factor, destination factor, combine, RB3D_CNTL of the second draw, a wait between)
BCASES = {
    'J1': ('ONE', 'ZERO', 'ADD_CLAMP', RB3D_BLEND, False),
    'J2': ('ZERO', 'ONE', 'ADD_CLAMP', RB3D_BLEND, False),
    'J3': ('ONE', 'ONE', 'ADD_CLAMP', RB3D_BLEND, False),
    'J4': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD_CLAMP', RB3D_BLEND, False),
    'J5': ('DST_COLOR', 'ZERO', 'ADD_CLAMP', RB3D_BLEND, False),
    'J6': ('SRC_ALPHA', 'ONE', 'ADD_CLAMP', RB3D_BLEND, False),
    'J7': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD_CLAMP', RB3D_BLEND_ROUND, False),
    'J8': ('ONE', 'ONE', 'SUB_CLAMP', RB3D_BLEND, False),
    'J9': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD_CLAMP', RB3D_BLEND, True),
    'J0': (None, None, None, 0, False),         # the control: the second draw with blending off
}


def blendcntl(case):
    fs, fd, comb, _, _ = BCASES[case]
    if fs is None:
        return 0
    return COMB[comb] | (GLF[fs] << 16) | (GLF[fd] << 24)


def rb3d2(case):
    return BCASES[case][3]


def blend_wait(case):
    return BCASES[case][4]


_bd = {}


def blend_dst():
    """the first draw's Gouraud destination by the measured rule B: {(x, y): (r, g, b, a)}"""
    if _bd:
        return _bd['v']
    pts = GEOM_Q
    out = dict((p, []) for p in go.covered(pts))
    for c in range(4):
        vals = [BLEND_DST_V[v][c] for v in range(3)]
        for p, b in zip(go.covered(pts), go.rule_b(pts, vals, 'even')):
            out[p].append(b)
    _bd['v'] = dict((p, tuple(v)) for p, v in out.items())
    return _bd['v']


def factor_value(name, src, dst, lane):
    """the 0..255 factor this GL name gives for one channel (lane order b, g, r, a)"""
    if name == 'ZERO':
        return 0
    if name == 'ONE':
        return 255
    if name == 'SRC_COLOR':
        return src[lane]
    if name == 'ONE_MINUS_SRC_COLOR':
        return 255 - src[lane]
    if name == 'DST_COLOR':
        return dst[lane]
    if name == 'ONE_MINUS_DST_COLOR':
        return 255 - dst[lane]
    if name == 'SRC_ALPHA':
        return src[3]
    if name == 'ONE_MINUS_SRC_ALPHA':
        return 255 - src[3]
    if name == 'DST_ALPHA':
        return dst[3]
    return 255 - dst[3]                          # ONE_MINUS_DST_ALPHA


FMAPS = {'id': lambda x: x, 'sat256': lambda x: 256 if x == 255 else x,
         'expand': lambda x: x + (x >> 7),
         # R6j on the hardware: 0x37 enters the product as 0x38 and 0xc8 as 0xc9, which neither of
         # the two saturating readings gives.  Both of these do; they differ only at f = 0, where
         # the product is zero either way, so they are one class (docs/R6J_PLAN.md 7).
         'plus1': lambda x: x + 1, 'ceil255': lambda x: -((-x * 256) // 255)}
BLEND_RULES = [(fm, r) for fm in sorted(FMAPS) for r in range(256)]


def blend_map(case, rule, comb_override=None):
    """{(x, y): pixel word} one R6j case under a named blend arithmetic; comb_override reads the
    combine function another way (SUB_CLAMP as destination minus source, say)"""
    fm, r = rule
    fs, fd, comb, _, _ = BCASES[case]
    if comb_override is not None:
        comb = comb_override
    out = {}
    for p, d in blend_dst().items():
        dl = (d[2], d[1], d[0], d[3])            # rule B gives (r, g, b, a); the word's lanes are b, g, r, a
        sl = (BLEND_SRC[2], BLEND_SRC[1], BLEND_SRC[0], BLEND_SRC[3])
        word = 0
        for lane in range(4):
            if fs is None:                       # blending off: the second draw replaces the destination
                v = sl[lane]
            else:
                a = FMAPS[fm](factor_value(fs, sl, dl, lane))
                b = FMAPS[fm](factor_value(fd, sl, dl, lane))
                t = (sl[lane] * a + r) >> 8
                u = (dl[lane] * b + r) >> 8
                if comb.startswith('ADD'):
                    v = t + u
                elif comb.startswith('RSUB'):
                    v = u - t
                elif comb.startswith('SUB'):
                    v = t - u
                elif comb == 'MIN':
                    v = min(t, u)
                else:
                    v = max(t, u)
                v = max(0, min(255, v)) if comb.endswith('CLAMP') else v & 0xff
            word |= (v & 0xff) << (8 * lane)
        out[p] = word
    return out


def blend_draw_words(case, seed):
    """R6j: F's state with Gouraud shading, the first draw (the destination), then -- in the same
    submission -- RB3D_BLENDCNTL and RB3D_CNTL, an optional WAIT_UNTIL, and the flat second draw"""
    fw = zo.draw_words('F', seed)
    state, pix, tail = list(fw[:26]), fw[26:34], fw[-10:]
    assert state[14] == zo.p0(zo.V('RADEON_SE_CNTL'))
    state[15] = go.se_cntl_gouraud()
    x1, y1, x2, y2 = to.CLIP
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]

    def draw(colours):
        body = [vf()]
        for (x, y), c in zip(GEOM_Q, colours):
            body += [to.fbits(x), to.fbits(y), to.fbits(0.5), to.fbits(1.0), to.word(c)]
        return [zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)] + body

    out = state + list(pix) + clip + draw([BLEND_DST_V[i] for i in range(3)])
    # the driver's second-draw path always re-states ZSTENCILCNTL first (R6g), then -- R6j -- the
    # blend registers, then the optional wait
    out += [zo.p0(zo.V('RADEON_RB3D_ZSTENCILCNTL')), do.ZCNTL[24]]
    bc = blendcntl(case)
    if bc:
        out += [zo.p0(zo.M('R200_RB3D_BLENDCNTL')), bc,
                zo.p0(zo.V('RADEON_RB3D_CNTL')), rb3d2(case)]
    if blend_wait(case):
        out += [zo.p0(zo.V('RADEON_WAIT_UNTIL')), do.WAIT_3D_IDLECLEAN]
    out += draw([BLEND_SRC] * 3)
    return out + list(tail)


def blend_g_values(case):
    """the twelve values of this case's cpR6G row: no prefill, the second draw's ZSTENCILCNTL, its
    three z values and flat colour, the wait flag, then (R6j) BLENDCNTL and the second RB3D_CNTL"""
    return [0, 0, 0, 0, do.ZCNTL[24], to.fbits(0.5), to.fbits(0.5), to.fbits(0.5),
            to.word(BLEND_SRC), 1 if blend_wait(case) else 0, blendcntl(case), rb3d2(case)]


def blend_case_values(case):
    """the 33 values of a blend case's row"""
    return [0, 0, 64, 64, 0, 0, 0, 0, to.fbits(0.5), RE_SCISSOR,
            0x1000, 0xffffffff, 0x803, 0x10000, header(case), vf(), 0, TRI_J, 0, 0,
            go.se_cntl_gouraud(), 0xf, 0, 0xf, do.ZCNTL[24], 0, 0, 0, do.RB3D_Z_ON,
            len(do.GORDER) + ORDER4.index(case) + 1, 0, 0, 0]


# ---- the R6i-2 weight-arithmetic space ----------------------------------------------------------

AQUANTA = (None, 16, 32, 64, 128, 256)
AWHERE = ('product', 'axis')                    # each of the four weights, or each axis then multiplied
AFINAL = ('floor', 'round')
ARULES = [(q, m, wh, f) for q in AQUANTA for m in QROUND for wh in AWHERE for f in AFINAL
          if not (q is None and (m != 'floor' or wh != 'product'))]

_am = {}


def arith_map(case, rule, off=None):
    """{(x, y): pixel word} -- the bilinear value this weight arithmetic gives, at the measured
    sample point and texel offset (docs/R6I2_PLAN.md 2-2)"""
    key = (case, rule, off)
    if key in _am:
        return _am[key]
    q, mode, where, fin = rule
    o = MEASURED_OFF if off is None else off
    w, h, _, pat = tex_of(case)
    st, tt = st_of(case)
    model = 'Pq' if recntl_of(case) & 8 else 'A'
    s, t = coord(case, st, model, o), coord(case, tt, model, o)
    c = clamp_of(case)
    out = {}
    for p in s:
        fs, ft = s[p] * w - Fr(1, 2), t[p] * h - Fr(1, 2)
        i0, j0 = math.floor(fs), math.floor(ft)
        fu, fv = fs - i0, ft - j0
        if where == 'axis':
            qu, qv = quantise(fu, q, mode), quantise(fv, q, mode)
            ws = [(0, 0, (1 - qu) * (1 - qv)), (1, 0, qu * (1 - qv)),
                  (0, 1, (1 - qu) * qv), (1, 1, qu * qv)]
        else:
            ws = [(0, 0, quantise((1 - fu) * (1 - fv), q, mode)), (1, 0, quantise(fu * (1 - fv), q, mode)),
                  (0, 1, quantise((1 - fu) * fv, q, mode)), (1, 1, quantise(fu * fv, q, mode))]
        word = 0
        for lane in range(4):
            acc = 0
            for du, dv, wt in ws:
                tx = sampled(case, _index(i0 + du, w, c), _index(j0 + dv, h, c))
                acc += wt * ((tx >> (8 * lane)) & 0xff)
            v = math.floor(acc + Fr(1, 2)) if fin == 'round' else math.floor(acc)
            word |= max(0, min(255, v)) << (8 * lane)
        out[p] = word
    _am[key] = out
    return out


# ---- the two-stage filter the R6i-2 boot measured (docs/R6I2_PLAN.md 8) ---------------------------
# Each axis' fraction is truncated to k/q; each 1-D mix is (a*(q-k) + b*k + r) >> log2(q), with its
# own rounding constant r.  The earlier one-step space could not express that (it had one rounding
# for the whole filter), which is why the first judging of ff6dab1c found no name.
AQ = (32, 64, 128, 256)
AR = (0, 1, 2, 3, 4, 5, 6, 7)                   # r = AR * q / 8
ARULES2 = [(q, m, r1, r2) for q in AQ for m in ('floor', 'round') for r1 in AR for r2 in AR]
MEASURED_ARITH = (64, 'floor', 6, 4)            # r1 = 48/64, r2 = 32/64 (bit clear, boot ff6dab1c)


def arith_map_chan(case, rule):
    """R6i-3: the same two-stage filter, but the rounding constant follows the COLOUR CHANNEL
    (R keeps the 48, G keeps the 32) instead of the axis -- the reading the transposed pattern
    tells apart (docs/R6I3_PLAN.md 2-3)"""
    q, mode, r1, r2 = rule
    sh = q.bit_length() - 1
    w, h, _, pat = tex_of(case)
    c = clamp_of(case)
    out = {}
    for p, i0, fu, j0, fv in taps(case):
        ku = math.floor(fu * q) if mode == 'floor' else math.floor(fu * q + Fr(1, 2))
        kv = math.floor(fv * q) if mode == 'floor' else math.floor(fv * q + Fr(1, 2))
        word = 0
        for lane in range(4):
            R = (r1 if lane == 2 else r2) * q // 8      # lane 2 is R, lane 1 is G (ARGB word)
            def tx(du, dv):
                return (sampled(case, _index(i0 + du, w, c), _index(j0 + dv, h, c)) >> (8 * lane)) & 0xff
            row0 = (tx(0, 0) * (q - ku) + tx(1, 0) * ku + R) >> sh
            row1 = (tx(0, 1) * (q - ku) + tx(1, 1) * ku + R) >> sh
            val = (row0 * (q - kv) + row1 * kv + R) >> sh
            word |= max(0, min(255, val)) << (8 * lane)
        out[p] = word
    return out

_taps = {}


def taps(case):
    """[(x, y, i0, ku, j0, kv)] per covered pixel, at the measured sample point and texel offset,
    for a quantum of 2^k: ku is computed per rule, so keep the exact fractions here"""
    if case in _taps:
        return _taps[case]
    w, h, _, _ = tex_of(case)
    st, tt = st_of(case)
    model = 'Pq' if recntl_of(case) & 8 else 'A'
    s, t = coord(case, st, model, MEASURED_OFF), coord(case, tt, model, MEASURED_OFF)
    out = []
    for p in sorted(s):
        u, v = s[p] * w - Fr(1, 2), t[p] * h - Fr(1, 2)
        i0, j0 = math.floor(u), math.floor(v)
        out.append((p, i0, u - i0, j0, v - j0))
    _taps[case] = out
    return out


_a2 = {}


def arith_map2(case, rule):
    """{(x, y): pixel word} under the two-stage filter"""
    key = (case, rule)
    if key in _a2:
        return _a2[key]
    q, mode, r1, r2 = rule
    sh = q.bit_length() - 1
    R1, R2 = r1 * q // 8, r2 * q // 8
    w, h, _, pat = tex_of(case)
    c = clamp_of(case)
    out = {}
    for p, i0, fu, j0, fv in taps(case):
        ku = math.floor(fu * q) if mode == 'floor' else math.floor(fu * q + Fr(1, 2))
        kv = math.floor(fv * q) if mode == 'floor' else math.floor(fv * q + Fr(1, 2))
        word = 0
        for lane in range(4):
            def tx(du, dv):
                return (sampled(case, _index(i0 + du, w, c), _index(j0 + dv, h, c)) >> (8 * lane)) & 0xff
            row0 = (tx(0, 0) * (q - ku) + tx(1, 0) * ku + R1) >> sh
            row1 = (tx(0, 1) * (q - ku) + tx(1, 1) * ku + R1) >> sh
            val = (row0 * (q - kv) + row1 * kv + R2) >> sh
            word |= max(0, min(255, val)) << (8 * lane)
        out[p] = word
    _a2[key] = out
    return out


def arith_classes2(cases):
    cls = {}
    for r in ARULES2:
        key = tuple(tuple(arith_map2(n, r)[p] for p in sorted(arith_map2(n, r))) for n in cases)
        cls.setdefault(key, []).append(r)
    return cls


def arith_classes(cases):
    """{picture: [rules that give it]} over the named arithmetic space -- the classes this rung can
    tell apart (the plan states the ones it cannot)"""
    cls = {}
    for r in ARULES:
        key = tuple(tuple(arith_map(n, r)[p] for p in sorted(arith_map(n, r))) for n in cases)
        cls.setdefault(key, []).append(r)
    return cls


# ---- PE (Gouraud with W) and PZ (depth with W) -------------------------------------------------

def gouraud_bytes(case, lane, model, wmode='even'):
    """R6e rule B (docs/R6E_PLAN.md 20) with the model's weights: the two weights other than the
    leftmost vertex's rounded to 1/256, the weighted sum floored -- in covered() order"""
    pts = geom_of(case)
    vals = go.lane_triple('V8', lane)
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in pts]
    L = min(range(3), key=lambda i: (P[i][0], P[i][1]))
    out = []
    W = weights(case, model, Fr(1, 2))
    for p in go.covered(pts):
        w = list(W[p])
        for i in range(3):
            if i != L:
                z = w[i] * 256
                w[i] = Fr(math.floor(z + Fr(1, 2)) if wmode == 'round' else round(z), 256)
        w[L] = 1 - sum(w[i] for i in range(3) if i != L)
        out.append(max(0, min(255, math.floor(sum(wi * Fr(ci) for wi, ci in zip(w, vals))))))
    return bytes(out)


def depth_values(case, model, bits=24):
    """{(x, y): the depth word} -- R6f's rule (the plane, floored) with the model's weights"""
    out = {}
    for p, w in weights(case, model, Fr(1, 2)).items():
        z = sum(w[i] * Z_I1[i] for i in range(3))
        out[p] = max(0, min((1 << bits) - 1, math.floor(z * (1 << bits))))
    return out


# ---- the ring words -------------------------------------------------------------------------------

def txfilter(case):
    """the case's PP_TXFILTER: MAG/MIN as the case asks, the clamp, MAX_MIP_LEVEL 0 (plan Y5, Y12)"""
    if filter_of(case) == 'linear':
        f = zo.M('R200_MAG_FILTER_LINEAR') | zo.M('R200_MIN_FILTER_LINEAR')
    else:
        f = zo.M('R200_MAG_FILTER_NEAREST') | zo.M('R200_MIN_FILTER_NEAREST')
    if clamp_of(case) == 'wrap':
        return f | zo.M('R200_CLAMP_S_WRAP') | zo.M('R200_CLAMP_T_WRAP')
    return f | zo.M('R200_CLAMP_S_CLAMP_LAST') | zo.M('R200_CLAMP_T_CLAMP_LAST')


def vf(nv=3):
    return (zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') |
            zo.M('R200_VF_COLOR_ORDER_RGBA') | (nv << 16))


def header(case):
    return zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), 3 * (7 if kind(case) == 'tex' else 5))


def draw_words(case, seed, win=0):
    if kind(case) == 'blend':
        return blend_draw_words(case, seed)
    """the case's submission: R6c F's state with this case's RE_CNTL / VTE (and, when textured, the
    texture unit and a seven-word vertex carrying W and ST)"""
    if kind(case) == 'tex':
        base = to_.draw_words('XA', seed, win)                  # R6h's shape: state 26, blend 8, tex 12, clip 4
        state, pix, tex, clip, tail = base[:26], base[26:34], base[34:46], base[46:50], base[-10:]
        w, h, stride, _ = tex_of(case)
        tex = list(tex)
        tex[1], tex[3], tex[5] = txfilter(case), to_.txformat(w, h), fmtx_of(case)
        tex[7], tex[9] = to_.txsize(w, h), to_.txpitch(stride) & M32
    else:
        src = go.draw_words('V8', seed) if kind(case) == 'gouraud' else do.draw_words('I1_24', seed)
        state, pix, tex, clip, tail = src[:26], src[26:34], [], src[34:38], src[-10:]
    state = list(state)
    assert state[4] == zo.p0(zo.V('R200_RE_CNTL')) and state[16] == zo.p0(zo.V('R200_SE_VTE_CNTL'))
    state[5], state[17] = recntl_of(case), vte_of(case)
    if kind(case) == 'tex':
        assert state[2] == zo.p0(zo.V('RADEON_PP_CNTL'))
        state[3] = ppcntl_of(case)              # R6i-2: FILTER_ROUND_MODE in Q5 (plan Z6)
    body = [vf()]
    W = [to.fbits(float(v)) for v in w_of(case)]
    if kind(case) == 'tex':
        st, tt = st_of(case)
        for (vx, vy), s, t, wq in zip(geom_of(case), st, tt, W):
            body += [to.fbits(vx), to.fbits(vy), to.fbits(0.5), wq, to.word(do.C1),
                     to.fbits(float(s)), to.fbits(float(t))]
    elif kind(case) == 'gouraud':
        for (vx, vy), c, wq in zip(GEOM_V8, go.GCASES['V8'][1], W):
            body += [to.fbits(vx), to.fbits(vy), to.fbits(to.Z), wq, to.word(c)]
    else:
        for (vx, vy), z, wq in zip(geom_of(case), do.ICASES['I1'][1], W):
            body += [to.fbits(vx), to.fbits(vy), int(z, 16), wq, to.word(do.C1)]
    hdr = zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)
    return list(state) + list(pix) + list(tex) + list(clip) + [hdr] + body + list(tail)


def words_needed(case):
    return len(draw_words(case, 1))


# ---- the C rows ------------------------------------------------------------------------------------

def tex_values(case):
    """the 15 values of a cpR6T row: w, h, stride, filter, format, txsize, txpitch, s0..t2, pat, fmtx"""
    w, h, stride, pat = tex_of(case)
    st, tt = st_of(case)
    return ([w, h, stride, txfilter(case), to_.txformat(w, h), to_.txsize(w, h), to_.txpitch(stride) & M32] +
            [to.fbits(float(v)) for pair in zip(st, tt) for v in pair] + [pat, fmtx_of(case)])


def w_values(row):
    return [to.fbits(float(v)) for v in WROW[row]]


def widx_of(case):
    W = w_of(case)
    for k, name in enumerate(W_ORDER):
        if WROW[name] == W:
            return k + 1
    return 0                                            # all ones: the driver writes 1.0


def case_values(case):
    """the 33 values of a case row (osrdn_cp.m cpR6Case + widx, vte)"""
    k = kind(case)
    if k == 'blend':
        return blend_case_values(case)
    vte = 0 if vte_of(case) == VTE_BASE else vte_of(case)
    if k == 'tex':
        tidx = len(to_.ORDER) + TEX_ORDER.index(case) + 1
        return [0, 0, 64, 64, 0, 0, 0, 0, to.fbits(0.5), recntl_of(case),
                ppcntl_of(case), 0xffffffff, 0x803, 0x10000, header(case), vf(), 0, tri_row(case), 0, 0,
                do.SE_CNTL_FLAT, 0xf, 0, 0, do.ZCNTL[24], 0, 0, 0, do.RB3D_Z_ON, 0, tidx,
                widx_of(case), vte]
    if k == 'gouraud':                                  # case 57 (V8) with this rung's two fields
        return [0, 0, 64, 64, 0, 0, 0, 0, to.fbits(1.0), recntl_of(case),
                0x1000, 0xffffffff, 0x803, 0x10000, header(case), vf(), 0, 49, 0, 0,
                go.se_cntl_gouraud(), 0xf, 0, 0xf, do.ZCNTL[24], 0, 0, 0, do.RB3D_Z_ON, 0, 0,
                widx_of(case), vte]
    return [0, 0, 64, 64, 0, 0, 0, 0, 0, recntl_of(case),                    # case 68 (I1_24)
            0x1000, 0xffffffff, 0x803, 0x10000, header(case), vf(), 0, do.TRI_FIRST, 0x78123456, 0x78123456,
            do.SE_CNTL_FLAT, 7, 0, 0, do.ZCNTL[24], 1, 0, 1, do.RB3D_Z_ON, 0, 0,
            widx_of(case), vte]


def _hex(x):
    return '0x%xUL' % x if x > 255 else '%dUL' % x


def c_tables():
    L = ['/* R6i (docs/R6I_PLAN.md 2-1): a per-vertex W triple, float32 bits */',
         'static const unsigned long cpR6W[%d][3] = {' % len(W_ORDER)]
    L.append(',\n'.join('    { ' + ', '.join(_hex(x) for x in w_values(n)) + ' }   /* %s */' % n for n in W_ORDER))
    L.append('};')
    L.append('/* R6i: the cpR6T rows this rung appends (15 columns: the R6h thirteen, then pat and PP_TXFORMAT_X) */')
    L.append(',\n'.join('    { ' + ', '.join(_hex(x) for x in tex_values(n)) + ' }   /* %s */' % n for n in TEX_ORDER))
    L.append('/* R6i case rows */')
    for n in ORDER:
        v = case_values(n)
        L.append('    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, %s, %s,     /* %s */\n' % (_hex(v[8]), _hex(v[9]), n) +
                 '      ' + ', '.join(_hex(x) for x in v[10:]) + ' },')
    return '\n'.join(L)


# ---- the simulator's model (tools/r5/sim/world5.c) -------------------------------------------------

SIM_ALIAS = {'PE': 'V8', 'PZ': 'I1_24'}         # what world5.c draws for the two untextured cases


def _fd(a, b):
    return math.floor(Fr(a, b))


def sim_map(case):
    """{(x, y): pixel word} the fake 3D writes for a textured case -- world5.c's model, mirrored
    exactly: NEAREST and AFFINE whatever the case asks for (the filter bits and W are what the
    hardware measures, not the model), ST interpolated in 1/65536 with the slopes floored to that
    unit, sampled at pixel + 1/2, the measured row stride (plan 2-5)"""
    if kind(case) == 'blend':
        # the model has no blend unit: its second draw overwrites with the flat source
        px = to.pixel(BLEND_SRC)
        return dict((p, px) for p in go.covered(GEOM_Q))
    if kind(case) != 'tex':
        return {}
    w, h, stride, pat = tex_of(case)
    st, tt = st_of(case)
    G = geom_of(case)
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in G]
    X = [int(p[0] * 16) for p in P]
    Y = [int(p[1] * 16) for p in P]
    S = [int(Fr(to.f32(float(v))) * 65536) for v in st]
    T = [int(Fr(to.f32(float(v))) * 65536) for v in tt]
    A = (X[1] - X[0]) * (Y[2] - Y[0]) - (X[2] - X[0]) * (Y[1] - Y[0])
    sgn = -1 if A < 0 else 1
    A *= sgn
    qsx = _fd(sgn * ((S[1] - S[0]) * (Y[2] - Y[0]) - (S[2] - S[0]) * (Y[1] - Y[0])) * 16, A)
    qsy = _fd(sgn * ((S[2] - S[0]) * (X[1] - X[0]) - (S[1] - S[0]) * (X[2] - X[0])) * 16, A)
    qtx = _fd(sgn * ((T[1] - T[0]) * (Y[2] - Y[0]) - (T[2] - T[0]) * (Y[1] - Y[0])) * 16, A)
    qty = _fd(sgn * ((T[2] - T[0]) * (X[1] - X[0]) - (T[1] - T[0]) * (X[2] - X[0])) * 16, A)
    mode = clamp_of(case)
    words = texture_words(case)
    out = {}
    for x, y in go.covered(G):
        sx, sy = x * 16 + 8, y * 16 + 8
        sv = S[0] + _fd(qsx * (sx - X[0]) + qsy * (sy - Y[0]), 16)
        tv = T[0] + _fd(qtx * (sx - X[0]) + qty * (sy - Y[0]), 16)
        u = _index(Fr(sv * w, 65536), w, mode)
        v = _index(Fr(tv * h, 65536), h, mode)
        out[(x, y)] = words[(v * max(w * 4, 32)) // 4 + u]
    return out


def sim_block(case):
    """the 256 KiB block the model leaves for a textured case (or an R6j blend one: no texture)"""
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    if kind(case) == 'tex':
        tex = texture_words(case)
        words[TEX_OFF // 4:TEX_OFF // 4 + len(tex)] = tex
    zv = do.space(24)[do.SIM_CONV](0.5)
    for (x, y), px in sim_map(case).items():
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = px
        k = (zo.DEPTH_OFF + do.mba_z32(x, y)) // 4
        words[k] = (words[k] & 0xff000000) | zv
    return words


def sim_coverage_words(case):
    w = [0] * 64
    for (x, y) in sim_map(case):
        i = y * 32 + x
        w[i >> 4] |= 3 << (2 * (i & 15))
    return w


# ---- self-test -----------------------------------------------------------------------------------

def self_test():
    bad = 0

    def expect(what, got, want):
        nonlocal bad
        ok = got == want
        bad += not ok
        print('  %s  %s%s' % ('ok  ' if ok else 'FAIL', what, '' if ok else ': got %s, want %s' % (got, want)))

    expect('cases 109 .. 145', (FIRST, LAST, len(ORDER), len(ORDER1), len(ORDER2), len(ORDER3), len(ORDER4)),
           (109, 145, 37, 16, 6, 5, 10))
    # R6i-3: the transposed pattern is what tells the two readings of the rounding constant apart
    expect('pattern 3 is pattern 2 transposed',
           [texel(3, u, v) for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))],
           [texel(2, u, v) for u, v in ((0, 0), (0, 1), (1, 0), (1, 1))])
    for n2 in ('N1', 'N2'):
        a2 = arith_map2(n2, MEASURED_ARITH)
        c2 = arith_map_chan(n2, MEASURED_ARITH)
        expect('%s: "the constant follows the axis" and "it follows the channel" differ on 21 pixels' % n2,
               sum(1 for q in a2 if a2[q] != c2[q]), 21)
    for n2 in ('N1', 'N3', 'N5'):
        expect('%s sweeps inside one texel with an even tap' % n2,
               (sorted(set(i for _, i, _, _, _ in taps(n2))), sorted(set(j for _, _, _, j, _ in taps(n2)))),
               ([0] if n2 == 'N1' else [2], [1]))
    for n2 in ('N2', 'N4'):
        expect('%s sweeps down inside one texel with an even tap' % n2,
               (sorted(set(i for _, i, _, _, _ in taps(n2))), sorted(set(j for _, _, _, j, _ in taps(n2)))),
               ([2], [0] if n2 == 'N2' else [2]))
    expect('the bit-set cases carry FILTER_ROUND_MODE in PP_CNTL',
           [ppcntl_of(n2) for n2 in ('N3', 'N4', 'N5')], [0x1410, 0x1410, 0x1010])
    # R6j (docs/R6J_PLAN.md 2)
    expect('cases 136 .. 145 are the blend ones', (len(ORDER4), CASE_NUM['J1'], CASE_NUM['J0']), (10, 136, 145))
    expect('the blend factors sit at their GL numbers and the shifts Mesa uses',
           (blendcntl('J4'), blendcntl('J8'), blendcntl('J0')),
           ((39 << 24) | (38 << 16), (33 << 24) | (33 << 16) | (2 << 12), 0))
    expect('the second draw turns blending on (and J7 also ROUND_ENABLE)',
           [rb3d2(n2) for n2 in ('J4', 'J7', 'J0')], [0x1903, 0x190b, 0])
    d = blend_dst()
    expect('the destination sweeps every channel', (len(d), [len(set(v[c] for v in d.values())) for c in range(4)]),
           (120, [117, 117, 114, 65]))
    bl = [blend_map(n2, ('id', 128)) for n2 in ('J1', 'J3', 'J4', 'J5', 'J6')]
    expect('the blend rules are told apart: r = 0 and r = 128 differ on at least 200 of 480 bytes',
           min(sum(1 for q in m for l in range(4)
                   if ((m[q] >> (8 * l)) & 0xff) != ((blend_map(n2, ('id', 0))[q] >> (8 * l)) & 0xff))
               for n2, m in zip(('J1', 'J3', 'J4', 'J5', 'J6'), bl)) >= 50, True)
    a8 = blend_map('J8', ('id', 0))
    expect('J8 tells the two subtract directions apart on every pixel',
           sum(1 for q in a8 if a8[q] != blend_map('J8', ('id', 0), 'RSUB_CLAMP')[q]), 120)
    expect('J9 is J4 with a wait between the draws',
           (blendcntl('J9') == blendcntl('J4'), blend_wait('J9'), blend_wait('J4')), (True, True, False))
    pat = set(zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4))
    tx = [texel(p, u, v) for p in (1, 2) for u in range(8) for v in range(8)]
    expect('no pattern word among the new texels', any(t in pat for t in tx), False)
    expect('pattern 1 tells the four corners of a 2x2 apart',
           sorted(set(texel(1, u, v) for u in range(2) for v in range(2))),
           [0xff000000, 0xff00ff00, 0xffff0000, 0xffffffff])
    expect('pattern 2 puts u in R and v in G only',
           (texel(2, 0, 0), texel(2, 1, 0), texel(2, 0, 1), texel(2, 1, 1)),
           (0xff000055, 0xffff0055, 0xff00ff55, 0xffffff55))
    expect('every W is non-zero', all(v != 0 for n in W_ORDER for v in WROW[n]), True)
    w, h, stride, _ = tex_of('LN')
    expect('the widest texture still fits the reserved KiB',
           max((tex_of(n)[1] - 1) * tex_of(n)[2] + tex_of(n)[0] * 4 for n in TEX_ORDER) <= TEX_BYTES, True)
    expect('LN is 2 wide, 8 high, 32-byte rows', (w, h, stride), (2, 8, 32))
    expect('the longest submission fits CP_R6_WORDS', max(words_needed(n) for n in ORDER) <= do.WORDS_MAX, True)

    # the state the cases ask for reaches the ring
    for n in ('PB', 'PF', 'LA'):
        dw = draw_words(n, 7, win=0x0029e000)
        expect('%s: RE_CNTL and VTE in the state block' % n, (dw[5], dw[17]), (recntl_of(n), vte_of(n)))
    dw = draw_words('PB', 7)
    expect('PB: the vertices carry the W triple', (dw[55], dw[62], dw[69]),
           tuple(to.fbits(float(v)) for v in WB))
    expect('LA: PP_TXFILTER has both LINEAR bits and MAX_MIP_LEVEL 0',
           (txfilter('LA') & 3, (txfilter('LA') >> 16) & 0xf), (3, 0))
    expect('LB: the same texture, nearest', txfilter('LB') & 3, 0)

    # separation: the models pick different texels
    for n, want in (('PB', 77), ('PC', 77)):
        worst = min(sum(1 for p, (v, s) in nearest_map(n, (m1, o1, None)).items()
                        if s and nearest_map(n, (m2, o2, None))[p][1] and v != nearest_map(n, (m2, o2, None))[p][0])
                    for m1 in MODELS for m2 in MODELS if m1 < m2 for o1 in OFFS for o2 in OFFS)
        expect('%s: every pair of models differs on at least %d safe pixels' % (n, want), worst >= want, True)
    expect('PA and PH are the affine picture (W = 1: the models coincide)',
           all(nearest_map('PA', ('A', MEASURED_OFF, None))[p][0] == nearest_map('PA', (m, MEASURED_OFF, None))[p][0]
               for m in MODELS for p in nearest_map('PA', ('A', MEASURED_OFF, None))), True)

    # the bilinear cases separate the texel offset a
    for n in ('LA', 'LC', 'LD', 'LF'):
        r0 = bilinear_map(n, ('A', MEASURED_OFF, Fr(0), None, 'floor', 'floor'))
        rh = bilinear_map(n, ('A', MEASURED_OFF, Fr(-1, 2), None, 'floor', 'floor'))
        both = [p for p in r0 if r0[p][1] and rh[p][1]]
        d = sum(1 for p in both if
                max(abs(((r0[p][0] >> (8 * l)) & 0xff) - ((rh[p][0] >> (8 * l)) & 0xff)) for l in range(4)) < 2)
        expect('%s: a = 0 and a = -1/2 agree on at most three pixels safe in both' % n,
               (len(both) >= 150, d <= 3), (True, True))
    b = bilinear_map('LD', ('A', MEASURED_OFF, Fr(0), None, 'floor', 'floor'))
    expect('LD: the alpha lane is 0xff and B is 0x55 everywhere (the weights sum to one)',
           set(((v[0] >> 24) & 0xff, v[0] & 0xff) for v in b.values()), {(0xff, 0x55)})

    expect('the I1 z triple is (1/4, 3/4, 1/2 of it): the R6f ramp', [float(z) for z in Z_I1], [0.25, 0.75, 0.25])
    expect('every ST value is exact in float32',
           all(Fr(to.f32(float(v))) == Fr(v) for n in TEX_ORDER for tup in st_of(n) for v in tup), True)
    # PE and PZ differ from their control cases only in RE_CNTL, VTE and the W words
    for n, ctl in (('PE', go.draw_words('V8', 7)), ('PZ', do.draw_words('I1_24', 7))):
        mine = draw_words(n, 7)
        diff = [i for i, (a, b) in enumerate(zip(mine, ctl)) if a != b]
        expect('%s is its control case but for RE_CNTL and the two W words that are not 1.0' % n,
               (len(mine) == len(ctl), diff, mine[5], mine[48], mine[53]),
               (True, [5, 48, 53], RE_PERSP, to.fbits(1 / 8.0), to.fbits(0.5)))

    # PE and PZ: the two models are far apart
    a8 = gouraud_bytes('PE', 'R', 'A')
    p8 = gouraud_bytes('PE', 'R', 'Pq')
    expect('PE: the affine and perspective colours differ on at least 60 pixels',
           sum(1 for x, y in zip(a8, p8) if abs(x - y) >= 8) >= 60, True)
    za, zp = depth_values('PZ', 'A'), depth_values('PZ', 'Pq')
    expect('PZ: every covered pixel differs by at least 256 depth LSBs',
           all(abs(za[p] - zp[p]) >= 256 for p in za), True)

    # LN tells the axes apart
    a = nearest_map('LN', ('A', MEASURED_OFF, None))
    b = nearest_map('LN', ('A', MEASURED_OFF, None), wh=(8, 2))
    expect('LN: 2x8 and the swapped 8x2 differ on 267 of 276 pixels',
           sum(1 for p in a if a[p][0] != b[p][0]), 267)

    expect('the model samples nearest and affine (PB and PD leave the same picture)',
           sim_map('PB') == sim_map('PD'), True)
    expect('LB and LA leave the same picture in the model (it ignores the filter bits)',
           sim_map('LA') == sim_map('LB'), True)
    expect('LN reaches twelve of its 2x8 texels (the triangle is half the square)',
           len(set(sim_map('LN').values())), 12)
    print('persp_oracle: %s' % ('PASS' if bad == 0 else 'FAIL %d' % bad))
    return bad == 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(0 if self_test() else 1)
    if sys.argv[1:] == ['--c-tables']:
        print(c_tables())
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
