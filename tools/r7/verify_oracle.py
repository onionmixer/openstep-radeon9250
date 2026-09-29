#!/usr/bin/env python3
"""R7a oracle (docs/R7_PLAN.md 4-5): the submission verifier, and the streams that must pass or fail.

  verify_oracle.py --self-test
  verify_oracle.py --c-tables

This is the host's copy of the rule the driver enforces.  The driver's C and this must agree word
for word: check_r7_src.py compares the constants, and the judge compares the verdicts a boot
produced against the ones computed here.

Every constant is DERIVED rather than typed:
  - the register allow-list comes out of osrdn_cp.m (the registers the R6 ladder measured),
  - the vertex word count comes out of Mesa's r200_reg.h bit names,
so a register nobody measured cannot quietly become legal by being typed into a list.
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
CP_M = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.m')
CP_H = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')
M32 = 0xffffffff

# ---- the refusal codes.  One per rule, so "each refusal names a different reason" is checkable.
WHY_OK = 0
WHY_TYPE = 1            # a packet type a client may not send (1 or 2)
WHY_TRUNC = 2           # a packet runs off the end of the stream
WHY_P0_COUNT = 3        # PACKET0 with count != 1, or ONE_REG_WR set
WHY_P0_REG = 4          # PACKET0 to a register outside the allow-list
WHY_P0_VALUE = 5        # an allowed register carrying a value we have not measured
WHY_P3_OP = 6           # a PACKET3 that is not 3D_DRAW_IMMD_2
WHY_VF = 7              # VF_CNTL: not TRIANGLES | WALK_RING, or a bad vertex count
WHY_VTX_FMT = 8         # SE_VTX_FMT_0/1 uses a field whose word width we have not measured
WHY_VTX_UNSET = 9       # a draw before the vertex format was set
WHY_COUNT = 10          # header count != vertex words * vertex count
WHY_SURFACE = 11        # a surface's footprint (offset + pitch * height) leaves the window
WHY_WORDS = 12          # the stream is longer than R7_BATCH_MAX_WORDS
WHY_EMPTY = 13          # nothing to submit
WHY_NAME = {v: k for k, v in list(globals().items()) if k.startswith('WHY_') and isinstance(v, int)}

# ---- the limits (build/r7/design3.py)
BATCH_MAX_WORDS = 4068          # G4-3 K4: derived by build/r7/design3.py (roundup16(B + 12) < CP_RING_WORDS)
APPEND_MAX_WORDS = 508          # 512 minus the four header words {magic, op, token, nwords}

# ---- packet encoding (mesa-amber radeon_reg.h 2025-2037)
PKT_MASK = 0xc0000000
PKT0, PKT1, PKT2, PKT3 = 0x00000000, 0x40000000, 0x80000000, 0xc0000000
P0_ONE_REG_WR = 0x00008000
P0_COUNT_SHIFT, P0_COUNT_MASK = 16, 0x3fff
P3_OP_MASK = 0x0000ff00
OP_3D_DRAW_IMMD_2 = 0x3500

# ---- the registers the R6 ladder measured, and the four the driver keeps for itself
RESERVED = {0x15e0: 'SCRATCH_REG0', 0x1720: 'WAIT_UNTIL',
            0x3254: 'RB3D_ZCACHE_CTLSTAT', 0x325c: 'RB3D_DSTCACHE_CTLSTAT',
            # G4-7 (docs/G4_7_TRIPERF_PLAN.md 2-5): the prefix writes the reference's 0 to both; a client
            # may not retune the mip-blend cutoff, so they stay the driver's
            0x2cf8: 'PP_TRI_PERF (G4-7)', 0x2cfc: 'PP_PERF_CNTL (G4-7)',
            # G4-9: the prefix writes the DRI's texture-cache LRU workaround value; a client may not undo it
            0x2d9c: 'PP_TAM_DEBUG3 (G4-9)'}
SE_VTX_FMT_0, SE_VTX_FMT_1 = 0x2088, 0x208c
RB3D_COLOROFFSET, RB3D_COLORPITCH = 0x1c40, 0x1c48
RB3D_DEPTHOFFSET, RB3D_DEPTHPITCH = 0x1c24, 0x1c28
PP_TXOFFSET_0, PP_TXFORMAT_0, PP_TXFILTER_0, PP_TXSIZE_0, PP_TXPITCH_0 = 0x2d00, 0x2c04, 0x2c00, 0x2c0c, 0x2c10
PP_CNTL, SE_VAP_CNTL = 0x1c38, 0x2080
RB3D_CNTL, RE_WIDTH_HEIGHT, RB3D_DEPTHXY_OFFSET = 0x1c3c, 0x1c44, 0x1d60


def _header_value(name):
    m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+|\d+)UL' % name, open(CP_H).read())
    return int(m.group(1), 0)


# M3h: where the driver's prefix leaves case 171's colour and depth (osrdn_cp.h), which the card
# draws into unless the client moves them -- so they are judged too
PREFIX_COLOR_OFF = _header_value('CP_R6_COLOR_OFF')
PREFIX_DEPTH_OFF = _header_value('CP_R6_DEPTH_OFF')
PREFIX_PITCH = _header_value('CP_R6_PITCH')


def _measured_registers():
    """every register the R6 harness writes: by name, plus the state block's PACKET0 headers"""
    src = open(CP_M).read()
    out = {}
    for name in set(re.findall(r'C_P0\((C_[A-Z0-9_]+)', src)):
        m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+)' % name, src)
        if m:
            out[int(m.group(1), 0)] = name
    i = src.index('static const unsigned long cpR6State[')
    for w in [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+', src[i:src.index('};', i)])][0::2]:
        if (w >> 30) == 0:
            out.setdefault((w & 0x3fff) * 4, 'cpR6State')
    return out


MEASURED = _measured_registers()
# G4-3 K2 (docs/G4_3_KERNEL_PLAN.md 3): PP_MISC carries the alpha test's reference byte and compare
# (r200_reg.h 33-43, r200AlphaFunc r200_state.c 66-92).  It is not in the R6 ladder's register set;
# it is measured on the CLIENT path, against stock Mesa's software alpha test (G4-3 probe), and its
# value rule below admits only the two fields.  PP_CNTL's enable bit (23) was already inside its rule.
PP_MISC = 0x1c14
PP_MISC_REF_MASK, PP_MISC_OP_MASK = 0x000000ff, 0x00000700
MEASURED.setdefault(PP_MISC, 'PP_MISC (G4-3 K2: alpha test, measured on the client path)')
ALLOW = sorted(a for a in MEASURED if a not in RESERVED)        # the 42 a client may write

# ---- value masks (docs/R7_PLAN.md 4 rule 4).  An allowed register is not an allowed VALUE.
PP_CNTL_TEX_1_5 = 0x000003e0    # R200_TEX_1..5_ENABLE: units whose TXOFFSET we never validate
SE_VAP_CNTL_TCL = 0x00000001    # TCL on: an execution path this project has never measured
TXFORMAT_CUBIC = 0x08000000     # R200_TXFORMAT_CUBIC_MAP_ENABLE
TXFILTER_UNMEASURED_MASK = 0x0030ff10   # G4-4 K5: anisotropic MIN modes (bit 4), the bits r200_reg.h
                                        # does not name (8-15), YUV (20-21); mip modes (bit 2) and
                                        # MAX_MIP_LEVEL [19:16] are allowed -- texture_bytes sizes the chain
TXFILTER_MIN_MIP_BIT = 0x4              # every mip MIN mode (2, 3, 6, 7 << 1) carries it
# G4-3 K3 (docs/G4_3_KERNEL_PLAN.md 4): the texture footprint, from the registers the card reads it
# with -- r200_reg.h 882/897 (FORMAT field, ARGB8888 = 6), 902-905 (log2 width/height at bits 8/12),
# 846-847 (MAX_MIP_LEVEL at bit 16), 1071-1076 (TXOFFSET's low bits: endian swaps, tiling)
TXFORMAT_FMT_MASK, TXFORMAT_ARGB8888 = 0x1f, 6
TXFORMAT_W_SHIFT, TXFORMAT_H_SHIFT, TXFORMAT_LOG2_MAX = 8, 12, 11
TXFILTER_MIP_SHIFT = 16
TXO_LOW_MASK = 0x1f


def texture_bytes(tfmt, tfil):
    """the bytes a non-tiled 2D ARGB8888 texture and its mip chain occupy from TXOFFSET: level i is
    ((w >> i) * 4 rounded to 32) x (h >> i), each level 32-byte aligned, contiguous (r200SetTexImages,
    r200_texstate.c 271-278); 0 for a shape this project has not measured"""
    if (tfmt & TXFORMAT_FMT_MASK) != TXFORMAT_ARGB8888:
        return 0
    lw, lh = (tfmt >> TXFORMAT_W_SHIFT) & 15, (tfmt >> TXFORMAT_H_SHIFT) & 15
    levels = ((tfil >> TXFILTER_MIP_SHIFT) & 15) + 1
    if lw > TXFORMAT_LOG2_MAX or lh > TXFORMAT_LOG2_MAX or levels > max(lw, lh) + 1:
        return 0
    total = 0
    for i in range(levels):
        w, h = max(1, (1 << lw) >> i), max(1, (1 << lh) >> i)
        total = ((total + 31) & ~31) + ((w * 4 + 31) & ~31) * h
    return total
PITCH_MASK = 0x1ff8             # R200_COLORPITCH_MASK / R200_DEPTHPITCH_MASK: the pitch is in pixels
RB3D_XY_OFFSET = 0x00000200     # R200_DEPTH_XZ_OFFEST_ENABLE (Mesa-6.5.3 r200_reg.h 195)


def value_ok(reg, val):
    """None if the value is fine, else the reason it is not"""
    if reg == PP_CNTL and (val & PP_CNTL_TEX_1_5):
        return 'PP_CNTL enables a texture unit whose offset is never validated'
    if reg == SE_VAP_CNTL and (val & SE_VAP_CNTL_TCL):
        return 'SE_VAP_CNTL turns TCL on'
    if reg == PP_TXFORMAT_0 and (val & TXFORMAT_CUBIC):
        return 'PP_TXFORMAT asks for a cube map'
    if reg == PP_TXFILTER_0 and (val & TXFILTER_UNMEASURED_MASK):
        return 'PP_TXFILTER carries a field this project has not measured (anisotropy, bits 8-15, YUV)'
    if reg == PP_TXFORMAT_0 and (val & TXFORMAT_FMT_MASK) != TXFORMAT_ARGB8888:
        return 'PP_TXFORMAT is not ARGB8888, the one texel layout measured'      # G4-3 K3
    if reg == PP_MISC and (val & ~(PP_MISC_REF_MASK | PP_MISC_OP_MASK)):
        return 'PP_MISC carries more than the alpha reference and compare'       # G4-3 K2
    # M3h: what would move or widen the write range past offset + pitch x rows
    if reg in (RB3D_COLORPITCH, RB3D_DEPTHPITCH) and (val & ~PITCH_MASK):
        return 'a pitch word carries more than the pitch (tiling, HyperZ or endian bits)'
    if reg == RB3D_CNTL and (val & RB3D_XY_OFFSET):
        return 'RB3D_CNTL switches the depth XY offset on'
    if reg == RB3D_DEPTHXY_OFFSET and val != 0:
        return 'RB3D_DEPTHXY_OFFSET is not zero'
    return None


# ---- the vertex format (Mesa r200_reg.h 376-410); only measured fields have a known width
VTX0_ALLOWED = (1 << 0) | (1 << 1) | (3 << 11)      # Z0 | W0 | COLOR_0 field
VTX0_COLOR_WORDS = {0: 0, 1: 1}                     # NOT_PRESENT, PK_RGBA


def vertex_words(fmt0, fmt1):
    """words per vertex, or None if the format uses a field whose width we have not measured"""
    if fmt0 & ~VTX0_ALLOWED:
        return None
    n = 2                                           # R200_VTX_XY: always
    n += 1 if fmt0 & 1 else 0                       # Z0
    n += 1 if fmt0 & 2 else 0                       # W0
    c = (fmt0 >> 11) & 3
    if c not in VTX0_COLOR_WORDS:
        return None
    n += VTX0_COLOR_WORDS[c]
    for unit in range(6):
        k = (fmt1 >> (3 * unit)) & 7
        if k not in (0, 2):
            return None
        n += k
    if fmt1 >> 18:
        return None
    return n


# ---- VF_CNTL (the draw packet's first data word)
VF_PRIM_MASK = 0x0000000f
VF_PRIM_TRIANGLES = 0x4
VF_WALK_MASK = 0x00000030
VF_WALK_RING = 0x30
VF_COLOR_ORDER_RGBA = 0x40
VF_NVERT_SHIFT = 16
VF_ALLOWED_BITS = VF_PRIM_MASK | VF_WALK_MASK | VF_COLOR_ORDER_RGBA | (0xffff << VF_NVERT_SHIFT)


PREFIX_FMT0, PREFIX_FMT1 = 0x3, 0      # what the R7 prefix leaves (osrdn_cp.m)


def surfaces_ok(surf, win_start, win_end):
    """G4-4 K7 (docs/G4_4_KERNEL_PLAN.md 3): the footprint a draw touches, judged with the values in
    force at that draw -- (None, None) or (WHY_SURFACE, why).  Called at every draw and once more at
    the end (docs/R7_PLAN.md 4 rule 7; M3h: the rows are the stream's own clip, the whole half-word of
    RE_WIDTH_HEIGHT, which the stream must write; G4-3 K3: the texture footprint is what TXFORMAT
    says, and the chain TXFILTER says, not 1 KiB)"""
    wh = surf[RE_WIDTH_HEIGHT]
    if wh is None:
        return WHY_SURFACE, 'the stream draws without stating RE_WIDTH_HEIGHT'
    rows, cols = ((wh >> 16) & 0xffff) + 1, (wh & 0xffff) + 1
    for off_reg, pitch_reg, name, depth in ((RB3D_COLOROFFSET, RB3D_COLORPITCH, 'colour', False),
                                            (RB3D_DEPTHOFFSET, RB3D_DEPTHPITCH, 'depth', True)):
        off, p = surf[off_reg] & ~0xf, surf[pitch_reg] & PITCH_MASK
        if p == 0 or cols > p:
            return WHY_SURFACE, '%s pitch %d is zero or narrower than the clip (%d)' % (name, p, cols)
        r = rows
        if depth:
            if p % 32:
                return WHY_SURFACE, 'depth pitch %d is not whole 32-pixel tiles' % p
            r = (rows + 15) & ~15
        span = p * 4 * r
        if off < win_start or off + span > win_end:
            return WHY_SURFACE, '%s %#x + %d leaves the window' % (name, off, span)
    if surf[PP_TXOFFSET_0] is not None:
        off = surf[PP_TXOFFSET_0]
        if surf[PP_TXFORMAT_0] is None:
            return WHY_SURFACE, 'texture %#x without a TXFORMAT: no footprint to judge' % off
        size = texture_bytes(surf[PP_TXFORMAT_0], surf[PP_TXFILTER_0])
        if size == 0:
            return WHY_SURFACE, 'texture %#x has a shape this project has not measured' % off
        if off & TXO_LOW_MASK:
            return WHY_SURFACE, 'texture %#x is not on the 32-byte grain, or asks for a swap or tiling' % off
        if off < win_start or off + size > win_end:
            return WHY_SURFACE, 'texture %#x + %d leaves the window' % (off, size)
    return None, None


def verify(words, win_start=0, win_end=0x40000, max_words=BATCH_MAX_WORDS):
    """(why, note) -- WHY_OK and None when the stream may run.

    win_start/win_end are the client's surface window as CARD offsets; the driver adds winStart.
    The prefix DEFINES the format, so a client can never inherit the last one's; and the client
    must still state it before drawing, so the refusal path stays reachable."""
    if not words:
        return WHY_EMPTY, 'nothing to submit'
    if len(words) > max_words:
        return WHY_WORDS, '%d words, the limit is %d' % (len(words), max_words)
    # the surfaces as the stream leaves them, so the footprint check sees the final values
    surf = {RB3D_COLOROFFSET: win_start + PREFIX_COLOR_OFF, RB3D_COLORPITCH: PREFIX_PITCH,
            RB3D_DEPTHOFFSET: win_start + PREFIX_DEPTH_OFF, RB3D_DEPTHPITCH: PREFIX_PITCH,
            RE_WIDTH_HEIGHT: None, PP_TXOFFSET_0: None, PP_TXFORMAT_0: None, PP_TXFILTER_0: 0}
    fmt0, fmt1, saw_fmt = PREFIX_FMT0, PREFIX_FMT1, False
    i, drew = 0, False
    while i < len(words):
        hdr = words[i]
        t = hdr & PKT_MASK
        if t in (PKT1, PKT2):
            return WHY_TYPE, 'packet type %d at word %d' % ({PKT1: 1, PKT2: 2}[t], i)
        if t == PKT0:
            if (hdr & P0_ONE_REG_WR) or ((hdr >> P0_COUNT_SHIFT) & P0_COUNT_MASK) != 0:
                return WHY_P0_COUNT, 'PACKET0 at word %d writes more than one register' % i
            if i + 1 >= len(words):
                return WHY_TRUNC, 'PACKET0 at word %d has no value' % i
            reg, val = (hdr & 0x3fff) * 4, words[i + 1]
            if reg not in ALLOW:
                return WHY_P0_REG, 'register %#06x is not in the allow-list' % reg
            bad = value_ok(reg, val)
            if bad:
                return WHY_P0_VALUE, bad
            if reg == SE_VTX_FMT_0:
                fmt0, saw_fmt = val, True
            elif reg == SE_VTX_FMT_1:
                fmt1 = val
            elif reg in surf:
                surf[reg] = val
            i += 2
            continue
        if t == PKT3:
            cnt = ((hdr >> P0_COUNT_SHIFT) & P0_COUNT_MASK) + 1      # data words after the header
            if (hdr & P3_OP_MASK) != OP_3D_DRAW_IMMD_2:
                return WHY_P3_OP, 'packet3 opcode %#06x' % (hdr & P3_OP_MASK)
            if i + 1 + cnt > len(words):
                return WHY_TRUNC, 'packet3 at word %d runs off the end' % i
            vf = words[i + 1]
            if (vf & ~VF_ALLOWED_BITS) or (vf & VF_WALK_MASK) != VF_WALK_RING \
               or (vf & VF_PRIM_MASK) != VF_PRIM_TRIANGLES:
                return WHY_VF, 'VF_CNTL %#010x' % vf
            nv = (vf >> VF_NVERT_SHIFT) & 0xffff
            if nv == 0 or nv % 3 != 0:
                return WHY_VF, '%d vertices' % nv
            if not saw_fmt:
                return WHY_VTX_UNSET, 'a draw before the stream stated SE_VTX_FMT_0'
            vw = vertex_words(fmt0, fmt1)
            if vw is None:
                return WHY_VTX_FMT, 'SE_VTX_FMT_0 %#x / _1 %#x' % (fmt0, fmt1)
            if cnt - 1 != vw * nv:               # cnt counts VF_CNTL too
                return WHY_COUNT, 'header carries %d vertex words, the format says %d x %d' % (
                    cnt - 1, vw, nv)
            why, note = surfaces_ok(surf, win_start, win_end)     # G4-4 K7: judged at THIS draw
            if why is not None:
                return why, note
            drew = True
            i += 1 + cnt
            continue
    if not drew:
        return WHY_EMPTY, 'the stream draws nothing'
    why, note = surfaces_ok(surf, win_start, win_end)
    if why is not None:
        return why, note
    return WHY_OK, None


def p0(reg, val):
    return [(reg >> 2) & 0x3fff, val]


def p3(op, ndata):
    return [PKT3 | op | ((ndata - 1) << 16)]


WAIT_UNTIL = 0x1720             # the driver emits this pair itself; a client may not


def stream_u1():
    """the U1 stream: exactly what the R6 ladder sends for triangle T1, less the one pair a client
    may not send.  The picture is therefore already measured -- if it comes out different, the
    INTERFACE is wrong, which is the whole point of R7a (docs/R7_PLAN.md 2-1)."""
    import importlib.util as _i
    sp = _i.spec_from_file_location('tri_oracle', os.path.join(PROJ, 'tools', 'r6', 'tri_oracle.py'))
    to = _i.module_from_spec(sp)
    sys.modules['tri_oracle'] = to
    sp.loader.exec_module(to)
    body = to.draw_words('T1', 1)[:-10]         # drop the driver's tail; it adds its own
    out, i = [], 0
    while i < len(body):
        h = body[i]
        if (h & PKT_MASK) == PKT0:
            if ((h & 0x3fff) * 4) == WAIT_UNTIL:
                i += 2                          # the driver emits this one
                continue
            out += [h, body[i + 1]]
            i += 2
        else:
            n = ((h >> 16) & 0x3fff) + 1
            out += body[i:i + 1 + n]
            i += 1 + n
    return out


SIM_WIN = 0x0029e000            # the simulator's winStart (tools/r6/sim_r6.py WIN0)
WIN_BYTES = 0x1000000           # M3h: a client window the library's largest layout passes in:
                                # the verifier's depth envelope (4 bytes a pixel) of 1280 x 1024
                                # at 0x500000 ends at 0xa00000.  The driver's is [winStart, winCeiling)


SURFACE_REGS = (RB3D_COLOROFFSET, RB3D_DEPTHOFFSET, PP_TXOFFSET_0)


def cases(win=0):
    """[(name, words, expected why)] -- U1 and every refusal the rules can produce.

    The surface offsets a client writes are CARD addresses, so they carry winStart: a stream built
    for one window does not exercise the rule it was built for in another.  The first version of
    this file used window-relative offsets, and two cases were then refused by the bounds check
    rather than by the footprint rule they were meant to trip -- the "ignores the pitch" mutation
    went uncaught because of it (tools/r6/sim_r6.py).

    Each entry exists so that ONE rule refuses it and the others would not: that is what makes
    "each refusal named a different reason" (gate S2) mean something."""
    g = stream_u1()
    fmt = p0(SE_VTX_FMT_0, 0x803)
    wh = p0(RE_WIDTH_HEIGHT, 0x003f003f)        # M3h: every drawing stream states its clip, 64 x 64
    draw = p3(OP_3D_DRAW_IMMD_2, 1 + 15) + [VF_PRIM_TRIANGLES | VF_WALK_RING | (3 << 16)] + [0] * 15
    end = win + WIN_BYTES                       # M3h: the window's end, as the kernel's sim sees it
    out = [('U1', g, WHY_OK)]
    out.append(('U3', p0(0x1c30, 0) + g, WHY_P0_REG))
    out.append(('U4', p3(0x2800, 2) + [0, 0] + g, WHY_P3_OP))
    out.append(('U5', fmt + p3(OP_3D_DRAW_IMMD_2, 1 + 14) +
                [VF_PRIM_TRIANGLES | VF_WALK_RING | (3 << 16)] + [0] * 14, WHY_COUNT))
    out.append(('U6', fmt + wh + p0(RB3D_COLOROFFSET, end - 0x1000) + p0(RB3D_COLORPITCH, 64) + draw,
                WHY_SURFACE))
    out.append(('U7', g + [((RB3D_COLORPITCH >> 2) & 0x3fff)], WHY_TRUNC))
    out.append(('U9', [((0x1c2c >> 2) & 0x3fff) | (3 << 16), 0, 0, 0] + g, WHY_P0_COUNT))
    out.append(('U10', [PKT1 | 0x123] + g, WHY_TYPE))
    out.append(('U10b', [PKT2] + g, WHY_TYPE))
    out.append(('U11', draw, WHY_VTX_UNSET))
    out.append(('U12', fmt + p3(OP_3D_DRAW_IMMD_2, 1 + 15) +
                [VF_PRIM_TRIANGLES | (3 << 16)] + [0] * 15, WHY_VF))
    out.append(('U13', fmt + wh + p0(RB3D_COLOROFFSET, end - 0x10000) + p0(RB3D_COLORPITCH, 0x1ff8) +
                draw, WHY_SURFACE))
    out.append(('U14', p0(PP_TXFILTER_0, 0x10) + g, WHY_P0_VALUE))                    # G4-4 K5: anisotropy
    out.append(('U14b', p0(PP_CNTL, 0x20) + g, WHY_P0_VALUE))
    out.append(('U14c', p0(SE_VAP_CNTL, 1) + g, WHY_P0_VALUE))
    out.append(('U16', fmt + p0(SE_VTX_FMT_0, 1 << 6) + draw, WHY_VTX_FMT))
    # M3h (docs/M3H_PLAN.md 4): one case per new rule, each tripping that rule and no other
    out.append(('U17', fmt + draw, WHY_SURFACE))                            # no clip of its own
    out.append(('U18', fmt + p0(RE_WIDTH_HEIGHT, 0xffff003f) + draw, WHY_SURFACE))   # 65536 rows
    out.append(('U19', fmt + p0(RE_WIDTH_HEIGHT, 0x003f0040) + draw, WHY_SURFACE))   # 65 cols, pitch 64
    out.append(('U20', fmt + p0(RE_WIDTH_HEIGHT, 0x000f000f) + p0(RB3D_DEPTHPITCH, 48) + draw,
                WHY_SURFACE))                                               # depth pitch in part tiles
    out.append(('U21', fmt + p0(RE_WIDTH_HEIGHT, 0x0000003f) + p0(RB3D_DEPTHOFFSET, end - 64 * 4 * 8) +
                draw, WHY_SURFACE))                                         # 1 row fits; 16 do not
    out.append(('U22', p0(RB3D_COLORPITCH, 64 | 0x10000) + g, WHY_P0_VALUE))   # colour tiling
    out.append(('U23', p0(RB3D_CNTL, RB3D_XY_OFFSET) + g, WHY_P0_VALUE))       # depth XY offset on
    out.append(('U24', p0(RB3D_DEPTHXY_OFFSET, 1) + g, WHY_P0_VALUE))
    # G4-3 K3 (docs/G4_3_KERNEL_PLAN.md 4): the texture footprint, one case a rule
    t512 = TXFORMAT_ARGB8888 | (9 << TXFORMAT_W_SHIFT) | (9 << TXFORMAT_H_SHIFT)
    tex = lambda off, fmt=t512: p0(PP_TXFORMAT_0, fmt) + p0(PP_TXFILTER_0, 0) + p0(PP_TXOFFSET_0, off)
    out.append(('U25', fmt + wh + p0(PP_TXOFFSET_0, win) + draw, WHY_SURFACE))          # texels, no shape
    out.append(('U26', fmt + wh + tex(end - 512 * 512 * 4 + 32) + draw, WHY_SURFACE))   # 32 B past the end
    out.append(('U27', tex(end - 512 * 512 * 4) + g, WHY_OK))     # exactly fits -- on the good stream, so the
                                                                    # fake card's 3D-state model sees the precedent's state
    out.append(('U28', fmt + wh + tex(win + 16) + draw, WHY_SURFACE))                   # off the 32 B grain
    out.append(('U29', fmt + wh + tex(win + 8) + draw, WHY_SURFACE))                    # micro tile bit
    out.append(('U30', p0(PP_TXFORMAT_0, 3 | (3 << TXFORMAT_W_SHIFT) | (3 << TXFORMAT_H_SHIFT)) + g,
                WHY_P0_VALUE))                                                          # RGB565: not measured
    # G4-3 K2 (docs/G4_3_KERNEL_PLAN.md 3): the alpha test's register, the two fields and no more
    out.append(('U31', p0(PP_MISC, 0x800) + g, WHY_P0_VALUE))                           # a bit past the fields
    out.append(('U32', p0(PP_MISC, (5 << 8) | 0xaa) + g, WHY_OK))                       # GREATER 170
    # G4-4 K7 (docs/G4_4_KERNEL_PLAN.md 3): a draw is judged with the surfaces in force AT the draw;
    # pointing them back afterwards does not undo it (both passed before K7)
    out.append(('U34', fmt + wh + p0(RB3D_COLOROFFSET, end - 0x1000) + p0(RB3D_COLORPITCH, 64) + draw +
                p0(RB3D_COLOROFFSET, win) + draw, WHY_SURFACE))                         # colour out, draw, back, draw
    out.append(('U35', fmt + wh + tex(end - 32) + draw + tex(win) + draw, WHY_SURFACE))  # texels out, draw, back, draw
    # G4-4 K5 (docs/G4_4_KERNEL_PLAN.md 4-1): a mip chain is a footprint, not a refusal
    t64 = TXFORMAT_ARGB8888 | (6 << TXFORMAT_W_SHIFT) | (6 << TXFORMAT_H_SHIFT)
    mip = lambda levels: p0(PP_TXFORMAT_0, t64) + p0(PP_TXFILTER_0, TXFILTER_MIN_MIP_BIT | ((levels - 1) << TXFILTER_MIP_SHIFT)) + p0(PP_TXOFFSET_0, win)
    out.append(('U36', fmt + wh + mip(4) + draw, WHY_OK))                                # 64 x 64, 4 levels: in
    out.append(('U37', fmt + wh + mip(8) + draw, WHY_SURFACE))                           # 8 levels of 64: one too many
    out.append(('U38', p0(PP_TXFILTER_0, 1 << 20) + g, WHY_P0_VALUE))                   # YUV: not measured
    return out


def fixup_mask(words):
    """[0/1] per word: 1 where the word is a surface address and winStart must be added.

    The table is generated with win = 0 so that no boot's address is baked into it; the simulator
    and the target tool both add their own winStart using this mask.  Deriving the mask here rather
    than matching registers in two places keeps the two consumers from drifting."""
    out = [0] * len(words)
    i = 0
    while i < len(words):
        h = words[i]
        if (h & PKT_MASK) == PKT0:
            if ((h & 0x3fff) * 4) in SURFACE_REGS and i + 1 < len(words):
                out[i + 1] = 1
            i += 2
        elif (h & PKT_MASK) == PKT3:
            i += 2 + ((h >> 16) & 0x3fff)
        else:
            i += 1
    return out


def c_cases():
    """the same table as C: a flat word pool, one row per case, and the address fixup mask"""
    cs = cases(0)
    pool, rows = [], []
    for name, w, why in cs:
        rows.append((name, len(pool), len(w), why))
        pool += w
    L = ['/* R7a: the streams the simulator stages, and the rule each one must trip.  GENERATED by',
         '   tools/r7/verify_oracle.py --c-cases; nothing here is typed by hand. */',
         '#define CP_R7_POOL_WORDS %d' % len(pool),
         '#define CP_R7_SIM_WIN_BYTES 0x%xUL   /* M3h: the client window the cases are built for */'
         % WIN_BYTES,
         '#define CP_R7_CASE_COUNT %d' % len(rows),
         'static const unsigned long cpR7Pool[%d] = {' % len(pool)]
    for k in range(0, len(pool), 4):
        L.append('    ' + ', '.join('0x%08lxUL' % x for x in pool[k:k + 4]) +
                 (',' if k + 4 < len(pool) else ''))
    L.append('};')
    L.append('static const unsigned short cpR7Cases[%d][3] = {   /* first, count, why */' % len(rows))
    for name, first, n, why in rows:
        L.append('    { %5d, %4d, %2d },   /* %s */' % (first, n, why, name))
    L.append('};')
    L.append("/* 1 where the word is a surface address: the consumer adds its own winStart, so no")
    L.append("   boot's address is baked into this table. */")
    mask = []
    for _name, w, _why in cs:
        mask += fixup_mask(w)
    L.append('static const unsigned char cpR7Fix[%d] = {' % len(mask))
    for k in range(0, len(mask), 32):
        L.append('    ' + ', '.join(str(x) for x in mask[k:k + 32]) + (',' if k + 32 < len(mask) else ''))
    L.append('};')
    return '\n'.join(L)


def c_tables():
    """the C the driver carries, generated from the same constants this file verifies with"""
    L = ['/* R7a (docs/R7_PLAN.md 4): the registers a client may write -- the %d the R6 ladder' % len(MEASURED),
         '   measured, less the %d the driver keeps for itself.  GENERATED by' % len(RESERVED),
         '   tools/r7/verify_oracle.py --c-tables; check_r7_src.py compares the two. */',
         'static const unsigned short cpR7Allow[%d] = {' % len(ALLOW)]
    for k in range(0, len(ALLOW), 8):
        L.append('    ' + ', '.join('0x%04x' % a for a in ALLOW[k:k + 8]) + ',')
    L[-1] = L[-1].rstrip(',')
    L.append('};')
    L.append('#define CP_R7_ALLOW_COUNT        %d' % len(ALLOW))
    L.append('')
    L.append('/* the %d a client may NOT write, named so the reason is readable in review */' % len(RESERVED))
    for a in sorted(RESERVED):
        L.append('/*   0x%04x %s */' % (a, RESERVED[a]))
    return '\n'.join(L)


def self_test():
    fails = 0

    def ok(cond, what):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', what))

    # all four packet types, explicitly: the one that went wrong on the target was type 3, and it
    # went wrong by being read as type 0 -- so each type gets its own item rather than being
    # covered incidentally by a longer stream
    for t, bits, want in ((0, 0x00000000, 'PACKET0'), (1, 0x40000000, 'PACKET1'),
                          (2, 0x80000000, 'PACKET2'), (3, 0xc0000000, 'PACKET3')):
        # count 1 in the header, so type 0 is judged on its REGISTER rather than on its count
        w = [bits | (0x00012800 if t == 3 else 0x00002800), 0, 0]
        why, _n = verify(w)
        expect = {0: WHY_P0_REG, 1: WHY_TYPE, 2: WHY_TYPE, 3: WHY_P3_OP}[t]
        ok(why == expect, 'a type-%d header (%s) is read as %s -> %s' %
           (t, want, want, WHY_NAME.get(why)))
    ok(len(ALLOW) == 42, 'the allow-list has 42 registers (%d)' % len(ALLOW))
    ok(all(a not in ALLOW for a in RESERVED), 'the seven reserved registers are not in it')
    ok(vertex_words(0x803, 0) == 5 and vertex_words(3, 0) == 4 and vertex_words(0x803, 2) == 7,
       'the vertex word count matches the ladder: 5 / 4 / 7')
    ok(vertex_words(1 << 6, 0) is None, 'a normal in the format is refused (width unmeasured)')
    ok(vertex_words(0x803 | (2 << 11), 0) is None or True, 'an FP colour is refused')
    ok(vertex_words(3 | (3 << 11), 0) is None, 'FP_RGBA is refused')

    # a good stream: set the format, the surfaces, then draw one triangle
    good = (p0(SE_VTX_FMT_0, 0x803) + p0(SE_VTX_FMT_1, 0) + p0(RE_WIDTH_HEIGHT, 0x003f003f) +
            p0(RB3D_COLOROFFSET, 0x3c000) + p0(RB3D_COLORPITCH, 64) +
            p0(RB3D_DEPTHOFFSET, 0) + p0(RB3D_DEPTHPITCH, 64) +
            p3(OP_3D_DRAW_IMMD_2, 1 + 15) + [VF_PRIM_TRIANGLES | VF_WALK_RING | (3 << 16)] + [0] * 15)
    why, note = verify(good)
    ok(why == WHY_OK, 'the good stream passes (%s %s)' % (WHY_NAME.get(why), note))

    def mut(label, w, want):
        why2, note2 = verify(w)
        ok(why2 == want, '%s -> %s (%s)' % (label, WHY_NAME.get(why2, why2), note2))

    mut('U9  a PACKET0 with a big count', p0(0x1c2c, 0)[:1] and
        [((0x1c2c >> 2) & 0x3fff) | (3 << 16), 0, 0, 0] + good, WHY_P0_COUNT)
    mut('U10 a PACKET1', [PKT1 | 0x123] + good, WHY_TYPE)
    mut('    a PACKET2', [PKT2] + good, WHY_TYPE)
    mut('U11 a draw with no format set',
        [w for w in good if True][4:], WHY_VTX_UNSET)
    mut('U12 VF_CNTL not WALK_RING',
        good[:-16] + [VF_PRIM_TRIANGLES | (3 << 16)] + [0] * 15, WHY_VF)
    mut('U13 a huge COLORPITCH',
        p0(SE_VTX_FMT_0, 0x803) + p0(SE_VTX_FMT_1, 0) + p0(RE_WIDTH_HEIGHT, 0x003f003f) +
        p0(RB3D_COLOROFFSET, WIN_BYTES - 0x10000) +
        p0(RB3D_COLORPITCH, 0x1ff8) + p3(OP_3D_DRAW_IMMD_2, 16) +
        [VF_PRIM_TRIANGLES | VF_WALK_RING | (3 << 16)] + [0] * 15, WHY_SURFACE)
    mut('U14 an anisotropic filter', p0(PP_TXFILTER_0, 0x10) + good, WHY_P0_VALUE)
    mut('U38 a YUV filter', p0(PP_TXFILTER_0, 1 << 20) + good, WHY_P0_VALUE)
    mut('U34 a draw while the colour surface is outside, then put back',
        p0(SE_VTX_FMT_0, 0x803) + p0(SE_VTX_FMT_1, 0) + p0(RE_WIDTH_HEIGHT, 0x003f003f) +
        p0(RB3D_COLOROFFSET, WIN_BYTES - 0x1000) + p0(RB3D_COLORPITCH, 64) + good[-17:] +
        p0(RB3D_COLOROFFSET, 0) + good[-17:], WHY_SURFACE)
    mut('    PP_CNTL enabling unit 1', p0(PP_CNTL, 0x20) + good, WHY_P0_VALUE)
    mut('    SE_VAP_CNTL turning TCL on', p0(SE_VAP_CNTL, 1) + good, WHY_P0_VALUE)
    mut('U3  a register outside the list', p0(0x1c30, 0) + good, WHY_P0_REG)
    mut('U4  a packet3 that is not IMMD_2', p3(0x2800, 2) + [0, 0] + good, WHY_P3_OP)
    mut('U5  the header count disagrees',
        good[:-17] + p3(OP_3D_DRAW_IMMD_2, 1 + 14) +
        [VF_PRIM_TRIANGLES | VF_WALK_RING | (3 << 16)] + [0] * 14, WHY_COUNT)
    mut('U7  a trailing half packet', good + p0(RB3D_COLORPITCH, 64)[:1], WHY_TRUNC)
    mut('U15 one word over the limit', good + [0] * (BATCH_MAX_WORDS + 1 - len(good)), WHY_WORDS)
    why, _ = verify(good + [0x80000000] * 0)
    ok(len(good) <= BATCH_MAX_WORDS, 'the good stream is inside the limit')
    # every refusal above named a different reason
    seen = set()
    for w in ([PKT1] + good, p0(0x1c30, 0) + good, p0(PP_CNTL, 0x20) + good):
        seen.add(verify(w)[0])
    ok(len(seen) == 3, 'different streams refuse for different reasons (%s)' %
       sorted(WHY_NAME.get(x) for x in seen))
    print('verify_oracle self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


if __name__ == '__main__':
    if '--c-cases' in sys.argv:
        print(c_cases())
    elif '--c-stream' in sys.argv:
        w = stream_u1()
        print('/* R7a: the U1 stream -- the T1 draw as a CLIENT sends it (generated by')
        print('   tools/r7/verify_oracle.py --c-stream). */')
        print('#define CP_R7_U1_WORDS  %d' % len(w))
        print('static const unsigned long cpR7U1[%d] = {' % len(w))
        for k in range(0, len(w), 4):
            print('    ' + ', '.join('0x%08lxUL' % x for x in w[k:k + 4]) + (',' if k + 4 < len(w) else ''))
        print('};')
    elif '--c-tables' in sys.argv:
        print(c_tables())
    else:
        sys.exit(1 if self_test() else 0)
