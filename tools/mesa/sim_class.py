#!/usr/bin/env python3
"""M1b: the state classifier, state by state (docs/M1B_PLAN.md 4).

  sim_class.py

The classifier is a function of plain integers precisely so that it can be
driven from a table here rather than only on the target.  Each row states a
state and the class and reason it must produce; the expected values are written
from the plan, not read out of the C.

It also walks the whole RasterMask space, because the interesting property is
not "DEPTH_BIT is accepted" but "every other bit, alone or combined, is not".
"""

import shutil
import atexit
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')
UNIT = os.path.join(MESA, 'OSRDNMesaClass.c')

TAKE, DECLINE, NO_ACCEL = 0, 1, 2
WHY = {'-': 0, 'FORMAT': 1, 'SMOOTH': 2, 'STIPPLE': 3, 'TEXTURE': 4,
       'RASTER': 5, 'DEPTH_WIDTH': 6, 'SHADE_MODEL': 7, 'TRI_SETUP': 8,
       'BLEND_MODE': 9, 'DEPTH': 10, 'ALPHA_MODE': 11}

RGBA, CI = 1, 0          # ctx->Visual->RGBAflag, not an OSMesa format
DEPTH = 0x004

# M1d.  FLAT is include/GL/gl.h 288; the caps are src/types.h 1501-1518, and
# tools/mesa/sim_trifunc.py recomputes their OR out of that file.
FLAT, GOURAUD = 0x1D00, 0x1D01
CULL, UNFILLED, OFFSET, TWOSIDE, CULL_BOTH = 0x400, 0x40, 0x200, 0x20, 0x400000

# M1f.  BLEND is RasterMask's BLEND_BIT (src/types.h 1450); the GL enums are
# include/GL/gl.h 324-331 and 822.  A row's blend column is None (disabled) or
# (src, dst, srcA, dstA, equation).
BLEND = 0x002
# src/types.h 1461: Mesa sets this for ANY texture, at src/state.c 817, from
# the same expression that fills the `texture` field -- so a row with one and
# not the other is a state Mesa cannot build, and the classifier says so.
TEXBIT = 0x1000
SA, OMSA, ONE, ZERO = 0x0302, 0x0303, 0x1, 0x0
ADD, SUB = 0x8006, 0x800A
OK_BLEND = (SA, OMSA, SA, OMSA, ADD)
NO = None

# M1g.  A row's texture column is None (no texture) or
# (unit0, w, h, border, format, minFilter, magFilter, wrapS, wrapT, envMode).
# TEXTURE0_2D is src/types.h 733; the enums are include/GL/gl.h 630-631, 457.
T2D, NEAREST, REPEAT, RGBA_, LINEAR, CLAMP = 0x2, 0x2600, 0x2901, 0x1908, 0x2601, 0x2900
# GL_REPLACE and GL_MODULATE: include/GL/gl.h.  MODULATE is Mesa's DEFAULT
# (src/context.c 602), so the near-miss row below is the state an
# application reaches by doing nothing at all.
REPLACE, MODULATE = 0x1E01, 0x2100
# M1i.  A row's depth column is None (the state is whatever the row's
# rasterMask says with the pair we send) or (func, mask).
GL_LESS, GL_LEQUAL, GL_ALWAYS = 0x0201, 0x0203, 0x0207
GL_GEQUAL, GL_NEVER, GL_GREATER = 0x0206, 0x0200, 0x0204
OMSC, DECAL = 0x0301, 0x2101
ALPHA = 0x001                   # G4-3 K2: ALPHATEST_BIT
# G4-1b: include/GL/gl.h -- RGB 0x1907, LUMINANCE 0x1909, LINEAR_MIPMAP_LINEAR 0x2703
RGB_, LUM_, MIPMAP = 0x1907, 0x1909, 0x2703
OK_DEPTH = (GL_LESS, 1)
OK_TEX = (T2D, 8, 8, 0, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, REPLACE)

# (label, accel, rasterMask, format, smooth, stipple, texture, depthBits,
#  shadeModel, triangleCaps, blend, texture-shape, want, why)
ROWS = [
    ('plain RGBA, nothing on',    1, 0, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, TAKE, '-'),
    # M1i draws depth now -- but only GL_LESS with the write on, which is what
    # the prologue carries.  Every other compare is still declined BY NAME.
    ('depth on, LESS and write',  1, DEPTH, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, TAKE, '-', OK_DEPTH),
    # G4-1a: four compares and either mask are drawn; NEVER and the rest are not
    ('depth on, LEQUAL',          1, DEPTH, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     TAKE, '-', (GL_LEQUAL, 1)),
    ('depth on, GEQUAL (ztrick)', 1, DEPTH, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     TAKE, '-', (GL_GEQUAL, 1)),
    ('depth on, ALWAYS',          1, DEPTH, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     TAKE, '-', (GL_ALWAYS, 1)),
    ('depth on, the write masked off', 1, DEPTH, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     TAKE, '-', (GL_LESS, 0)),
    ('depth on, NEVER',           1, DEPTH, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     DECLINE, 'DEPTH', (GL_NEVER, 1)),
    ('depth on, GREATER',         1, DEPTH, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     DECLINE, 'DEPTH', (GL_GREATER, 1)),
    ('depth OFF, an odd compare',  1, 0, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     TAKE, '-', (GL_ALWAYS, 0)),
    ('depth on, 24 bits',         1, DEPTH, RGBA, 0, 0, 0, 24, FLAT, 0, NO, NO, DECLINE, 'DEPTH_WIDTH'),
    ('depth OFF, odd depthBits',  1, 0, RGBA, 0, 0, 0, 24, FLAT, 0, NO, NO, TAKE, '-'),
    ('colour index',              1, 0, CI, 0, 0, 0, 16, FLAT, 0, NO, NO, DECLINE, 'FORMAT'),
    ('polygon smooth',            1, 0, RGBA, 1, 0, 0, 16, FLAT, 0, NO, NO, DECLINE, 'SMOOTH'),
    ('polygon stipple',           1, 0, RGBA, 0, 1, 0, 16, FLAT, 0, NO, NO, DECLINE, 'STIPPLE'),
    ('an unknown raster bit',     1, 0x008, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, DECLINE, 'RASTER'),
    ('depth AND an unknown bit',  1, DEPTH | 0x008, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, DECLINE, 'RASTER'),
    ('no acceleration at all',    0, 0, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, NO_ACCEL, '-'),
    ('no acceleration, bad state', 0, 0x008, CI, 1, 1, 1, 24, 0x1D02, CULL, NO, NO, NO_ACCEL, '-'),
    # ---- M1d/M1e
    ('Gouraud shading',           1, 0, RGBA, 0, 0, 0, 16, GOURAUD, 0, NO, NO, TAKE, '-'),
    ('a shade model that is neither', 1, 0, RGBA, 0, 0, 0, 16, 0x1D02, 0, NO, NO, DECLINE, 'SHADE_MODEL'),
    # M3b: the hook culls for itself now (docs/M3B_PLAN.md 7-8)
    ('back-face culling',         1, 0, RGBA, 0, 0, 0, 16, FLAT, CULL, NO, NO, TAKE, '-'),
    ('culling with two-sided',    1, 0, RGBA, 0, 0, 0, 16, FLAT, CULL | TWOSIDE, NO, NO, DECLINE, 'TRI_SETUP'),
    ('culling with offset',       1, 0, RGBA, 0, 0, 0, 16, FLAT, CULL | OFFSET, NO, NO, DECLINE, 'TRI_SETUP'),
    ('unfilled polygons',         1, 0, RGBA, 0, 0, 0, 16, FLAT, UNFILLED, NO, NO, DECLINE, 'TRI_SETUP'),
    ('polygon offset',            1, 0, RGBA, 0, 0, 0, 16, FLAT, OFFSET, NO, NO, DECLINE, 'TRI_SETUP'),
    ('two-sided lighting',        1, 0, RGBA, 0, 0, 0, 16, FLAT, TWOSIDE, NO, NO, DECLINE, 'TRI_SETUP'),
    ('cull front and back',       1, 0, RGBA, 0, 0, 0, 16, FLAT, CULL_BOTH, NO, NO, DECLINE, 'TRI_SETUP'),
    ('a cap outside DD_SW_SETUP', 1, 0, RGBA, 0, 0, 0, 16, FLAT, 0x1000000, NO, NO, TAKE, '-'),
    # ---- M1f
    ('blend on, the pair we send', 1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0, OK_BLEND, NO, TAKE, '-'),
    ('blend on, ONE/ZERO',         1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0,
     (ONE, ZERO, ONE, ZERO, ADD), NO, DECLINE, 'BLEND_MODE'),
    # G4-1a: GLQuake's two other pairs
    ('blend on, ZERO/ONE_MINUS_SRC_COLOR', 1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0,
     (ZERO, OMSC, ZERO, OMSC, ADD), NO, TAKE, '-'),
    ('blend on, ONE/ONE',          1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0,
     (ONE, ONE, ONE, ONE, ADD), NO, TAKE, '-'),
    ('blend on, SRC_ALPHA/ONE',    1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0,
     (SA, ONE, SA, ONE, ADD), NO, DECLINE, 'BLEND_MODE'),
    ('blend on, ONE/ONE but a separate alpha pair', 1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0,
     (ONE, ONE, ZERO, OMSC, ADD), NO, DECLINE, 'BLEND_MODE'),
    ('blend on, SUB equation',     1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0,
     (SA, OMSA, SA, OMSA, SUB), NO, DECLINE, 'BLEND_MODE'),
    ('blend on, separate alpha',   1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0,
     (SA, OMSA, ONE, ZERO, ADD), NO, DECLINE, 'BLEND_MODE'),
    ('the bit set but blending off', 1, BLEND, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, TAKE, '-'),
    # ---- M1g: the one texture this rung uploads, and the near misses.  Without
    # these rows the texture clauses are untested and a mutation that deletes one
    # is NOT CAUGHT -- which is what happened the first time.
    ('the texture we upload',      1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO, OK_TEX, TAKE, '-'),
    # G4-1b (docs/G4_GLQUAKE_PLAN.md 5 T1): the shape is widened to any power of
    # two from 8 to 512 a side, RGB or RGBA, NEAREST or LINEAR (no mips) -- the
    # rows that were near misses in M1g are TAKEN now, and the edges move out.
    ('a 16x16 texture',            1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 16, 16, 0, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, REPLACE), TAKE, '-'),
    ('8x8 but linear filtering',   1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 8, 8, 0, RGBA_, LINEAR, NEAREST, REPEAT, REPEAT, REPLACE), TAKE, '-'),
    ('512x512, both linear, RGB',  1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 512, 512, 0, RGB_, LINEAR, LINEAR, REPEAT, REPEAT, MODULATE), TAKE, '-'),
    ('256x64, a GLQuake lightmap shape', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 256, 64, 0, RGBA_, LINEAR, LINEAR, REPEAT, REPEAT, MODULATE), TAKE, '-'),
    ('4x4 is below the measured grain', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 4, 4, 0, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE'),
    ('1024 wide is past the largest', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 1024, 8, 0, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE'),
    ('24x8 is not a power of two', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 24, 8, 0, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE'),
    ('8x8 LUMINANCE (Mesa keeps 1 byte)', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 8, 8, 0, LUM_, NEAREST, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE'),
    ('8x8 with a mipmap min filter (G4-3)', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 8, 8, 0, RGBA_, MIPMAP, LINEAR, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE'),
    # G4-5 (docs/G4_5_MIP_PLAN.md 2-2, 2-3): (knob, complete, lambda unclamped) -- knob 0 OFF, 1 MEASURED, 2 ALL
    ('mip NEAREST_MIPMAP_NEAREST, measured, complete', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2700, NEAREST, REPEAT, REPEAT, REPLACE), TAKE, '-', None, None, (1, 1, 1)),
    ('mip NEAREST_MIPMAP_NEAREST, knob OFF', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2700, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE', None, None, (0, 1, 1)),
    ('mip NEAREST_MIPMAP_NEAREST, incomplete', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2700, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE', None, None, (1, 0, 1)),
    ('mip NEAREST_MIPMAP_NEAREST, MinLod/MaxLod/LodBias set', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2700, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE', None, None, (1, 1, 0)),
    ('mip LINEAR_MIPMAP_NEAREST, measured knob (G4-5 scene C)', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2701, LINEAR, REPEAT, REPEAT, REPLACE), TAKE, '-', None, None, (1, 1, 1)),
    ('mip NEAREST_MIPMAP_LINEAR, measured knob (G4-10: admitted, sent as NEAREST_MIPMAP_NEAREST)', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2702, LINEAR, REPEAT, REPEAT, REPLACE), TAKE, '-', None, None, (1, 1, 1)),
    ('mip LINEAR_MIPMAP_LINEAR, measured knob (G4-10: admitted, sent as LINEAR_MIPMAP_NEAREST)', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, MIPMAP, LINEAR, REPEAT, REPEAT, REPLACE), TAKE, '-', None, None, (1, 1, 1)),
    ('mip NEAREST_MIPMAP_LINEAR, measured knob, incomplete chain', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2702, LINEAR, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE', None, None, (1, 0, 1)),
    ('mip NEAREST_MIPMAP_LINEAR, knob OFF', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2702, LINEAR, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE', None, None, (0, 1, 1)),
    ('mip LINEAR_MIPMAP_NEAREST, knob ALL', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, 0x2701, LINEAR, REPEAT, REPEAT, REPLACE), TAKE, '-', None, None, (2, 1, 1)),
    ('mip LINEAR_MIPMAP_LINEAR, knob ALL', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, MIPMAP, LINEAR, REPEAT, REPEAT, REPLACE), TAKE, '-', None, None, (2, 1, 1)),
    ('mip LINEAR_MIPMAP_LINEAR, knob ALL, incomplete', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 64, 64, 0, RGBA_, MIPMAP, LINEAR, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE', None, None, (2, 0, 1)),
    ('8x8 but clamped',            1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 8, 8, 0, RGBA_, NEAREST, NEAREST, CLAMP, REPEAT, REPLACE), DECLINE, 'TEXTURE'),
    ('8x8 but with a border',      1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 8, 8, 1, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, REPLACE), DECLINE, 'TEXTURE'),
    ('8x8 but MODULATE, Mesa\'s default', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 8, 8, 0, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, MODULATE), TAKE, '-'),
    ('8x8 but DECAL',              1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO,
     (T2D, 8, 8, 0, RGBA_, NEAREST, NEAREST, REPEAT, REPEAT, DECAL), DECLINE, 'TEXTURE'),
    ('texturing on with no object', 1, TEXBIT, RGBA, 0, 0, T2D, 16, FLAT, 0, NO, NO, DECLINE, 'TEXTURE'),
    ('the texture BIT with no texture', 1, TEXBIT, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO,
     DECLINE, 'TEXTURE'),
    ('a texture with no BIT',      1, 0, RGBA, 0, 0, T2D, 16, FLAT, 0, NO, OK_TEX,
     DECLINE, 'TEXTURE'),
    # G4-3 K2 (docs/G4_3_KERNEL_PLAN.md 3): the alpha test.  ALPHA is RasterMask's ALPHATEST_BIT
    # (src/types.h 1449); a row's 16th column is (enabled, func, ref) or None.
    ('alpha GREATER 170 (GLQuake\'s 2D)', 1, ALPHA, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, TAKE, '-', None,
     (1, GL_GREATER, 170)),
    ('alpha NEVER, drawn as FAIL', 1, ALPHA, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, TAKE, '-', None,
     (1, GL_NEVER, 0)),
    ('alpha ALWAYS, drawn as PASS', 1, ALPHA, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, TAKE, '-', None,
     (1, GL_ALWAYS, 255)),
    ('the alpha BIT with the test off', 1, ALPHA, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, DECLINE, 'RASTER', None,
     (0, 0, 0)),
    ('alpha on with no BIT',       1, 0, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, DECLINE, 'RASTER', None,
     (1, GL_GREATER, 170)),
    ('alpha with a compare no code names', 1, ALPHA, RGBA, 0, 0, 0, 16, FLAT, 0, NO, NO, DECLINE, 'ALPHA_MODE', None,
     (1, 0x1234, 170)),
]

HARNESS = r'''
int printf(const char *, ...);
void exit(int);
#include "OSRDNMesaClass.h"

/* C89 has no designated initialisers; zero it by hand so a field added to the
   struct cannot be read before it is written (M1g added nine at once). */
static void zero(osrdn_class_state *s)
{
    unsigned char *p = (unsigned char *)s;
    unsigned int i;

    for (i = 0; i < sizeof(*s); i++)
        p[i] = 0;
}

static void one(const char *label, int accel, unsigned long rm, int fmt,
                int sm, int st, int tx, int db, unsigned long sh, unsigned long tc,
                int be, unsigned long bs, unsigned long bd,
                unsigned long bsa, unsigned long bda, unsigned long beq,
                unsigned long tu, unsigned long tw, unsigned long th,
                unsigned long tb, unsigned long tfm, unsigned long tmin,
                unsigned long tmag, unsigned long tws, unsigned long twt,
                unsigned long tenv,
                unsigned long dfn, unsigned long dmsk,
                int ae, unsigned long af, unsigned long ar,
                unsigned long mip, unsigned long cpl, unsigned long lod)
{
    osrdn_class_state s;
    int why = -1, c;

    zero(&s);
    s.rasterMask = rm; s.rgba = fmt; s.smooth = sm; s.stipple = st;
    s.texture = tx; s.depthBits = db; s.rowLength = 640; s.yUp = 1;
    s.shadeModel = sh; s.triangleCaps = tc;
    s.blendEnabled = be; s.blendSrcRGB = bs; s.blendDstRGB = bd;
    s.blendSrcA = bsa; s.blendDstA = bda; s.blendEquation = beq;
    s.texUnit0 = tu; s.texWidth = tw; s.texHeight = th; s.texBorder = tb;
    s.texFormat = tfm; s.texMinFilter = tmin; s.texMagFilter = tmag;
    s.texWrapS = tws; s.texWrapT = twt; s.texEnvMode = tenv;
    s.depthFunc = dfn; s.depthMask = dmsk;
    s.alphaEnabled = ae; s.alphaFunc = af; s.alphaRef = ar;     /* G4-3 K2 */
    s.texMip = mip; s.texComplete = cpl; s.texLodOk = lod;      /* G4-5 */
    c = osrdn_class_of(&s, accel, &why);
    printf("ROW %%s|%%d|%%d\n", label, c, why);
}

int main(void)
{
    unsigned long rm;
    osrdn_class_state s;
    int why, c, take = 0, i;

    zero(&s);

%(rows)s

    /* G4-1a: the codes, for the host to recompute from the generated table */
    printf("CODE depth 0201 1 %%d\n", osrdn_class_depth_code(0x0201UL, 1UL));
    printf("CODE depth 0203 0 %%d\n", osrdn_class_depth_code(0x0203UL, 0UL));
    printf("CODE depth 0206 1 %%d\n", osrdn_class_depth_code(0x0206UL, 1UL));
    printf("CODE depth 0207 0 %%d\n", osrdn_class_depth_code(0x0207UL, 0UL));
    printf("CODE depth 0200 1 %%d\n", osrdn_class_depth_code(0x0200UL, 1UL));
    printf("CODE blend 0302 0303 %%d\n", osrdn_class_blend_code(0x0302UL, 0x0303UL));
    printf("CODE blend 0000 0301 %%d\n", osrdn_class_blend_code(0UL, 0x0301UL));
    printf("CODE blend 0001 0001 %%d\n", osrdn_class_blend_code(1UL, 1UL));
    printf("CODE blend 0302 0001 %%d\n", osrdn_class_blend_code(0x0302UL, 1UL));
    printf("CODE env 1e01 %%d\n", osrdn_class_env_code(0x1E01UL));
    printf("CODE env 2100 %%d\n", osrdn_class_env_code(0x2100UL));
    printf("CODE env 2101 %%d\n", osrdn_class_env_code(0x2101UL));
    /* the whole RasterMask space: only DEPTH_BIT alone may be taken */
    for (rm = 0UL; rm < 0x2000UL; rm++) {
        s.rasterMask = rm; s.rgba = 1; s.smooth = 0; s.stipple = 0;
        s.texture = 0; s.depthBits = 16; s.rowLength = 640; s.yUp = 1;
        s.shadeModel = 0x1D00UL; s.triangleCaps = 0UL;      /* GL_FLAT, no caps */
        s.blendEnabled = 0; s.blendSrcRGB = 0UL; s.blendDstRGB = 0UL;
        s.blendSrcA = 0UL; s.blendDstA = 0UL; s.blendEquation = 0UL;
        s.depthFunc = 0x0201UL; s.depthMask = 1UL;     /* M1i: GL_LESS, write on */
        c = osrdn_class_of(&s, 1, &why);
        if (c == OSRDN_CLASS_WOULD_TAKE) {
            take++;
            printf("MASKTAKE %%lu\n", rm);
        }
    }
    printf("MASKCOUNT %%d\n", take);

    /* names exist for every class and reason, and only for them */
    for (i = -1; i <= OSRDN_CLASSES; i++)
        printf("CNAME %%d %%s\n", i, osrdn_class_name(i));
    for (i = -1; i <= OSRDN_WHY_REASONS; i++)
        printf("WNAME %%d %%s\n", i, osrdn_class_why_name(i));
    return 0;
}
__attribute__((force_align_arg_pointer))
void _start(void) { exit(main()); }
'''


def build_and_run(src, work):
    rows = '\n'.join(
        '    one("%s", %d, 0x%03xUL, 0x%04x, %d, %d, %d, %d, 0x%04xUL, 0x%08xUL, '
        '%d, 0x%04xUL, 0x%04xUL, 0x%04xUL, 0x%04xUL, 0x%04xUL, '
        '0x%04xUL, %dUL, %dUL, %dUL, 0x%04xUL, 0x%04xUL, 0x%04xUL, 0x%04xUL, 0x%04xUL, '
        '0x%04xUL, 0x%04xUL, %dUL, %d, 0x%04xUL, %dUL, %dUL, %dUL, %dUL);'
        % ((l, a, rm, f, sm, st, tx, db, sh, tc) +
           ((1,) + bl if bl else (0, 0, 0, 0, 0, 0)) +
           (tl if tl else (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)) +
           (dp if dp else (0, 0)) +
           (al if al else (0, 0, 0)) +
           (mp if mp else (0, 0, 0)))
        for (l, a, rm, f, sm, st, tx, db, sh, tc, bl, tl, _w, _y, dp, al, mp) in
        (r + (None,) * (17 - len(r)) for r in ROWS))
    open(os.path.join(work, 'h.c'), 'w').write(HARNESS % dict(rows=rows))
    unit = os.path.join(work, 'OSRDNMesaClass.c')
    open(unit, 'w').write(src)
    exe = os.path.join(work, 'h')
    r = subprocess.run(['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Werror', '-Wno-main',
                        '-I', MESA, unit, os.path.join(work, 'h.c'),
                        '-nostdlib', '-nostartfiles', '/usr/lib32/libc.so.6',
                        '-Wl,-dynamic-linker,/lib/ld-linux.so.2', '-o', exe],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-900:]
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, 'it hangs'
    return r.stdout.splitlines(), ''


def judge(lines):
    p = []
    got = {}
    for l in lines:
        if l.startswith('ROW '):
            label, c, w = l[4:].rsplit('|', 2)
            got[label] = (int(c), int(w))
    for row in ROWS:
        (label, _a, _rm, _f, _sm, _st, _tx, _db, _sh, _tc, _bl, _tl,
         want, why) = row[:14]
        if label not in got:
            p.append('%s: no answer' % label)
            continue
        c, w = got[label]
        if c != want or w != WHY[why]:
            names = {0: 'TAKE', 1: 'DECLINE', 2: 'NO_ACCEL'}
            back = dict((v, k) for k, v in WHY.items())
            p.append('%s: got %s/%s, want %s/%s'
                     % (label, names.get(c, c), back.get(w, w), names.get(want), why))

    taken = [int(l.split()[1]) for l in lines if l.startswith('MASKTAKE ')]
    m = [l for l in lines if l.startswith('MASKCOUNT ')]
    if not m:
        p.append('the RasterMask walk did not run')
    else:
        n = int(m[0].split()[1])
        # M1f: the blend bit joined the known set, so the accepted masks were
        # 0, DEPTH, BLEND and both together.  M1i-to-be took DEPTH back out: the
        # bit is KNOWN (the mask was never the problem) but no rung draws depth,
        # so the state is declined by name (OSRDN_WHY_DEPTH) until one does.
        # The texture bit cannot be accepted here at all -- this sweep leaves
        # `texture` at 0, and the bit and the field have to agree.
        # M1i draws depth, so DEPTH is accepted again -- with the compare this
        # sweep now names.  TEXTURE cannot be: the sweep leaves `texture` 0 and
        # the bit and the field have to agree.
        want = sorted([0, DEPTH, BLEND, DEPTH | BLEND])
        if sorted(taken) != want or n != len(want):
            p.append('the accepted RasterMask values are %s (%d), want %s'
                     % (sorted(taken), n, want))

    # G4-1a: the codes against the generated table (OSRDNMesaTriTable.h), never a typed number
    tab = open(os.path.join(MESA, 'OSRDNMesaTriTable.h')).read()
    def T(name):
        m = re.search(r'#define %s\s+(\d+)(?:UL)?\b' % name, tab)
        return int(m.group(1))
    zt = dict((f, T('OSRDN_TRI_ZTEST_%s' % n)) for f, n in ((0x201, 'LESS'), (0x203, 'LEQUAL'), (0x206, 'GEQUAL'), (0x207, 'ALWAYS')))
    codes = dict((tuple(l.split()[1:-1]), int(l.split()[-1])) for l in lines if l.startswith('CODE '))
    want = {('depth', '0201', '1'): 1 | zt[0x201] << 1 | 16, ('depth', '0203', '0'): 1 | zt[0x203] << 1,
            ('depth', '0206', '1'): 1 | zt[0x206] << 1 | 16, ('depth', '0207', '0'): 1 | zt[0x207] << 1,
            ('depth', '0200', '1'): 0,
            ('blend', '0302', '0303'): T('OSRDN_TRI_BLEND_SRCA'), ('blend', '0000', '0301'): T('OSRDN_TRI_BLEND_ZERO_OMSC'),
            ('blend', '0001', '0001'): T('OSRDN_TRI_BLEND_ONE_ONE'), ('blend', '0302', '0001'): 0,
            ('env', '1e01'): T('OSRDN_TRI_TEX_REPLACE'), ('env', '2100'): T('OSRDN_TRI_TEX_MODULATE'), ('env', '2101'): 0}
    for k, v in want.items():
        if codes.get(k) != v:
            p.append('code %s is %s, want %d' % (' '.join(k), codes.get(k), v))
    cn = dict((int(l.split()[1]), l.split()[2]) for l in lines if l.startswith('CNAME '))
    for v, n in ((0, 'WOULD_TAKE'), (1, 'WOULD_DECLINE'), (2, 'NO_ACCEL'), (-1, '?'), (3, '?')):
        if cn.get(v) != n:
            p.append('class name %d is %r, want %r' % (v, cn.get(v), n))
    wn = dict((int(l.split()[1]), l.split()[2]) for l in lines if l.startswith('WNAME '))
    for n, v in WHY.items():
        if wn.get(v) != n:
            p.append('reason name %d is %r, want %r' % (v, wn.get(v), n))
    for v in (-1, len(WHY)):
        if wn.get(v) != '?':
            p.append('reason name %d is %r, want "?"' % (v, wn.get(v)))
    return p


MUTATIONS = [
    ('colour index is accepted', '    if (!s->rgba)\n        w = OSRDN_WHY_FORMAT;\n', ''),
    ('smooth polygons are accepted', '    else if (s->smooth)\n        w = OSRDN_WHY_SMOOTH;\n', ''),
    ('stipple is accepted', '    else if (s->stipple)\n        w = OSRDN_WHY_STIPPLE;\n', ''),
    ('texturing stops being checked at all',
     '    else if (s->texture &&', '    else if (0 &&'),
    ('any 2D texture is accepted, whatever its shape',
     '!osrdn_class_tex_dim_ok(s->texWidth) ||\n'
     '              !osrdn_class_tex_dim_ok(s->texHeight) ||',
     '              0 ||'),
    ('a non-power-of-two side passes the dimension check',
     '(d & (d - 1UL)) == 0UL;', '1;'),
    ('the min filter is not checked (a mipmap filter would be taken)',
     '              !classMinOk(s) ||', '              0 ||'),
    ('G4-5: an incomplete chain is taken', 'if (s->texComplete == 0UL || s->texLodOk == 0UL)', 'if (s->texLodOk == 0UL)'),
    ('G4-5: a clamped or biased lambda is taken', 'if (s->texComplete == 0UL || s->texLodOk == 0UL)', 'if (s->texComplete == 0UL)'),
    ('G4-5: the knob\'s OFF is not honoured', '    if (s->texMip == (unsigned long)OSRDN_TRI_MIP_MEASURED)',
     '    if (1)'),
    # G4-6: all four modes are measured now, so "an unmeasured mode is taken" cannot be seen; the
    # mask is still the path the default knob takes -- dropping it must decline every mip row
    ('G4-6: the default knob ignores the measured mask', '        return (OSRDN_MIP_MEASURED & (1UL << code)) != 0UL ? 1 : 0;', '        return 0;'),
    ('the alpha bit is admitted without the state agreeing',
     '    else if (((s->rasterMask & RM_ALPHA) != 0UL) != (s->alphaEnabled != 0))\n        w = OSRDN_WHY_RASTER;\n', ''),
    ('the alpha compare is not checked (any function would be drawn)',
     'osrdn_class_alpha_code(s->alphaFunc, s->alphaRef) == 0)', '0)'),
    ('the format is not checked (LUMINANCE would be taken)',
     '(s->texFormat != GL_RGBA_ && s->texFormat != GL_RGB_) ||', '0 ||'),
    ('the texture env mode is not checked (DECAL would be taken)',
     'osrdn_class_env_code(s->texEnvMode) == 0))', '0))'),
    # M1i REFINED this.  It used to remove the blanket "depth is not drawn"
    # refusal; now the rung draws GL_LESS and the reason asks WHICH depth, so
    # the mutations take away each half of that question.
    ('the depth compare is not checked',
     'osrdn_class_depth_code(s->depthFunc, s->depthMask) == 0', '0'),
    ('GL_NEVER is drawn as ALWAYS',
     '        return 0;                       /* NEVER, GREATER, EQUAL, NOTEQUAL: not drawn */',
     '        zt = OSRDN_TRI_ZTEST_ALWAYS;'),
    ('a fourth blend pair is accepted',
     '    if (src == GL_ONE_ && dst == GL_ONE_)\n        return OSRDN_TRI_BLEND_ONE_ONE;\n    return 0;',
     '    return OSRDN_TRI_BLEND_ONE_ONE;'),
    ('an unknown raster bit is accepted', '(s->rasterMask & ~RM_KNOWN) != 0UL',
     '(s->rasterMask & ~0xfffUL) != 0UL'),
    ('the depth width is not checked',
     '    else if ((s->rasterMask & RM_DEPTH) != 0UL && s->depthBits != SOFTWARE_DEPTH_BITS)\n        w = OSRDN_WHY_DEPTH_WIDTH;\n', ''),
    ('the depth width is checked even with depth off',
     '(s->rasterMask & RM_DEPTH) != 0UL && s->depthBits != SOFTWARE_DEPTH_BITS',
     's->depthBits != SOFTWARE_DEPTH_BITS'),
    # ---- M1d
    ('the shade model stops being checked at all',
     '    else if (s->shadeModel != GL_FLAT_ && s->shadeModel != GL_SMOOTH_)\n'
     '        w = OSRDN_WHY_SHADE_MODEL;\n', ''),
    ('smooth is accepted but flat is not (the two values swapped away)',
     's->shadeModel != GL_FLAT_ && s->shadeModel != GL_SMOOTH_',
     's->shadeModel != GL_SMOOTH_'),
    ('the setup caps are accepted',
     '    else if ((s->triangleCaps & DD_DECLINE_) != 0UL)\n        w = OSRDN_WHY_TRI_SETUP;\n', ''),
    # M3b: the decline mask is DD_SW_SETUP_ without the cull bit
    ('the decline mask declines culling again', 'DD_DECLINE_     0x00400260UL',
     'DD_DECLINE_     0x00400660UL'),
    ('the decline mask loses the offset bit', 'DD_DECLINE_     0x00400260UL',
     'DD_DECLINE_     0x00400060UL'),
    ('the decline mask loses the two-sided bit', 'DD_DECLINE_     0x00400260UL',
     'DD_DECLINE_     0x00400240UL'),
    ('any cap at all is declined', '(s->triangleCaps & DD_DECLINE_) != 0UL',
     's->triangleCaps != 0UL'),
    # ---- M1f
    ('the blend mode stops being checked',
     '    else if (s->blendEnabled &&', '    else if (0 &&'),
    ('a separate alpha function is accepted',
     '              s->blendSrcA != s->blendSrcRGB ||\n'
     '              s->blendDstA != s->blendDstRGB))',
     '              0))'),
    ('an extra raster bit joins the known set',
     '#define RM_KNOWN        (RM_DEPTH | RM_BLEND | RM_TEXTURE | RM_ALPHA)',
     '#define RM_KNOWN        (RM_DEPTH | RM_BLEND | RM_TEXTURE | RM_ALPHA | 0x008UL)'),
    ('the texture bit is admitted without the field agreeing',
     '    else if (((s->rasterMask & RM_TEXTURE) != 0UL) != (s->texture != 0UL))\n'
     '        w = OSRDN_WHY_TEXTURE;\n', ''),
    ('no acceleration is folded into declined', '        return OSRDN_CLASS_NO_ACCEL;',
     '        return OSRDN_CLASS_WOULD_DECLINE;'),
]


def main():
    if not os.path.exists('/usr/lib32/libc.so.6'):
        print('  --   /usr/lib32/libc.so.6 not present, skipped')
        return 0
    src = open(UNIT).read()
    work = tempfile.mkdtemp(prefix='simclass.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    fails = 0

    lines, err = build_and_run(src, work)
    if lines is None:
        print('  FAIL the classifier does not build or run\n' + err)
        return 1
    probs = judge(lines)
    for x in probs:
        print('  FAIL %s' % x)
    fails += len(probs)
    if not probs:
        print('  ok   %d states, each giving the class and reason the plan states' % len(ROWS))
        # the message must say what was CHECKED, not what used to be true:
        # M1f widened the accepted set from two values to four and this line
        # went on printing 'exactly two'.
        acc = sorted(int(l.split()[1]) for l in lines if l.startswith('MASKTAKE '))
        print('  ok   of 8192 RasterMask values exactly %d are accepted: %s'
              % (len(acc), ', '.join('%#05x' % v for v in acc)))

    for label, old, new in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL mutation %-46s anchor found %d times' % (label, src.count(old)))
            fails += 1
            continue
        w2 = tempfile.mkdtemp(prefix='simclassm.', dir=os.environ.get('TMPDIR'))
        atexit.register(shutil.rmtree, w2, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
        ls, e2 = build_and_run(src.replace(old, new), w2)
        if ls is None:
            caught, why = True, 'does not build'
        else:
            p2 = judge(ls)
            caught, why = bool(p2), (p2[0] if p2 else '')
        print('  %-4s mutation %-46s %s' % ('ok' if caught else 'FAIL', label,
                                            why if caught else 'NOT CAUGHT'))
        fails += 0 if caught else 1

    print('sim_class: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
