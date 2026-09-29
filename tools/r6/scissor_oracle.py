#!/usr/bin/env python3
"""R6k oracle (docs/R6K_PLAN.md 2-4): the auxiliary scissor -- three rectangles nothing in the
reference ever enables, and the main scissor's remaining corner cases.

  scissor_oracle.py --self-test
  scissor_oracle.py --c-tables

Cases 146-160 draw one flat box over the 32 x 32 map (AS7: a bigger box, to see whether the aux
scissor can widen what the main one allows) and read the coverage map back.  The rule space names
how a rectangle is read (docs/R6K_PLAN.md 3): coordinate layout, BR end, polarity, combination,
bias, the width of each half, signedness, and whether RE_CNTL bit 1 gates the unit -- 513 rules,
191 classes over these cases, computed in build/r6k/design2.py and checked again here.
"""

import importlib.util
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pe = _load('persp_oracle')
do, go, to, zo = pe.do, pe.go, pe.to, pe.zo
M32 = 0xffffffff
MAPW = 32
SIM_BITS = 24                                   # every R6k case runs the 24-bit depth format

FIRST = pe.LAST + 1                             # 146
COLOUR = to.C1                                  # the flat colour every scissor case draws
PIXEL = to.pixel(COLOUR)
TRI_S = 59                                      # the cpR6Tris row that covers the map exactly
TRI_B = 60                                      # the bigger box, wider than the main scissor (AS7)
G24 = 15                                        # the cpR6G row that prefills a 24-bit depth ramp
Z_AS8 = 0x3f000001                               # 0.5 + 2^-24: floor(z * 2^24) = 0x800001, which the
                                                # ramp (multiples of 0x20000) never takes

# ---- the rectangles, as the words we write (x | y << 16 -- F12) ----------------------------------

RECTS = {
    'R0': ((6, 3), (20, 13)),
    'R1': ((10, 8), (26, 24)),
    'R2': ((2, 18), (14, 29)),
    'inv': ((20, 13), (6, 3)),                  # AS6: top-left past bottom-right
    'all': ((0, 0), (63, 63)),                  # AS7: the whole buffer
    'bias': ((6 + 1440, 3 + 1440), (20 + 1440, 13 + 1440)),     # AS9: R300's 1440 offset
    'hx': ((6 + 2048, 3), (20 + 2048, 13)),     # AS10: a high bit on the x half only
    'hy': ((6, 3 + 2048), (20, 13 + 2048)),     # AS13: on the y half only
    'neg': ((2048 - 16, 2048 - 16), (20, 13)),  # AS14: a top-left that is negative if signed
}

# name: (enabled slots [(slot, rect, exclusive)], RE_CNTL, clip box, cpR6Tris row, what to read)
SCASES = {
    'AS0': ([], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS1': ([(0, 'R0', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS2': ([(0, 'R0', 1)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS3': ([(0, 'R0', 0), (1, 'R1', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS4': ([(0, 'R0', 0), (1, 'R1', 1)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS5': ([(2, 'R2', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS6': ([(0, 'inv', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS7': ([(0, 'all', 0)], 2, (0, 0, 32, 32), TRI_B, 'colour'),
    'AS8': ([(0, 'R0', 0)], 2, (0, 0, 64, 64), TRI_S, 'depth'),
    'AS9': ([(0, 'bias', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS10': ([(0, 'hx', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS11': ([], 2, (20, 13, 7, 4), TRI_S, 'colour'),            # the main scissor inverted
    'AS12': ([(0, 'R0', 0)], 0, (0, 0, 64, 64), TRI_S, 'colour'),  # RE_CNTL bit 1 clear
    'AS13': ([(0, 'hy', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
    'AS14': ([(0, 'neg', 0)], 2, (0, 0, 64, 64), TRI_S, 'colour'),
}
ORDER = ['AS%d' % k for k in range(15)]
CASE_NUM = dict((n, FIRST + k) for k, n in enumerate(ORDER))
LAST = FIRST + len(ORDER) - 1                   # 160
GATED = ['AS1', 'AS2', 'AS3', 'AS4', 'AS5', 'AS6', 'AS9', 'AS10', 'AS12', 'AS13', 'AS14']
DEPTH_CASE = 'AS8'

# ---- the geometry ---------------------------------------------------------------------------------

BOX = {TRI_S: 32.0, TRI_B: 40.0}                # the two boxes, each two triangles


def box_tris(row):
    """the box as two triangles, in the packet's vertex order"""
    s = BOX[row]
    return [[(0.0, 0.0), (s, 0.0), (0.0, s)], [(s, 0.0), (s, s), (0.0, s)]]


def tri_row(case):
    return SCASES[case][3]


def recntl_of(case):
    return SCASES[case][1]


def clip_of(case):
    return SCASES[case][2]


def read_of(case):
    return SCASES[case][4]


def slots_of(case):
    return SCASES[case][0]


_cov = {}


def covered_geom(case):
    """the pixels of the 32 x 32 map the two triangles cover, by the measured coverage rule"""
    row = tri_row(case)
    if row not in _cov:
        out = set()
        for pts in box_tris(row):
            for p in go.covered(pts):
                assert p not in out, ('the two triangles overlap at', p)
                out.add(p)
        _cov[row] = out
    return _cov[row]


def clip_keep(case, p):
    """rule H (docs/R6B_PLAN.md 92): WIDTH_HEIGHT always, TOP_LEFT only with RE_CNTL bit 1"""
    x1, y1, x2, y2 = clip_of(case)
    lo = (x1, y1) if recntl_of(case) & 2 else (0, 0)
    return lo[0] <= p[0] <= x2 - 1 and lo[1] <= p[1] <= y2 - 1


# ---- the named rule space ---------------------------------------------------------------------

AXES = (('x_low', 'y_low'), ('br_incl', 'br_excl'), ('keep', 'drop'), ('and', 'or'),
        ('b0', 'b1440'), (11, 16), (11, 16), ('unsigned', 'signed'), ('free', 'gated'))
RULES = [('none',)] + [tuple(a) for a in itertools.product(*AXES)]


def _coord(v, w, sign):
    v &= (1 << w) - 1
    if sign == 'signed' and (v >> (w - 1)):
        v -= 1 << w
    return v


_bnd = {}


def bounds(rect, rule):
    """(x0, x1, y0, y1) the rectangle covers under this rule, ends inclusive (x1 < x0: empty)"""
    key = (rect, rule)
    if key in _bnd:
        return _bnd[key]
    layout, br, _, _, bias, wx, wy, sign, _ = rule
    (ax, ay), (bx, by) = RECTS[rect]
    if layout == 'y_low':                       # the halves read the other way round
        ax, ay, bx, by = ay, ax, by, bx
    b = 1440 if bias == 'b1440' else 0
    ax, bx = _coord(ax, wx, sign) - b, _coord(bx, wx, sign) - b
    ay, by = _coord(ay, wy, sign) - b, _coord(by, wy, sign) - b
    hi = 0 if br == 'br_incl' else -1
    _bnd[key] = (ax, bx + hi, ay, by + hi)
    return _bnd[key]


def _inside(p, rect, rule):
    x0, x1, y0, y1 = bounds(rect, rule)
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def aux_keep(case, p, rule):
    """does the auxiliary unit let this pixel through, under this named rule"""
    if rule == ('none',):
        return True
    pol, comb, gate = rule[2], rule[3], rule[8]
    if gate == 'gated' and not (recntl_of(case) & 2):
        return True
    keeps = []
    for _, rect, exc in slots_of(case):
        ins = _inside(p, rect, rule)
        keeps.append(ins if (pol == 'keep') != bool(exc) else not ins)
    if not keeps:
        return True
    return all(keeps) if comb == 'and' else any(keeps)


_pic = {}


def picture(case, rule):
    """{(x, y)} the pixels this case writes inside the map, under a named aux rule"""
    key = (case, rule)
    if key not in _pic:
        _pic[key] = frozenset(p for p in covered_geom(case)
                              if p[0] < MAPW and p[1] < MAPW and clip_keep(case, p) and aux_keep(case, p, rule))
    return _pic[key]


def coverage_words(case, rule):
    """the 64 words the driver logs for this case: code 1 where written, 0 elsewhere"""
    return cov_words_of(picture(case, rule))


def pixel_array(case, rule):
    """64 x 64 int64 of the colour buffer: the flat pixel where written, -1 elsewhere"""
    a = np.full((64, 64), -1, np.int64)
    for x, y in picture(case, rule):
        a[y, x] = PIXEL
    return a


def hw_depth_value(case):
    """floor(z * 2^24), the measured rule (docs/R6F_PLAN.md 11), saturated at 24 bits"""
    return 0x800001 if read_of(case) == 'depth' else 0xffffff


def depth_map(case, px):
    """{(x, y): value} the depth buffer should hold: the prefill where the case asks for one, the
    drawn value on the written pixels"""
    vals = {}
    if read_of(case) == 'depth':
        vals = dict(((x, y), depth_ramp(x, y)) for y in range(MAPW) for x in range(MAPW))
    for q in px:
        if q[0] < MAPW and q[1] < MAPW:
            vals[q] = hw_depth_value(case)
    return vals


def block_of(case, px, dvals=None):
    """the 256 KiB block the hardware should leave when it writes exactly px: the depth prefill
    where the case asks for one, then that picture's colour and depth"""
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    vals = depth_map(case, px) if dvals is None else dvals
    if vals:
        d = do.block_from_values(vals, SIM_BITS)
        words[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(d)] = d
    for x, y in px:
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = PIXEL
    return words


def planes_of(case, px, dvals=None):
    """the depth planes the driver logs for that picture"""
    blk = block_of(case, px, dvals)
    return do.plane_words(blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + zo.BUF_BYTES // 4], SIM_BITS)


def cov_words_of(px):
    """the 64 coverage words: code 1 (the flat colour) where written.  A pixel outside the map is
    not in the map at all -- that is exactly what the digest is there to catch (AS7)"""
    out = [0] * (1024 // 16)
    for x, y in px:
        if x >= MAPW or y >= MAPW:
            continue
        i = y * MAPW + x
        out[i >> 4] |= 1 << (2 * (i & 15))
    return out


def hw_block(case, rule):
    return block_of(case, picture(case, rule))


def digests(case, rule):
    """(colour, depth) digests the driver should report, from the same picture"""
    blk = hw_block(case, rule)
    return (zo.digest(blk, zo.COLOR_OFF // 4, zo.BUF_BYTES // 4),
            zo.digest(blk, zo.DEPTH_OFF // 4, zo.BUF_BYTES // 4))


def hw_planes(case, rule):
    """the depth planes the driver logs for the depth case"""
    return planes_of(case, picture(case, rule))


def classes(cases=None):
    """{signature: [rules]} over the gated cases -- how well the boot can name the unit"""
    cases = cases or GATED
    out = {}
    for r in RULES:
        out.setdefault(tuple(picture(c, r) for c in cases), []).append(r)
    return out


# ---- the depth case ---------------------------------------------------------------------------

def depth_ramp(x, y):
    """the CPU prefill of the G24 row: A + B*x + C*y, clamped to 24 bits"""
    return min(0xffffff, 0x3c0000 + 0x40000 * x + 0x20000 * y)


def depth_values(case, rule):
    """{(x, y): 24-bit value} after the draw: the drawn z where written, the ramp elsewhere"""
    px = picture(case, rule)
    return dict(((x, y), 0x800001 if (x, y) in px else depth_ramp(x, y))
                for y in range(MAPW) for x in range(MAPW))


# ---- the ring words ------------------------------------------------------------------------------

def aux_cntl(case):
    c = 0
    for slot, _, exc in slots_of(case):
        c |= zo.M('R200_SCISSOR_ENABLE_%d' % slot)
        if exc:
            c |= zo.M('R200_EXCLUSIVE_SCISSOR_%d' % slot)
    return c


def rect_words(case, slot):
    """(TL, BR) for one slot: the pair we write, or (0, 0) when the slot is off"""
    for s, rect, _ in slots_of(case):
        if s == slot:
            (ax, ay), (bx, by) = RECTS[rect]
            return (ax | (ay << 16)) & M32, (bx | (by << 16)) & M32
    return 0, 0


def s_values(case):
    """the seven values of this case's cpR6S row: the control word, then TL/BR for the three slots"""
    out = [aux_cntl(case)]
    for slot in range(3):
        out += list(rect_words(case, slot))
    return out


def sidx_of(case):
    """0 when the case writes no auxiliary state, else 1 + its cpR6S row"""
    return 0 if not slots_of(case) else S_ORDER.index(case) + 1


S_ORDER = [n for n in ORDER if SCASES[n][0]]    # the cases that get a cpR6S row


def aux_words(case):
    """the seven register writes, in the order the driver emits them (before RE_TOP_LEFT)"""
    v = s_values(case)
    w = [zo.p0(zo.V('R200_RE_AUX_SCISSOR_CNTL')), v[0]]
    for k, slot in enumerate(range(3)):
        w += [zo.p0(zo.V('RADEON_SCISSOR_TL_%d' % slot)), v[1 + 2 * k],
              zo.p0(zo.V('RADEON_SCISSOR_BR_%d' % slot)), v[2 + 2 * k]]
    return w


def nverts(case):
    return 6


def vf(case):
    return (zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') |
            zo.M('R200_VF_COLOR_ORDER_RGBA') | (nverts(case) << 16))


def header(case):
    return zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), 5 * nverts(case))


def zbits(case):
    return Z_AS8 if read_of(case) == 'depth' else to.fbits(to.Z)


def draw_words(case, seed):
    """the case's submission: R6c F's state with this case's RE_CNTL, the seven auxiliary words,
    the clip, then one 3D_DRAW_IMMD_2 with the box's two triangles"""
    fw = zo.draw_words('F', seed)
    state, pix, tail = list(fw[:26]), fw[26:34], fw[-10:]
    head = []
    if read_of(case) == 'depth':                # the prefill row makes the driver purge first (R6g)
        head = [zo.p0(zo.V('RADEON_RB3D_DSTCACHE_CTLSTAT')), zo.PURGE_DC,
                zo.p0(zo.V('RADEON_RB3D_ZCACHE_CTLSTAT')), zo.PURGE_ZC]
    assert state[4] == zo.p0(zo.V('R200_RE_CNTL'))
    state[5] = recntl_of(case)
    x1, y1, x2, y2 = clip_of(case)
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]
    body = [vf(case)]
    for pts in box_tris(tri_row(case)):
        for (x, y) in pts:
            body += [to.fbits(x), to.fbits(y), zbits(case), to.fbits(1.0), to.word(COLOUR)]
    hdr = zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)
    assert hdr == header(case)
    aux = aux_words(case) if sidx_of(case) else []
    return head + state + list(pix) + aux + clip + [hdr] + body + list(tail)


def words_needed(case):
    return len(draw_words(case, 1))


# ---- the C rows -------------------------------------------------------------------------------

def tri_values(row):
    """a cpR6Tris row: nv, then x, y, colour per vertex"""
    out = []
    for pts in box_tris(row):
        for (x, y) in pts:
            out.append([to.fbits(x), to.fbits(y), to.word(COLOUR)])
    return nverts('AS0'), out


def case_values(case):
    """the 34 values of a case row (the 33 of osrdn_cp.m cpR6Case, then sidx)"""
    x1, y1, x2, y2 = clip_of(case)
    depth = read_of(case) == 'depth'
    return [x1, y1, x2, y2, 0, 0, 0, 0, zbits(case), recntl_of(case),
            0x1000, 0xffffffff, 0x803, 0x10000, header(case), vf(case), 0, tri_row(case),
            PIXEL, PIXEL, do.SE_CNTL_FLAT, 7 if depth else 0, 0, 0, do.ZCNTL[24],
            0, 0, 1 if depth else 0, do.RB3D_Z_ON, G24 if depth else 0, 0, 0, 0, sidx_of(case)]


def _hex(x):
    return '0x%xUL' % x if x > 255 else '%dUL' % x


def c_tables():
    L = ['/* R6k (docs/R6K_PLAN.md 4): the auxiliary scissor state a case writes --',
         '   R200_RE_AUX_SCISSOR_CNTL, then TL/BR for the three slots */',
         'static const unsigned long cpR6S[%d][7] = {' % len(S_ORDER)]
    L.append(',\n'.join('    { ' + ', '.join(_hex(x) for x in s_values(n)) + ' }   /* %s */' % n
                        for n in S_ORDER))
    L.append('};')
    L.append('/* R6k: the two boxes (cpR6Tris rows %d and %d) */' % (TRI_S, TRI_B))
    for row, name in ((TRI_S, 'S1: the 32 x 32 map'), (TRI_B, 'S2: 40 x 40, wider than the clip')):
        nv, vs = tri_values(row)
        L.append('    { %dUL, { ' % nv + ', '.join('{ ' + ', '.join(_hex(x) for x in v) + ' }' for v in vs) +
                 ' } }   /* %s */,' % name)
    L.append('/* R6k case rows */')
    for n in ORDER:
        v = case_values(n)
        L.append('    { %d, %d, %d, %d, 0UL, 0UL, 0UL, 0UL, %s, %s,     /* %s */\n' %
                 (v[0], v[1], v[2], v[3], _hex(v[8]), _hex(v[9]), n) +
                 '      ' + ', '.join(_hex(x) for x in v[10:]) + ' },')
    return '\n'.join(L)


# ---- the simulator's model ---------------------------------------------------------------------

def sim_depth_value(case):
    """the model's depth conversion (depth_oracle SIM_CONV) of this case's constant z"""
    return do.space(SIM_BITS)[do.SIM_CONV](to.f32(_float_of(zbits(case))))


def _float_of(bits):
    import struct
    return struct.unpack('<f', struct.pack('<I', bits))[0]


_simb = {}


def sim_block(case):
    """the 256 KiB block world5.c leaves: the depth prefill where the case asks for one, then the
    model's draw (which knows the main scissor and nothing of the auxiliary one)"""
    if case in _simb:
        return _simb[case]
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    vals = {}
    if read_of(case) == 'depth':                # the CPU prefill the driver writes before the draw
        vals = dict(((x, y), depth_ramp(x, y)) for y in range(MAPW) for x in range(MAPW))
    for p in sim_map(case):
        vals[p] = sim_depth_value(case)
    d = do.block_from_values(vals, SIM_BITS)
    words[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(d)] = d
    for x, y in sim_map(case):
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = PIXEL
    _simb[case] = words
    return words


def sim_coverage_words(case):
    """the 64 coverage words the model's picture gives"""
    out = [0] * (1024 // 16)
    for x, y in sim_map(case):
        i = y * MAPW + x
        out[i >> 4] |= 1 << (2 * (i & 15))
    return out


def sim_map(case):
    """{(x, y): pixel} world5.c's fake 3D: it knows the main scissor (rule H) and the geometry, and
    -- like the hardware under the plain reading -- nothing about the auxiliary unit, which the
    stream comparison covers instead"""
    return dict((p, PIXEL) for p in covered_geom(case)
                if p[0] < MAPW and p[1] < MAPW and clip_keep(case, p))


def self_test():
    fails = 0

    def ok(cond, what):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', what))

    ok(CASE_NUM['AS0'] == 146 and LAST == 160, 'the cases are 146 .. 160 (%d .. %d)' % (FIRST, LAST))
    ok(len(covered_geom('AS0')) == 1024, 'the two triangles cover the map exactly (%d pixels)'
       % len(covered_geom('AS0')))
    big = covered_geom('AS7')                    # covered() only looks at the 32 x 32 map
    ok(len(big) == 1024, 'the bigger box covers the whole map too (%d pixels)' % len(big))
    ok(len(RULES) == 513, 'the rule space is 513 rules (%d)' % len(RULES))
    cl = classes()
    ok(len(cl) == 191, 'the gated cases give 191 classes (%d)' % len(cl))
    alone = [v for v in cl.values() if v == [('none',)]]
    ok(bool(alone), "'a unit that does nothing' is named on its own")
    base = ('x_low', 'br_incl', 'keep', 'and', 'b0', 16, 16, 'unsigned', 'free')
    mine = [v for v in cl.values() if base in v]
    ok(len(mine) == 1 and len(mine[0]) == 2 and
       set(mine[0]) == {base, base[:7] + ('signed',) + base[8:]},
       'the plain reading is named up to the signedness of a 16-bit half (%s)' % (mine and mine[0],))
    # the three behaviours the cross-review named (docs/R6K_PLAN.md 8: Y10, Y12)
    for w, what in (((16, 11), 'a y half narrower than the x half'), ((11, 16), 'the other way round')):
        r = base[:5] + w + base[7:]
        ok(all(picture(c, r) == picture(c, base) for c in GATED) is False, '%s is separated' % what)
    s11 = ('x_low', 'br_incl', 'keep', 'and', 'b0', 11, 11, 'signed', 'free')
    u11 = ('x_low', 'br_incl', 'keep', 'and', 'b0', 11, 11, 'unsigned', 'free')
    ok(any(picture(c, s11) != picture(c, u11) for c in GATED),
       'a signed 11-bit half is separated from an unsigned one (AS14)')
    # every case's picture under the plain reading, and the ones that must differ
    p = dict((c, picture(c, base)) for c in ORDER)
    ok(len(p['AS0']) == 1024 and len(p['AS7']) == 1024, 'AS0 and AS7 fill the map')
    ok(len(p['AS1']) == 15 * 11, 'AS1 keeps R0 only (%d pixels)' % len(p['AS1']))
    ok(len(p['AS2']) == 1024 - 15 * 11, 'AS2 drops R0 (%d pixels)' % len(p['AS2']))
    ok(p['AS6'] == frozenset(), 'AS6 (an inverted rectangle) keeps nothing')
    ok(p['AS9'] == frozenset() and p['AS10'] == frozenset() and p['AS13'] == frozenset(),
       'the bias and high-bit rectangles fall outside the map')
    ok(p['AS12'] == p['AS1'], 'AS12 differs from AS1 only if the unit is gated')
    ok(p['AS14'] == frozenset(), 'AS14 is empty under the unsigned reading (%d)' % len(p['AS14']))
    ok(len(picture('AS14', s11)) == 21 * 14,
       'AS14 under a signed 11-bit half is 21 x 14 (%d)' % len(picture('AS14', s11)))
    ok(p['AS11'] == frozenset(), 'AS11 (the main scissor inverted) writes nothing under rule H')
    # the words
    w = draw_words('AS1', 1)
    hdr = zo.p0(zo.V('R200_RE_AUX_SCISSOR_CNTL'))
    at = [i for i, v in enumerate(w) if v == hdr]
    ok(len(at) == 2 and w[at[0] + 1] == 0 and at[0] < 26,
       'the state block zeroes the control word first (F7), then the case writes it')
    ok(len(draw_words('AS0', 1)) + 14 == len(w), 'a case with no rectangle writes no auxiliary state')
    ok(w[at[1] + 1] == zo.M('R200_SCISSOR_ENABLE_0'),
       'AS1 enables slot 0 only (%08x)' % aux_cntl('AS1'))
    ok(aux_cntl('AS2') == zo.M('R200_SCISSOR_ENABLE_0') | zo.M('R200_EXCLUSIVE_SCISSOR_0'),
       'AS2 adds the exclusive bit')
    ok(aux_cntl('AS5') == zo.M('R200_SCISSOR_ENABLE_2'), 'AS5 uses slot 2')
    ok(rect_words('AS1', 0) == (6 | (3 << 16), 20 | (13 << 16)), 'R0 is written x | y << 16 (F12)')
    ok(all(len(case_values(n)) == 34 for n in ORDER), 'every case row has 34 values')
    ok(case_values('AS8')[27] == 1 and case_values('AS8')[29] == G24,
       'AS8 reads the 24-bit depth and prefills with the G24 ramp')
    ok(sorted(set(depth_values('AS8', base).values())) != [0x800001],
       'the depth case tells drawn from prefilled (%d distinct values)'
       % len(set(depth_values('AS8', base).values())))
    ok(0x800001 not in [depth_ramp(x, y) for x in range(32) for y in range(32)],
       'the drawn depth never collides with the ramp')
    cw = coverage_words('AS1', base)
    ok(sum(bin(w).count('1') for w in cw) == len(p['AS1']), 'the coverage words hold AS1\'s pixels')
    dc, dd = digests('AS1', base)
    ok(dc['changed'] == len(p['AS1']) and dd['changed'] == len(p['AS1']),
       'the digests count the same pixels (%d, %d)' % (dc['changed'], dd['changed']))
    print('scissor_oracle self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


if __name__ == '__main__':
    if '--c-tables' in sys.argv:
        print(c_tables())
    else:
        sys.exit(1 if self_test() else 0)
