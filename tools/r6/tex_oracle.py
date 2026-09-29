#!/usr/bin/env python3
"""R6h oracle (docs/R6H_PLAN.md 2): the first textured triangle -- the texels the CPU writes, the
ring words, and the pixel every named ST -> texel rule predicts.

  tex_oracle.py --self-test
  tex_oracle.py --c-tables          the C rows the driver carries (osrdn_cp.m)

Cases 102-108 draw T1z with a nearest-filtered ARGB8888 texture in the alias at 0x20000 and read the
colour buffer back as four byte planes.  The rule space is u = C(floor(s*w + a)), a in {0, -1/2, +1/2},
C in {clamp to last, wrap, mirror}; a pixel whose texel coordinate lands within 2^-10 of a texel
boundary is RISKY (the interpolation's own rounding could move it) and is recorded, not gated.
"""

import importlib.util
import math
import os
import sys
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('depth_oracle', os.path.join(HERE, 'depth_oracle.py'))
do = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(do)
go, to, zo = do.go, do.to, do.zo
M32 = 0xffffffff

TEX_OFF = 0x20000                               # inside the alias, clear of depth and colour (plan X6)
TEX_BYTES = 1024                                # reserved: the widest row stride case needs 512
GEOM = do.GEOM['T1z']
C1 = do.C1
DELTA = Fr(1, 1024)                             # "far from a texel boundary" (plan 2-2)


def texel(u, v):
    """the texel word the CPU writes: distinct, and never equal to a ZPREP pattern word (alpha ff)"""
    return 0xff000000 | ((u * 32) << 16) | ((v * 32) << 8) | 0x55


# ---- the texture state (Mesa r200_reg.h through zclear_oracle's header reader) ----------------

def M(name):
    return zo.M(name)


def txfilter(mode):
    """nearest in both directions, the case's clamp on S and T"""
    f = M('R200_MAG_FILTER_NEAREST') | M('R200_MIN_FILTER_NEAREST')
    if mode == 'wrap':
        return f | M('R200_CLAMP_S_WRAP') | M('R200_CLAMP_T_WRAP')
    return f | M('R200_CLAMP_S_CLAMP_LAST') | M('R200_CLAMP_T_CLAMP_LAST')


def txformat(w, h):
    """ARGB8888 with alpha from the map (plan X2b) and the power-of-two size in log2 fields"""
    return (M('R200_TXFORMAT_ARGB8888') | M('R200_TXFORMAT_ALPHA_IN_MAP') |
            (int(math.log2(w)) << M('R200_TXFORMAT_WIDTH_SHIFT')) |
            (int(math.log2(h)) << M('R200_TXFORMAT_HEIGHT_SHIFT')) | M('R200_TXFORMAT_ST_ROUTE_STQ0'))


def txsize(w, h):
    return (w - 1) | ((h - 1) << 16)


def txpitch(stride):
    """what goes in PP_TXPITCH: the byte stride minus 32 (EXA), but never below Mesa's floor of a
    64-byte pitch -- a 4-wide ARGB8888 row is 16 bytes and stride - 32 would be negative (plan X9)"""
    return (stride if stride >= 32 else 64) - 32


def blend_texture():
    """stage 0 passes the sampled texel: out = R0 * (1 - 0) + 0, colour and alpha alike (plan X3)"""
    c = M('R200_TXC_OP_MADD') | M('R200_TXC_ARG_A_R0_COLOR') | M('R200_TXC_ARG_B_ZERO') | \
        M('R200_TXC_COMP_ARG_B') | M('R200_TXC_ARG_C_ZERO')
    a = M('R200_TXA_OP_MADD') | M('R200_TXA_ARG_A_R0_ALPHA') | M('R200_TXA_ARG_B_ZERO') | \
        M('R200_TXA_COMP_ARG_B') | M('R200_TXA_ARG_C_ZERO')
    return c, M('R200_TXC_CLAMP_0_1') | M('R200_TXC_OUTPUT_REG_R0'), a, M('R200_TXA_CLAMP_0_1') | M('R200_TXA_OUTPUT_REG_R0')


PP_CNTL_TEX = M('R200_TEX_BLEND_0_ENABLE') | M('R200_TEX_0_ENABLE')
VTX_FMT_1_ST = 2                                # two components on unit 0 (TEX0_COMP_CNT_SHIFT = 0)

# ---- the cases ----------------------------------------------------------------------------

# name: (texture (w, h, stride bytes), clamp mode, s triple, t triple)
TCASES = {
    'XA': ((8, 8, 32), 'clamp', (0, 1, 0), (0, 0, 1)),
    'XB': ((8, 8, 32), 'clamp', (Fr(1, 16), Fr(17, 16), Fr(1, 16)), (Fr(1, 16), Fr(1, 16), Fr(17, 16))),
    'XC': ((8, 8, 32), 'wrap', (0, 2, 0), (0, 0, 2)),
    'XD': ((8, 8, 32), 'clamp', (Fr(-1, 4), Fr(5, 4), Fr(-1, 4)), (Fr(-1, 4), Fr(-1, 4), Fr(5, 4))),
    'XE': ((8, 8, 64), 'clamp', (0, 1, 0), (0, 0, 1)),          # a 64-byte row stride: does POT read the pitch?
    'XF': ((4, 4, 16), 'clamp', (0, 1, 0), (0, 0, 1)),
    'XG': ((8, 8, 32), 'wrap', (0, 1, 0), (Fr(17, 32),) * 3),   # t fixed off a boundary (plan 2-2)
}
ORDER = ['XA', 'XB', 'XC', 'XD', 'XE', 'XF', 'XG']
FIRST = do.GLAST + 1                            # 102
CASE_NUM = dict((n, FIRST + k) for k, n in enumerate(ORDER))
LAST = FIRST + len(ORDER) - 1                   # 108


def tex_of(case):
    return TCASES[case][0]


def st_of(case):
    return TCASES[case][2], TCASES[case][3]


_tw = {}
_iv = {}
_rm = {}


def texture_words(case, stride_read=None):
    """the texture as words in the alias: row v at byte v*stride, texels across.  stride_read lets
    the judge ask "what if the sampler assumed another stride" (case XE, plan X9)"""
    if case in _tw:
        return _tw[case]
    w, h, stride = tex_of(case)
    n = TEX_BYTES // 4
    out = [zo.pattern((TEX_OFF // 4) + i) for i in range(n)]
    for v in range(h):
        for u in range(w):
            out[(v * stride) // 4 + u] = texel(u, v)
    _tw[case] = out
    return out


def row_stride(w):
    """the row stride the sampler uses (measured on boot ff9bdf88): the width in bytes, but never
    below 32 -- PP_TXPITCH is not read for a power-of-two texture (docs/R6H_PLAN.md X9)"""
    return max(w * 4, 32)


def sampled(case, u, v, stride_assumed=None):
    """the texel word the sampler reads for (u, v); stride_assumed overrides the measured stride"""
    w, h, stride = tex_of(case)
    s = stride_assumed if stride_assumed is not None else row_stride(w)
    words = texture_words(case)
    return words[(v * s) // 4 + u]


# ---- interpolation and the rule space ------------------------------------------------------

def interp(vals, off=Fr(1, 2)):
    """exact barycentric interpolation of a per-vertex value at pixel + off (1/16-truncated vertices).

    The default is 1/2 -- the PIXEL CENTRE -- because that is what R6i measured
    (docs/R6I_PLAN.md 199).  R6h had named 0 here; its cases were linear in ST
    and could not tell the two apart, and this docstring said so as if it were a
    finding.  It was not."""
    key = (tuple(vals), off)
    if key in _iv:
        return _iv[key]
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in GEOM]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    out = {}
    for x, y in go.covered(GEOM):
        sx, sy = Fr(x) + off, Fr(y) + off
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        out[(x, y)] = (1 - w1 - w2) * Fr(vals[0]) + w1 * Fr(vals[1]) + w2 * Fr(vals[2])
    _iv[key] = out
    return out


# a rule is (sample offset inside the pixel, the offset added before the floor, the clamp mode)
RULES = [(o, a, c) for o in (Fr(0), Fr(1, 2)) for a in (0, Fr(-1, 2), Fr(1, 2))
         for c in ('clamp', 'wrap', 'mirror')]
# SUPERSEDED, and kept only because R6h's own judging is written against it.
# R6i measured the ST sample position again with PERSPECTIVE (R6h's cases were
# linear in ST and could not separate the offsets at all) and found the PIXEL
# CENTRE: persp_oracle.MEASURED_OFF = 1/2, boot ff78c18a, docs/R6I_PLAN.md 199.
# ANYTHING NEW MUST USE 1/2.  Reading this constant as "the measured rule" is a
# live trap -- it agrees with R6h's geometry and is wrong in general.
MEASURED = (Fr(0), 0, None)                     # boot ff9bdf88, CORRECTED BY R6i -- see above


def _index(f, n, c):
    t = math.floor(f)
    if c == 'clamp':
        return max(0, min(n - 1, t))
    if c == 'wrap':
        return t % n
    p = t % (2 * n)                             # mirror: 0..n-1 then n-1..0
    return p if p < n else 2 * n - 1 - p


def rule_map(case, rule, stride_assumed=None):
    """{(x, y): (pixel word, safe)} -- what this rule predicts, and whether the pixel is far enough
    from a texel boundary for the prediction to be trusted"""
    if (case, rule, stride_assumed) in _rm:
        return _rm[(case, rule, stride_assumed)]
    o, a, c = rule
    if c is None:
        c = 'clamp' if case_rule_of(case) == 'clamp' else 'wrap'
    w, h, _ = tex_of(case)
    st, tt = st_of(case)
    s, t = interp(st, o), interp(tt, o)
    out = {}
    for p in s:
        fs, ft = s[p] * w + a, t[p] * h + a
        safe = min(fs - math.floor(fs), math.floor(fs) + 1 - fs) > DELTA and \
               min(ft - math.floor(ft), math.floor(ft) + 1 - ft) > DELTA
        out[p] = (sampled(case, _index(fs, w, c), _index(ft, h, c), stride_assumed), safe)
    _rm[(case, rule, stride_assumed)] = out
    return out


def case_rule_of(case):
    """the clamp mode the case's PP_TXFILTER asks for"""
    return TCASES[case][1]


# ---- the ring words -------------------------------------------------------------------------

def draw_words(case, seed, win=0):
    """R6c F's state with the texture unit on, the six texture registers, the whole-buffer clip, one
    3D_DRAW_IMMD_2 of three seven-word vertices (x, y, z, w, colour, s, t), the tail"""
    w, h, stride = tex_of(case)
    fw = zo.draw_words('F', seed)
    state, pix, tail = fw[:26], fw[26:34], fw[-10:]
    assert state[2] == zo.p0(zo.V('RADEON_PP_CNTL')) and state[18] == zo.p0(zo.V('R200_SE_VTX_FMT_0'))
    assert state[20] == zo.p0(zo.V('R200_SE_VTX_FMT_1'))
    state = state[:3] + [PP_CNTL_TEX] + state[4:21] + [VTX_FMT_1_ST] + state[22:]
    c0, c2, a0, a2 = blend_texture()
    pix = [zo.p0(zo.M('R200_PP_TXCBLEND_0')), c0, zo.p0(zo.M('R200_PP_TXCBLEND2_0')), c2,
           zo.p0(zo.M('R200_PP_TXABLEND_0')), a0, zo.p0(zo.M('R200_PP_TXABLEND2_0')), a2]
    tex = [zo.p0(zo.M('R200_PP_TXFILTER_0')), txfilter(case_rule_of(case)),
           zo.p0(zo.M('R200_PP_TXFORMAT_0')), txformat(w, h),
           zo.p0(zo.M('R200_PP_TXFORMAT_X_0')), 0,
           zo.p0(zo.M('R200_PP_TXSIZE_0')), txsize(w, h),
           zo.p0(zo.M('R200_PP_TXPITCH_0')), txpitch(stride) & M32,
           zo.p0(zo.M('R200_PP_TXOFFSET_0')), (win + TEX_OFF) & M32]
    x1, y1, x2, y2 = to.CLIP
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]
    st, tt = st_of(case)
    body = [vf()]
    for (vx, vy), s, t in zip(GEOM, st, tt):
        body += [to.fbits(vx), to.fbits(vy), to.fbits(0.5), to.fbits(1.0), to.word(C1),
                 to.fbits(float(s)), to.fbits(float(t))]
    hdr = zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)
    return state + pix + tex + clip + [hdr] + body + tail


def vf():
    return (zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') |
            zo.M('R200_VF_COLOR_ORDER_RGBA') | (3 << 16))


def header():
    return zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), 3 * 7)


def words_needed(case):
    return len(draw_words(case, 1))


# ---- the simulator's model (tools/r5/sim/world5.c r6Tri, textured) --------------------------

def _fd(a, b):
    """floor division, as world5.c's r6FloorDiv does it"""
    return -((-a) // b) if False else math.floor(Fr(a, b))


def sim_map(case):
    """{(x, y): pixel word} the fake 3D writes: ST interpolated in 1/65536 with the slopes floored to
    that unit, nearest, the case's clamp, POT addressing (row stride = width * 4)"""
    w, h, _ = tex_of(case)
    st, tt = st_of(case)
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in GEOM]
    X = [int(p[0] * 16) for p in P]
    Y = [int(p[1] * 16) for p in P]
    S = [int(Fr(v) * 65536) for v in st]
    T = [int(Fr(v) * 65536) for v in tt]
    A = (X[1] - X[0]) * (Y[2] - Y[0]) - (X[2] - X[0]) * (Y[1] - Y[0])
    sgn = -1 if A < 0 else 1
    A *= sgn
    qsx = _fd(sgn * ((S[1] - S[0]) * (Y[2] - Y[0]) - (S[2] - S[0]) * (Y[1] - Y[0])) * 16, A)
    qsy = _fd(sgn * ((S[2] - S[0]) * (X[1] - X[0]) - (S[1] - S[0]) * (X[2] - X[0])) * 16, A)
    qtx = _fd(sgn * ((T[1] - T[0]) * (Y[2] - Y[0]) - (T[2] - T[0]) * (Y[1] - Y[0])) * 16, A)
    qty = _fd(sgn * ((T[2] - T[0]) * (X[1] - X[0]) - (T[1] - T[0]) * (X[2] - X[0])) * 16, A)
    mode = case_rule_of(case)
    words = texture_words(case)
    out = {}
    for x, y in go.covered(GEOM):
        sx, sy = x * 16 + 8, y * 16 + 8
        sv = S[0] + _fd(qsx * (sx - X[0]) + qsy * (sy - Y[0]), 16)
        tv = T[0] + _fd(qtx * (sx - X[0]) + qty * (sy - Y[0]), 16)
        u = _index(Fr(sv * w, 65536), w, 'clamp' if mode == 'clamp' else 'wrap')
        v = _index(Fr(tv * h, 65536), h, 'clamp' if mode == 'clamp' else 'wrap')
        out[(x, y)] = words[(v * max(w * 4, 32)) // 4 + u]  # the measured row stride (R6h 8)
    return out


def sim_block(case):
    """the 256 KiB block the model leaves: the texture, the depth of a z-0.5 ALWAYS draw, the texels"""
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    tex = texture_words(case)
    words[TEX_OFF // 4:TEX_OFF // 4 + len(tex)] = tex
    zv = do.space(24)[do.SIM_CONV](0.5)
    for (x, y), px in sim_map(case).items():
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = px
        k = (zo.DEPTH_OFF + do.mba_z32(x, y)) // 4
        words[k] = (words[k] & 0xff000000) | zv
    return words


def sim_coverage_words(case):
    """the map: every covered pixel matches neither map colour (both 0), so code 3"""
    w = [0] * 64
    for (x, y) in sim_map(case):
        i = y * 32 + x
        w[i >> 4] |= 3 << (2 * (i & 15))
    return w


# ---- the C rows ------------------------------------------------------------------------------

def tex_values(case):
    """the 13 values of a cpR6T row: w, h, stride, filter, format, txsize, txpitch, s0..t2"""
    w, h, stride = tex_of(case)
    st, tt = st_of(case)
    return ([w, h, stride, txfilter(case_rule_of(case)), txformat(w, h), txsize(w, h), txpitch(stride) & M32] +
            [to.fbits(float(v)) for pair in zip(st, tt) for v in pair])


def case_values(case):
    """the 30 values of a case row (osrdn_cp.m cpR6Case) -- R6h uses gidx for its texture row"""
    return [0, 0, 64, 64, 0, 0, 0, 0, to.fbits(0.5), 2,
            PP_CNTL_TEX, 0xffffffff, 0x803, 0x10000, header(), vf(), 0, do.TRI_FIRST, 0, 0,
            # the map's two colours are 0: a textured pixel matches neither, so the map only says
            # "drawn or not" (the planes carry the texel), docs/R6H_PLAN.md 2-3
            do.SE_CNTL_FLAT, 0xf, 0, 0,
            do.ZCNTL[24], 0, 0, 0,
            do.RB3D_Z_ON, 0, ORDER.index(case) + 1]


def c_tables():
    L = ['/* R6h (docs/R6H_PLAN.md 2): the texture of each case -- w, h, row stride, PP_TXFILTER,',
         '   PP_TXFORMAT, PP_TXSIZE, PP_TXPITCH, then s0, t0, s1, t1, s2, t2 (float32) */',
         'static const unsigned long cpR6T[%d][13] = {' % len(ORDER)]
    L.append(',\n'.join('    { ' + ', '.join('0x%xUL' % x if x > 255 else '%dUL' % x for x in tex_values(n)) +
                        ' }   /* %s */' % n for n in ORDER))
    L.append('};')
    L.append('/* R6h case rows */')
    for n in ORDER:
        v = case_values(n)
        L.append('    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x%08xUL, 2UL,     /* %s */\n' % (v[8], n) +
                 '      ' + ', '.join('0x%xUL' % x if x > 255 else '%dUL' % x for x in v[10:]) + ' },')
    return '\n'.join(L)


# ---- self-test ---------------------------------------------------------------------------------

def self_test():
    bad = 0

    def expect(what, got, want):
        nonlocal bad
        ok = got == want
        bad += not ok
        print('  %s  %s%s' % ('ok  ' if ok else 'FAIL', what, '' if ok else ': got %s, want %s' % (got, want)))

    pat = set(zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4))
    tx = [texel(u, v) for v in range(8) for u in range(8)]
    expect('texels are distinct and never a pattern word', (len(set(tx)), any(t in pat for t in tx)), (64, False))
    expect('the texture area is clear of both buffers and 32-byte aligned',
           (zo.DEPTH_OFF + zo.BUF_BYTES <= TEX_OFF, TEX_OFF + TEX_BYTES <= zo.COLOR_OFF, TEX_OFF % 32), (True, True, 0))
    expect('cases 102 .. 108', (FIRST, LAST, len(ORDER)), (102, 108, 7))
    # the state values the plan names
    expect('PP_CNTL has both texture bits', PP_CNTL_TEX, 0x1010)
    expect('TXFORMAT 8x8 ARGB8888 with alpha in the map', txformat(8, 8), 0x46 | (3 << 8) | (3 << 12))
    expect('TXFILTER nearest, clamp / wrap', (txfilter('clamp'), txfilter('wrap')), (2 << 23 | 2 << 27, 0))
    expect('TXSIZE and TXPITCH for 8x8, stride 32', (txsize(8, 8), txpitch(32)), (0x00070007, 0))
    expect('a vertex is seven words, the header counts 21', (len(draw_words('XA', 1)), (header() >> 16) & 0x3fff),
           (26 + 8 + 12 + 4 + 1 + 1 + 21 + 10, 21))
    expect('the longest submission fits CP_R6_WORDS', max(words_needed(n) for n in ORDER) <= do.WORDS_MAX, True)
    dw = draw_words('XA', 7, win=0x0029e000)
    expect('the texture registers carry the case values (state 26 + blend 8, then six pairs)',
           (dw[35], dw[37], dw[39], dw[41], dw[43], dw[45]),
           (txfilter('clamp'), txformat(8, 8), 0, txsize(8, 8), txpitch(32) & M32, 0x0029e000 + TEX_OFF))
    # the measured rule is told apart from every other named rule; some OTHER pairs coincide on the
    # safe pixels of these seven cases (a stated limit of this rung, not a pass under a wrong name)
    worst = min(sum(1 for n in ORDER for p, (va, sa) in rule_map(n, MEASURED).items()
                    if sa and rule_map(n, b)[p][1] and va != rule_map(n, b)[p][0]) for b in RULES)
    expect('the measured rule differs from every other named rule on safe pixels', worst >= 12, True)
    safe = dict((n, sum(1 for p, (_, s) in rule_map(n, MEASURED).items() if s)) for n in ORDER)
    expect('safe pixels per case under the measured rule', safe,
           {'XA': 112, 'XB': 276, 'XC': 112, 'XD': 66, 'XE': 112, 'XF': 174, 'XG': 176})
    # XE tells the two stride readings apart
    a = rule_map('XE', MEASURED)                           # the sampler uses the width (POT)
    b = rule_map('XE', MEASURED, stride_assumed=64)        # the sampler uses PP_TXPITCH
    expect('XE separates "POT ignores the pitch" from "it reads it" (84 safe pixels, 210 in all)',
           (sum(1 for p in a if a[p][1] and a[p][0] != b[p][0]), sum(1 for p in a if a[p][0] != b[p][0])), (84, 210))
    expect('the measured row stride is the width, floored at 32 bytes', (row_stride(8), row_stride(4)), (32, 32))
    print('tex_oracle: %s' % ('PASS' if bad == 0 else 'FAIL %d' % bad))
    return bad == 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(0 if self_test() else 1)
    if sys.argv[1:] == ['--c-tables']:
        print(c_tables())
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
