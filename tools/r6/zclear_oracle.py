#!/usr/bin/env python3
"""R6a oracle (docs/R6_PLAN.md 7): the ring words of ZCLEAR and the depth buffer
they must leave, independent of the driver.

  zclear_oracle.py --self-test

The precedent part (WAIT_UNTIL, the 12 state registers, the clip rectangle and
the 3D_DRAW_IMMD_2 packet) is tools/oracle/r200_clear_oracle.py's clear_stream,
imported, never copied: that module ties it to FreeBSD radeon_state.c.  This file
adds only what the plan adds:
  - the prefix: SE_TCL_STATE_FLUSH (FreeBSD radeon_state.c 172-178), the four
    front-end registers xf86 writes before any R200 3D (radeon_commonfuncs.c
    777-792), the two buffers' offsets and pitches, a scratch marker;
  - case C: geometry larger than the clip rectangle;
  - the tail: PURGE_CACHE, PURGE_ZCACHE, WAIT_UNTIL_IDLE (FreeBSD radeon_cp.c
    551-563), RB3D_CNTL = 0 (operator D1), a scratch marker;
  - the block pattern, the depth buffer after each case under two hypotheses
    (Mesa r200_span.c r200_mba_z32 tiling, and linear), and the digests the
    driver logs (so the judge can compare 4096 words through a few numbers).
"""

import importlib.util
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location('r200_clear_oracle',
                                               os.path.join(PROJ, 'tools', 'oracle', 'r200_clear_oracle.py'))
rco = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rco)
V, p0 = rco.V, rco.p0

M32 = 0xffffffff

# the block (card addresses relative to winStart, docs/R6_PLAN.md 7; R4's S0..D stay clear)
ALIAS_BYTES = 0x40000
DEPTH_OFF = 0x00000
COLOR_OFF = 0x3c000
PITCH = 64                      # pixels, both buffers (a multiple of 32: xf86 radeon_accel.c 1183-1189)
WIDTH = HEIGHT = 64
BUF_BYTES = PITCH * HEIGHT * 4

# registers the plan adds (FreeBSD radeon_drv.h, except PP_TXMULTI_CTL_0: Mesa r200_reg.h / xf86 radeon_reg.h)
SE_TCL_STATE_FLUSH = 0x2284
SE_VAP_CNTL_STATUS = 0x2140
PP_CNTL_X = 0x2cc4
PP_TXMULTI_CTL_0 = 0x2c1c
SE_VTX_STATE_CNTL = 0x2180
RB3D_DEPTHXY_OFFSET = 0x1d60    # FreeBSD radeon_drv.h 1318; Mesa writes 0 (r200_state_init.c 697)
PRE_GATE = 0x10f                # prefix_expect indexes that gate the draw (placement); the rest are recorded
RB3D_DEPTHOFFSET = 0x1c24
RB3D_DEPTHPITCH = 0x1c28
RB3D_COLOROFFSET = 0x1c40
RB3D_COLORPITCH = 0x1c48
RB3D_CNTL = 0x1c3c
SCRATCH_REG0 = 0x15e0
PP_TRI_PERF = 0x2cf8            # G4-7: r200_reg.h 1074; the reference writes 0 (r200_state_init.c 984-986)
PP_PERF_CNTL = 0x2cfc           # G4-7: r200_reg.h 1076
PP_TAM_DEBUG3 = 0x2d9c          # G4-9: r200_reg.h 1122; the DRI writes 0x6 (texture cache LRU hang workaround)
TAM_LRU = 0x0                   # G4-9 measured: 0x6 hangs RV280 on the first blend-mip submission; the reference's non-R200 value
SCRATCH_REG2 = 0x15e8
DSTCACHE_CTLSTAT = 0x325c
ZCACHE_CTLSTAT = 0x3254
WAIT_UNTIL = 0x1720
PURGE_DC = 0xf                  # RADEON_RB3D_DC_FLUSH | DC_FREE (radeon_drv.h 933-934)
PURGE_ZC = 0x5                  # RADEON_RB3D_ZC_FLUSH | ZC_FREE (radeon_drv.h 924-925)
WAIT_IDLE = 0x00070000          # 2D | 3D | HOST idleclean (RADEON_WAIT_UNTIL_IDLE)

CASES = {
    # case: (clip box, geometry box, z, R200_RE_CNTL) -- docs/R6B_PLAN.md 5
    'A': ((5, 3, 37, 21), (5, 3, 37, 21), 1.0, 0),
    'B': ((5, 3, 37, 21), (5, 3, 37, 21), 0.5, 0),
    'C': ((5, 3, 37, 21), (0, 0, 64, 32), 1.0, 0),
    'D': ((5, 3, 37, 21), (0, 0, 64, 32), 1.0, 2),     # C with SCISSOR_ENABLE
    'E': ((20, 12, 37, 21), (0, 0, 64, 32), 1.0, 0),   # TL moved, RE_CNTL 0
}
# R6c (docs/R6C_PLAN.md 6): A's box with SCISSOR_ENABLE (rule H: geometry = clip), and colour
CASES.update({
    'F': ((5, 3, 37, 21), (5, 3, 37, 21), 1.0, 2),
    'G': ((5, 3, 37, 21), (5, 3, 37, 21), 1.0, 2),
    'H': ((5, 3, 37, 21), (5, 3, 37, 21), 1.0, 2),
})
CASE_NUM = {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8}
SCISSOR_ENABLE = 0x2            # R200_RE_CNTL bit 1 (Mesa r200_reg.h 269)

# R6c colour: the vertex colour (r, g, b, a), whether VF_CNTL carries COLOR_ORDER_RGBA, and the
# SE_VTX_STATE_CNTL the prefix writes (Mesa's init value, or 0 for H)
RGBA = (0x12, 0x34, 0x56, 0x78)
COLOUR = {'F': dict(order=True, vsc='mesa'), 'G': dict(order=False, vsc='mesa'), 'H': dict(order=True, vsc=0)}

# Mesa 6.5.3 r200_reg.h, parsed here -- the values never come from the driver
MESA_REG = os.path.join(PROJ, 'ref', 'upstream', 'unpacked', 'Mesa-6.5.3', 'src', 'mesa', 'drivers', 'dri', 'r200',
                        'r200_reg.h')
_mesa = None


def M(name):
    global _mesa
    if _mesa is None:
        _mesa = {}
        for line in open(MESA_REG, errors='replace'):
            m = re.match(r'#define\s+(R200_\w+)\s+(.+?)\s*(/\*.*)?$', line)
            if m:
                _mesa[m.group(1)] = m.group(2)

    def ev(n):
        e = re.sub(r'(R200_\w+)', lambda m: '(%d)' % ev(m.group(1)), _mesa[n])
        return int(eval(e.replace('UL', '').replace('u', ''), {}))
    return ev(name) & M32


def colour_word():
    """Mesa's vertex colour with COLOR_IS_RGBA on a little-endian host: bytes r g b a"""
    r, g, b, a = RGBA
    return r | (g << 8) | (b << 16) | (a << 24)


def argb(r, g, b, a):
    """what the CPU reads from a linear ARGB8888 pixel (Mesa spantmp2.h 100-104)"""
    return (a << 24) | (r << 16) | (g << 8) | b


def colour_pixel(case):
    """the pixel Mesa's assumption predicts: with the order bit the word is r g b a,
    without it the hardware reads b g r a (the judge names the other outcomes)"""
    if case not in COLOUR:
        return None
    r, g, b, a = RGBA
    return argb(r, g, b, a) if COLOUR[case]['order'] else argb(b, g, r, a)


def vsc(case):
    if case not in COLOUR:
        return 0
    v = COLOUR[case]['vsc']
    return M('R200_VSC_UPDATE_USER_COLOR_0_ENABLE') if v == 'mesa' else v


def covered(case):
    """rule H (docs/R6B_PLAN.md 5): the geometry, cut by RE_WIDTH_HEIGHT (inclusive
    end) always and by RE_TOP_LEFT only with SCISSOR_ENABLE.  Measured on boot
    e3ec4d0c for RE_CNTL 0 (case C); the rule the R6a plan used -- TL always --
    was refuted there (docs/R6_PLAN.md 9)."""
    clip, geom, z, recntl = CASES[case]
    x0 = clip[0] if recntl & SCISSOR_ENABLE else 0
    y0 = clip[1] if recntl & SCISSOR_ENABLE else 0
    return (max(x0, geom[0]), max(y0, geom[1]), min(clip[2], geom[2]), min(clip[3], geom[3]))


def pattern(i):
    """block word i (0 .. 65535): the low 24 bits (0x0000..0xffff) never equal a
    depth the cases write (0xffffff, 0x7fffff, 0x800000); the top byte is the
    stencil byte the draw must leave alone"""
    return (0xa5000000 | (i & 0xffff)) & M32


def mba_z32(pitch, x, y):
    """Mesa 6.5.3 r200_span.c r200_mba_z32, depthHasSurface false"""
    def bit(v, b):
        return (v >> b) & 1
    b = ((y & 0x7ff) >> 4) * ((pitch & 0xfff) >> 5) + ((x & 0x7ff) >> 5)
    par = (b & 1) if (pitch & 0x20) else ((b & 1) ^ bit(y, 4))
    return ((bit(x, 0) << 2) | (bit(y, 0) << 3) | (bit(x, 1) << 4) | (bit(y, 1) << 5) | (bit(x, 3) << 6) |
            (bit(x, 4) << 7) | (bit(x, 2) << 8) | (bit(y, 2) << 9) | (bit(y, 3) << 10) | (par << 11) |
            ((b >> 1) << 12))


def linear32(pitch, x, y):
    return 4 * (x + y * pitch)


def pairs(regvals):
    out = []
    for reg, val in regvals:
        out += [p0(reg), val & M32]
    return out


def prefix_words(win, seed, case='A'):
    """the prefix, submitted and read back before anything is drawn"""
    return pairs([(SE_TCL_STATE_FLUSH, 0), (SE_VAP_CNTL_STATUS, 0), (PP_CNTL_X, 0), (PP_TXMULTI_CTL_0, 0),
                  (SE_VTX_STATE_CNTL, vsc(case)), (RB3D_DEPTHXY_OFFSET, 0),
                  (RB3D_DEPTHOFFSET, win + DEPTH_OFF), (RB3D_DEPTHPITCH, PITCH),
                  (RB3D_COLOROFFSET, win + COLOR_OFF), (RB3D_COLORPITCH, PITCH),
                  (PP_TRI_PERF, 0), (PP_PERF_CNTL, 0),      # G4-7: last, so [9] stays SE_VTX_STATE_CNTL
                  (PP_TAM_DEBUG3, TAM_LRU),                  # G4-9
                  (SCRATCH_REG0, seed)])


# what the prefix read-back must see (register, value) -- the ring's own values
def prefix_expect(win, case='A'):
    return [(RB3D_DEPTHOFFSET, win + DEPTH_OFF), (RB3D_DEPTHPITCH, PITCH), (RB3D_COLOROFFSET, win + COLOR_OFF),
            (RB3D_COLORPITCH, PITCH), (SE_VAP_CNTL_STATUS, 0), (PP_CNTL_X, 0), (PP_TXMULTI_CTL_0, 0),
            (SE_VTX_STATE_CNTL, vsc(case)), (RB3D_DEPTHXY_OFFSET, 0),
            (PP_TRI_PERF, 0), (PP_PERF_CNTL, 0),      # G4-7: recorded, not gated (PRE_GATE unchanged)
            (PP_TAM_DEBUG3, TAM_LRU)]                 # G4-9: recorded


def draw_words(case, seed):
    """the precedent, verbatim (state, clip, draw), then the tail"""
    clip, geom, z, recntl = CASES[case]
    st = dict(rco.clear_stream([clip], z))
    state = list(st['state (BEGIN_RING 26)'])
    assert state[4] == p0(V('R200_RE_CNTL'))
    state[5] = recntl
    cliprect = st['clip rect (BEGIN_RING 4)']
    draw = dict(rco.clear_stream([geom], z))['3D_DRAW_IMMD_2 (BEGIN_RING 14)']
    tail = pairs([(DSTCACHE_CTLSTAT, PURGE_DC), (ZCACHE_CTLSTAT, PURGE_ZC), (WAIT_UNTIL, WAIT_IDLE),
                  (RB3D_CNTL, 0), (SCRATCH_REG2, seed ^ M32)])
    if case not in COLOUR:
        return state + cliprect + draw + tail
    # R6c: Mesa's colour state (r200_state_init.c 607-608, 686, 770-792, 825), from Mesa's macros
    for reg, val in (('RADEON_PP_CNTL', M('R200_TEX_BLEND_0_ENABLE')),
                     ('RADEON_RB3D_PLANEMASK', 0xffffffff),
                     ('R200_SE_VTX_FMT_0', M('R200_VTX_Z0') | M('R200_VTX_W0') |
                      (M('R200_VTX_PK_RGBA') << M('R200_VTX_COLOR_0_SHIFT')))):
        k = state.index(p0(V(reg)))
        state[k + 1] = val
    pix = pairs([(M('R200_PP_TXCBLEND_0'), M('R200_TXC_ARG_A_ZERO') | M('R200_TXC_ARG_B_ZERO') |
                  M('R200_TXC_ARG_C_DIFFUSE_COLOR') | M('R200_TXC_OP_MADD')),
                 (M('R200_PP_TXCBLEND2_0'), M('R200_TXC_SCALE_1X') | M('R200_TXC_CLAMP_0_1') |
                  M('R200_TXC_OUTPUT_REG_R0')),
                 (M('R200_PP_TXABLEND_0'), M('R200_TXA_ARG_A_ZERO') | M('R200_TXA_ARG_B_ZERO') |
                  M('R200_TXA_ARG_C_DIFFUSE_ALPHA') | M('R200_TXA_OP_MADD')),
                 (M('R200_PP_TXABLEND2_0'), M('R200_TXA_SCALE_1X') | M('R200_TXA_CLAMP_0_1') |
                  M('R200_TXA_OUTPUT_REG_R0'))])
    # the precedent's packet, each vertex followed by the colour (Mesa r200_swtcl.c 106-126:
    # COLOR0 right after the four position words); the count is the payload minus one
    verts = draw[2:]
    body = [draw[1] | (M('R200_VF_COLOR_ORDER_RGBA') if COLOUR[case]['order'] else 0)]
    for v in range(3):
        body += verts[4 * v:4 * v + 4] + [colour_word()]
    hdr = rco.p3(V('R200_3D_DRAW_IMMD_2'), len(body) - 1)
    return state + pix + cliprect + [hdr] + body + tail


def depth24(z, rounding):
    """z float -> 24-bit: 'trunc' (Mesa r200_state.c 379-391, d * 0xffffff) or 'round'"""
    v = z * 0xffffff
    return int(v) if rounding == 'trunc' else int(v + 0.5)


def expected_block(case, layout='tiled', rounding='trunc', clayout='linear', pixel=None):
    """the whole 256 KiB block (words) after ZPREP then ZCLEAR <case>; a colour case
    also fills the colour buffer (pixel: the value, default colour_pixel(case);
    clayout: 'linear' -- pitch 64 with no tile bits, r200_reg.h 213-219 -- or 'tiled')"""
    clip, geom, z, recntl = CASES[case]
    words = [pattern(i) for i in range(ALIAS_BYTES // 4)]
    d = depth24(z, rounding)
    addr = mba_z32 if layout == 'tiled' else linear32
    caddr = mba_z32 if clayout == 'tiled' else linear32
    if pixel is None:
        pixel = colour_pixel(case)
    x0, y0, x1, y1 = covered(case)
    for y in range(y0, y1):
        for x in range(x0, x1):
            k = (DEPTH_OFF + addr(PITCH, x, y)) // 4
            words[k] = (words[k] & 0xff000000) | d
            if pixel is not None:
                words[(COLOR_OFF + caddr(PITCH, x, y)) // 4] = pixel & M32
    return words


def digest(words, first, count):
    """what the driver logs for words[first:first+count] (the C side computes the
    same, tools/r6 sim compares): xor, a position-weighted sum, how many differ
    from the pattern, the xor and sum of their indexes, and up to four distinct
    changed values"""
    x = s = n = ix = isum = 0
    vals = []
    for k in range(first, first + count):
        w = words[k]
        x ^= w
        s = (s + w * (2 * (k - first) + 1)) & M32
        if w != pattern(k):
            n += 1
            ix ^= (k - first)
            isum = (isum + (k - first)) & M32
            if w not in vals and len(vals) < 4:
                vals.append(w)
    return dict(xor=x, wsum=s, changed=n, ixor=ix, isum=isum, vals=vals)


def self_test():
    bad = 0

    def expect(label, got, want):
        nonlocal bad
        ok = got == want
        print('  %-4s %-66s %s' % ('ok' if ok else 'FAIL', label, '' if ok else 'got %r want %r' % (got, want)))
        bad += 0 if ok else 1

    # the pattern never collides with a depth the cases write, and is unique per word
    lows = set(pattern(i) & 0xffffff for i in range(ALIAS_BYTES // 4))
    expect('pattern low 24 bits never 0xffffff/0x7fffff/0x800000', lows & {0xffffff, 0x7fffff, 0x800000}, set())
    expect('pattern unique over the block', len(set(pattern(i) for i in range(ALIAS_BYTES // 4))), ALIAS_BYTES // 4)
    # tiling: a bijection inside the buffer
    ad = [mba_z32(PITCH, x, y) for y in range(HEIGHT) for x in range(WIDTH)]
    expect('r200_mba_z32 pitch 64: 4096 distinct addresses', len(set(ad)), 4096)
    expect('r200_mba_z32 pitch 64: all inside the 16 KiB buffer', max(ad) < BUF_BYTES, True)
    expect('the colour buffer lies outside the depth buffer and inside the block',
           DEPTH_OFF + BUF_BYTES <= COLOR_OFF and COLOR_OFF + BUF_BYTES <= ALIAS_BYTES, True)
    # R4's surfaces (osrdn_engine.h) do not overlap either buffer
    r4 = [(16384, 81920), (98304, 163840), (180224, 212992), (229376, 245760)]
    ov = [r for r in r4 for b in ((DEPTH_OFF, DEPTH_OFF + BUF_BYTES), (COLOR_OFF, COLOR_OFF + BUF_BYTES))
          if r[0] < b[1] and b[0] < r[1]]
    expect('no overlap with R4 S0/S1/S2/D', ov, [])
    # depth values
    expect('z 1.0 -> 0xffffff (trunc and round)', (depth24(1.0, 'trunc'), depth24(1.0, 'round')), (0xffffff, 0xffffff))
    expect('z 0.5 -> 0x7fffff trunc, 0x800000 round', (depth24(0.5, 'trunc'), depth24(0.5, 'round')), (0x7fffff, 0x800000))
    # the streams
    win = 0x0029e000
    pw = prefix_words(win, 0x1234)
    expect('prefix: 14 PACKET0 pairs', len(pw), 28)
    expect('prefix gate = the five placement registers', [r for k, (r, _) in enumerate(prefix_expect(win)) if PRE_GATE >> k & 1],
           [RB3D_DEPTHOFFSET, RB3D_DEPTHPITCH, RB3D_COLOROFFSET, RB3D_COLORPITCH, RB3D_DEPTHXY_OFFSET])
    expect('prefix: DEPTHOFFSET = winStart', pw[pw.index(p0(RB3D_DEPTHOFFSET)) + 1], win)
    dw = draw_words('C', 0x1234)
    expect('draw: 26 state + 4 clip + 14 draw + 10 tail words', len(dw), 54)
    expect('draw C: clip is (5,3)-(37,21), inclusive end', dw[26:30],
           [p0(V('RADEON_RE_TOP_LEFT')), (3 << 16) | 5, p0(V('RADEON_RE_WIDTH_HEIGHT')), (20 << 16) | 36])
    expect('draw C: geometry x2 = 64.0f', dw[30 + 2 + 8], rco.fbits(64.0))
    expect('draw: IMMD_2 count 12 = 3 vertices x 4 words (SE_VTX_FMT_0 = Z0|W0 over XY)',
           (dw[30] >> 16) & 0x3fff, 12)
    expect('tail: RB3D_CNTL = 0 before the last marker', dw[-4:-2], [p0(RB3D_CNTL), 0])
    # the expected blocks: tiled and linear differ, the outside is untouched
    for case in 'ABCDEFGH':
        t = expected_block(case, 'tiled')
        dg = digest(t, DEPTH_OFF // 4, BUF_BYTES // 4)
        want_n = {'A': 576, 'B': 576, 'C': 777, 'D': 576, 'E': 777, 'F': 576, 'G': 576, 'H': 576}[case]
        expect('case %s: %d words changed in the depth buffer (rule H)' % (case, want_n), dg['changed'], want_n)
        rest = digest(t, COLOR_OFF // 4, BUF_BYTES // 4)
        expect('case %s: colour buffer %s' % (case, 'untouched' if case in 'ABCDE' else '576 words'),
               rest['changed'], 0 if case in 'ABCDE' else 576)
        lin = digest(expected_block(case, 'linear'), DEPTH_OFF // 4, BUF_BYTES // 4)
        expect('case %s: tiled and linear digests differ' % case, dg['ixor'] != lin['ixor'] or dg['isum'] != lin['isum'], True)
    b_t = digest(expected_block('B', 'tiled', 'trunc'), 0, BUF_BYTES // 4)
    b_r = digest(expected_block('B', 'tiled', 'round'), 0, BUF_BYTES // 4)
    expect('case B: the two roundings give different values', b_t['vals'] != b_r['vals'], True)
    expect('rule H: C covers [0,37)x[0,21) (the measured e3ec4d0c rectangle)', covered('C'), (0, 0, 37, 21))
    expect('rule H: D (SCISSOR_ENABLE) leaves the depth buffer A leaves',
           expected_block('A')[:BUF_BYTES // 4] == expected_block('D')[:BUF_BYTES // 4], True)
    expect('rule H: E (TL moved, RE_CNTL 0) leaves the depth buffer C leaves',
           expected_block('C')[:BUF_BYTES // 4] == expected_block('E')[:BUF_BYTES // 4], True)
    expect('rule H: C and D differ', expected_block('C')[:BUF_BYTES // 4] != expected_block('D')[:BUF_BYTES // 4], True)
    expect('draw D: RE_CNTL value word is 2, C\'s is 0', (draw_words('D', 1)[5], draw_words('C', 1)[5]), (2, 0))
    # R6c (docs/R6C_PLAN.md 6): the numbers the plan states, from Mesa's macros
    fw = draw_words('F', 0x1234)
    expect('draw F: 26 state + 8 blend + 4 clip + 17 draw + 10 tail = 65 words', len(fw), 65)
    expect('draw F: PP_CNTL, PLANEMASK, SE_VTX_FMT_0 value words', (fw[3], fw[13], fw[19]), (0x1000, 0xffffffff, 0x803))
    expect('draw F: blend stage 0 = 0x2f00 1000, 2f04 11000, 2f08 1000, 2f0c 11000', fw[26:34],
           [p0(0x2f00), 0x1000, p0(0x2f04), 0x11000, p0(0x2f08), 0x1000, p0(0x2f0c), 0x11000])
    expect('draw F: header 0xc00f3500, VF_CNTL 0x00030078', fw[38:40], [0xc00f3500, 0x00030078])
    expect('draw G: VF_CNTL 0x00030038 (order bit off)', draw_words('G', 1)[39], 0x00030038)
    expect('draw F: colour word 0x78563412 after each vertex', [fw[40 + 5 * v + 4] for v in range(3)], [0x78563412] * 3)
    expect('draw F/A: same geometry words', [fw[40 + 5 * v:44 + 5 * v] for v in range(3)],
           [draw_words('A', 1)[32 + 4 * v:36 + 4 * v] for v in range(3)])
    for case in 'ABCDEFGH':
        dw = draw_words(case, 1)
        k = dw.index(rco.p3(V('R200_3D_DRAW_IMMD_2'), 12) if case in 'ABCDE' else 0xc00f3500)
        fmt = dw[19]
        vs = 4 + (1 if (fmt >> M('R200_VTX_COLOR_0_SHIFT')) & 3 else 0)
        expect('case %s: IMMD count = 3 x %d vertex words (SE_VTX_FMT_0 %03x)' % (case, vs, fmt),
               (dw[k] >> 16) & 0x3fff, 3 * vs)
    expect('pixels: F 0x78123456, G 0x78563412, H 0x78123456',
           [colour_pixel(c) for c in 'FGH'], [0x78123456, 0x78563412, 0x78123456])
    expect('prefix: SE_VTX_STATE_CNTL F 0x10000, H 0, A 0', [prefix_words(win, 1, c)[9] for c in 'FHA'], [0x10000, 0, 0])
    expect('rule H: F covers A\'s box', covered('F'), covered('A'))
    expect('F: depth buffer = A\'s', expected_block('F')[:BUF_BYTES // 4] == expected_block('A')[:BUF_BYTES // 4], True)
    lc = digest(expected_block('F'), COLOR_OFF // 4, BUF_BYTES // 4)
    tc = digest(expected_block('F', clayout='tiled'), COLOR_OFF // 4, BUF_BYTES // 4)
    expect('F: linear and tiled colour digests differ', (lc['ixor'], lc['isum']) != (tc['ixor'], tc['isum']), True)
    expect('F: last colour word ends at 0x3d494 (inside the block)',
           COLOR_OFF + linear32(PITCH, 36, 20) + 4, 0x3d494)
    print('zclear_oracle self-test: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(self_test())
    sys.exit(__doc__)
