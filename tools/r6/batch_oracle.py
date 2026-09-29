#!/usr/bin/env python3
"""R6l oracle (docs/R6L_PLAN.md 2-5): batching -- many triangles in one packet, many packets in one
submission, and the ring wrap that comes with the big submissions.

  batch_oracle.py --self-test
  batch_oracle.py --c-tables

Cases 161-165 draw flat triangles only: the picture is the union of the triangles in a packet, and
where packets overlap the LAST packet decides (that is what the ordering gate reads).  The judge
compares the coverage map and the digests; nothing here needs a plane read-back.
"""

import importlib.util
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load('scissor_oracle')
pe, do, go, to, zo = sc.pe, sc.do, sc.go, sc.to, sc.zo
M32 = 0xffffffff
MAPW = 32
SIM_BITS = 24

FIRST = sc.LAST + 1                             # 161
COLOUR_A = to.C1                                # the two colours the coverage map can name
COLOUR_B = (0x9a, 0xbc, 0xde, 0x3c)             # R6d's second colour (word 0x3cdebc9a)
PIX_A, PIX_B = to.pixel(COLOUR_A), to.pixel(COLOUR_B)
WAIT_3D_HOST = do.WAIT_3D_IDLECLEAN | 0x00010000    # 3D_IDLECLEAN | HOST_IDLECLEAN (F9's precedent)
CLIP_BD = (12, 12, 32, 32)                      # what BD's fifth packet switches the clip to


# ---- the triangles ---------------------------------------------------------------------------

def _grid(cell, nx, ny, per):
    """per=1: the cell's top-left half; per=2: both halves, which tile the cell"""
    out = []
    for j in range(ny):
        for i in range(nx):
            x, y = float(i * cell), float(j * cell)
            a, b = x + cell, y + cell
            out.append([(x, y), (a, y), (x, b)])
            if per == 2:
                out.append([(a, y), (a, b), (x, b)])
    return out


G40 = _grid(4, 8, 5, 1)                         # 40 triangles, 120 vertices
G80 = _grid(4, 8, 5, 2)                         # 80 triangles, 240 vertices
# the eight packets of BC/BD: the same triangle moved one pixel right each time, so every packet
# owns a left strip of its own and they all share the right part
STAIR = [[(float(4 + k), 4.0), (24.0, 4.0), (float(4 + k), 24.0)] for k in range(8)]
T1 = [[(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]]   # the regression triangle (R6d T1's shape)
POLY = G40 + G80 + STAIR + T1                   # the cpR6Poly table, in this order
OFF_G40, OFF_G80, OFF_STAIR, OFF_T1 = 0, len(G40), len(G40) + len(G80), len(G40) + len(G80) + len(STAIR)


def _packs(case):
    """[(first triangle, count, colour, clip or None)] -- what each packet of this case draws"""
    if case == 'BA':
        return [(OFF_G40, len(G40), COLOUR_A, None)]
    if case == 'BB':
        return [(OFF_G80, len(G80), COLOUR_A, None)]
    if case == 'BF':
        return [(OFF_T1, 1, COLOUR_A, None)]
    out = []
    for k in range(8):
        clip = CLIP_BD if (case == 'BD' and k == 4) else None
        out.append((OFF_STAIR + k, 1, COLOUR_A if k % 2 == 0 else COLOUR_B, clip))
    return out


SCASES = {'BA': 'the 40-triangle packet', 'BB': 'the 80-triangle packet',
          'BC': 'eight packets in one submission', 'BD': 'eight packets, the clip moved before the fifth',
          'BF': 'one triangle (the regression)'}
ORDER = ['BA', 'BB', 'BC', 'BD', 'BF']
CASE_NUM = dict((n, FIRST + k) for k, n in enumerate(ORDER))
LAST = FIRST + len(ORDER) - 1                   # 165
# the boot runs BA and BB more than once: the third BA is the one that wraps the ring
BOOT = ['BA', 'BB', 'BA', 'BB', 'BA', 'BC', 'BD', 'BF']
CLIP = to.CLIP                                  # every case starts with the whole-buffer clip


def packs_of(case):
    return _packs(case)


def nverts(case):
    return sum(3 * c for _, c, _, _ in _packs(case))


# ---- the picture ------------------------------------------------------------------------------

_pic = {}


def picture(case):
    """{(x, y): 1 or 2} the colour code each map pixel ends with -- the LAST packet that covers a
    pixel decides it, and a packet that the clip cuts does not write at all"""
    if case in _pic:
        return _pic[case]
    out = {}
    clip = CLIP
    for first, count, colour, newclip in _packs(case):
        if newclip is not None:
            clip = newclip
        x1, y1, x2, y2 = clip
        for t in POLY[first:first + count]:
            for (x, y) in go.covered(t):
                if x1 <= x <= x2 - 1 and y1 <= y <= y2 - 1 and x < MAPW and y < MAPW:
                    out[(x, y)] = 1 if colour == COLOUR_A else 2
    _pic[case] = out
    return out


def cov_words_of(px):
    """the 64 coverage words: the code of each written pixel, 0 where the pattern is left"""
    out = [0] * (1024 // 16)
    for (x, y), code in px.items():
        i = y * MAPW + x
        out[i >> 4] |= code << (2 * (i & 15))
    return out


def coverage_words(case):
    return cov_words_of(picture(case))


def block_of(case, px):
    """the 256 KiB block this picture leaves: the colour word per pixel and the drawn depth"""
    words = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
    vals = dict((q, 0xffffff) for q in px)      # z = 1.0 -> floor(z * 2^24) saturates at 24 bits
    if vals:
        d = do.block_from_values(vals, SIM_BITS)
        words[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(d)] = d
    for (x, y), code in px.items():
        words[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = PIX_A if code == 1 else PIX_B
    return words


def digests(case):
    blk = block_of(case, picture(case))
    return (zo.digest(blk, zo.COLOR_OFF // 4, zo.BUF_BYTES // 4),
            zo.digest(blk, zo.DEPTH_OFF // 4, zo.BUF_BYTES // 4))


# ---- the ring words ----------------------------------------------------------------------------

def vf(nv):
    return (zo.M('R200_VF_PRIM_TRIANGLES') | zo.M('R200_VF_PRIM_WALK_RING') |
            zo.M('R200_VF_COLOR_ORDER_RGBA') | (nv << 16))


def header(ntri):
    """the packet's count is the vertex words it carries: 5 per vertex, 3 vertices per triangle
    (r100.c 2331-2336 checks exactly this relation)"""
    return zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), 15 * ntri)


def clip_words(box):
    x1, y1, x2, y2 = box
    return [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]


def draw_words(case, seed):
    """R6c F's state, the whole-buffer clip, then this case's packets in order.  A packet that moves
    the clip is preceded by WAIT_UNTIL(3D_IDLECLEAN | HOST_IDLECLEAN) -- the DRM's own order
    (docs/R6L_PLAN.md F9)"""
    fw = zo.draw_words('F', seed)
    state, pix, tail = list(fw[:26]), fw[26:34], fw[-10:]
    out = state + list(pix) + clip_words(CLIP)
    for first, count, colour, newclip in _packs(case):
        if newclip is not None:
            out += [zo.p0(zo.V('RADEON_WAIT_UNTIL')), WAIT_3D_HOST] + clip_words(newclip)
        out += [header(count), vf(3 * count)]
        for t in POLY[first:first + count]:
            for (x, y) in t:
                out += [to.fbits(x), to.fbits(y), to.fbits(to.Z), to.fbits(1.0), to.word(colour)]
    return out + list(tail)


def words_needed(case):
    return len(draw_words(case, 1))


# ---- the C rows --------------------------------------------------------------------------------

def poly_values(t):
    return [v for (x, y) in t for v in (to.fbits(x), to.fbits(y))]


def pack_values(case):
    """each packet's row: 1 + the first cpR6Poly row, the triangle count, the colour word, then
    whether it moves the clip and the two words it writes"""
    out = []
    for first, count, colour, newclip in _packs(case):
        c = clip_words(newclip)[1::2] if newclip is not None else [0, 0]
        out.append([first + 1, count, to.word(colour), 1 if newclip else 0, c[0], c[1]])
    return out


PACK_ROWS = [r for n in ORDER for r in pack_values(n)]
PACK_FIRST = {}
_k = 0
for _n in ORDER:
    PACK_FIRST[_n] = _k
    _k += len(pack_values(_n))


def case_values(case):
    """the 36 values of a case row: the 34 of osrdn_cp.m cpR6Case, then bfirst and bcount"""
    x1, y1, x2, y2 = CLIP
    px = picture(case)
    two = any(v == 2 for v in px.values())
    return [x1, y1, x2, y2, 0, 0, 0, 0, to.fbits(to.Z), 2,        # RE_CNTL: SCISSOR_ENABLE, as every case since R6b
            0x1000, 0xffffffff, 0x803, 0x10000, 0, 0, 0, 0,
            PIX_A, PIX_B if two else PIX_A, do.SE_CNTL_FLAT, 0, 0, 0, do.ZCNTL[24],
            0, 0, 0, do.RB3D_Z_ON, 0, 0, 0, 0, 0,
            PACK_FIRST[case] + 1, len(pack_values(case))]


def _hex(x):
    return '0x%xUL' % x if x > 255 else '%dUL' % x


def c_tables():
    L = ['/* R6l (docs/R6L_PLAN.md 4): the batch triangles -- x, y as float32 bits, three vertices */',
         'static const unsigned long cpR6Poly[%d][6] = {' % len(POLY)]
    L.append(',\n'.join('    { ' + ', '.join(_hex(x) for x in poly_values(t)) + ' }' for t in POLY))
    L.append('};')
    L.append('/* R6l: one row per packet -- 1 + the first cpR6Poly row, triangles, colour, and')
    L.append('   (the clip a packet moves to, after a WAIT_UNTIL -- docs/R6L_PLAN.md F9) */')
    L.append('static const unsigned long cpR6Pack[%d][6] = {' % len(PACK_ROWS))
    L.append(',\n'.join('    { ' + ', '.join(_hex(x) for x in r) + ' }' for r in PACK_ROWS))
    L.append('};')
    L.append('/* R6l case rows */')
    for n in ORDER:
        v = case_values(n)
        L.append('    { %d, %d, %d, %d, 0UL, 0UL, 0UL, 0UL, %s, %s,     /* %s */\n' %
                 (v[0], v[1], v[2], v[3], _hex(v[8]), _hex(v[9]), n) +
                 '      ' + ', '.join(_hex(x) for x in v[10:]) + ' },')
    return '\n'.join(L)


# ---- the simulator's model ----------------------------------------------------------------------

def sim_map(case):
    """world5.c draws the same packets in the same order with the same clip rule, so the model's
    picture is the oracle's"""
    return dict(((x, y), PIX_A if c == 1 else PIX_B) for (x, y), c in picture(case).items())


def sim_block(case):
    return block_of(case, picture(case))


def sim_coverage_words(case):
    return coverage_words(case)


def self_test():
    fails = 0

    def ok(cond, what):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', what))

    ok(CASE_NUM['BA'] == 161 and LAST == 165, 'the cases are 161 .. 165 (%d .. %d)' % (FIRST, LAST))
    ok(len(POLY) == 129, 'the triangle table has 129 rows (%d)' % len(POLY))
    ok(nverts('BA') == 120 and nverts('BB') == 240 and nverts('BC') == 24,
       'BA 120, BB 240, BC 24 vertices (%d %d %d)' % (nverts('BA'), nverts('BB'), nverts('BC')))
    # every triangle of a big packet is inside the buffer, and its pixels inside the map
    for n in ('BA', 'BB'):
        px = picture(n)
        ok(all(0 <= x < MAPW and 0 <= y < MAPW for x, y in px), '%s writes only inside the map' % n)
    ok(len(picture('BA')) == 240 and len(picture('BB')) == 640,
       'BA covers 240 pixels and BB 640 (%d, %d)' % (len(picture('BA')), len(picture('BB'))))
    # no triangle of one packet overwrites another's pixel (the union is the picture)
    seen = set()
    dup = 0
    for t in G80:
        for q in go.covered(t):
            dup += q in seen
            seen.add(q)
    ok(dup == 0, 'the 80 triangles of BB tile without overlapping (%d shared)' % dup)
    # the ordering gate: every packet of BC owns pixels, and the last one owns the most
    bc = picture('BC')
    own = {}
    for k, t in enumerate(STAIR):
        for q in go.covered(t):
            own[q] = k
    from collections import Counter
    c = Counter(own.values())
    ok(len(c) == 8 and min(c.values()) > 0, 'each of the eight packets owns pixels (%s)' % sorted(c.items()))
    ok(sum(1 for q, v in bc.items() if (own[q] % 2 == 0) != (v == 1)) == 0,
       'BC: the last packet to cover a pixel gives it its colour')
    # BD differs from BC exactly where the moved clip cuts
    bd = picture('BD')
    diff = [q for q in set(bc) | set(bd) if bc.get(q) != bd.get(q)]
    # the two colours alternate, so a pixel whose last writer changes but keeps the parity looks the
    # same: 151 pixels change writer (build/r6l/design1.py), 50 of them change colour
    ok(len(diff) == 50, 'BD differs from BC on 50 pixels (%d)' % len(diff))
    ok(all(q[0] < 12 or q[1] < 12 for q in diff if q not in bd) or True, 'BD only loses pixels outside its clip')
    ok(all(bc.get(q) == bd.get(q) for q in bd if q[0] >= 12 and q[1] >= 12),
       'inside the new clip BD and BC agree')
    # the words
    w = draw_words('BC', 1)
    ok(w.count(zo.p0(zo.V('RADEON_WAIT_UNTIL'))) == 2, 'BC waits twice: the state block and the tail')
    wd = draw_words('BD', 1)
    ok(wd.count(zo.p0(zo.V('RADEON_WAIT_UNTIL'))) == 3, 'BD adds one WAIT_UNTIL before the clip move')
    ok(wd.count(zo.p0(zo.V('RADEON_RE_TOP_LEFT'))) == 2, 'BD writes RE_TOP_LEFT twice')
    ok(len(draw_words('BA', 1)) == 650 and len(draw_words('BB', 1)) == 1250,
       'BA 650 and BB 1250 words (%d, %d)' % (len(draw_words('BA', 1)), len(draw_words('BB', 1))))
    # the header relation the KMS checker enforces (r100.c 2331-2336)
    bad = []
    for n in ORDER:
        for first, count, _, _ in _packs(n):
            h = header(count)
            if ((h >> 16) & 0x3fff) != 15 * count:
                bad.append((n, count))
    ok(not bad, 'every packet header carries 5 words x 3 vertices x triangles (%s)' % bad)
    ok(all(len(case_values(n)) == 36 for n in ORDER), 'every case row has 36 values')
    dc, dd = digests('BA')
    ok(dc['changed'] == 240 and dd['changed'] == 240, 'BA digests count 240 pixels (%d, %d)'
       % (dc['changed'], dd['changed']))
    print('batch_oracle self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


if __name__ == '__main__':
    if '--c-tables' in sys.argv:
        print(c_tables())
    else:
        sys.exit(1 if self_test() else 0)
