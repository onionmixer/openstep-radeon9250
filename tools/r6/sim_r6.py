#!/usr/bin/env python3
"""R6a against the fake CP's 3D model (tools/r5/sim/world5.c), judged by the oracle
(tools/r6/zclear_oracle.py), then every mutation (docs/R6_PLAN.md 7).

  sim_r6.py        the baseline must PASS and every mutation must FAIL, in this run

For each ZCLEAR case the world prints every PACKET0 and PACKET3 the fake CP ran
(R6W / R6P3) and the driver's digests (R6DIG).  This script requires:
  - the executed register writes and the draw packet, in order, equal the
    oracle's prefix and draw streams (PACKET2 padding aside);
  - the driver's depth and colour digests, both passes, equal the oracle's for
    the tiled layout and Mesa's truncating depth conversion.

WHAT THIS PROVES: that the driver emits the reviewed stream and digests the
block the way the oracle does, against OUR model of the 3D engine (the model
draws with the same Mesa tile formula the oracle uses).  The hardware is judged
on the machine only (tools/r6/check_r6a.py).
"""

import importlib.util
import shutil
import atexit
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


zo = _load('zclear_oracle', os.path.join(HERE, 'zclear_oracle.py'))
to = _load('tri_oracle', os.path.join(HERE, 'tri_oracle.py'))
go = _load('gouraud_oracle', os.path.join(HERE, 'gouraud_oracle.py'))
GRULE = ('t16', (8, 8), ('q', 8, 'trunc', 'v0'), 'c', 'floor')    # the rule world5 interpolates with
do = _load('depth_oracle', os.path.join(HERE, 'depth_oracle.py'))  # R6f
te = _load('tex_oracle', os.path.join(HERE, 'tex_oracle.py'))      # R6h
pe = _load('persp_oracle', os.path.join(HERE, 'persp_oracle.py'))  # R6i
sc = _load('scissor_oracle', os.path.join(HERE, 'scissor_oracle.py'))  # R6k
ba = _load('batch_oracle', os.path.join(HERE, 'batch_oracle.py'))  # R6l
vo = _load('verify_oracle', os.path.join(PROJ, 'tools', 'r7', 'verify_oracle.py'))  # R7a
ru = _load('reuse_oracle', os.path.join(HERE, 'reuse_oracle.py'))  # R6m
s5 = _load('sim_r5', os.path.join(PROJ, 'tools', 'r5', 'sim_r5.py'))

WIN0 = 0x0029e000
CASE_NAME = {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'E', 6: 'F', 7: 'G', 8: 'H'}
CASE_NAME.update(dict((v, k) for k, v in to.CASE_NUM.items()))     # R6d: 9 .. 25
CASE_NAME.update(dict((v, k) for k, v in go.CASE_NUM.items()))     # R6e: 26 .. 59
CASE_NAME.update(dict((v, k) for k, v in do.CASE_NUM.items()))     # R6f: 60 .. 81
CASE_NAME.update(dict((v, k) for k, v in do.GCASE_NUM.items()))    # R6g: 82 .. 101
CASE_NAME.update(dict((v, k) for k, v in te.CASE_NUM.items()))     # R6h: 102 .. 108
CASE_NAME.update(dict((v, k) for k, v in pe.CASE_NUM.items()))     # R6i: 109 .. 124
CASE_NAME.update(dict((v, k) for k, v in sc.CASE_NUM.items()))     # R6k: 146 .. 160
CASE_NAME.update(dict((v, k) for k, v in ba.CASE_NUM.items()))     # R6l: 161 .. 165
CASE_NAME.update(dict((v, k) for k, v in ru.CASE_NUM.items()))     # R6m: 166 .. 170
CASE_NAME[171] = 'UC'                                              # R7a: the client's own stream

# M1m: read from the driver's header, never typed here -- if the driver widens
# or narrows the client's digest, this follows it or the comparison fails.
def _digest_words():
    import os as _os
    h = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..',
                      'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')
    m = re.search(r'#define\s+CP_R7_DIGEST_WORDS\s+(\d+)', open(h).read())
    if not m:
        raise RuntimeError('osrdn_cp.h has no CP_R7_DIGEST_WORDS')
    return int(m.group(1))


DIGEST_WORDS = _digest_words()

# the second lines of the case rows (anchored by the next row's comment: F and H share theirs)
_ROW = '    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, '
_A2 = '      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n' + _ROW + '0x3f000000UL, 0UL,     /* B'
_F2 = ('      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030078UL, 0x78563412UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n' + _ROW +
       '0x3f800000UL, 2UL,     /* G')
_G2 = ('      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030038UL, 0x78563412UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n' + _ROW +
       '0x3f800000UL, 2UL,     /* H')

MUTATIONS = [
    # R6l (docs/R6L_PLAN.md 5)
    ('a triangle of the big packet moves',
     'cpR6Poly[129][6] = {\n    { 0UL, 0UL, 0x40800000UL, 0UL, 0UL, 0x40800000UL }',
     'cpR6Poly[129][6] = {\n    { 0UL, 0UL, 0x40800000UL, 0UL, 0UL, 0x40000000UL }', 'osrdn_cp.m'),
    ('the packets of a batch come out in the wrong order',
     'for (b = 0; b < cs->bcount; b++) {\n            const unsigned long *pk = cpR6Pack[cs->bfirst - 1UL + b];\n            unsigned long t;',
     'for (b = 0; b < cs->bcount; b++) {\n            const unsigned long *pk = cpR6Pack[cs->bfirst - 1UL + (cs->bcount - 1UL - b)];\n            unsigned long t;',
     'osrdn_cp.m'),
    ('the clip moves without the wait the precedent puts first',
     '                w[n++] = C_P0(C_WAIT_UNTIL);        w[n++] = C_WAIT_3D_HOST;\n',
     '', 'osrdn_cp.m'),
    ('a batch packet claims one triangle too few',
     'w[n++] = C_P3_IMMD(15UL * pk[1]);', 'w[n++] = C_P3_IMMD(15UL * pk[1] - 15UL);', 'osrdn_cp.m'),
    # R6k (docs/R6K_PLAN.md 7)
    ('M1 keeps a rectangle the oracle does not',
     '{ 0x10000000UL, 0x30006UL, 0xd0014UL, 0UL, 0UL, 0UL, 0UL }   /* M1 */',
     '{ 0x10000000UL, 0x30007UL, 0xd0014UL, 0UL, 0UL, 0UL, 0UL }   /* M1 */', 'osrdn_cp.m'),
    ('the auxiliary control word is never written',
     '        w[n++] = C_P0(C_RE_AUX_SCISSOR_CNTL);   w[n++] = sc[0];\n',
     '        w[n++] = C_P0(C_RE_AUX_SCISSOR_CNTL);   w[n++] = 0UL;\n', 'osrdn_cp.m'),
    ('M7 draws the small box',
     '0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 7UL, 0UL, 0UL, 0UL, 0UL, 0UL }',
     '0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }',
     'osrdn_cp.m'),
    ('the depth pitch is 32, not 64', '#define CP_R6_PITCH             64UL', '#define CP_R6_PITCH             32UL', 'osrdn_cp.h'),
    ('the clip end is exclusive (cx2, not cx2 - 1)',
     '((cs->cy2 - 1UL) << 16) | (cs->cx2 - 1UL)', '((cs->cy2 - 1UL) << 16) | cs->cx2', 'osrdn_cp.m'),
    ('no Z cache purge in the tail', '    w[n++] = C_P0(C_RB3D_ZCACHE_CTLSTAT);   w[n++] = C_PURGE_ZC;\n    w[n++] = C_P0(C_WAIT_UNTIL);',
     '    w[n++] = C_P0(C_WAIT_UNTIL);', 'osrdn_cp.m'),
    ('RB3D_CNTL is not put back (operator D1)',
     '    w[n++] = C_P0(C_RB3D_CNTL);             w[n++] = 0UL;               /* operator D1 */\n', '', 'osrdn_cp.m'),
    ('the prefix leaves out RB3D_DEPTHOFFSET',
     '    w[n++] = C_P0(C_RB3D_DEPTHOFFSET);      w[n++] = c->winStart + cpR6DepthOff(cs);\n', '', 'osrdn_cp.m'),
    ('the prefix leaves out SE_VAP_CNTL_STATUS (xf86 R200 init)',
     '    w[n++] = C_P0(C_SE_VAP_CNTL_STATUS);    w[n++] = 0UL;\n', '', 'osrdn_cp.m'),
    ('the prefix read-back does not stop the draw',
     '    if ((c->prefixBad & CP_R6_PRE_GATE) != 0UL) {\n        c->failed = 1;', '    if (0) {\n        c->failed = 1;', 'osrdn_cp.m'),
    ('the surface gate is gone',
     '    if (c->surfaceCntl != C_SURF_TRANSLATION_DIS)\n        return cpRefused(c, CP_WHY_SURFACE, c->surfaceCntl);\n', '', 'osrdn_cp.m'),
    # M1h REFINED this, it did not drop it.  The rule used to be "every ZCLEAR
    # needs a ZPREP"; the client's stream is now exempt (docs/M1H_PLAN.md 7),
    # so the mutation removes the gate that is LEFT -- an R6 case measuring
    # against a pattern nobody laid down.  Both halves are checked: this one
    # proves the R6 gate still fires, and the one below proves the exemption
    # is for the client case ONLY.
    ('an R6 ZCLEAR does not need a ZPREP',
     '    if (zc != (unsigned long)CP_R7_CASE && !c->zprepped)\n        return cpRefused(c, CP_WHY_NOT_PREPPED, 0);\n', '', 'osrdn_cp.m'),
    ('the prep exemption is given to every case',
     'if (zc != (unsigned long)CP_R7_CASE && !c->zprepped)',
     'if (0 && !c->zprepped)', 'osrdn_cp.m'),
    ('the pattern is not the oracle\'s', '    return 0xa5000000UL | (i & 0xffffUL);', '    return 0xa5000000UL | (i & 0xfffeUL);', 'osrdn_cp.m'),
    ('the digest weight is off by one', '        d->wsum += w * (2UL * k + 1UL);', '        d->wsum += w * (2UL * k);', 'osrdn_cp.m'),
    ('case B draws at z 1.0', '0x41a80000UL, 0x3f000000UL, 0UL,     /* B', '0x41a80000UL, 0x3f800000UL, 0UL,     /* B', 'osrdn_cp.m'),
    ('case C writes RE_CNTL = 2 (scissor enable)',
     '0x42800000UL, 0x42000000UL, 0x3f800000UL, 0UL,     /* C', '0x42800000UL, 0x42000000UL, 0x3f800000UL, 2UL,     /* C',
     'osrdn_cp.m'),
    ('case D writes RE_CNTL = 0',
     '0x42800000UL, 0x42000000UL, 0x3f800000UL, 2UL,     /* D', '0x42800000UL, 0x42000000UL, 0x3f800000UL, 0UL,     /* D',
     'osrdn_cp.m'),
    ('E\'s TL is C\'s (the model is blind to TL with RE_CNTL 0: only the stream sees it)',
     '    { 20, 12, 37, 21, 0x00000000UL,', '    { 5, 3, 37, 21, 0x00000000UL,', 'osrdn_cp.m'),
    ('the per-case RE_CNTL is not written into the state block', '    w[st + 5] = cs->recntl;', '    (void)cs->recntl;', 'osrdn_cp.m'),
    # M3f: 'a 3D packet may cross the ring end' was a mutation here; it is now the
    # driver's behaviour (docs/M3F_PLAN.md), and check_r5_src's m3f-wrap-like-bsd
    # catches the opposite -- the fill to the end coming back.
    ('the prefix leaves out RB3D_DEPTHXY_OFFSET',
     '    w[n++] = C_P0(C_RB3D_DEPTHXY_OFFSET);   w[n++] = 0UL;       /* Mesa\'s init value (8-2 M1) */\n', '', 'osrdn_cp.m'),
    ('the gate also stops on the front-end registers', '#define CP_R6_PRE_GATE          0x10fUL', '#define CP_R6_PRE_GATE          0x1ffUL',
     'osrdn_cp.h'),
    ('ZPREP runs with the CP stopped',
     '    if (c->state != CP_ST_RUNNING)          /* R4 engine operations are refused meanwhile (8-2 m5) */\n'
     '        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);\n', '', 'osrdn_cp.m'),
    # R6c (docs/R6C_PLAN.md 6)
    ('F without the order bit (F = G)', _F2, _F2.replace('0x00030078UL', '0x00030038UL'), 'osrdn_cp.m'),
    ('G with the order bit (G = F)', _G2, _G2.replace('0x00030038UL', '0x00030078UL'), 'osrdn_cp.m'),
    ('F\'s colour word is the pixel, not r g b a', _F2, _F2.replace('0x78563412UL', '0x78123456UL'), 'osrdn_cp.m'),
    ('F\'s SE_VTX_STATE_CNTL is 0 (F = H)', _F2, _F2.replace('0x803UL, 0x10000UL', '0x803UL, 0UL'), 'osrdn_cp.m'),
    ('F\'s header counts one word short', _F2, _F2.replace('0xc00f3500UL', '0xc00e3500UL'), 'osrdn_cp.m'),
    ('F\'s header counts one word long', _F2, _F2.replace('0xc00f3500UL', '0xc0103500UL'), 'osrdn_cp.m'),
    ('A carries F\'s colour state', _A2, _A2.replace('0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL',
                                                      '0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030078UL, 0x78563412UL'),
     'osrdn_cp.m'),
    ('blend stage 0 misses TXCBLEND2', '        w[n++] = C_P0(C_PP_TXCBLEND2_0);    w[n++] = C_TXBLEND2_R0;\n', '', 'osrdn_cp.m'),
    ('the third vertex has no colour word',
     '        w[n++] = cs->gx2; w[n++] = cs->gy2; w[n++] = cs->z; w[n++] = C_FLOAT_ONE;\n        if (cs->fmt & C_VTX_COLOR0)\n            w[n++] = cs->colour;\n',
     '        w[n++] = cs->gx2; w[n++] = cs->gy2; w[n++] = cs->z; w[n++] = C_FLOAT_ONE;\n', 'osrdn_cp.m'),
    ('the plane mask is not written (colour cases keep 0)', '    w[st + 13] = cs->planemask;', '    (void)cs->planemask;', 'osrdn_cp.m'),
    ('PP_CNTL is not written', '    w[st + 3] = cs->ppcntl;', '    (void)cs->ppcntl;', 'osrdn_cp.m'),
    ('SE_VTX_FMT_0 is not written', '    w[st + 19] = cs->fmt;', '    (void)cs->fmt;', 'osrdn_cp.m'),
    ('the prefix writes SE_VTX_STATE_CNTL 0 for every case',
     '    w[n++] = C_P0(C_SE_VTX_STATE_CNTL);     w[n++] = cs->vsc;', '    w[n++] = C_P0(C_SE_VTX_STATE_CNTL);     w[n++] = 0UL;', 'osrdn_cp.m'),
    ('the prefix read-back expects SE_VTX_STATE_CNTL 0',
     '    if (k == 7 && c->zcase >= 1 && c->zcase <= CP_R6_CASES)\n', '    if (0)\n', 'osrdn_cp.m'),
    # R6d (docs/R6D_PLAN.md 10)
    ('a triangle vertex moves by one float32 step',
     '{ 0x40800000UL, 0x40800000UL, 0x78563412UL }, { 0x41e00000UL, 0x40800000UL, 0x78563412UL }, { 0x40800000UL, 0x41e00000UL, 0x78563412UL } } }   /* T1 */',
     '{ 0x40800001UL, 0x40800000UL, 0x78563412UL }, { 0x41e00000UL, 0x40800000UL, 0x78563412UL }, { 0x40800000UL, 0x41e00000UL, 0x78563412UL } } }   /* T1 */',
     'osrdn_cp.m'),
    ('T1 drawn as a RECT_LIST', '0xc00f3500UL, 0x00030074UL, 0UL, 1UL,', '0xc00f3500UL, 0x00030078UL, 0UL, 1UL,', 'osrdn_cp.m'),
    ('T3 counts one vertex short', '0xc01e3500UL, 0x00060074UL, 0UL, 3UL,', '0xc01e3500UL, 0x00050074UL, 0UL, 3UL,', 'osrdn_cp.m'),
    ('T3 names the second colour as the first', '0x00060074UL, 0UL, 3UL, 0x78123456UL, 0x3c9abcdeUL',
     '0x00060074UL, 0UL, 3UL, 0x78123456UL, 0x78123456UL', 'osrdn_cp.m'),
    ('a triangle case uses the box emitter', '    } else if (tr != 0) {                       /* R6d: the triangles, colour after W */',
     '    } else if (0) {                       /* R6d: the triangles, colour after W */', 'osrdn_cp.m'),
    ('the map code is shifted by one pixel', '            c->cov[i >> 4] |= code << (2UL * (i & 15UL));',
     '            c->cov[i >> 4] |= code << (2UL * ((i + 1UL) & 15UL));', 'osrdn_cp.m'),
    ('the map reads the depth buffer', '            unsigned long at = cpR6ColorOff(cs) / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), code;',
     '            unsigned long at = cpR6DepthOff(cs) / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), code;', 'osrdn_cp.m'),
    ('the triangle clip is 32 x 32', '    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T1 */',
     '    { 0, 0, 32, 32, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T1 */', 'osrdn_cp.m'),
    # R6e (docs/R6E_PLAN.md 9)
    ('SE_CNTL is not patched (Gouraud cases stay flat)', '    w[st + 15] = cs->secntl;', '    (void)cs->secntl;', 'osrdn_cp.m'),
    ('a plane byte from the wrong lane', '                b = (v >> (8UL * l)) & 0xffUL;', '                b = (v >> (8UL * (l ^ 1UL))) & 0xffUL;', 'osrdn_cp.m'),
    ('a plane byte in the wrong pixel slot', '                    c->plane[l][i >> 2] |= b << (8UL * (i & 3UL));',
     '                    c->plane[l][i >> 2] |= b << (8UL * ((i + 1UL) & 3UL));', 'osrdn_cp.m'),
    ('the lane misses count the varying lanes', '                if (!(cs->gvary & (1UL << l)) && b != ((cs->gconst >> (8UL * l)) & 0xffUL))',
     '                if (b != ((cs->gconst >> (8UL * l)) & 0xffUL))', 'osrdn_cp.m'),
    ('every lane is logged', '    c->planeLanes = cs->lanes;', '    c->planeLanes = 0xfUL;', 'osrdn_cp.m'),
    ('N1 vertex 0 R byte off by one', '{ 0x41e63127UL, 0x41e9ba5eUL, 0xbb5634bbUL }, { 0x41c91893UL', '{ 0x41e63127UL, 0x41e9ba5eUL, 0xbb5634baUL }, { 0x41c91893UL', 'osrdn_cp.m'),
    ('ZPREP and ZCLEAR do not clear the planes first', '    if (op == CP_OP_ZPREP || op == CP_OP_ZCLEAR)\n        c->planeValid = 0;',
     '    if (0)\n        c->planeValid = 0;', 'osrdn_cp.m'),
    ('PLANE does not check the stored lanes', '    if (len >= 16UL || !c->planeValid || !(c->planeLanes & (1UL << (len >> 2))))',
     '    if (len >= 16UL || !c->planeValid)', 'osrdn_cp.m'),
    ('PLANE accepts len 16', '    if (len >= 16UL || !c->planeValid || !(c->planeLanes & (1UL << (len >> 2))))',
     '    if (len >= 17UL || !c->planeValid || !(c->planeLanes & (1UL << ((len >> 2) & 3UL))))', 'osrdn_cp.m'),
    ('the planes are published with the wrong operation number', '        c->planeZop = c->ops;', '        c->planeZop = c->ops - 1UL;', 'osrdn_cp.m'),
    ('the colour buffer overlaps the depth buffer', '#define CP_R6_COLOR_OFF         0x3c000UL', '#define CP_R6_COLOR_OFF         0x02000UL',
     'osrdn_cp.h'),
    # R6f (docs/R6F_PLAN.md 5)
    ('ZSTENCILCNTL is not written (16-bit cases draw 24-bit)', '    w[st + 9] = cs->zcntl;', '    (void)cs->zcntl;', 'osrdn_cp.m'),
    ('K16a carries the 24-bit ZSTENCILCNTL', '0x42227070UL, 0UL, 1UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', '0x42227072UL, 0UL, 1UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', 'osrdn_cp.m'),
    ('the driver\'s mba_z16 swaps x4 and x5', '(((x >> 4) & 1UL) << 6) | (((x >> 5) & 1UL) << 7) | (((x >> 3) & 1UL) << 8) |',
     '(((x >> 5) & 1UL) << 6) | (((x >> 4) & 1UL) << 7) | (((x >> 3) & 1UL) << 8) |', 'osrdn_cp.m'),
    ('the 16-bit plane reads the other halfword',
     'v = (((volatile unsigned long *)c->alias)[(cpR6DepthOff(cs) + a) / 4UL] >> (16UL * ((a >> 1) & 1UL))) & 0xffffUL;',
     'v = (((volatile unsigned long *)c->alias)[(cpR6DepthOff(cs) + a) / 4UL] >> (16UL * (((a >> 1) & 1UL) ^ 1UL))) & 0xffffUL;',
     'osrdn_cp.m'),
    ('the 16-bit plane uses the 24-bit address', '            if (cs->dsrc == 1UL) {\n                a = cpMbaZ32',
     '            if (cs->dsrc != 0UL) {\n                a = cpMbaZ32', 'osrdn_cp.m'),
    ('every vertex takes the z row\'s first z', '(cs->zrow != 0UL) ? cpR6Zv[cs->zrow - 1UL][i] : cs->z;',
     '(cs->zrow != 0UL) ? cpR6Zv[cs->zrow - 1UL][0] : cs->z;', 'osrdn_cp.m'),
    ('the grid skips its first cell', '        for (i = 0; i < CP_R6_CELLS; i++) {', '        for (i = 1; i < CP_R6_CELLS; i++) {', 'osrdn_cp.m'),
    ('the word array is too small for the biggest packet (the guard must refuse)',
     '#define CP_R6_WORDS             4080', '#define CP_R6_WORDS             1240', 'osrdn_cp.h'),
    ('the word count is off by one (the n == need check must refuse)',
     '    need = 26UL + ((cs->ppcntl != 0UL) ? 8UL : 0UL) + 4UL + 2UL + nvert * vw + 10UL;',
     '    need = 26UL + ((cs->ppcntl != 0UL) ? 8UL : 0UL) + 4UL + 2UL + nvert * vw + 11UL;', 'osrdn_cp.m'),
    ('the plane source is not recorded', '    c->planeSrc = cs->dsrc;', '', 'osrdn_cp.m'),
    ('an anchor moves by one float32 step', '0x3cd54000UL, 0x3f419601UL', '0x3cd54001UL, 0x3f419601UL', 'osrdn_cp.m'),
    ('the grid\'s colour word is the pixel', '0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 1UL,',
     '0xc0f03500UL, 0x300074UL, 0x78123456UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 1UL,', 'osrdn_cp.m'),
    ('I3 reads the 16-bit plane lanes only', '0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 3UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }',
     '0x480055deUL, 3UL, 0UL, 0UL, 0x42227072UL, 3UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', 'osrdn_cp.m'),
    # R6g (docs/R6G_PLAN.md 2, 6)
    ('the prefill ramp is flat (B = 0)', '{ 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GN */',
     '{ 1UL, 0x3c00UL, 0UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GN */', 'osrdn_cp.m'),
    ('the prefill writes 24-bit words in a 16-bit case', '            if (cs->dsrc == 2UL) {\n                a = cpMbaZ16(CP_R6_PITCH, x, y);\n                k = (cpR6DepthOff(cs) + a) / 4UL;',
     '            if (0) {\n                a = cpMbaZ16(CP_R6_PITCH, x, y);\n                k = (cpR6DepthOff(cs) + a) / 4UL;', 'osrdn_cp.m'),
    ('no cache purge before the draw', '        w[n++] = C_P0(C_RB3D_DSTCACHE_CTLSTAT); w[n++] = C_PURGE_DC;\n        w[n++] = C_P0(C_RB3D_ZCACHE_CTLSTAT);   w[n++] = C_PURGE_ZC;\n',
     '', 'osrdn_cp.m'),
    ('the second draw keeps the first ZSTENCILCNTL', '        w[n++] = C_P0(C_RB3D_ZSTENCILCNTL);     w[n++] = g[4];\n',
     '', 'osrdn_cp.m'),
    ('every two-draw case waits between the draws', '        if (g[9] != 0UL) {', '        if (1) {', 'osrdn_cp.m'),
    ('RB3D_CNTL is not patched (Z_ENABLE always on)', '    w[st + 7] = cs->rb3d;', '    (void)cs->rb3d;', 'osrdn_cp.m'),
    ('the second draw carries the first draw\'s colour', '            w[n++] = g[8];', '            w[n++] = tr->v[i][2];', 'osrdn_cp.m'),
    ('every second-draw vertex takes the first z', 'w[n++] = g[5 + i];', 'w[n++] = g[5];', 'osrdn_cp.m'),
    ('the write bit is dropped from the second draw', 'w[n++] = C_P0(C_RB3D_ZSTENCILCNTL);     w[n++] = g[4];',
     'w[n++] = C_P0(C_RB3D_ZSTENCILCNTL);     w[n++] = g[4] & ~0x40000000UL;', 'osrdn_cp.m'),
    # R6h (docs/R6H_PLAN.md 2)
    ('the texture offset misses the texture area', 'w[n++] = C_P0(C_PP_TXOFFSET_0);     w[n++] = c->winStart + cpR6TexOff(cs);',
     'w[n++] = C_P0(C_PP_TXOFFSET_0);     w[n++] = c->winStart;', 'osrdn_cp.m'),
    ('the texture filter register carries the format', 'w[n++] = C_P0(C_PP_TXFILTER_0);     w[n++] = tx[3];',
     'w[n++] = C_P0(C_PP_TXFILTER_0);     w[n++] = tx[4];', 'osrdn_cp.m'),
    ('SE_VTX_FMT_1 keeps 0 (no ST in the vertex)', '        w[st + 21] = C_VTX_FMT_1_ST;', '        (void)0;', 'osrdn_cp.m'),
    ('s and t are swapped in the vertex', '                w[n++] = cpR6T[cs->tidx - 1UL][7 + 2UL * i];\n                w[n++] = cpR6T[cs->tidx - 1UL][8 + 2UL * i];',
     '                w[n++] = cpR6T[cs->tidx - 1UL][8 + 2UL * i];\n                w[n++] = cpR6T[cs->tidx - 1UL][7 + 2UL * i];', 'osrdn_cp.m'),
    ('the texel formula swaps u and v', 'return 0xff000000UL | ((u * 32UL) << 16) | ((v * 32UL) << 8) | 0x55UL;',
     'return 0xff000000UL | ((v * 32UL) << 16) | ((u * 32UL) << 8) | 0x55UL;', 'osrdn_cp.m'),
    ('the texture fill ignores the row stride', 'al[(cpR6TexOff(cs) + vv * stride) / 4UL + u] = cpR6Texel(pat, u, vv);',
     'al[(cpR6TexOff(cs) + vv * tw * 4UL) / 4UL + u] = cpR6Texel(pat, u, vv);', 'osrdn_cp.m'),
    ('PP_TXSIZE is not written', '        w[n++] = C_P0(C_PP_TXSIZE_0);       w[n++] = tx[5];\n', '', 'osrdn_cp.m'),
    # R6i (docs/R6I_PLAN.md 2-1)
    ('the vertices keep W = 1 (the W row is ignored)', 'w[n++] = (wv != 0) ? wv[i] : C_FLOAT_ONE;',
     'w[n++] = C_FLOAT_ONE;', 'osrdn_cp.m'),
    ('the W row is taken one too far', 'wv = (cs->widx != 0UL) ? cpR6W[cs->widx - 1UL] : 0;',
     'wv = (cs->widx != 0UL) ? cpR6W[cs->widx % CP_R6_WROWS] : 0;', 'osrdn_cp.m'),
    ('SE_VTE_CNTL is not patched', '        w[st + 17] = cs->vte;', '        w[st + 17] = w[st + 17];', 'osrdn_cp.m'),
    ('the texel pattern is ignored (always the R6h ramp)', 'cpR6Texel(unsigned long pat, unsigned long u, unsigned long v)\n{\n    if (pat == 1UL)',
     'cpR6Texel(unsigned long pat, unsigned long u, unsigned long v)\n{\n    if (pat == 9UL)', 'osrdn_cp.m'),
    ('PP_TXFORMAT_X keeps zero', 'w[n++] = tx[14];   /* R6i: TEXCOORD_PROJ in PH */', 'w[n++] = 0UL;', 'osrdn_cp.m'),
    # R6i-2 (docs/R6I2_PLAN.md 2-1)
    ('the new triangle is the old one', '{ 0x40800000UL, 0x41a00000UL, 0x78563412UL } } }   /* T2p */',
     '{ 0x40800000UL, 0x41e00000UL, 0x78563412UL } } }   /* T2p */', 'osrdn_cp.m'),
    # R6j (docs/R6J_PLAN.md 2-1)
    ('the second draw does not turn blending on', '            w[n++] = C_P0(C_RB3D_CNTL);         w[n++] = g[11];',
     '            w[n++] = C_P0(C_RB3D_CNTL);         w[n++] = 0x1902UL;', 'osrdn_cp.m'),
    ('the blend register carries the ZSTENCILCNTL value', 'w[n++] = C_P0(C_RB3D_BLENDCNTL);    w[n++] = g[10];',
     'w[n++] = C_P0(C_RB3D_BLENDCNTL);    w[n++] = g[4];', 'osrdn_cp.m'),
    # R6i-3 (docs/R6I3_PLAN.md 2-1)
    ('pattern 3 is not transposed', 'if (pat == 3UL)                             /* R6i-3: pattern 2 transposed (docs/R6I3_PLAN.md 2-1) */\n        return 0xff000000UL | ((255UL * (v & 1UL)) << 16) | ((255UL * (u & 1UL)) << 8) | 0x55UL;',
     'if (pat == 3UL)                             /* R6i-3: pattern 2 transposed (docs/R6I3_PLAN.md 2-1) */\n        return 0xff000000UL | ((255UL * (u & 1UL)) << 16) | ((255UL * (v & 1UL)) << 8) | 0x55UL;', 'osrdn_cp.m'),
    ('N5 carries the FILTER_ROUND_MODE bit too', '0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 32UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }',
     '0x1410UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 32UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', 'osrdn_cp.m'),
    ('Q2 takes Q1\'s t (the fv = 1/2 case is lost)',
     '0x3e004000UL, 0x3e800000UL, 0x3e802000UL, 0x3e800000UL, 0x3e084000UL, 0x3e800000UL, 2UL, 0UL }   /* Q2 */',
     '0x3e004000UL, 0x3e400000UL, 0x3e802000UL, 0x3e400000UL, 0x3e084000UL, 0x3e400000UL, 2UL, 0UL }   /* Q2 */', 'osrdn_cp.m'),
    # R7a (docs/R7_PLAN.md 5 gate S3): every verifier rule, weakened one at a time.  The streams
    # world5 stages are built so that exactly one rule refuses each, so a rule that stops refusing
    # shows up as a case that ran when it should not have.
    ("the allow-list is not consulted", '            if (!cpR7RegAllowed(reg))\n                return CP_R7_WHY_P0_REG;',
     '            if (0)\n                return CP_R7_WHY_P0_REG;', 'osrdn_cp.m'),
    ("the value masks are not consulted", '            if (!cpR7ValueAllowed(reg, val))\n                return CP_R7_WHY_P0_VALUE;',
     '            if (0)\n                return CP_R7_WHY_P0_VALUE;', 'osrdn_cp.m'),
    ("packet types 1 and 2 are let through",
     '        if (t == 1UL || t == 2UL)\n            return CP_R7_WHY_TYPE;',
     '        if (0)\n            return CP_R7_WHY_TYPE;', 'osrdn_cp.m'),
    ("the packet type is read from the wrong bits", '        t = hdr >> 30;', '        t = hdr >> 28;',
     'osrdn_cp.m'),
    ("a PACKET0 may write a run of registers",
     '            if ((hdr & 0x8000UL) != 0UL || ((hdr >> 16) & 0x3fffUL) != 0UL)\n                return CP_R7_WHY_P0_COUNT;',
     '            if (0)\n                return CP_R7_WHY_P0_COUNT;', 'osrdn_cp.m'),
    ("the draw header's count is not cross-checked",
     '        if (cnt - 1UL != vw * nv)               /* cnt counts VF_CNTL as well */\n            return CP_R7_WHY_COUNT;',
     '        if (0)\n            return CP_R7_WHY_COUNT;', 'osrdn_cp.m'),
    ("VF_CNTL is not checked",
     '        if ((vf & ~CP_R7_VF_ALLOWED) != 0UL ||\n            (vf & CP_R7_VF_WALK_MASK) != CP_R7_VF_WALK_RING ||\n            (vf & CP_R7_VF_PRIM_MASK) != CP_R7_VF_PRIM_TRIANGLES)\n            return CP_R7_WHY_VF;',
     '        if (0)\n            return CP_R7_WHY_VF;', 'osrdn_cp.m'),
    ("the surface footprint ignores the pitch",
     '    span = p * 4UL * r;',
     '    span = 4UL * r;', 'osrdn_cp.m'),
    # M3h (docs/M3H_PLAN.md 4): the rows come from the stream's clip, and nothing may widen them
    ("a draw without its own RE_WIDTH_HEIGHT is allowed",           # G4-4 K7: the check lives in cpR7SurfacesOk
     '    if (!haveWH)\n        return 0;\n',
     '    if (0)\n        return 0;\n', 'osrdn_cp.m'),
    ("the footprint counts 64 rows again, whatever the clip",
     '    unsigned long p = pitch & CP_R7_PITCH_MASK, r = rows, span;',
     '    unsigned long p = pitch & CP_R7_PITCH_MASK, r = 64UL, span;', 'osrdn_cp.m'),
    ("a clip wider than the pitch is allowed",
     '    if (p == 0UL || cols > p || r == 0UL)',
     '    if (p == 0UL || r == 0UL)', 'osrdn_cp.m'),
    ("depth rows are not taken up to the tile",
     '        r = (r + 15UL) & ~15UL;',
     '        r = r;', 'osrdn_cp.m'),
    ("a depth pitch of part tiles is allowed",
     '        if ((p & 31UL) != 0UL)\n            return 0;',
     '        if (0)\n            return 0;', 'osrdn_cp.m'),
    ("a pitch word may carry tiling bits",
     '    if ((reg == C_RB3D_COLORPITCH || reg == C_RB3D_DEPTHPITCH) && (val & ~CP_R7_PITCH_MASK) != 0UL)',
     '    if (0 && (val & ~CP_R7_PITCH_MASK) != 0UL)', 'osrdn_cp.m'),
    ("RB3D_CNTL may switch the depth XY offset on",
     '    if (reg == C_RB3D_CNTL && (val & CP_R7_RB3D_XY_OFFSET) != 0UL)',
     '    if (0 && (val & CP_R7_RB3D_XY_OFFSET) != 0UL)', 'osrdn_cp.m'),
    ("RB3D_DEPTHXY_OFFSET may be non-zero",
     '    if (reg == C_RB3D_DEPTHXY_OFFSET && val != 0UL)',
     '    if (0 && val != 0UL)', 'osrdn_cp.m'),
    ("the prefix's surfaces are not judged",
     '    coff = defC; cpitch = defPitch; zoff = defZ; zpitch = defPitch;',
     '    coff = c->winStart; cpitch = 8UL; zoff = c->winStart; zpitch = 32UL;', 'osrdn_cp.m'),
    ("a draw before the format is stated is allowed",
     '        if (!sawFmt)\n            return CP_R7_WHY_VTX_UNSET; /* the prefix defines it, but a client must still say so */',
     '        if (0)\n            return CP_R7_WHY_VTX_UNSET;', 'osrdn_cp.m'),
    ("an unmeasured vertex format is accepted",
     '    if ((fmt0 & ~CP_R7_VTX0_ALLOWED) != 0UL)\n        return 0UL;',
     '    if (0)\n        return 0UL;', 'osrdn_cp.m'),
    ("the client's words are copied before they are judged",
     '                              c->winStart + cpR6DepthOff(cs), CP_R6_PITCH);\n        if (c->r7Why != (unsigned long)CP_R7_WHY_OK)\n            return cpRefused(c, CP_WHY_R7, c->r7Why);',
     '                              c->winStart + cpR6DepthOff(cs), CP_R6_PITCH);', 'osrdn_cp.m'),
    # R6m (docs/R6M_PLAN.md 5): a surface the case moved but the driver does not
    ("the case's colour surface is ignored",
     'return (cs != 0 && cs->coff != 0UL) ? cs->coff : CP_R6_COLOR_OFF;',
     'return CP_R6_COLOR_OFF;', 'osrdn_cp.m'),
    ("the case's depth surface is ignored",
     'return (cs != 0 && cs->zoff != 0UL) ? cs->zoff : CP_R6_DEPTH_OFF;',
     'return CP_R6_DEPTH_OFF;', 'osrdn_cp.m'),
    ("the case's texture surface is ignored",
     'return (cs != 0 && cs->toff != 0UL) ? cs->toff : CP_R6_TEX_OFF;',
     'return CP_R6_TEX_OFF;', 'osrdn_cp.m'),
]


_sigs = []


def SIGS():
    if not _sigs:
        _sigs.append(to.named_signatures())         # the judge's space: every named rule (docs/R6D_PLAN.md 11)
    return _sigs[0]


def expected_writes(case, seed):
    """[(kind, value)] the fake CP must run for one ZCLEAR: ('w', (reg, val)) and ('p3', words)"""
    out = []
    name = CASE_NAME[case]
    if name == 'UC':
        # R7a: the prefix gains the vertex-format pair (docs/R7_PLAN.md 4-1 c), and the draw
        # submission is our WAIT_UNTIL, the CLIENT's words, and our tail
        pre = list(zo.prefix_words(WIN0, seed, 'F'))
        k = pre.index(zo.p0(zo.PP_TRI_PERF))      # G4-7: the format pair goes before the TRI_PERF pair (osrdn_cp.m)
        pre = pre[:k] + [zo.p0(zo.V('R200_SE_VTX_FMT_0')), 3,
                         zo.p0(zo.V('R200_SE_VTX_FMT_1')), 0] + pre[k:]
        tail = zo.draw_words('F', seed)[-10:]
        streams = (pre, [zo.p0(zo.V('RADEON_WAIT_UNTIL')), 0x00050000] + vo.stream_u1() + list(tail))
    elif name in ru.SCASES:
        # R6m: the prefix names this case's surfaces, and the draw its texture (docs/R6M_PLAN.md 4)
        streams = (ru.prefix_words(WIN0, seed, name), ru.draw_words(name, seed, WIN0))
    elif name in ba.SCASES:
        streams = (to.prefix_words(WIN0, seed), ba.draw_words(name, seed))
    elif name in sc.SCASES:
        streams = (to.prefix_words(WIN0, seed), sc.draw_words(name, seed))
    elif name in pe.CASE_NUM:
        streams = (to.prefix_words(WIN0, seed), pe.draw_words(name, seed, WIN0))
    elif name in te.CASE_NUM:
        streams = (to.prefix_words(WIN0, seed), te.draw_words(name, seed, WIN0))
    elif name in do.GCASE_NUM:
        streams = (to.prefix_words(WIN0, seed), do.g_draw_words(name, seed))
    elif name in do.CASE_NUM:
        streams = (to.prefix_words(WIN0, seed), do.draw_words(name, seed))
    elif name in go.GCASES:
        streams = (to.prefix_words(WIN0, seed), go.draw_words(name, seed))
    elif name in to.TRI:
        streams = (to.prefix_words(WIN0, seed), to.draw_words(name, seed))
    else:
        streams = (zo.prefix_words(WIN0, seed, name), zo.draw_words(name, seed))
    for words in streams:
        k = 0
        while k < len(words):
            if words[k] & 0xc0000000:           # the draw packet: header + count + 1
                n = ((words[k] >> 16) & 0x3fff) + 2
                out.append(('p3', tuple(words[k:k + n])))
                k += n
            else:
                out.append(('w', ((words[k] & 0x1fff) << 2, words[k + 1])))
                k += 2
    return out


def judge(out):
    p = []
    cases = {}
    cur = None
    for line in out.splitlines():
        m = re.match(r'R6CASE (\d+) ([0-9a-f]{8})', line)
        if m:
            cur = int(m.group(1))
            cases[cur] = dict(seed=int(m.group(2), 16), got=[], dig={})
            continue
        m = re.match(r'R6W ([0-9a-f]{4}) ([0-9a-f]{8})', line)
        if m and cur:
            cases[cur]['got'].append(('w', (int(m.group(1), 16), int(m.group(2), 16))))
            continue
        # R6l: the batch packets are much longer than the old 242-word cap
        m = re.match(r'R6P3 ((?:[0-9a-f]{8} ?){14,1300})$', line)
        if m and cur:
            cases[cur]['got'].append(('p3', tuple(int(x, 16) for x in m.group(1).split())))
            continue
        m = re.match(r'R6OFF (\d+) (\d+) (\d+) (\d+) (\d+) ([0-9a-f]+) (\d+)$', line)
        if m:
            cases[int(m.group(1))]['off'] = [int(m.group(k)) for k in range(2, 6)]
            cases[int(m.group(1))]['lanes'] = int(m.group(6), 16)
            cases[int(m.group(1))]['src'] = int(m.group(7))        # R6f
            continue
        m = re.match(r'R6PL (\d+) (\d) ((?:[0-9a-f]{8} ?){256})$', line)
        if m:
            cases[int(m.group(1))].setdefault('pl', {})[int(m.group(2))] = [int(x, 16) for x in m.group(3).split()]
            continue
        m = re.match(r'R6COV (\d+) ((?:[0-9a-f]{8} ?){64})$', line)
        if m:
            cases[int(m.group(1))]['cov'] = [int(x, 16) for x in m.group(2).split()]
            continue
        m = re.match(r'R6DIG (\d+) (\d) (\w+) ([0-9a-f]{8}) ([0-9a-f]{8}) (\d+) (\d+) (\d+) (\d) ((?:[0-9a-f]{8} ?){4})', line)
        if m:
            c = int(m.group(1))
            vals = [int(x, 16) for x in m.group(10).split()][:int(m.group(9))]
            cases[c]['dig'][(int(m.group(2)), m.group(3))] = dict(
                xor=int(m.group(4), 16), wsum=int(m.group(5), 16), changed=int(m.group(6)), ixor=int(m.group(7)),
                isum=int(m.group(8)), vals=vals)
    if sorted(cases) != sorted(CASE_NAME):
        return ['cases seen %s, want %s' % (sorted(cases), sorted(CASE_NAME))]
    got = tuple(tuple(cases[to.CASE_NUM[n]].get('cov') or ()) for n in to.GATED)
    match = [name for name, sig in SIGS() if sig == got]
    # the gated maps cannot split the measured rule from its winding twin (R6d 13: T1r did)
    if ('gated', to.MEASURED) not in match or any(m[1][:4] != to.MEASURED[:4] for m in match):
        p.append('the maps select %s, the model draws %s' % (match[:4], to.MEASURED))
    # R6e: the planes select the rule world5 interpolates with (RGB and alpha alike)
    for kind in ('RGB', 'A'):
        planes, sig, by = go.classes(kind)
        obs = {}
        for n, l in planes:
            obs[(n, l)] = (cases[go.CASE_NUM[n]].get('pl') or {}).get('BGRA'.index(l), [0] * 256)
        got = go.observed_sig(planes, obs)
        m = [go.ALL[k] for k in by.get(got, [])]
        if GRULE not in m:
            p.append('%s planes select %s, the model interpolates with %s' % (kind, m[:4], GRULE))
    # R6f: the 64 anchors read back through the planes name the model's conversion (both formats)
    for bits in (16, 24):
        obs = []
        for g in 'abcd':
            n = 'K%d%s' % (bits, g)
            pl = cases[do.CASE_NUM[n]].get('pl') or {}
            if sorted(pl) != list(range(len(pl))) or len(pl) != (2 if bits == 16 else 3):
                obs += [None] * 16
                continue
            vals = do.values_from_planes(pl, bits)
            for z, cell in do.cell_values(n, vals):
                obs.append(cell[0] if len(set(cell)) == 1 else None)
        names, near = do.name_conversion(bits, obs)
        if do.SIM_CONV not in names:
            p.append('%d-bit anchors name %s (nearest %s), the model converts with %s' % (bits, names[:3], near, do.SIM_CONV))
    for c, d in sorted(cases.items()):
        # the CP also runs the SUBMIT-free stream only: drop scratch sentinel writes? none go through the ring
        want = expected_writes(c, d['seed'])
        if d['got'] != want:
            first = next((k for k, (g, w) in enumerate(zip(d['got'], want)) if g != w), min(len(d['got']), len(want)))
            p.append('case %s: the CP ran %d items, the oracle wants %d; first difference at %d: %s vs %s' % (
                CASE_NAME[c], len(d['got']), len(want), first,
                d['got'][first] if first < len(d['got']) else None, want[first] if first < len(want) else None))
        if CASE_NAME[c] in pe.CASE_NUM and pe.kind(CASE_NAME[c]) in ('gouraud', 'depth'):
            # R6i: PE and PZ are their control cases as far as the model is concerned (it has no
            # perspective divide): the same planes as V8 and I1_24 (tools/r6/persp_oracle.py SIM_ALIAS)
            n = CASE_NAME[c]
            a = pe.SIM_ALIAS[n]
            if pe.kind(n) == 'gouraud':
                blk = go.expected_block(a, GRULE, GRULE)
                if d.get('lanes') != go.lanes_mask(a):
                    p.append('case %s: lanes %s, want %x' % (n, d.get('lanes'), go.lanes_mask(a)))
                for l in 'BGRA':
                    if go.lanes_mask(a) & go.LANE_BIT[l]:
                        if (d.get('pl') or {}).get('BGRA'.index(l)) != go.plane_words(go.expected_values(a, l, GRULE)):
                            p.append('case %s: plane %s differs from the oracle' % (n, l))
            else:
                blk = do.full_block(a)
                if (d.get('lanes'), d.get('src')) != (do.lanes(a), do.dsrc(a)):
                    p.append('case %s: lanes %s src %s' % (n, d.get('lanes'), d.get('src')))
                want = do.plane_words(blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + zo.BUF_BYTES // 4], do.fmt_bits(a))
                for l, wds in want.items():
                    if (d.get('pl') or {}).get(l) != wds:
                        p.append('case %s: depth plane %d differs from the model' % (n, l))
                if d.get('cov') != do.coverage_words(a):
                    p.append('case %s: coverage map differs from the model' % n)
        elif CASE_NAME[c] in te.CASE_NUM or CASE_NAME[c] in pe.CASE_NUM:
            # R6h, R6i: the model's texture sampling; R6j: its second draw simply overwrites
            n = CASE_NAME[c]
            oc = te if n in te.CASE_NUM else pe
            blk = oc.sim_block(n)
            if (d.get('lanes'), d.get('src')) != (0xf, 0):
                p.append('case %s: lanes %s src %s, want f 0' % (n, d.get('lanes'), d.get('src')))
            for l in range(4):
                wl = go.plane_words(dict(((x, y), (blk[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] >> (8 * l)) & 0xff)
                                         for (x, y) in oc.sim_map(n)))
                if (d.get('pl') or {}).get(l) != wl:
                    p.append('case %s: colour plane %d differs from the model' % (n, l))
            if d.get('cov') != oc.sim_coverage_words(n):
                p.append('case %s: coverage map differs from the model' % n)
        elif CASE_NAME[c] == 'UC':
            # R7a: the client sent T1's own words, so the picture must be T1's (docs/R7_PLAN.md 2-1)
            blk = to.expected_block('T1', to.MEASURED)
            if (d.get('lanes') or 0) != 0:
                p.append('case UC: lanes %s, want 0' % d.get('lanes'))
            if d.get('cov') != to.coverage_map('T1', to.MEASURED):
                p.append('case UC: the coverage map is not T1\'s')
        elif CASE_NAME[c] in ru.SCASES:
            # R6m: the same picture, in the case's own surfaces (the offsets are checked below)
            n = CASE_NAME[c]
            blk = ru.sim_block(n)
            rco, rzf, _rtf = ru.offsets(n)
            want_lanes = 0xf if ru.is_tex(n) else 0
            if (d.get('lanes') or 0) != want_lanes:
                p.append('case %s: lanes %s, want %x' % (n, d.get('lanes'), want_lanes))
            if ru.is_tex(n):
                for l in range(4):
                    wl = go.plane_words(dict(((x, y), (blk[(rco + 4 * (x + zo.PITCH * y)) // 4] >> (8 * l)) & 0xff)
                                             for (x, y) in ru.sim_map(n)))
                    if (d.get('pl') or {}).get(l) != wl:
                        p.append('case %s: colour plane %d differs from the model' % (n, l))
            if d.get('cov') != ru.sim_coverage_words(n):
                p.append('case %s: coverage map differs from the model' % n)
        elif CASE_NAME[c] in ba.SCASES:
            # R6l: the model draws the same packets in the same order (no auxiliary scissor here)
            n = CASE_NAME[c]
            blk = ba.sim_block(n)
            if (d.get('lanes') or 0) != 0:
                p.append('case %s: lanes %s, want 0' % (n, d.get('lanes')))
            if d.get('cov') != ba.sim_coverage_words(n):
                p.append('case %s: coverage map differs from the model' % n)
        elif CASE_NAME[c] in sc.SCASES:
            # R6k: the model knows the main scissor and nothing of the auxiliary one -- the words
            # are what prove the auxiliary state (docs/R6K_PLAN.md 7)
            n = CASE_NAME[c]
            blk = sc.sim_block(n)
            depth = sc.read_of(n) == 'depth'
            if ((d.get('lanes') or 0), (d.get('src') or 0)) != ((7, 1) if depth else (0, 0)):
                p.append('case %s: lanes %s src %s' % (n, d.get('lanes'), d.get('src')))
            if depth:
                want = do.plane_words(blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + zo.BUF_BYTES // 4], 24)
                for l, wds in want.items():
                    if (d.get('pl') or {}).get(l) != wds:
                        p.append('case %s: depth plane %d differs from the model' % (n, l))
            if d.get('cov') != sc.sim_coverage_words(n):
                p.append('case %s: coverage map differs from the model' % n)
        elif CASE_NAME[c] in do.GCASE_NUM:
            # R6g: the model's depth test (sim_g_*), the planes of the case's format
            n = CASE_NAME[c]
            blk = do.sim_g_block(n)
            bits = do.g_bits(n)
            want_lanes = 0x3 if bits == 16 else 0x7
            if (d.get('lanes'), d.get('src')) != (want_lanes, 2 if bits == 16 else 1):
                p.append('case %s: lanes %s src %s' % (n, d.get('lanes'), d.get('src')))
            want = do.plane_words(blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + zo.BUF_BYTES // 4], bits)
            for l, wds in want.items():
                if (d.get('pl') or {}).get(l) != wds:
                    p.append('case %s: depth plane %d differs from the model' % (n, l))
            if d.get('cov') != do.sim_g_coverage_words(n):
                p.append('case %s: coverage map differs from the model' % n)
        elif CASE_NAME[c] in do.CASE_NUM:
            # R6f: the model's depth (first vertex's z, SIM_CONV), the planes of the case's source
            n = CASE_NAME[c]
            blk = do.full_block(n)
            if (d.get('lanes'), d.get('src')) != (do.lanes(n), do.dsrc(n)):
                p.append('case %s: lanes %s src %s, want %x %d' % (n, d.get('lanes'), d.get('src'), do.lanes(n), do.dsrc(n)))
            want = do.plane_words(blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + zo.BUF_BYTES // 4], do.fmt_bits(n))
            for l, w in want.items():
                if (d.get('pl') or {}).get(l) != w:
                    p.append('case %s: depth plane %d differs from the model' % (n, l))
            if d.get('cov') != do.coverage_words(n):
                p.append('case %s: coverage map differs from the oracle\'s' % n)
            if d.get('off') != [0, 0, 0, 0]:
                p.append('case %s: lane misses %s on a depth source' % (n, d.get('off')))
        elif CASE_NAME[c] in go.GCASES:
            n = CASE_NAME[c]
            blk = go.expected_block(n, GRULE, GRULE)
            want_lanes = go.lanes_mask(n)
            if d.get('lanes') != want_lanes:
                p.append('case %s: lanes %s, want %x' % (n, d.get('lanes'), want_lanes))
            for l in 'BGRA':
                if want_lanes & go.LANE_BIT[l]:
                    want = go.plane_words(go.expected_values(n, l, GRULE))
                    if (d.get('pl') or {}).get('BGRA'.index(l)) != want:
                        p.append('case %s: plane %s differs from the oracle' % (n, l))
            if d.get('off') != [0, 0, 0, 0]:
                p.append('case %s: constant lanes missed %s' % (n, d.get('off')))
        elif CASE_NAME[c] in to.TRI:
            # R6d: world5 draws with ONE rule (to.MEASURED since R6d 13); the map must be that rule's
            blk = to.expected_block(CASE_NAME[c], to.MEASURED)
            if d.get('cov') != to.coverage_map(CASE_NAME[c], to.MEASURED):
                p.append('case %s: coverage map differs from the oracle\'s (%s)' % (CASE_NAME[c], d.get('cov') and 'present'))
        else:
            blk = zo.expected_block(CASE_NAME[c], 'tiled', 'trunc')
        dof, cof = zo.DEPTH_OFF, zo.COLOR_OFF
        if CASE_NAME[c] in ru.SCASES:                   # R6m: the digests are over the case's own
            cof, dof, _tf = ru.offsets(CASE_NAME[c])
        #
        # M1m: THE CLIENT'S DIGEST IS A SAMPLE, NOT A SCAN.
        #
        # Two passes over 4096 words each is 16,384 uncached reads through the
        # VRAM alias, and that was the WHOLE fixed cost of a client submission
        # (13.5 ms, measured).  The driver now digests CP_R7_DIGEST_WORDS for
        # the client case and the full buffer for every R6 case, so the oracle
        # has to ask the same question -- the width comes from the driver's own
        # header rather than from a number typed here.
        #
        words = DIGEST_WORDS if CASE_NAME[c] == 'UC' else zo.BUF_BYTES // 4
        for region, first in (('depth', dof // 4), ('color', cof // 4)):
            e = zo.digest(blk, first, words)
            for k in (0, 1):
                g = d['dig'].get((k, region))
                if g != e:
                    p.append('case %s pass %d %s digest %s, oracle %s' % (CASE_NAME[c], k, region, g, e))
    return p


def run_one(cp_text=None, h_text=None):
    tp = s5.TPROJ
    work = s5.tempfile.mkdtemp(prefix='simr6.', dir=os.environ.get('TMPDIR'))
    # 2026-09-24: none of these tools removed what they made, and /tmp
    # reached 35.6 GiB of our scratch.  atexit, so a failure path cleans
    # up too -- the tool exits on a bad verdict from several places.
    atexit.register(shutil.rmtree, work, True)
    cp = os.path.join(tp, 'osrdn_cp.m')
    if cp_text is not None or h_text is not None:
        # a mutated copy of the unit (and, for header mutations, of the header beside it)
        inc = os.path.join(work, 'inc')
        os.makedirs(inc)
        open(os.path.join(inc, 'osrdn_cp.h'), 'w').write(h_text if h_text is not None else open(os.path.join(tp, 'osrdn_cp.h')).read())
        cp = os.path.join(inc, 'osrdn_cp.m')
        open(cp, 'w').write(cp_text if cp_text is not None else open(os.path.join(tp, 'osrdn_cp.m')).read())
    exe = os.path.join(work, 'r6')
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Wno-deprecated', '-nostdinc',
           '-I', s5.INC, '-I', os.path.dirname(cp), '-I', tp, '-x', 'c', cp, s5.SNAP, s5.WORLD,
           '-x', 'none', '-nostdlib', '-nostartfiles', s5.LIBC32, '-Wl,-dynamic-linker,' + s5.LD32, '-o', exe]
    r = s5.subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr
    rc, out = s5.run(exe)
    return rc, out


def main():
    if not os.path.exists(s5.LIBC32):
        print('  --   %s not present, R6 simulation skipped' % s5.LIBC32)
        return 0
    failures = 0
    rc, out = run_one()
    if rc is None:
        print('  FAIL baseline does not build\n' + out[-2000:])
        return 1
    p = judge(out)
    if rc == 0 and 'world5: PASS' in out and not p:
        print('  ok   baseline: the world PASS, the stream and the digests equal the oracle (%d cases)' % len(CASE_NAME))
    else:
        print('  FAIL baseline: rc %d %s' % (rc, p[:3] or [l for l in out.splitlines() if 'FAIL' in l][:3]))
        failures += 1
    tp = s5.TPROJ
    for label, old, new, f in MUTATIONS:
        text = open(os.path.join(tp, f)).read()
        # G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 10-3): cpAsubmit repeats cpZclear's client-case words on
        # purpose (check_r5_src g52-async holds them equal), so a ZCLEAR anchor is sought inside cpZclear
        # -- this world runs ZCLEAR, and the anchor must still be unique there
        lo, hi = 0, len(text)
        if f == 'osrdn_cp.m' and text.count(old) == 2:
            lo = text.index('\ncpZclear(osrdn_cp_state *c')
            hi = text.index('\n}\n', lo)
        if text[lo:hi].count(old) != 1:
            print('  FAIL mutation %-58s anchor found %d times' % (label, text[lo:hi].count(old)))
            failures += 1
            continue
        mut = text[:lo] + text[lo:hi].replace(old, new) + text[hi:]
        rc, out = run_one(cp_text=mut if f == 'osrdn_cp.m' else None, h_text=mut if f == 'osrdn_cp.h' else None)
        if rc is None:
            print('  FAIL mutation %-58s does not build\n%s' % (label, out[-400:]))
            failures += 1
            continue
        q = judge(out)
        caught = rc != 0 or bool(q)
        why = ([l.strip() for l in out.splitlines() if l.strip().startswith('FAIL')] + q + ['caught'])[0]
        print('  %-4s mutation %-58s %s' % ('ok' if caught else 'FAIL', label, why[:70] if caught else 'NOT CAUGHT'))
        failures += 0 if caught else 1
    print('sim_r6: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
