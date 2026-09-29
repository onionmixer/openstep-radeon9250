#!/usr/bin/env python3
"""The present blit the driver must put on the ring, written from the reference
and NOT from osrdn_cp.m (docs/G3_PRESENT_PLAN.md 2-4).

radeon_cp_dispatch_swap (FreeBSD radeon_state.c 1343-1400) per box:
    WAIT_UNTIL_3D_IDLE                       -> PACKET0(WAIT_UNTIL,0), 3D_IDLECLEAN|HOST_IDLECLEAN
    PACKET0(DP_GUI_MASTER_CNTL,0), gmc
    PACKET0(SRC_PITCH_OFFSET,1), src, dst    (pitch_bytes/64 << 22 | card_addr >> 10, radeon_cp.c 1315-1317)
    PACKET0(SRC_X_Y,2), x<<16|y, x<<16|y, w<<16|h
    WAIT_UNTIL_2D_IDLE                       -> PACKET0(WAIT_UNTIL,0), 2D_IDLECLEAN|HOST_IDLECLEAN
The bits are radeon_reg.h 683-737 (GMC), 1715-1719 (WAIT), 1891 (CP_PACKET0); the
registers 683, 784, 792, 797, 1580, 1585, 1705.

  present_oracle.py            prints the 13 words for the demo's frame and a self-check
"""
import sys

DP_GUI_MASTER_CNTL = 0x146c
SRC_PITCH_OFFSET = 0x1428
DST_PITCH_OFFSET = 0x142c
SRC_X_Y = 0x1590
DST_X_Y = 0x1594
DST_WIDTH_HEIGHT = 0x1598
WAIT_UNTIL = 0x1720

GMC_SRC_PITCH_OFFSET_CNTL = 1 << 0
GMC_DST_PITCH_OFFSET_CNTL = 1 << 1
GMC_BRUSH_NONE = 15 << 4
GMC_DST_32BPP = 6 << 8
GMC_SRC_DATATYPE_COLOR = 3 << 12
ROP3_S = 0x00cc0000
DP_SRC_SOURCE_MEMORY = 2 << 24
GMC_CLR_CMP_CNTL_DIS = 1 << 28
GMC_WR_MSK_DIS = 1 << 30
WAIT_2D_IDLECLEAN = 1 << 16
WAIT_3D_IDLECLEAN = 1 << 17
WAIT_HOST_IDLECLEAN = 1 << 18

GMC = (GMC_SRC_PITCH_OFFSET_CNTL | GMC_DST_PITCH_OFFSET_CNTL | GMC_BRUSH_NONE | GMC_DST_32BPP |
       GMC_SRC_DATATYPE_COLOR | ROP3_S | DP_SRC_SOURCE_MEMORY | GMC_CLR_CMP_CNTL_DIS | GMC_WR_MSK_DIS)


def packet0(reg, n):
    """n = registers - 1, as CP_PACKET0(reg, n) counts (radeon_drv.h 1891)."""
    return (n << 16) | (reg >> 2)


def pitch_offset(pitch_bytes, card_addr):
    assert pitch_bytes % 64 == 0 and card_addr % 1024 == 0
    return ((pitch_bytes // 64) << 22) | (card_addr >> 10)


def words(src_card, src_stride_px, src_x, src_y, w, h, dst_x, dst_y, screen_pitch_bytes):
    return [
        packet0(WAIT_UNTIL, 0), WAIT_3D_IDLECLEAN | WAIT_HOST_IDLECLEAN,
        packet0(DP_GUI_MASTER_CNTL, 0), GMC,
        packet0(SRC_PITCH_OFFSET, 1), pitch_offset(src_stride_px * 4, src_card), pitch_offset(screen_pitch_bytes, 0),
        packet0(SRC_X_Y, 2), (src_x << 16) | src_y, (dst_x << 16) | dst_y, (w << 16) | h,
        packet0(WAIT_UNTIL, 0), WAIT_2D_IDLECLEAN | WAIT_HOST_IDLECLEAN,
    ]


# ---- G3b: the clear (docs/G3B_CLEAR_PLAN.md 2-1), from radeon_cp_dispatch_clear
# (radeon_state.c 892-912 the colour fill, 1160-1262 the R200 depth rectangle)
CNTL_PAINT_MULTI = 0x00009A00          # radeon_drv.h 1178
CP_PACKET3 = 0xC0000000                # radeon_drv.h 1155
R200_3D_DRAW_IMMD_2 = 0xC0003500       # radeon_drv.h 1345
DP_WRITE_MASK = 0x16cc
# G3d: the X driver's solid fill registers (radeon_reg.h 669-672, 774, 784, 800; DEFAULT_SC 0x16e8)
DEFAULT_SC_BOTTOM_RIGHT, DP_BRUSH_FRGD_CLR, DP_BRUSH_BKGD_CLR = 0x16e8, 0x147c, 0x1478
DP_SRC_FRGD_CLR, DP_SRC_BKGD_CLR, DP_CNTL, DST_Y_X, DST_HEIGHT_WIDTH = 0x15d8, 0x15dc, 0x16c0, 0x1438, 0x143c
DST_X_LEFT_TO_RIGHT, DST_Y_TOP_TO_BOTTOM = 1 << 0, 1 << 1
GMC_BRUSH_SOLID_COLOR = 13 << 4
ROP3_P = 0x00f00000
GMC_CLEAR = (GMC_DST_PITCH_OFFSET_CNTL | GMC_BRUSH_SOLID_COLOR | GMC_DST_32BPP |
             GMC_SRC_DATATYPE_COLOR | ROP3_P | GMC_CLR_CMP_CNTL_DIS)
PRIM_RECT_LIST_3 = (8 << 0) | (3 << 4) | (3 << 16)     # RECT_LIST | WALK_RING | 3 vertices (radeon_drv.h 1207-1219)
Z_TEST_ALWAYS = 7 << 4
STENCIL_TEST_ALWAYS = 7 << 12
Z_WRITE_ENABLE = 1 << 30
DEPTH_FORMAT_16BIT = 0 << 0
# G3c: the CLIENT's depth format -- 16-bit (OSRDN_TRI_ZSTENCIL_LESS 0x42227010, format nibble 0) --
# with Z_TEST_ALWAYS, stencil ALWAYS, ops 0x0222_0000 and Z_WRITE_ENABLE: the reference builds its clear
# word from depth_clear->rb3d_zstencilcntl, the format the client drew with (radeon_state.c 1219-1221);
# R6f D2 names 0x42227070 as the 16-bit clear value.  G3b sent the precedent's 0x42227072 (format 2,
# 24-bit) and the card cleared one 24-bit z per word while the client tested 16-bit half-words (boot 5).
CLEAR_ZSTENCIL = 0x02220000 | DEPTH_FORMAT_16BIT | STENCIL_TEST_ALWAYS | Z_TEST_ALWAYS | Z_WRITE_ENABLE
# the state the reference sets for its depth rectangle (radeon_state.c 1195-1215): cpR6State's registers
PP_CNTL, RE_CNTL, RB3D_CNTL, RB3D_ZSTENCILCNTL = 0x1c38, 0x1c50, 0x1c3c, 0x1c2c
RB3D_STENCILREFMASK, RB3D_PLANEMASK, SE_CNTL = 0x1d7c, 0x1d84, 0x1c4c
SE_VTE_CNTL, SE_VTX_FMT_0, SE_VTX_FMT_1, SE_VAP_CNTL, RE_AUX_SCISSOR_CNTL = 0x20b0, 0x2088, 0x208c, 0x2080, 0x26f0
RB3D_DEPTHOFFSET, RE_TOP_LEFT, RE_WIDTH_HEIGHT = 0x1c24, 0x26c0, 0x1c44
RB3D_DSTCACHE_CTLSTAT, RB3D_ZCACHE_CTLSTAT = 0x325c, 0x3254
RB3D_CNTL_Z = 0x00001902               # plane mask enable, ARGB8888, Z_ENABLE (cpR6State)
SE_CNTL_FLAT, VTE_XY_Z, VTX_FMT_Z0_W0, VAP_9 = 0x480055de, 0x300, 0x3, 0x240000


def packet3(op, n):
    return CP_PACKET3 | (n << 16) | op


def f32(x):
    import struct
    return struct.unpack('<I', struct.pack('<f', x))[0]


def clear_words(flags, colour_card, colour_pitch_px, colour, depth_card, depth_pitch_px, z_bits, w, h,
                screen_pitch_bytes=None):
    """flags: 1 colour, 2 depth, 3 both.  Card addresses (winStart + window offset)."""
    wd = []
    if flags & 1:       # "Ensure the 3D stream is idle before doing a 2D fill" (radeon_state.c 880-884)
        # G3d: then the X driver's solid fill register by register (radeon_exa_funcs.c Emit2DState
        # 90-131, RADEONSolid 222-245) -- the DRM's PAINT_MULTI packet wrote nothing through this CP
        # (boot 6), the register-driven blit draws; DP_CNTL is what nobody had ever written
        wd += [packet0(WAIT_UNTIL, 0), WAIT_3D_IDLECLEAN | WAIT_HOST_IDLECLEAN,
               packet0(DEFAULT_SC_BOTTOM_RIGHT, 0), 0x1fff1fff,
               packet0(DP_GUI_MASTER_CNTL, 0), GMC_CLEAR,
               packet0(DP_BRUSH_FRGD_CLR, 0), colour,
               packet0(DP_BRUSH_BKGD_CLR, 0), 0,
               packet0(DP_SRC_FRGD_CLR, 0), 0xffffffff,
               packet0(DP_SRC_BKGD_CLR, 0), 0,
               packet0(DP_WRITE_MASK, 0), 0xffffffff,
               packet0(DP_CNTL, 0), DST_X_LEFT_TO_RIGHT | DST_Y_TOP_TO_BOTTOM,
               packet0(DST_PITCH_OFFSET, 0), pitch_offset(colour_pitch_px * 4, colour_card),
               packet0(DST_Y_X, 0), 0,
               packet0(DST_HEIGHT_WIDTH, 0), (h << 16) | w,
               packet0(WAIT_UNTIL, 0), WAIT_2D_IDLECLEAN | WAIT_HOST_IDLECLEAN]
    if flags & 2:
        wd += [packet0(WAIT_UNTIL, 0), WAIT_2D_IDLECLEAN | WAIT_HOST_IDLECLEAN,
               packet0(PP_CNTL, 0), 0, packet0(RE_CNTL, 0), 0,
               packet0(RB3D_CNTL, 0), RB3D_CNTL_Z, packet0(RB3D_ZSTENCILCNTL, 0), CLEAR_ZSTENCIL,
               packet0(RB3D_STENCILREFMASK, 0), 0, packet0(RB3D_PLANEMASK, 0), 0,
               packet0(SE_CNTL, 0), SE_CNTL_FLAT, packet0(SE_VTE_CNTL, 0), VTE_XY_Z,
               packet0(SE_VTX_FMT_0, 0), VTX_FMT_Z0_W0, packet0(SE_VTX_FMT_1, 0), 0,
               packet0(SE_VAP_CNTL, 0), VAP_9, packet0(RE_AUX_SCISSOR_CNTL, 0), 0,
               packet0(RB3D_DEPTHOFFSET, 1), depth_card, depth_pitch_px,
               packet0(RE_TOP_LEFT, 0), 0, packet0(RE_WIDTH_HEIGHT, 0), ((h - 1) << 16) | (w - 1),
               packet3(R200_3D_DRAW_IMMD_2, 12), PRIM_RECT_LIST_3,
               f32(0.0), f32(0.0), z_bits, f32(1.0),
               f32(0.0), f32(float(h)), z_bits, f32(1.0),
               f32(float(w)), f32(float(h)), z_bits, f32(1.0)]
    # no cache purge tail: the reference ends with the rectangle; IDLECLEAN waits (ours, and the next
    # submission's own WAIT_UNTIL) are what keep the caches coherent (codex, 2026-09-26)
    return wd


def self_check():
    assert GMC_CLEAR == ((1 << 1) | (13 << 4) | (6 << 8) | (3 << 12) | 0x00f00000 | (1 << 28)), hex(GMC_CLEAR)
    assert PRIM_RECT_LIST_3 == 0x00030038
    assert packet3(CNTL_PAINT_MULTI, 4) == 0xC0049A00 and packet3(R200_3D_DRAW_IMMD_2, 12) == 0xC00C3500
    assert CLEAR_ZSTENCIL == 0x42227070, hex(CLEAR_ZSTENCIL)
    # the clear word IS the client's LESS word with the test field set to ALWAYS: same format, same
    # stencil ops, same write bit -- read from the generated table, not typed twice
    import os, re
    tab = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'mesa', 'OSRDNMesaTriTable.h')).read()
    less = int(re.search(r'#define OSRDN_TRI_ZSTENCIL_LESS\s+0x([0-9a-fA-F]+)UL', tab).group(1), 16)
    assert (less & ~(7 << 4)) | Z_TEST_ALWAYS == CLEAR_ZSTENCIL, hex(less)
    assert (less & 0xf) == DEPTH_FORMAT_16BIT
    assert len(clear_words(3, 0x400000, 800, 0x11223344, 0x900000, 800, f32(1.0), 800, 600)) == 26 + 2 + 24 + 3 + 4 + 14   # colour 26 (13 register pairs), depth 47: the draw is header + prim word + 12
    assert len(clear_words(1, 0x400000, 800, 0, 0, 0, 0, 800, 600)) == 26
    assert clear_words(1, 0x400000, 800, 0, 0, 0, 0, 800, 600)[16:18] == [packet0(DP_CNTL, 0), 3]

    assert GMC == 0x52cc36f3, hex(GMC)
    assert (WAIT_3D_IDLECLEAN | WAIT_HOST_IDLECLEAN) == 0x60000
    assert (WAIT_2D_IDLECLEAN | WAIT_HOST_IDLECLEAN) == 0x50000
    assert packet0(SRC_X_Y, 2) == 0x00020564
    assert pitch_offset(4096, 0) == (64 << 22)
    assert pitch_offset(800 * 4, 0x400000) == ((50 << 22) | 0x1000)
    w = words(0x400000, 800, 0, 599, 800, 1, 0, 0, 4096)
    assert len(w) == 13 and w[8] == 599 and w[10] == (800 << 16) | 1
    return True


if __name__ == '__main__':
    self_check()
    for v in words(0x400000, 800, 0, 0, 800, 1, 0, 599, 4096):
        print('%08x' % v)
    print('present_oracle: self-check PASS')
