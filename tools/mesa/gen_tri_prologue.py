#!/usr/bin/env python3
"""M1d step 1: the CP prologue one triangle needs, generated from the oracles.

  gen_tri_prologue.py            write mesa/OSRDNMesaTriTable.h
  gen_tri_prologue.py --stdout   print it instead
  gen_tri_prologue.py --self-test

NOTHING HERE IS TYPED BY HAND.  The words come from tools/r7/verify_oracle.py's
stream_u1() -- the R6 ladder's measured T1 draw in the form a client may send --
and the register numbers and bit positions are parsed out of the driver's own
header and out of ref/upstream's r200_reg.h.  A renumbered bit changes this
table instead of quietly invalidating it, which is the same reason R7a's case
table is generated rather than written.

Two things this does to the oracle's stream, and why:

  * IT TURNS DEPTH OFF.  The measured prologue has R200_Z_ENABLE in RB3D_CNTL
    and R200_Z_WRITE_ENABLE in RB3D_ZSTENCILCNTL, and the driver's prefix points
    RB3D_DEPTHOFFSET at winStart + CP_R6_DEPTH_OFF, which is winStart + 0 -- the
    very bytes M1c maps as its COLOUR surface.  Sent unchanged, the depth writes
    would land on the picture.  R6 never saw it because its colour buffer sits
    at winStart + 0x3c000 instead.  (docs/M1D_PLAN.md 4d)

  * IT ADDS RB3D_COLOROFFSET AND RB3D_COLORPITCH.  The oracle's client stream
    writes neither -- it draws wherever the driver's prefix pointed, which is
    the R6 colour buffer, not M1c's surface.  M1d has to say where it is
    drawing, and the verifier requires the two to come as a pair.

The result is a template with SLOTS: the C fills in the surface address (which
it learns from CAPS, never from a constant) and the clip rectangle.
"""

import os
import re
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.join(HERE, '..', '..')
OUT = os.path.join(PROJ, 'mesa', 'OSRDNMesaTriTable.h')
CP_H = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')
CP_M = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.m')
R200 = os.path.join(PROJ, 'ref', 'upstream', 'unpacked', 'Mesa-6.5.3', 'src',
                    'mesa', 'drivers', 'dri', 'r200', 'r200_reg.h')

PKT_MASK = 0xc0000000
PKT0, PKT3 = 0x00000000, 0xc0000000

# what each word of the template is.  A literal is a literal; the rest the C fills.
SLOT_LITERAL = 0
SLOT_COLOROFFSET = 1        # winStart + the surface's byte offset
SLOT_COLORPITCH = 2         # the surface's pitch, in pixels
SLOT_WIDTH_HEIGHT = 3       # (h-1) << 16 | (w-1)
SLOT_TOP_LEFT = 4           # y << 16 | x
SLOT_SE_CNTL = 5            # M1e: the flat value or the Gouraud one
SLOT_RB3D_CNTL = 6          # M1f: with or without ALPHA_BLEND_ENABLE
SLOT_BLENDCNTL = 7          # M1f: the blend pair, or the default when blending is off
SLOT_TXOFFSET = 8           # M1g: winStart + where the texels were put
# G4-1a (docs/G4_GLQUAKE_PLAN.md 5 M): the texture combiner's two words -- REPLACE (the measured
# template) or MODULATE (the same words with the arguments R0 x DIFFUSE, r200_texstate.c 797-802)
SLOT_TXCBLEND = 12
SLOT_TXABLEND = 13
# G4-1b (docs/G4_GLQUAKE_PLAN.md 5 T1): the texture's own words -- filter, format (log2 size), size, pitch
SLOT_TXFILTER = 14
SLOT_TXFORMAT = 15
SLOT_TXSIZE = 16
SLOT_TXPITCH = 17
# G4-3 K2 (docs/G4_3_KERNEL_PLAN.md 3): the alpha test -- PP_CNTL's enable bit and PP_MISC's ref/compare
SLOT_PP_CNTL = 18
SLOT_PP_MISC = 19
# M3h (docs/M3H_PLAN.md 4-7): the window laid out for the LARGEST surface the
# library takes, so no offset depends on the size of the one being drawn.
# Colour at 0 (w x h x 4); depth after it, as the reference allocates a tiled
# buffer -- pitch up to 32 pixels, rows up to 16, 4 KiB aligned (xf86
# radeon_accel.c 1187-1189); the texels after that.  R6m measured that moving
# a surface inside the window leaves the picture unchanged.  M1i put depth at
# 0x10000 and the texels at 0x20000 for a 64 x 64 surface only.
SURF_MAX_W, SURF_MAX_H = 1280, 1024
DEPTH_OFF = 0x500000
TEX_OFF = 0x780000


def _up(x, n):
    return (x + n - 1) // n * n


assert DEPTH_OFF >= SURF_MAX_W * SURF_MAX_H * 4 and DEPTH_OFF % 4096 == 0
assert TEX_OFF >= DEPTH_OFF + _up(_up(SURF_MAX_H, 16) * _up(SURF_MAX_W, 32) * 2, 4096)

SLOT_ZSTENCILCNTL = 9       # M1i: depth off (M1d's value) or on, with the compare
SLOT_DEPTHOFFSET = 10       # M1i: winStart + where the depth buffer was put
SLOT_DEPTHPITCH = 11        # M1i: the depth pitch, in pixels
SLOT_NAMES = ['LITERAL', 'COLOROFFSET', 'COLORPITCH', 'WIDTH_HEIGHT', 'TOP_LEFT',
              'SE_CNTL', 'RB3D_CNTL', 'BLENDCNTL', 'TXOFFSET',
              'ZSTENCILCNTL', 'DEPTHOFFSET', 'DEPTHPITCH', 'TXCBLEND', 'TXABLEND',
              'TXFILTER', 'TXFORMAT', 'TXSIZE', 'TXPITCH', 'PP_CNTL', 'PP_MISC']
TEX_BLEND = {}              # G4-1a: the template's TXCBLEND_0 / TXABLEND_0 words (REPLACE), filled by tex_template()


def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


def defines(path, prefix):
    """{name: value} for the plain numeric #defines in a file"""
    out = {}
    for m in re.finditer(r'^#define\s+(%s\w+)\s+\(?\s*(0x[0-9a-fA-F]+|\d+)'
                         r'(?:\s*<<\s*(\d+))?' % prefix,
                         open(path, errors='replace').read(), re.M):
        v = int(m.group(2), 0)
        if m.group(3):
            v <<= int(m.group(3))
        out[m.group(1)] = v
    return out


def regs():
    """register address -> name, from the driver's own header and source"""
    out = {}
    for path in (CP_H, CP_M):
        for m in re.finditer(r'^#define\s+(C_[A-Z0-9_]+)\s+(0x[0-9a-fA-F]+)',
                             open(path, errors='replace').read(), re.M):
            v = int(m.group(2), 16)
            if v < 0x8000:
                out.setdefault(v, m.group(1))
    return out


REG = regs()
R200_BITS = defines(R200, 'R200_')
CP_CONST = defines(CP_H, 'CP_R6_')


def reg_of(word):
    return (word & 0x3fff) * 4


def p0(reg, val):
    return [(reg >> 2) & 0x3fff, val]


def build():
    """(words, slots, body_first) -- the template and what each word is for"""
    vo = load('verify_oracle', os.path.join(PROJ, 'tools', 'r7', 'verify_oracle.py'))
    u1 = vo.stream_u1()

    # where the PKT3 starts: everything before it is the prologue
    i, head = 0, None
    while i < len(u1):
        if (u1[i] & PKT_MASK) == PKT3:
            head = i
            break
        i += 2                                  # the prologue is PKT0 pairs only
    if head is None:
        raise RuntimeError('the oracle stream has no PKT3')

    zsten = next(r for r, n in REG.items() if n == 'C_RB3D_ZSTENCILCNTL')
    cntl = next(r for r, n in REG.items() if n == 'C_RB3D_CNTL')
    coff = next(r for r, n in REG.items() if n == 'C_RB3D_COLOROFFSET')
    cpit = next(r for r, n in REG.items() if n == 'C_RB3D_COLORPITCH')
    wh = next(r for r, n in REG.items() if n == 'C_RE_WIDTH_HEIGHT')
    tl = next(r for r, n in REG.items() if n == 'C_RE_TOP_LEFT')
    # The driver has no symbolic name for SE_CNTL -- it appears only as a number
    # in the allow-list arrays -- so the register is asked of the same oracle the
    # prologue came from, exactly as gouraud_oracle.py asks it.
    zo = load('zclear_oracle', os.path.join(PROJ, 'tools', 'r6', 'zclear_oracle.py'))
    se = zo.V('RADEON_SE_CNTL')
    # the oracle's macro source does not carry this one; the driver's own
    # header does (C_RB3D_BLENDCNTL), and that is where every other
    # register in this function comes from anyway.
    bcn = next(r for r, n in REG.items() if n == 'C_RB3D_BLENDCNTL')

    pcn = next(r for r, n in REG.items() if n == 'C_PP_CNTL')
    words, slots = [], []
    i = 0
    while i < head:
        r, v = reg_of(u1[i]), u1[i + 1]
        slot = SLOT_LITERAL
        if r == pcn:
            slot = SLOT_PP_CNTL                         # G4-3 K2: | ALPHA_TEST_ENABLE when the test is on
        elif r == zsten:
            v &= ~R200_BITS['R200_Z_WRITE_ENABLE']      # 4d
            # M1i: the LITERAL stays M1d's (depth off), so a C that ignores this
            # slot still draws what M1d drew -- a new slot must not change an old
            # picture.  That is the rule SE_CNTL was added under.
            slot = SLOT_ZSTENCILCNTL
        elif r == cntl:
            # ONE branch does both.  RB3D_CNTL is the same register 4d clears the
            # depth bit in and M1f turns into a slot; writing them as two elif
            # arms of the same chain left the second unreachable and the slot was
            # never created -- the self-test found it, not a reading.
            v &= ~R200_BITS['R200_Z_ENABLE']            # 4d
            slot = SLOT_RB3D_CNTL                       # M1f
        elif r == wh:
            slot = SLOT_WIDTH_HEIGHT
        elif r == tl:
            slot = SLOT_TOP_LEFT
        elif r == se:
            # M1e: flat or Gouraud, chosen at run time.  The literal stays the
            # flat value so that a C that ignores the slot still draws what M1d
            # drew -- a new slot must not change an old picture.
            slot = SLOT_SE_CNTL
        words += [u1[i], v]
        slots += [SLOT_LITERAL, slot]
        i += 2

    # the surface the oracle's stream never names
    words += p0(coff, 0)
    slots += [SLOT_LITERAL, SLOT_COLOROFFSET]
    words += p0(cpit, 0)
    slots += [SLOT_LITERAL, SLOT_COLORPITCH]

    # M1f: the blend unit, which the oracle's stream never writes at all.  The
    # reference driver insists this register carry a defined value even when
    # blending is OFF (r200_state.c 197-200), so it is always sent.
    _abe, boff, _bon = blend_values()
    words += p0(bcn, boff)
    slots += [SLOT_LITERAL, SLOT_BLENDCNTL]

    # M1i: WHERE the depth buffer is.  The driver's prefix already writes these
    # two, pointing at its own CP_R6_DEPTH_OFF -- which for the client case is
    # offset 0, i.e. ON TOP OF the colour surface (docs/M1D_PLAN.md 4d).  That is
    # why M1d turned depth off rather than moving it.  Our words come after the
    # prefix in the same submission, so writing them again is what moves it.
    dof = next(r for r, n in REG.items() if n == 'C_RB3D_DEPTHOFFSET')
    dpi = next(r for r, n in REG.items() if n == 'C_RB3D_DEPTHPITCH')
    words += p0(dof, 0)
    slots += [SLOT_LITERAL, SLOT_DEPTHOFFSET]
    words += p0(dpi, 0)
    slots += [SLOT_LITERAL, SLOT_DEPTHPITCH]
    # G4-3 K2: the alpha test's reference and compare; 0 = FAIL/ref 0, which the enable bit off leaves unread
    words += p0(next(r for r, n in REG.items() if n == 'C_PP_MISC'), 0)
    slots += [SLOT_LITERAL, SLOT_PP_MISC]
    return words, slots


def blend_values():
    """the four M1f values, all DERIVED.

      RB3D_CNTL plain   the literal already in the oracle's stream
      RB3D_CNTL blend   that, with R200_ALPHA_BLEND_ENABLE out of r200_reg.h
      BLENDCNTL off     ONE / ZERO / ADD_CLAMP -- the value the reference driver
                        insists on even when blending is disabled, because at
                        least GL_MIN and GL_FUNC_REVERSE_SUBTRACT go wrong
                        otherwise (r200_state.c 197-200).  Our prologue has
                        never written this register at all.
      BLENDCNTL on      SRC_ALPHA / ONE_MINUS_SRC_ALPHA / ADD_CLAMP

    The two BLENDCNTL words are checked against the values the R6j ladder
    actually sent (the driver's own cpR6G table), so they are measured values
    and not a reading of the encoding that happens to look right.
    """
    src = open(R200, errors='replace').read()
    def d(name):
        m = re.search(r'#define\s+%s\s+\((\d+)\)' % name, src)
        if not m:
            raise RuntimeError('no %s in r200_reg.h' % name)
        return int(m.group(1))
    def sh(name):
        m = re.search(r'#define\s+%s\s+\((\d+)\)' % name, src)
        return int(m.group(1))
    def bit(name):
        m = re.search(r'#define\s+%s\s+\((\d+)\s*<<\s*(\d+)\)' % name, src)
        return int(m.group(1)) << int(m.group(2))
    S, D = sh('R200_SRC_BLEND_SHIFT'), sh('R200_DST_BLEND_SHIFT')
    comb = bit('R200_COMB_FCN_ADD_CLAMP')
    off = (d('R200_BLEND_GL_ONE') << S) | (d('R200_BLEND_GL_ZERO') << D) | comb
    on = ((d('R200_BLEND_GL_SRC_ALPHA') << S) |
          (d('R200_BLEND_GL_ONE_MINUS_SRC_ALPHA') << D) | comb)

    # the ladder's own rows -- if the encoding above were misread these would
    # not match, and the generator would stop rather than emit a plausible lie
    cp = open(CP_M, errors='replace').read()
    blk = cp.split('static const unsigned long cpR6G[30][12] = {')[1].split('};')[0]
    sent = set()
    for row in re.findall(r'\{([^}]*)\}', blk):
        v = [x.strip() for x in row.split(',') if x.strip()]
        if len(v) >= 12:
            b = int(v[10].replace('UL', ''), 0)
            if b:
                sent.add(b)
    for v, what in ((off, 'ONE/ZERO/ADD_CLAMP'), (on, 'SRC_ALPHA/ONE_MINUS_SRC_ALPHA')):
        if v not in sent:
            raise RuntimeError('%s builds 0x%08x, which the R6j ladder never sent %s'
                               % (what, v, sorted('0x%08x' % x for x in sent)))
    return bit('R200_ALPHA_BLEND_ENABLE'), off, on


RE_CNTL_REG = 0x1c50            # R200_RE_CNTL (r200_reg.h 267); the kernel block names it by its packet0 header


def tex_template():
    """M1g: the TEXTURED prologue, from tools/r6/tex_oracle.py -- the same stream
    R6h and R6i measured the sampling rule with, in the form a client may send.

    Case XA: 8 x 8 ARGB8888 at alias + 0x20000, stride 32, nearest, POT (the
    log2 fields in TXFORMAT; PP_TXSIZE and PP_TXPITCH go out as Mesa sends them
    but the hardware does not read them for a POT texture -- measured, XE).

    Returns (words, slots, geometry) with geometry = (w, h, stride, texOff).
    """
    te = load('tex_oracle', os.path.join(PROJ, 'tools', 'r6', 'tex_oracle.py'))
    full = te.draw_words('XA', 1, win=0)

    # the client form: the driver adds its own tail and its own WAIT_UNTIL
    body, out, i = full[:-10], [], 0
    while i < len(body):
        h = body[i]
        if (h & PKT_MASK) == PKT0:
            if ((h & 0x3fff) * 4) == 0x1720:
                i += 2
                continue
            out += [h, body[i + 1]]
            i += 2
        else:
            n = ((h >> 16) & 0x3fff) + 1
            out += body[i:i + 1 + n]
            i += 1 + n

    # walk in PAIRS.  Scanning every index for a PKT3 finds a DATA word whose
    # top two bits happen to be 11 (a float, or a register value like
    # 0xc0000000) and stops the prologue early -- it did, at 18 words.
    head, k = None, 0
    while k < len(out):
        if (out[k] & PKT_MASK) == PKT3:
            head = k
            break
        k += 2
    if head is None:
        raise RuntimeError('the textured stream has no PKT3')
    zsten = next(r for r, n in REG.items() if n == 'C_RB3D_ZSTENCILCNTL')
    cntl = next(r for r, n in REG.items() if n == 'C_RB3D_CNTL')
    coff = next(r for r, n in REG.items() if n == 'C_RB3D_COLOROFFSET')
    cpit = next(r for r, n in REG.items() if n == 'C_RB3D_COLORPITCH')
    wh = next(r for r, n in REG.items() if n == 'C_RE_WIDTH_HEIGHT')
    tl = next(r for r, n in REG.items() if n == 'C_RE_TOP_LEFT')
    txo = next(r for r, n in REG.items() if n == 'C_PP_TXOFFSET_0')
    txf = next(r for r, n in REG.items() if n == 'C_PP_TXFILTER_0')
    txc = next(r for r, n in REG.items() if n == 'C_PP_TXCBLEND_0')
    txa = next(r for r, n in REG.items() if n == 'C_PP_TXABLEND_0')
    txfmt = next(r for r, n in REG.items() if n == 'C_PP_TXFORMAT_0')
    txsz = next(r for r, n in REG.items() if n == 'C_PP_TXSIZE_0')
    txpi = next(r for r, n in REG.items() if n == 'C_PP_TXPITCH_0')
    bcn = next(r for r, n in REG.items() if n == 'C_RB3D_BLENDCNTL')
    zo = load('zclear_oracle', os.path.join(PROJ, 'tools', 'r6', 'zclear_oracle.py'))
    se = zo.V('RADEON_SE_CNTL')

    words, slots, k = [], [], 0
    while k < head:
        r, v = reg_of(out[k]), out[k + 1]
        slot = SLOT_LITERAL
        if r == zsten:
            v &= ~R200_BITS['R200_Z_WRITE_ENABLE']      # M1d 4d: depth off
            # G4-11: the same slot the plain table has (line ~190).  Without it
            # every textured draw went out with the OFF literal whatever depth
            # code the caller passed -- GLQuake's world drew with no depth test
            # (docs/G4_11_TEX_DEPTH_SLOT_PLAN.md 0).
            slot = SLOT_ZSTENCILCNTL
        elif r == cntl:
            v &= ~R200_BITS['R200_Z_ENABLE']
            slot = SLOT_RB3D_CNTL
        elif r == wh:
            slot = SLOT_WIDTH_HEIGHT
        elif r == tl:
            slot = SLOT_TOP_LEFT
        elif r == se:
            slot = SLOT_SE_CNTL
        elif r == txo:
            slot = SLOT_TXOFFSET
        elif r == txc:
            slot = SLOT_TXCBLEND
            TEX_BLEND['c'] = v
        elif r == txa:
            slot = SLOT_TXABLEND
            TEX_BLEND['a'] = v
        elif r == txfmt:
            slot = SLOT_TXFORMAT
        elif r == txsz:
            slot = SLOT_TXSIZE
        elif r == txpi:
            slot = SLOT_TXPITCH
        elif r == RE_CNTL_REG:
            # G4-1b: PERSPECTIVE_ENABLE.  R6i measured (docs/R6I_PLAN.md 8): with this bit
            # the card weights s and t by the vertex W word (q = W0, zero mismatch on PB/PC),
            # and WITHOUT it the W word is ignored (PD = PA, every pixel).  XA was measured
            # with W = 1 and the bit off; the library now sends Mesa's 1/w (Win[3]) on a
            # textured vertex, and Mesa's own textured triangle is perspective-correct
            # (triangle.c 1612), so the bit goes with the texture template only.  The plain
            # template keeps its measured word: Gouraud there is screen-linear like Mesa's.
            v |= R200_BITS['R200_PERSPECTIVE_ENABLE']
        elif r == next(rr for rr, nn in REG.items() if nn == 'C_PP_CNTL'):
            slot = SLOT_PP_CNTL                         # G4-3 K2
        elif r == txf:
            # XA's own filter word says CLAMP_LAST, and the CLASSIFIER accepts
            # only GL_REPEAT (OSRDNMesaClass.c 89-90).  Those are two different
            # promises about the same triangle: inside [0,1] they agree, so the
            # picture would have looked right while the contract was wrong, and
            # the first ST that left the square would have sampled the edge
            # texel where Mesa wrapped.  Send the WRAP filter -- R6h measured it
            # too, on XC and XG, with this very texture (8 x 8, stride 32).
            v = te.txfilter('wrap')
            slot = SLOT_TXFILTER
        words += [out[k], v]
        slots += [SLOT_LITERAL, slot]
        k += 2

    words += p0(coff, 0)
    slots += [SLOT_LITERAL, SLOT_COLOROFFSET]
    words += p0(cpit, 0)
    slots += [SLOT_LITERAL, SLOT_COLORPITCH]
    _abe, boff, _bon = blend_values()
    words += p0(bcn, boff)
    slots += [SLOT_LITERAL, SLOT_BLENDCNTL]
    # G4-1b: the depth buffer, as the plain prologue carries it (build()).  Without these two the
    # kernel's surface check sees the driver prefix's depth (pitch 64) under a full-size clip and
    # refuses every textured triangle wider than 64 (boot 7: CP_R7_WHY_SURFACE at the draw header)
    dof = next(r for r, n in REG.items() if n == 'C_RB3D_DEPTHOFFSET')
    dpi = next(r for r, n in REG.items() if n == 'C_RB3D_DEPTHPITCH')
    words += p0(dof, 0)
    slots += [SLOT_LITERAL, SLOT_DEPTHOFFSET]
    words += p0(dpi, 0)
    slots += [SLOT_LITERAL, SLOT_DEPTHPITCH]
    # G4-3 K2: the alpha test's reference and compare; 0 = FAIL/ref 0, which the enable bit off leaves unread
    words += p0(next(r for r, n in REG.items() if n == 'C_PP_MISC'), 0)
    slots += [SLOT_LITERAL, SLOT_PP_MISC]
    w, h, stride = te.tex_of('XA')
    # M3h: the texels sit at the library's TEX_OFF, not where XA measured them
    # (te.TEX_OFF) -- the offset is a slot, filled per draw
    return words, slots, (w, h, stride, TEX_OFF)


def state_values():
    """G4-1a (docs/G4_GLQUAKE_PLAN.md 5 D, B, M): the words a widened state needs, DERIVED from
    r200_reg.h and the measured template -- never typed.
      depth   the Z_TEST field values LESS/LEQUAL/GEQUAL/ALWAYS (r200DepthFunc, r200_state.c 344)
              and the two masks the C uses to build ZSTENCILCNTL from the measured LESS word
      blend   the two pairs GLQuake adds (ZERO, ONE_MINUS_SRC_COLOR) and (ONE, ONE), packed as
              blend_values() packs the measured pair (r200_reg.h codes, ADD_CLAMP)
      env     MODULATE = the measured REPLACE words with ONLY the argument fields changed:
              A = R0 (the texel), B = DIFFUSE, C = ZERO, MADD, and COMP_ARG_B off (REPLACE
              multiplies by ~ZERO = 1 -- r200_texstate.c 797-802, 893-898)
    """
    B = R200_BITS
    zt = dict((n, B['R200_Z_TEST_%s' % n] >> 4) for n in ('LESS', 'LEQUAL', 'GEQUAL', 'ALWAYS'))
    if B['R200_Z_TEST_MASK'] != 7 << 4:
        raise RuntimeError('Z_TEST is not bits 6:4')
    S, D = B['R200_SRC_BLEND_SHIFT'], B['R200_DST_BLEND_SHIFT']
    comb = B['R200_COMB_FCN_ADD_CLAMP']
    zero_omsc = (B['R200_BLEND_GL_ZERO'] << S) | (B['R200_BLEND_GL_ONE_MINUS_SRC_COLOR'] << D) | comb
    one_one = (B['R200_BLEND_GL_ONE'] << S) | (B['R200_BLEND_GL_ONE'] << D) | comb
    if not TEX_BLEND:
        tex_template()
    cmask = B['R200_TXC_ARG_A_MASK'] | B['R200_TXC_ARG_B_MASK'] | B['R200_TXC_COMP_ARG_B']
    amask = B['R200_TXA_ARG_A_MASK'] | B['R200_TXA_ARG_B_MASK'] | B['R200_TXA_COMP_ARG_B']
    cmod = (TEX_BLEND['c'] & ~cmask) | B['R200_TXC_ARG_A_R0_COLOR'] | B['R200_TXC_ARG_B_DIFFUSE_COLOR'] | B['R200_TXC_ARG_C_ZERO'] | B['R200_TXC_OP_MADD']
    amod = (TEX_BLEND['a'] & ~amask) | B['R200_TXA_ARG_A_R0_ALPHA'] | B['R200_TXA_ARG_B_DIFFUSE_ALPHA'] | B['R200_TXA_ARG_C_ZERO'] | B['R200_TXA_OP_MADD']
    return dict(ztest=zt, zmask=B['R200_Z_TEST_MASK'], zwrite=B['R200_Z_WRITE_ENABLE'],
                zero_omsc=zero_omsc, one_one=one_one, crep=TEX_BLEND['c'], arep=TEX_BLEND['a'], cmod=cmod, amod=amod)


def gouraud():
    """the two SE_CNTL values, both out of the R6 oracles -- neither is typed here.

    R6e measured the Gouraud interpolation rule with EXACTLY this value
    (gouraud_oracle.py 278-286), which is why M1e sends it rather than the
    reference driver's five-field version (0x4a00aade): the prediction the gate
    compares against belongs to the state it was measured in."""
    go = load('gouraud_oracle', os.path.join(PROJ, 'tools', 'r6', 'gouraud_oracle.py'))
    return go.SE_CNTL_FLAT, go.se_cntl_gouraud()


def emit():
    words, slots = build()
    sv = state_values()                    # G4-1a: computed before the text, used twice below
    vo = sys.modules['verify_oracle']
    to = sys.modules['tri_oracle']
    flat, smooth = gouraud()
    abe, boff, bon = blend_values()
    #
    # M1i: the depth control words.  The OFF value is the literal this generator
    # already put in the table (M1d cleared Z_WRITE_ENABLE from the measured
    # stream); the ON value adds it back with the LESS compare, which is what
    # GL_LESS -- the GL default -- asks for.  Both bit names come from the same
    # oracle every other register in this file comes from.
    #
    zo2 = load('zclear_oracle', os.path.join(PROJ, 'tools', 'r6', 'zclear_oracle.py'))
    zsten_r = next(r for r, n in REG.items() if n == 'C_RB3D_ZSTENCILCNTL')
    zoff_v = next(words[k + 1] for k in range(0, len(words), 2)
                  if reg_of(words[k]) == zsten_r)
    #
    # AND THE FORMAT.  The measured stream's ZSTENCILCNTL carries
    # DEPTH_FORMAT_24BIT_INT_Z (the format field is 2), because the R6 ladder
    # measured both widths and this case is the 24-bit one.  M1i is 16-bit --
    # that is what Mesa's software buffer is, what SOFTWARE_DEPTH_BITS says, and
    # what the address table below is built for.
    #
    # Leaving the field alone cost a hardware run: the card stored 32-bit depth
    # at mba_z32 addresses while the clear filled mba_z16 ones, and the read-back
    # came out a patchwork of ffff and 0000 -- two layouts over one buffer.
    #
    zon_v = ((zoff_v & ~(zo2.M('R200_Z_TEST_MASK') | zo2.M('R200_DEPTH_FORMAT_MASK'))) |
             zo2.M('R200_Z_WRITE_ENABLE') | zo2.M('R200_Z_TEST_LESS') |
             zo2.M('R200_DEPTH_FORMAT_16BIT_INT_Z'))
    zena = zo2.M('R200_Z_ENABLE')
    # M1i: the depth address table and the far value, both computed here from
    # the measured oracles -- see the comment the emitter writes beside them.
    do2 = load('depth_oracle', os.path.join(PROJ, 'tools', 'r6', 'depth_oracle.py'))
    depth_at = [do2.mba_z16(x, y, 64) for y in range(64) for x in range(64)]
    depth_bytes = max(depth_at) + 2
    far16 = do2.space(16)[('qNone', 'p2', 'floor')](1.0)
    plain = next(w for k, w in enumerate(words)
                 if slots[k] == SLOT_RB3D_CNTL)
    base = to.vf_cntl('T1') & 0xffff             # the flags, without the vertex count

    L = ['/*',
         ' * OSRDNMesaTriTable.h - M1d: the prologue one triangle needs.',
         ' *',
         ' * GENERATED by tools/mesa/gen_tri_prologue.py from tools/r7/verify_oracle.py\'s',
         ' * stream_u1() -- the R6 ladder\'s measured T1 draw, in the form a client may',
         ' * send.  Nothing in this file is typed by hand; regenerate it, do not edit it.',
         ' *',
         ' * Depth is OFF here on purpose: the measured prologue enables it, and the',
         ' * driver\'s prefix points the depth buffer at winStart + 0, which is where M1c',
         ' * maps its COLOUR surface (docs/M1D_PLAN.md 4d).',
         ' */',
         '',
         '#ifndef OSRDN_MESA_TRI_TABLE_H',
         '#define OSRDN_MESA_TRI_TABLE_H',
         '',
         '#define OSRDN_TRI_PROLOGUE_WORDS  %d' % len(words),
         '#define OSRDN_TRI_VERTEX_WORDS    %d   /* x, y, z, w, colour */' % 5,
         '#define OSRDN_TRI_VF_CNTL_FLAGS   0x%08lxUL  /* prim, walk, colour order */' % base,
         '#define OSRDN_TRI_DRAW_HDR_BASE   0x%08lxUL  /* PKT3 | 3D_DRAW_IMMD_2 */'
         % (PKT3 | 0x3500),
         '',
         '/* M1e: what goes in the SE_CNTL slot.  Both come from tools/r6, and the',
         '   Gouraud one is the value R6e measured its interpolation rule under. */',
         '#define OSRDN_TRI_SE_CNTL_FLAT    0x%08lxUL' % flat,
         '#define OSRDN_TRI_SE_CNTL_GOURAUD 0x%08lxUL' % smooth,
         '',
         '/* M1f: the blend unit.  BLENDCNTL carries a defined value even when',
         '   blending is off, which the reference driver requires; both words are',
         '   values the R6j ladder actually sent. */',
         '#define OSRDN_TRI_RB3D_CNTL_PLAIN 0x%08lxUL' % plain,
         '#define OSRDN_TRI_RB3D_CNTL_BLEND 0x%08lxUL' % (plain | abe),
         '#define OSRDN_TRI_BLENDCNTL_OFF   0x%08lxUL' % boff,
         '#define OSRDN_TRI_BLENDCNTL_SRCA  0x%08lxUL' % bon,
         '',
         '/* M1i: depth.  The ZSTENCILCNTL literal in the table is M1d\'s -- depth',
         '   OFF -- so a C that ignores the slot draws what M1d drew.  The ON value',
         '   is that literal with Z_WRITE_ENABLE and the LESS compare, and RB3D_CNTL',
         '   needs Z_ENABLE ORed in; both bits are the ones R6f and R6g measured',
         '   with (docs/M1I_PLAN.md 8).  The offset is where docs/M1I_PLAN.md 7',
         '   computed the buffer can sit without touching colour or texels. */',
         '#define OSRDN_TRI_ZSTENCIL_OFF    0x%08lxUL' % zoff_v,
         '#define OSRDN_TRI_ZSTENCIL_LESS   0x%08lxUL' % zon_v,
         '#define OSRDN_TRI_RB3D_CNTL_Z     0x%08lxUL' % zena,
         '/* G4-1a (docs/G4_GLQUAKE_PLAN.md 5 D, B): the compare field and the write bit the C',
         '   puts into the LESS word above; the Z_TEST values are r200_reg.h 107-115 (r200DepthFunc),',
         '   GL_NEVER/GREATER/EQUAL/NOTEQUAL are not offered.  The depth CODE a state carries is',
         '   1 | ztest << 1 | write << 4 (OSRDNMesaClass.c osrdn_class_depth_code). */',
         '#define OSRDN_TRI_ZSTENCIL_TEST_MASK 0x%08lxUL' % sv['zmask'],
         '#define OSRDN_TRI_ZSTENCIL_TEST_SHIFT 4',
         '#define OSRDN_TRI_ZSTENCIL_WRITE  0x%08lxUL' % sv['zwrite'],
         '#define OSRDN_TRI_ZTEST_LESS      %dUL' % sv['ztest']['LESS'],
         '#define OSRDN_TRI_ZTEST_LEQUAL    %dUL' % sv['ztest']['LEQUAL'],
         '#define OSRDN_TRI_ZTEST_GEQUAL    %dUL' % sv['ztest']['GEQUAL'],
         '#define OSRDN_TRI_ZTEST_ALWAYS    %dUL' % sv['ztest']['ALWAYS'],
         '/* the blend CODES a state carries and the words they select (blend_values() packing) */',
         '#define OSRDN_TRI_BLEND_OFF       0',
         '#define OSRDN_TRI_BLEND_SRCA      1',
         '#define OSRDN_TRI_BLEND_ZERO_OMSC 2   /* (GL_ZERO, GL_ONE_MINUS_SRC_COLOR): GLQuake lightmaps */',
         '#define OSRDN_TRI_BLEND_ONE_ONE   3   /* (GL_ONE, GL_ONE): GLQuake flash blend */',
         '#define OSRDN_TRI_BLENDCNTL_ZERO_OMSC 0x%08lxUL' % sv['zero_omsc'],
         '#define OSRDN_TRI_BLENDCNTL_ONE_ONE 0x%08lxUL' % sv['one_one'],
         '#define OSRDN_TRI_DEPTH_BYTE_OFF  0x%08lxUL' % DEPTH_OFF,
         '/* M3h: the largest surface the window is laid out for; the depth',
         '   pitch is the surface width taken up to 32 (docs/M3H_PLAN.md 4). */',
         '#define OSRDN_TRI_SURF_MAX_W      %d' % SURF_MAX_W,
         '#define OSRDN_TRI_SURF_MAX_H      %d' % SURF_MAX_H,
         '#define OSRDN_TRI_DEPTH_PITCH     %d' % 64,
         '#define OSRDN_TRI_DEPTH_W         64',
         '#define OSRDN_TRI_DEPTH_H         64',
         '#define OSRDN_TRI_DEPTH_BYTES     %d' % depth_bytes,
         '#define OSRDN_TRI_DEPTH_FAR       0x%04xUL   /* glClearDepth(1.0) */' % far16,
         '',
         '/* M1i: the byte address of depth pixel (x, y), GENERATED from',
         '   tools/r6/depth_oracle.py mba_z16 -- the tiling R6f measured.  A C',
         '   that computed this itself would be a second copy of a rule that was',
         '   hard to get right once; the whole 64 x 64 is %d entries of two'
         % (64 * 64),
         '   bytes, small enough to be a table and exact by construction. */',
         'static const unsigned short osrdnDepthAt[OSRDN_TRI_DEPTH_W *',
         '                                        OSRDN_TRI_DEPTH_H] = {'] + \
        [('    ' + ' '.join('0x%04x,' % a for a in depth_at[k:k + 12]))
         for k in range(0, len(depth_at), 12)] + \
        ['};',
         '',
         '/* what the C must put in each word; anything else is sent as it stands */']
    for k, n in enumerate(SLOT_NAMES):
        L.append('#define OSRDN_TRI_SLOT_%-13s %d' % (n, k))
    L += ['',
          'static const unsigned long osrdnTriPrologue[OSRDN_TRI_PROLOGUE_WORDS] = {']
    for k in range(0, len(words), 4):
        L.append('    ' + ', '.join('0x%08lxUL' % w for w in words[k:k + 4]) +
                 (',' if k + 4 < len(words) else ''))
    L += ['};', '',
          'static const unsigned char osrdnTriSlot[OSRDN_TRI_PROLOGUE_WORDS] = {']
    for k in range(0, len(slots), 16):
        L.append('    ' + ', '.join(str(x) for x in slots[k:k + 16]) +
                 (',' if k + 16 < len(slots) else ''))
    L += ['};', '']

    # ---- M1g: the textured prologue, its slots and its geometry
    tw, ts, (gw, gh, gstride, goff) = tex_template()
    te = sys.modules['tex_oracle']
    L += ['/* M1g: the TEXTURED prologue -- the same stream R6h and R6i measured the',
          '   sampling rule with, in the form a client may send.  The vertex is SEVEN',
          '   words here (x, y, z, w, colour, s, t) because SE_VTX_FMT_1 asks for two',
          '   components on unit 0, and the kernel checks that count. */',
          '#define OSRDN_TEX_PROLOGUE_WORDS  %d' % len(tw),
          '#define OSRDN_TEX_VERTEX_WORDS    7',
          '#define OSRDN_TEX_VF_CNTL_FLAGS   0x%08lxUL' % (te.vf() & 0xffff),
          '#define OSRDN_TEX_W               %d' % gw,
          '#define OSRDN_TEX_H               %d' % gh,
          '/* the row stride the HARDWARE reads: max(w * 4, 32).  The CPU must lay the',
          '   texels out at exactly this, or rows below 8 pixels wide are read shuffled',
          '   (measured, R6h case XF: 16 and 64 both wrong, 32 exact). */',
          '#define OSRDN_TEX_STRIDE          %d' % max(gw * 4, 32),
          '#define OSRDN_TEX_BYTE_OFF        0x%08lxUL' % goff,
          '/* G4-1a (docs/G4_GLQUAKE_PLAN.md 5 M): the texture CODES a state carries and the two',
          '   combiner words each selects -- REPLACE is the measured template, MODULATE is R0 x',
          '   DIFFUSE in the same words (r200_texstate.c 797-802, 893-898) */',
          '#define OSRDN_TRI_TEX_OFF         0',
          '#define OSRDN_TRI_TEX_REPLACE     1',
          '#define OSRDN_TRI_TEX_MODULATE    2',
          '#define OSRDN_TEX_TXCBLEND_REPLACE  0x%08lxUL' % sv['crep'],
          '#define OSRDN_TEX_TXABLEND_REPLACE  0x%08lxUL' % sv['arep'],
          '#define OSRDN_TEX_TXCBLEND_MODULATE 0x%08lxUL' % sv['cmod'],
          '#define OSRDN_TEX_TXABLEND_MODULATE 0x%08lxUL' % sv['amod'],
          '/* G4-1b (docs/G4_GLQUAKE_PLAN.md 5 T1): what the C composes a texture\'s words from --',
          '   tools/r6/tex_oracle.py txformat/txfilter as constants (r200_reg.h 827-830, 853-865, 876-910):',
          '   TXFORMAT = ARGB | log2 w << 8 | log2 h << 12, TXFILTER = wrap-nearest base | mag/min linear bits,',
          '   TXSIZE = (w-1) | (h-1) << 16, TXPITCH = w x 4 - 32 (rows are w x 4 bytes, 32 at least). */',
          '#define OSRDN_TEX_TXFORMAT_ARGB     0x%08lxUL' % (te.M('R200_TXFORMAT_ARGB8888') | te.M('R200_TXFORMAT_ALPHA_IN_MAP') | te.M('R200_TXFORMAT_ST_ROUTE_STQ0')),
          '#define OSRDN_TEX_TXFORMAT_WIDTH_SHIFT  %d' % te.M('R200_TXFORMAT_WIDTH_SHIFT'),
          '#define OSRDN_TEX_TXFORMAT_HEIGHT_SHIFT %d' % te.M('R200_TXFORMAT_HEIGHT_SHIFT'),
          '#define OSRDN_TEX_TXFILTER_WRAP_NEAREST 0x%08lxUL' % te.txfilter('wrap'),
          '#define OSRDN_TEX_TXFILTER_MAG_LINEAR 0x%08lxUL' % te.M('R200_MAG_FILTER_LINEAR'),
          '#define OSRDN_TEX_TXFILTER_MIN_LINEAR 0x%08lxUL' % te.M('R200_MIN_FILTER_LINEAR'),
          '/* G4-4 K5 (docs/G4_4_KERNEL_PLAN.md 4-2): the four mip MIN modes as r200SetTexFilter maps the GL',
          '   filters onto them (r200_tex.c 206-231: GL NEAREST_MIPMAP_LINEAR -> LINEAR_MIP_NEAREST and',
          '   LINEAR_MIPMAP_NEAREST -> NEAREST_MIP_LINEAR), and the level-count field [19:16] */',
          '#define OSRDN_TEX_TXFILTER_MIN_MASK          0x%08lxUL' % te.M('R200_MIN_FILTER_MASK'),
          '#define OSRDN_TEX_TXFILTER_MIN_NEAREST_MIP_NEAREST 0x%08lxUL' % te.M('R200_MIN_FILTER_NEAREST_MIP_NEAREST'),
          '#define OSRDN_TEX_TXFILTER_MIN_NEAREST_MIP_LINEAR  0x%08lxUL' % te.M('R200_MIN_FILTER_NEAREST_MIP_LINEAR'),
          '#define OSRDN_TEX_TXFILTER_MIN_LINEAR_MIP_NEAREST  0x%08lxUL' % te.M('R200_MIN_FILTER_LINEAR_MIP_NEAREST'),
          '#define OSRDN_TEX_TXFILTER_MIN_LINEAR_MIP_LINEAR   0x%08lxUL' % te.M('R200_MIN_FILTER_LINEAR_MIP_LINEAR'),
          '#define OSRDN_TEX_TXFILTER_MAX_MIP_SHIFT     %d' % te.M('R200_MAX_MIP_LEVEL_SHIFT'),
          '#define OSRDN_TEX_TXFILTER_MAX_MIP_MASK      0x%08lxUL' % te.M('R200_MAX_MIP_LEVEL_MASK'),
          '#define OSRDN_TEX_MAX_LEVELS      16    /* MAX_MIP_LEVEL is four bits */',
          '/* the MIN filter as a code between the classifier and the Tri unit -- GL\'s six, named as GL names',
          '   them (OSRDNMesaTri.c triMinField maps them onto the field above the way r200SetTexFilter does) */',
          '#define OSRDN_TRI_MIN_NEAREST                0',
          '#define OSRDN_TRI_MIN_LINEAR                 1',
          '#define OSRDN_TRI_MIN_NEAREST_MIPMAP_NEAREST 2',
          '#define OSRDN_TRI_MIN_LINEAR_MIPMAP_NEAREST  3',
          '#define OSRDN_TRI_MIN_NEAREST_MIPMAP_LINEAR  4',
          '#define OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR   5',
          '#define OSRDN_TRI_MIN_MIP_FIRST              2',
          '#define OSRDN_TRI_MIN_CODES                  6',
          '/* G4-5 (docs/G4_5_MIP_PLAN.md 2-3): what the RDNMesaMip knob allows (osrdn_tri_mip_mode) */',
          '#define OSRDN_TRI_MIP_OFF       0',
          '#define OSRDN_TRI_MIP_MEASURED  1',
          '#define OSRDN_TRI_MIP_ALL       2',
          '#define OSRDN_TEX_MIN_DIM         8     /* 8 x 8 is what R6h measured; smaller rows are read shuffled (XF) */',
          '#define OSRDN_TEX_MAX_DIM         512   /* GLQuake\'s largest (lq_e0m1); the log2 field goes further */',
          '#define OSRDN_TEX_ARENA_BYTES     0x%08lxUL   /* 32 MiB after the texels\' start: the pak\'s upper bound is 21.3 (build/g4/model.py) */' % (32 << 20),
          '/* G4-3 K2 (docs/G4_3_KERNEL_PLAN.md 3): the alpha test, r200AlphaFunc\'s encoding (r200_state.c 66-92,',
          '   r200_reg.h 33-43, 180).  A code is 1 | op << 1 | ref << 4; op is the R200 compare field value. */',
          '#define OSRDN_ALPHA_ENABLE        0x%08lxUL   /* PP_CNTL: R200_ALPHA_TEST_ENABLE */' % R200_BITS['R200_ALPHA_TEST_ENABLE'],
          '#define OSRDN_ALPHA_REF_MASK      0x%08lxUL' % R200_BITS['R200_REF_ALPHA_MASK'],
          '#define OSRDN_ALPHA_OP_SHIFT      8',
          '#define OSRDN_ALPHA_OP_FAIL       %d' % (R200_BITS['R200_ALPHA_TEST_FAIL'] >> 8),
          '#define OSRDN_ALPHA_OP_LESS       %d' % (R200_BITS['R200_ALPHA_TEST_LESS'] >> 8),
          '#define OSRDN_ALPHA_OP_LEQUAL     %d' % (R200_BITS['R200_ALPHA_TEST_LEQUAL'] >> 8),
          '#define OSRDN_ALPHA_OP_EQUAL      %d' % (R200_BITS['R200_ALPHA_TEST_EQUAL'] >> 8),
          '#define OSRDN_ALPHA_OP_GEQUAL     %d' % (R200_BITS['R200_ALPHA_TEST_GEQUAL'] >> 8),
          '#define OSRDN_ALPHA_OP_GREATER    %d' % (R200_BITS['R200_ALPHA_TEST_GREATER'] >> 8),
          '#define OSRDN_ALPHA_OP_NEQUAL     %d' % (R200_BITS['R200_ALPHA_TEST_NEQUAL'] >> 8),
          '#define OSRDN_ALPHA_OP_PASS       %d' % (R200_BITS['R200_ALPHA_TEST_PASS'] >> 8),
          '',
          'static const unsigned long osrdnTexPrologue[OSRDN_TEX_PROLOGUE_WORDS] = {']
    for k in range(0, len(tw), 4):
        L.append('    ' + ', '.join('0x%08lxUL' % x for x in tw[k:k + 4]) +
                 (',' if k + 4 < len(tw) else ''))
    L += ['};', '',
          'static const unsigned char osrdnTexSlot[OSRDN_TEX_PROLOGUE_WORDS] = {']
    for k in range(0, len(ts), 16):
        L.append('    ' + ', '.join(str(x) for x in ts[k:k + 16]) +
                 (',' if k + 16 < len(ts) else ''))
    #
    # M1k: what a BATCH may hold.  The limit is the verifier's
    # (BATCH_MAX_WORDS), and a batch is "the prologue once, then ONE draw packet
    # carrying every triangle" -- the shape R6 measured with (tri_oracle.py:143).
    # Two packets per triangle would fit fewer (115 vs 131), so there is one.
    #
    # The number the LIBRARY uses is computed at run time out of caps->maxWords,
    # the prologue it actually sent and the vertex width.  These constants only
    # size the arrays, so the run-time number can never exceed them.
    #
    bmax = vo.BATCH_MAX_WORDS
    ktris = max((bmax - len(words) - 2) // (3 * 5),
                (bmax - len(tw) - 2) // (3 * 7))
    L += ['/* M1k: the batch.  A batch is the prologue once and ONE draw packet with',
          '   every triangle in it -- the shape R6 measured with.  These size the',
          '   arrays; the library computes the real bound at run time from',
          '   caps->maxWords, the prologue it sent and the vertex width, so it can',
          '   only ever be SMALLER than this. */',
          '#define OSRDN_BATCH_MAX_WORDS     %d' % bmax,
          '#define OSRDN_BATCH_MAX_TRIS      %d' % ktris,
          '',
          '/* Replaying a batch to the software function is only correct because the',
          '   class declines DD_TRI_OFFSET and DD_TRI_LIGHT_TWOSIDE: both put state',
          '   in the context that is set just before the triangle call and cleared',
          '   just after it (vbrender.c:298-305, 307-311, 324-329), which a later',
          '   replay would read wrong.  The generator checks the two bits are inside',
          '   OSRDNMesaClass.c\'s DD_SW_SETUP_ -- see self_test(). */',
          '#define OSRDN_BATCH_NEEDS_SW_SETUP_DECLINED 1',
          '']
    L += ['};', '', '#endif /* OSRDN_MESA_TRI_TABLE_H */', '']
    return '\n'.join(L)


def self_test():
    # G4-1a: the derived words, checked against python's own reading of r200_reg.h
    sv = state_values()
    B = R200_BITS
    assert sv['ztest'] == {'LESS': 1, 'LEQUAL': 2, 'GEQUAL': 4, 'ALWAYS': 7}, sv['ztest']
    assert sv['zwrite'] == 1 << 30 and sv['zmask'] == 0x70
    assert sv['zero_omsc'] == (32 << 16) | (35 << 24) and sv['one_one'] == (33 << 16) | (33 << 24), (hex(sv['zero_omsc']), hex(sv['one_one']))
    assert (sv['crep'] & 31) == B['R200_TXC_ARG_A_R0_COLOR'] and (sv['crep'] & B['R200_TXC_COMP_ARG_B']), hex(sv['crep'])
    assert sv['cmod'] == B['R200_TXC_ARG_A_R0_COLOR'] | B['R200_TXC_ARG_B_DIFFUSE_COLOR'], hex(sv['cmod'])
    assert sv['amod'] == B['R200_TXA_ARG_A_R0_ALPHA'] | B['R200_TXA_ARG_B_DIFFUSE_ALPHA'], hex(sv['amod'])
    # G4-3 K2: the alpha encoding read from r200_reg.h, and the two slots in both templates
    B = R200_BITS
    assert B['R200_ALPHA_TEST_ENABLE'] == 0x00800000 and B['R200_REF_ALPHA_MASK'] == 0xff, 'alpha bits'
    assert [B['R200_ALPHA_TEST_%s' % n] >> 8 for n in ('FAIL', 'LESS', 'LEQUAL', 'EQUAL', 'GEQUAL', 'GREATER', 'NEQUAL', 'PASS')] == list(range(8))
    assert B['R200_ALPHA_TEST_OP_MASK'] == 7 << 8
    for tmpl in (build()[:2], tex_template()[:2]):
        tw_, ts_ = tmpl[0], tmpl[1]
        assert ts_.count(SLOT_PP_CNTL) == 1 and ts_.count(SLOT_PP_MISC) == 1, 'alpha slots'
        assert tw_[ts_.index(SLOT_PP_MISC)] == 0 and (tw_[ts_.index(SLOT_PP_CNTL)] & B['R200_ALPHA_TEST_ENABLE']) == 0
    # G4-1b: the C's composition of TXFORMAT/TXFILTER from the constants must give the template's words
    tw, ts, (gw, gh, gstride, goff) = tex_template()
    # G4-1b: PERSPECTIVE_ENABLE rides the texture template only (R6i: q = W0 needs the bit)
    rc_t = [tw[i + 1] for i in range(0, len(tw) - 1, 2) if tw[i] == (RE_CNTL_REG >> 2)]
    pw, _ps = build()[:2] if isinstance(build(), tuple) else (build(), None)
    rc_p = [pw[i + 1] for i in range(0, len(pw) - 1, 2) if pw[i] == (RE_CNTL_REG >> 2)]
    assert rc_t == [R200_BITS['R200_SCISSOR_ENABLE'] | R200_BITS['R200_PERSPECTIVE_ENABLE']], [hex(x) for x in rc_t]
    assert rc_p == [R200_BITS['R200_SCISSOR_ENABLE']], [hex(x) for x in rc_p]
    te = sys.modules['tex_oracle']
    fmt_i = ts.index(SLOT_TXFORMAT); fil_i = ts.index(SLOT_TXFILTER); sz_i = ts.index(SLOT_TXSIZE); pi_i = ts.index(SLOT_TXPITCH)
    base = te.M('R200_TXFORMAT_ARGB8888') | te.M('R200_TXFORMAT_ALPHA_IN_MAP') | te.M('R200_TXFORMAT_ST_ROUTE_STQ0')
    assert tw[fmt_i] == base | (3 << te.M('R200_TXFORMAT_WIDTH_SHIFT')) | (3 << te.M('R200_TXFORMAT_HEIGHT_SHIFT')), hex(tw[fmt_i])
    assert tw[fil_i] == te.txfilter('wrap') and tw[sz_i] == 7 | 7 << 16 and tw[pi_i] == te.txpitch(gstride), (hex(tw[fil_i]), hex(tw[sz_i]), tw[pi_i])
    assert te.txpitch(gstride) == gw * 4 - 32
    fails = 0

    def one(label, cond):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', label))

    words, slots = build()
    vo = sys.modules['verify_oracle']
    to = sys.modules['tri_oracle']

    one('the template is whole PKT0 pairs', len(words) % 2 == 0)
    one('a slot code for every word', len(slots) == len(words))

    # the two bits 4d is about, read back out of the generated words
    got = {}
    for i in range(0, len(words), 2):
        got[reg_of(words[i])] = words[i + 1]
    zsten = next(r for r, n in REG.items() if n == 'C_RB3D_ZSTENCILCNTL')
    cntl = next(r for r, n in REG.items() if n == 'C_RB3D_CNTL')
    one('4d: R200_Z_WRITE_ENABLE is CLEAR in RB3D_ZSTENCILCNTL',
        (got[zsten] & R200_BITS['R200_Z_WRITE_ENABLE']) == 0)
    one('4d: R200_Z_ENABLE is CLEAR in RB3D_CNTL',
        (got[cntl] & R200_BITS['R200_Z_ENABLE']) == 0)
    # and that the test could have failed: the oracle's own stream HAS them set
    u1 = vo.stream_u1()
    was = {}
    for i in range(0, len(u1), 2):
        if (u1[i] & PKT_MASK) != PKT0:
            break
        was[reg_of(u1[i])] = u1[i + 1]
    one('and the measured stream really did have both set '
        '(so clearing them is a change, not a no-op)',
        (was[zsten] & R200_BITS['R200_Z_WRITE_ENABLE']) != 0 and
        (was[cntl] & R200_BITS['R200_Z_ENABLE']) != 0)

    coff = next(r for r, n in REG.items() if n == 'C_RB3D_COLOROFFSET')
    cpit = next(r for r, n in REG.items() if n == 'C_RB3D_COLORPITCH')
    one('the surface offset and pitch are both present (the verifier wants a pair)',
        coff in got and cpit in got)
    one('and each has a slot, so no card address is in the table',
        slots[[reg_of(words[i]) for i in range(0, len(words), 2)].index(coff) * 2 + 1]
        == SLOT_COLOROFFSET)
    # The rule this replaced was junk: PKT0 is 0, so "(w & PKT_MASK) == PKT0" is
    # true of almost every word, and it read a REGISTER VALUE (0x42227072) as if
    # it were an address.  What is actually wanted is the oracle's own answer to
    # "which words carry a surface address", and that every one of them is a slot.
    fix = vo.fixup_mask(words)
    marked = [i for i, x in enumerate(fix) if x]
    one('the oracle marks the surface-address words (%d of them)' % len(marked),
        len(marked) > 0)
    one('and every marked word is a SLOT, so no card address is in the table',
        all(slots[i] != SLOT_LITERAL for i in marked))
    # the pitch is not an address, so fixup_mask does not mark it -- leaving it
    # out of this list made the rule fail on a correct table
    one('every slot is an address the oracle marked, a pitch, the clip, the '
        'shade control, the blend unit, the depth control or the alpha test',
        all(slots[i] == SLOT_LITERAL or fix[i] or
            slots[i] in (SLOT_COLORPITCH, SLOT_WIDTH_HEIGHT, SLOT_TOP_LEFT,
                         SLOT_SE_CNTL, SLOT_RB3D_CNTL, SLOT_BLENDCNTL,
                         # M1i: the depth PITCH and the depth CONTROL are not
                         # addresses, so fixup_mask does not mark them; the
                         # depth OFFSET is one and it does.
                         SLOT_DEPTHPITCH, SLOT_ZSTENCILCNTL,
                         # G4-3 K2: the alpha test's enable and its ref/compare
                         SLOT_PP_CNTL, SLOT_PP_MISC)
            for i in range(len(words))))
    # and the depth offset had better be one the oracle marks, or the driver
    # would not relocate it and the client would be writing a raw card address
    kd = [i for i, sl in enumerate(slots) if sl == SLOT_DEPTHOFFSET]
    one('there is exactly one DEPTHOFFSET slot and the oracle marks it as an '
        'address', len(kd) == 1 and fix[kd[0]])

    # M1e: the shade slot, and that its two values are the oracles' own
    flat, smooth = gouraud()
    k = [i for i, s in enumerate(slots) if s == SLOT_SE_CNTL]
    one('there is exactly one SE_CNTL slot', len(k) == 1)
    one('and the literal under it is the FLAT value, so a C that ignores the slot '
        'draws what M1d drew', bool(k) and words[k[0]] == flat)
    one('the Gouraud value differs from the flat one in the two shade fields only '
        '(0x%08x ^ 0x%08x = 0x%08x)' % (flat, smooth, flat ^ smooth),
        (flat ^ smooth) == ((3 << 8) | (3 << 10)) & (flat ^ smooth) and
        (flat ^ smooth) != 0 and ((flat ^ smooth) & ~((3 << 8) | (3 << 10))) == 0)

    # the whole point: a filled-in stream must pass the verifier oracle
    win, pitch, w, h = vo.SIM_WIN, 64, 64, 64
    filled = list(words)
    for i, s in enumerate(slots):
        if s == SLOT_COLOROFFSET:
            filled[i] = win
        elif s == SLOT_COLORPITCH:
            filled[i] = pitch
        elif s == SLOT_WIDTH_HEIGHT:
            filled[i] = ((h - 1) << 16) | (w - 1)
        elif s == SLOT_TOP_LEFT:
            filled[i] = 0
        elif s == SLOT_DEPTHOFFSET:
            filled[i] = win + DEPTH_OFF
        elif s == SLOT_DEPTHPITCH:
            filled[i] = pitch
        elif s == SLOT_ZSTENCILCNTL:
            filled[i] = filled[i]              # the literal is depth OFF (M1d)
    body = [(to.vf_cntl('T1') & 0xffff) | (3 << 16)]
    for (x, y) in ((4.0, 4.0), (28.0, 4.0), (4.0, 28.0)):
        body += [to.fbits(x), to.fbits(y), to.fbits(1.0), to.fbits(1.0), 0x78563412]
    stream = filled + [PKT3 | 0x3500 | ((len(body) - 1) << 16)] + body
    why, msg = vo.verify(stream, win_start=win, win_end=win + vo.WIN_BYTES)
    one('a filled-in one-triangle stream passes the verifier oracle (why=%s %s)'
        % (why, msg), why == 0)

    #
    # M1i gate B: the same stream with DEPTH ON.  This is the evidence for the
    # plan's claim that the rung needs no driver change -- the five depth
    # registers are in the client allow-list, and the verifier is the thing that
    # decides.  It already proved half of it by REFUSING an unfilled depth
    # offset ("depth 0x0 + 0 leaves the window").
    #
    zo3 = load('zclear_oracle', os.path.join(PROJ, 'tools', 'r6', 'zclear_oracle.py'))
    kz = [i for i, sl in enumerate(slots) if sl == SLOT_ZSTENCILCNTL]
    kc = [i for i, sl in enumerate(slots) if sl == SLOT_RB3D_CNTL]
    one('there is exactly one ZSTENCILCNTL slot and one RB3D_CNTL slot',
        len(kz) == 1 and len(kc) == 1)
    # the format the ON value asks for must be the one the address table is
    # built for -- 16 bits.  These two were allowed to disagree once.

    if kz and kc:
        zstream = list(stream)
        zon = ((stream[kz[0]] &
                ~(zo3.M('R200_Z_TEST_MASK') | zo3.M('R200_DEPTH_FORMAT_MASK'))) |
               zo3.M('R200_Z_WRITE_ENABLE') | zo3.M('R200_Z_TEST_LESS') |
               zo3.M('R200_DEPTH_FORMAT_16BIT_INT_Z'))
        zstream[kz[0]] = zon
        # THE FORMAT AND THE ADDRESS TABLE MUST AGREE.  They were allowed to
        # disagree once: the measured stream carries 24-bit depth, the table is
        # built from mba_z16, and the card then stored 32-bit values at
        # addresses the 16-bit clear had never touched.
        #
        # EVERY BIT WE CHANGED MUST BE ONE WE NAMED.
        #
        # This is the M1i bug as a rule.  The ON value is built from a MEASURED
        # literal by masking in the bits we mean to change; the field we did not
        # mean to touch -- the depth FORMAT -- stayed at the measured stream's
        # 24-bit and the card then used a layout the address table was not built
        # for.  Naming the masks and checking the XOR against them turns "I did
        # not think about that field" into a failed self-test.
        #
        named = (zo3.M('R200_Z_TEST_MASK') | zo3.M('R200_Z_WRITE_ENABLE') |
                 zo3.M('R200_DEPTH_FORMAT_MASK'))
        one('turning depth on changes only bits this file NAMES '
            '(0x%08x changed, 0x%08x named)' % (stream[kz[0]] ^ zon, named),
            (stream[kz[0]] ^ zon) & ~named == 0)
        zfmt = zon & zo3.M('R200_DEPTH_FORMAT_MASK')
        one('the depth-on value asks for 16-bit depth (format field %d), which is '
            'what the address table is built for' % zfmt,
            zfmt == zo3.M('R200_DEPTH_FORMAT_16BIT_INT_Z'))
        one('and the table it is emitted beside is the 16-bit one',
            'mba_z16' in open(__file__).read())
        zstream[kc[0]] = stream[kc[0]] | zo3.M('R200_Z_ENABLE')
        zwhy, zmsg = vo.verify(zstream, win_start=win, win_end=win + vo.WIN_BYTES)
        one('gate B: the stream with DEPTH ON passes the verifier (why=%s %s)'
            % (zwhy, zmsg), zwhy == 0)
        one('and turning depth on changes exactly two words',
            sum(1 for a, b in zip(stream, zstream) if a != b) == 2)

    # M1e gate B: the SAME stream with the Gouraud shade value and three
    # different vertex colours must also pass.  Checking it here rather than
    # once by hand is what keeps it true after an edit.
    gstream = list(stream)
    gstream[k[0]] = smooth
    for i, c in enumerate((0xff4020ff, 0x10ff80aa, 0x4020ff55)):
        gstream[len(filled) + 2 + i * 5 + 4] = c
    # ---- M1f: the blend unit
    abe, boff, bon = blend_values()
    kc = [i for i, s in enumerate(slots) if s == SLOT_RB3D_CNTL]
    kb = [i for i, s in enumerate(slots) if s == SLOT_BLENDCNTL]
    one('there is exactly one RB3D_CNTL slot and one BLENDCNTL slot',
        len(kc) == 1 and len(kb) == 1)
    one('the blend-on RB3D_CNTL adds ALPHA_BLEND_ENABLE and nothing else '
        '(0x%08x -> 0x%08x)' % (words[kc[0]], words[kc[0]] | abe),
        bool(kc) and ((words[kc[0]] | abe) ^ words[kc[0]]) == abe)
    one('BLENDCNTL is written even with blending off (the reference requires a '
        'defined value there: 0x%08x)' % boff, bool(kb) and words[kb[0]] == boff)
    one('and the two BLENDCNTL words differ (0x%08x vs 0x%08x)' % (boff, bon),
        boff != bon)

    # the blended stream must pass the verifier too -- gate B
    bstream = list(stream)
    bstream[kc[0]] = words[kc[0]] | abe
    bstream[kb[0]] = bon
    bwhy, bmsg = vo.verify(bstream, win_start=win, win_end=win + vo.WIN_BYTES)
    one('the BLENDED stream passes the verifier oracle (why=%s %s)' % (bwhy, bmsg),
        bwhy == 0)
    one('and it differs from the plain one in exactly two words',
        sum(1 for a, b in zip(stream, bstream) if a != b) == 2)

    gwhy, gmsg = vo.verify(gstream, win_start=win, win_end=win + vo.WIN_BYTES)
    one('and so does the GOURAUD stream, with three different vertex colours '
        '(why=%s %s)' % (gwhy, gmsg), gwhy == 0)
    one('the two streams differ in exactly four words (the shade value and three '
        'colours)',
        sum(1 for a, b in zip(stream, gstream) if a != b) == 4)

    # and a mutation of it does not, so the check above is not vacuous
    bad = list(stream)
    bad[1] |= R200_BITS['R200_Z_ENABLE'] if reg_of(bad[0]) == cntl else 0
    broke = list(stream)
    broke[-1] = 0                                  # a short body
    why2, _ = vo.verify(broke[:-1], win_start=win, win_end=win + vo.WIN_BYTES)
    one('and a truncated body is refused (so the oracle is really judging)', why2 != 0)

    one('the vertex count is what the body says',
        ((body[0] >> 16) & 0xffff) == 3 and (len(body) - 1) == 3 * 5)

    # ---- M1g: the textured prologue, and gate B for it
    tw, ts, (gw, gh, gstride, goff) = tex_template()
    te = sys.modules['tex_oracle']
    one('the textured prologue is whole PKT0 pairs with a slot for every word',
        len(tw) % 2 == 0 and len(ts) == len(tw))
    for nm, sl in (('TXOFFSET', SLOT_TXOFFSET), ('SE_CNTL', SLOT_SE_CNTL),
                   ('RB3D_CNTL', SLOT_RB3D_CNTL), ('BLENDCNTL', SLOT_BLENDCNTL),
                   ('COLOROFFSET', SLOT_COLOROFFSET),
                   ('ZSTENCILCNTL', SLOT_ZSTENCILCNTL)):   # G4-11: was missing, depth never on
        one('the textured prologue has exactly one %s slot' % nm,
            ts.count(sl) == 1)
    # G4-11: every slot the plain table carries on a register the textured table
    # also writes, the textured table carries too -- the two tables are one
    # convention, and a slot added to one only (M1i's depth slot) is the bug
    # this plan fixed.
    preg = dict((reg_of(words[i - 1]), slots[i]) for i in range(1, len(words), 2))
    treg = dict((reg_of(tw[i - 1]), ts[i]) for i in range(1, len(tw), 2))
    shared = [r for r in preg if r in treg and preg[r] != SLOT_LITERAL]
    one('every non-literal slot of the plain table is a slot of the textured table too',
        len(shared) > 0 and all(treg[r] == preg[r] for r in shared))
    # the filter the stream actually carries, read back out of the words -- the
    # classifier accepts GL_REPEAT and only GL_REPEAT, so the hardware must wrap
    txfr = next(r for r, n in REG.items() if n == 'C_PP_TXFILTER_0')
    got_f = [tw[i + 1] for i in range(0, len(tw), 2)
             if (tw[i] & PKT_MASK) == PKT0 and reg_of(tw[i]) == txfr]
    one('the textured prologue sends exactly one PP_TXFILTER_0', len(got_f) == 1)
    one('and it is the WRAP filter (%08x), not XA\'s CLAMP_LAST (%08x) -- the '
        'classifier accepts GL_REPEAT only' % (te.txfilter('wrap'), te.txfilter('clamp')),
        got_f and got_f[0] == te.txfilter('wrap') and
        te.txfilter('wrap') != te.txfilter('clamp'))
    one('the hardware row stride is max(w*4, 32) = %d for this %dx%d texture'
        % (max(gw * 4, 32), gw, gh), max(gw * 4, 32) == 32 and gw == 8)

    tf = list(tw)
    for i, sl in enumerate(ts):
        if sl == SLOT_COLOROFFSET:
            tf[i] = win
        elif sl == SLOT_COLORPITCH:
            tf[i] = 64
        elif sl == SLOT_WIDTH_HEIGHT:
            tf[i] = (63 << 16) | 63
        elif sl == SLOT_TOP_LEFT:
            tf[i] = 0
        elif sl == SLOT_SE_CNTL:
            tf[i] = flat
        elif sl == SLOT_RB3D_CNTL:
            tf[i] = tf[i]                      # the literal is the plain value
        elif sl == SLOT_BLENDCNTL:
            tf[i] = boff
        elif sl == SLOT_TXOFFSET:
            tf[i] = win + goff
        elif sl == SLOT_DEPTHOFFSET:
            tf[i] = win + DEPTH_OFF
        elif sl == SLOT_DEPTHPITCH:
            tf[i] = 64
        elif sl == SLOT_ZSTENCILCNTL:
            tf[i] = tf[i]                      # the literal is depth OFF (M1d)
    tbody = [(te.vf() & 0xffff) | (3 << 16)]
    for (vx, vy), sv, tv in zip([(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)],
                                (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        tbody += [to.fbits(vx), to.fbits(vy), to.fbits(0.5), to.fbits(1.0),
                  0x78563412, to.fbits(sv), to.fbits(tv)]
    tstream = tf + [PKT3 | 0x3500 | ((len(tbody) - 1) << 16)] + tbody
    twhy, tmsg = vo.verify(tstream, win_start=win, win_end=win + vo.WIN_BYTES)
    one('gate B: the filled-in TEXTURED stream passes the verifier (why=%s %s)'
        % (twhy, tmsg), twhy == 0)
    one('and its vertices are seven words each',
        (len(tbody) - 1) == 3 * 7)

    #
    # ---- M1k: the batch bound.  The header carries a number; this asks the
    # VERIFIER where the wall is and checks the number sits exactly under it.
    # A bound that is only computed is a bound nobody measured.
    #
    bmax = vo.BATCH_MAX_WORDS
    kplain = (bmax - len(words) - 2) // (3 * 5)
    ktex = (bmax - len(tw) - 2) // (3 * 7)

    def batch_stream(pro, vwords, k, mk):
        b = [(mk() & 0xffff) | ((3 * k) << 16)]
        for _ in range(k):
            for (vx, vy) in ((4.0, 4.0), (28.0, 4.0), (4.0, 28.0)):
                b += [to.fbits(vx), to.fbits(vy), to.fbits(0.5), to.fbits(1.0),
                      0x78563412]
                if vwords == 7:
                    b += [to.fbits(0.0), to.fbits(0.0)]
        return pro + [PKT3 | 0x3500 | ((len(b) - 1) << 16)] + b

    for nm, pro, vwords, kk, mk in (('plain', filled, 5, kplain,
                                     lambda: to.vf_cntl('T1')),
                                    ('textured', tf, 7, ktex, lambda: te.vf())):
        st = batch_stream(pro, vwords, kk, mk)
        why, msg = vo.verify(st, win_start=win, win_end=win + vo.WIN_BYTES)
        one('gate B: a %s batch of %d triangles (%d words) passes the verifier '
            '(why=%s %s)' % (nm, kk, len(st), why, msg), why == 0)
        st2 = batch_stream(pro, vwords, kk + 1, mk)
        why2, _ = vo.verify(st2, win_start=win, win_end=win + vo.WIN_BYTES)
        one('and ONE MORE (%d words) is refused for the WORD reason (why=%s, '
            'want %s)' % (len(st2), why2, vo.WHY_WORDS), why2 == vo.WHY_WORDS)
    one('the header sizes the arrays for the larger of the two (%d)'
        % max(kplain, ktex), max(kplain, ktex) == kplain)
    #
    # Replay is only correct because the class declines the states that put
    # per-call values in the context.  If a bit ever leaves DD_SW_SETUP_ the
    # batch would keep working and draw the WRONG pixels on a failed flush --
    # so the two bits are checked here, against types.h, not against a memory.
    #
    th = os.path.join(PROJ, '..', 'openstep-mesa342', 'upstream', 'Mesa-3.4.2',
                      'src', 'types.h')
    cc = os.path.join(PROJ, 'mesa', 'OSRDNMesaClass.c')
    if not os.path.exists(th) or not os.path.exists(cc):
        one('types.h and OSRDNMesaClass.c are both readable', False)
    else:
        dd = dict((m.group(1), int(m.group(2), 0)) for m in re.finditer(
            r'#define\s+(DD_[A-Z_0-9]+)\s+(0x[0-9A-Fa-f]+|\d+)',
            open(th, errors='replace').read()))
        # M3b: the mask that is DECLINED, which is no longer DD_SW_SETUP_
        m = re.search(r'#define\s+DD_DECLINE_\s+(0x[0-9A-Fa-f]+)',
                      open(cc).read())
        one('OSRDNMesaClass.c defines DD_DECLINE_', m is not None)
        if m:
            sw = int(m.group(1), 0)
            for bit in ('DD_TRI_OFFSET', 'DD_TRI_LIGHT_TWOSIDE'):
                one('%s (%#x) is inside DD_DECLINE_ (%#x) -- replay depends on '
                    'the class declining it' % (bit, dd.get(bit, 0), sw),
                    bit in dd and (sw & dd[bit]) == dd[bit] and dd[bit] != 0)

    print('gen_tri_prologue self-test: %s'
          % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


def main():
    if '--self-test' in sys.argv:
        return 1 if self_test() else 0
    if '--check' in sys.argv:
        # A generated file that has drifted from its generator is worse than no
        # generated file: it looks derived and is not.
        text = emit()
        if not os.path.exists(OUT):
            print('gen_tri_prologue --check: FAIL (%s does not exist)'
                  % os.path.relpath(OUT, PROJ))
            return 1
        have = open(OUT).read()
        if have != text:
            a, b = have.split('\n'), text.split('\n')
            k = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]),
                     min(len(a), len(b)))
            print('gen_tri_prologue --check: FAIL (the table is stale, first '
                  'difference at line %d)' % (k + 1))
            print('  on disk:   %s' % (a[k] if k < len(a) else '<end>'))
            print('  generated: %s' % (b[k] if k < len(b) else '<end>'))
            return 1
        print('gen_tri_prologue --check: PASS (%d lines, regenerated identically)'
              % len(text.split('\n')))
        return 0
    text = emit()
    if '--stdout' in sys.argv:
        sys.stdout.write(text)
        return 0
    open(OUT, 'w').write(text)
    print('wrote %s (%d words)' % (os.path.relpath(OUT, PROJ), text.count('0x')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
