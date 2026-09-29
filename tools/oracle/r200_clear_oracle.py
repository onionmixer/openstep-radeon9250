#!/usr/bin/env python3
"""The R200 depth/stencil clear quad: the one window-coordinate 3D precedent.

  r200_clear_oracle.py --self-test
  r200_clear_oracle.py --markdown        example streams for docs/R6_CLEAR_QUAD.md

Transcribes FreeBSD radeon_state.c radeon_cp_dispatch_clear, the branch
`microcode_version == UCODE_R200 && flags & (RADEON_DEPTH | RADEON_STENCIL)`
(PLAN R6 cites it as the precedent), with the hard-coded depth_clear state
from radeon_cp.c radeon_do_init_cp and the client side from Mesa 6.5.3
r200_ioctl.c (boxes as floats in window pixels, depth = ctx->Depth.Clear).

Tied to the source mechanically, not by reading:
  - the registers of the state block, in order, are parsed from the
    OUT_RING_REG lines of that branch and must equal the oracle's order;
  - every BEGIN_RING(n) in the branch (and in radeon_emit_clip_rect) must
    equal the number of words the oracle emits for it;
  - every constant is evaluated from radeon_drv.h with cmacro.py.
"""

import importlib.util
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
DRM = os.path.join(PROJ, 'ref', 'upstream', 'freebsd-stable9', 'sys', 'dev', 'drm')
STATE = os.path.join(DRM, 'radeon_state.c')

_spec = importlib.util.spec_from_file_location('cmacro', os.path.join(HERE, 'cmacro.py'))
cmacro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmacro)
H = cmacro.Headers([os.path.join(DRM, 'radeon_drv.h'), os.path.join(DRM, 'radeon_drm.h')])
V = H.value

STATE_ORDER = ['RADEON_PP_CNTL', 'R200_RE_CNTL', 'RADEON_RB3D_CNTL', 'RADEON_RB3D_ZSTENCILCNTL',
               'RADEON_RB3D_STENCILREFMASK', 'RADEON_RB3D_PLANEMASK', 'RADEON_SE_CNTL', 'R200_SE_VTE_CNTL',
               'R200_SE_VTX_FMT_0', 'R200_SE_VTX_FMT_1', 'R200_SE_VAP_CNTL', 'R200_RE_AUX_SCISSOR_CNTL']


def p0(reg, n=0):
    return V('RADEON_CP_PACKET0') | (n << 16) | (reg >> 2)


def p3(pkt, n):
    return V('RADEON_CP_PACKET3') | pkt | (n << 16)


def fbits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def depth_clear_state(fb_bpp=32, depth_bpp=24):
    """radeon_cp.c radeon_do_init_cp: color_fmt, depth_fmt and the three
    hard-coded registers (R200 microcode: no ZBLOCK16)."""
    color_fmt = V('RADEON_COLOR_FORMAT_RGB565') if fb_bpp == 16 else V('RADEON_COLOR_FORMAT_ARGB8888')
    depth_fmt = V('RADEON_DEPTH_FORMAT_16BIT_INT_Z') if depth_bpp == 16 else V('RADEON_DEPTH_FORMAT_24BIT_INT_Z')
    rb3d_cntl = V('RADEON_PLANE_MASK_ENABLE') | (color_fmt << 10)
    zs = (depth_fmt | V('RADEON_Z_TEST_ALWAYS') | V('RADEON_STENCIL_TEST_ALWAYS') |
          V('RADEON_STENCIL_S_FAIL_REPLACE') | V('RADEON_STENCIL_ZPASS_REPLACE') |
          V('RADEON_STENCIL_ZFAIL_REPLACE') | V('RADEON_Z_WRITE_ENABLE'))
    se = (V('RADEON_FFACE_CULL_CW') | V('RADEON_BFACE_SOLID') | V('RADEON_FFACE_SOLID') |
          V('RADEON_FLAT_SHADE_VTX_LAST') | V('RADEON_DIFFUSE_SHADE_FLAT') | V('RADEON_ALPHA_SHADE_FLAT') |
          V('RADEON_SPECULAR_SHADE_FLAT') | V('RADEON_FOG_SHADE_FLAT') | V('RADEON_VTX_PIX_CENTER_OGL') |
          V('RADEON_ROUND_MODE_TRUNC') | V('RADEON_ROUND_PREC_8TH_PIX'))
    return dict(rb3d_cntl=rb3d_cntl, rb3d_zstencilcntl=zs, se_cntl=se)


def clear_stream(boxes, depth, depth_flag=True, stencil_flag=False, stencil_mask=0,
                 fb_bpp=32, depth_bpp=24):
    """boxes: [(x1, y1, x2, y2)] integer window pixels (the sarea cliprects,
    which the client also copies into depth_boxes as floats).  Returns
    [(label, [words])] in ring order."""
    dc = depth_clear_state(fb_bpp, depth_bpp)
    rb3d_cntl = dc['rb3d_cntl']
    rb3d_cntl = rb3d_cntl | V('RADEON_Z_ENABLE') if depth_flag else rb3d_cntl & ~V('RADEON_Z_ENABLE')
    if stencil_flag:
        rb3d_cntl |= V('RADEON_STENCIL_ENABLE')
        refmask = stencil_mask
    else:
        rb3d_cntl &= ~V('RADEON_STENCIL_ENABLE')
        refmask = 0
    values = {
        'RADEON_PP_CNTL': 0, 'R200_RE_CNTL': 0, 'RADEON_RB3D_CNTL': rb3d_cntl & 0xffffffff,
        'RADEON_RB3D_ZSTENCILCNTL': dc['rb3d_zstencilcntl'], 'RADEON_RB3D_STENCILREFMASK': refmask,
        'RADEON_RB3D_PLANEMASK': 0, 'RADEON_SE_CNTL': dc['se_cntl'],
        'R200_SE_VTE_CNTL': V('SE_VTE_CNTL__VTX_XY_FMT_MASK') | V('SE_VTE_CNTL__VTX_Z_FMT_MASK'),
        'R200_SE_VTX_FMT_0': V('SE_VTX_FMT_0__VTX_Z0_PRESENT_MASK') | V('SE_VTX_FMT_0__VTX_W0_PRESENT_MASK'),
        'R200_SE_VTX_FMT_1': 0,
        'R200_SE_VAP_CNTL': 0x9 << V('SE_VAP_CNTL__VF_MAX_VTX_NUM__SHIFT'),
        'R200_RE_AUX_SCISSOR_CNTL': 0,
    }
    state = [p0(V('RADEON_WAIT_UNTIL')), V('RADEON_WAIT_2D_IDLECLEAN') | V('RADEON_WAIT_HOST_IDLECLEAN')]
    for name in STATE_ORDER:
        state += [p0(V(name)), values[name]]
    out = [('state (BEGIN_RING 26)', state)]
    w1 = fbits(1.0)
    for (x1, y1, x2, y2) in boxes:
        clip = [p0(V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
                p0(V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]
        out.append(('clip rect (BEGIN_RING 4)', clip))
        fx1, fy1, fx2, fy2, fz = (fbits(float(x1)), fbits(float(y1)), fbits(float(x2)), fbits(float(y2)),
                                  fbits(depth))
        draw = [p3(V('R200_3D_DRAW_IMMD_2'), 12),
                V('RADEON_PRIM_TYPE_RECT_LIST') | V('RADEON_PRIM_WALK_RING') | (3 << V('RADEON_NUM_VERTICES_SHIFT')),
                fx1, fy1, fz, w1,
                fx1, fy2, fz, w1,
                fx2, fy2, fz, w1]
        out.append(('3D_DRAW_IMMD_2 (BEGIN_RING 14)', draw))
    return out


# ---- ties to the source ----------------------------------------------------------

def branch_text():
    src = open(STATE).read()
    a = src.index('else if ((dev_priv->microcode_version == UCODE_R200) &&\n\t\t(flags & (RADEON_DEPTH | RADEON_STENCIL)))')
    b = src.index('} else if ((flags & (RADEON_DEPTH | RADEON_STENCIL)))', a)
    return src[a:b], src[:a].count('\n') + 1, src[:b].count('\n') + 1


def source_ties():
    problems = []
    text, l0, l1 = branch_text()
    regs = re.findall(r'OUT_RING_REG\(\s*(\w+)\s*,', text)
    if regs != STATE_ORDER:
        problems.append('state register order in source %s differs from oracle' % regs)
    rings = [int(n) for n in re.findall(r'BEGIN_RING\((\d+)\)', text)]
    stream = clear_stream([(0, 0, 10, 10)], 1.0)
    emitted = [len(w) for label, w in stream if not label.startswith('clip')]
    if rings != emitted:
        problems.append('BEGIN_RING sizes in source %s, oracle emits %s' % (rings, emitted))
    if 'OUT_RING(0x3f800000);' not in text or text.count('OUT_RING(0x3f800000);') != 3:
        problems.append('W words in source are not three literal 0x3f800000')
    order = re.findall(r'OUT_RING\(depth_boxes\[i\]\.ui\[(CLEAR_\w+)\]\);', text)
    want_order = ['CLEAR_X1', 'CLEAR_Y1', 'CLEAR_DEPTH', 'CLEAR_X1', 'CLEAR_Y2', 'CLEAR_DEPTH',
                  'CLEAR_X2', 'CLEAR_Y2', 'CLEAR_DEPTH']
    if order != want_order:
        problems.append('vertex field order in source %s differs from oracle' % order)
    if '(0x9 <<' not in text:
        problems.append('SE_VAP_CNTL max vertex number 9 not found in source')
    src = open(STATE).read()
    clip = src[src.index('static __inline__ void radeon_emit_clip_rect'):]
    clip = clip[:clip.index('\n}') + 2]
    if int(re.search(r'BEGIN_RING\((\d+)\)', clip).group(1)) != 4:
        problems.append('radeon_emit_clip_rect ring size is not 4')
    for want in ('RADEON_RE_TOP_LEFT', '(box->y1 << 16) | box->x1', 'RADEON_RE_WIDTH_HEIGHT',
                 '((box->y2 - 1) << 16) | (box->x2 - 1)'):
        if want not in clip:
            problems.append('radeon_emit_clip_rect lacks %r' % want)
    return problems, (l0, l1)


def self_test():
    bad = 0

    def expect(label, got, want):
        nonlocal bad
        ok = got == want
        print('%-4s %-60s %s' % ('ok' if ok else 'FAIL', label, '' if ok else 'got %r want %r' % (got, want)))
        bad += 0 if ok else 1

    problems, lines = source_ties()
    expect('oracle tied to radeon_state.c:%d-%d (order, ring sizes, W, VAP)' % lines, problems, [])
    s = dict(clear_stream([(10, 20, 110, 70)], 0.5))
    draw = s['3D_DRAW_IMMD_2 (BEGIN_RING 14)']
    expect('packet 3 header: 0xc0000000 | 0x3500 | 12 << 16', draw[0], 0xc00c3500)
    expect('VF_CNTL: RECT_LIST | WALK_RING | 3 vertices', draw[1], 0x8 | 0x30 | (3 << 16))
    expect('vertex 0 x = 10.0f', draw[2], 0x41200000)
    expect('vertex 2 y = 70.0f', draw[11], 0x428c0000)
    expect('depth 0.5f in every vertex', (draw[4], draw[8], draw[12]), (0x3f000000,) * 3)
    expect('W = 1.0f in every vertex', (draw[5], draw[9], draw[13]), (0x3f800000,) * 3)
    st = s['state (BEGIN_RING 26)']
    vals = dict(zip(STATE_ORDER, st[3::2]))
    expect('SE_VTE_CNTL = XY_FMT | Z_FMT (viewport transform off)', vals['R200_SE_VTE_CNTL'], 0x300)
    expect('SE_VTX_FMT_0 = Z0 | W0 (no colour, no texture)', vals['R200_SE_VTX_FMT_0'], 0x3)
    expect('SE_VAP_CNTL = 9 << 18 (TCL off, FORCE_W_TO_ONE commented out)', vals['R200_SE_VAP_CNTL'], 9 << 18)
    expect('RB3D_PLANEMASK = 0 (no colour writes)', vals['RADEON_RB3D_PLANEMASK'], 0)
    expect('RB3D_CNTL 32 bpp, depth on: PLANE_MASK_ENABLE | ARGB8888<<10 | Z_ENABLE',
           vals['RADEON_RB3D_CNTL'], 0x2 | (6 << 10) | 0x100)
    expect('RE_WIDTH_HEIGHT is inclusive: (y2-1)<<16 | (x2-1)',
           dict(clear_stream([(10, 20, 110, 70)], 0.5))['clip rect (BEGIN_RING 4)'][3], (69 << 16) | 109)
    # control: a wrong register order must be caught
    saved = list(STATE_ORDER)
    STATE_ORDER[0], STATE_ORDER[1] = STATE_ORDER[1], STATE_ORDER[0]
    try:
        expect('control: swapped state order is caught', bool(source_ties()[0]), True)
    finally:
        STATE_ORDER[:] = saved
    print('r200_clear_oracle self-test:', 'PASS' if bad == 0 else 'FAIL (%d)' % bad)
    return 1 if bad else 0


def markdown():
    problems, (l0, l1) = source_ties()
    if problems:
        raise SystemExit('source ties failed: %s' % problems)
    out = ['### 생성표 — 32 bpp·24 비트 깊이, 깊이만 지움, 상자 (10,20)-(110,70), 깊이 0.5', '',
           '원천: `radeon_state.c` %d–%d 행(이 도구가 레지스터 순서와 `BEGIN_RING` 크기를 대조).' % (l0, l1), '', '```']
    names = {}
    for n in STATE_ORDER + ['RADEON_WAIT_UNTIL', 'RADEON_RE_TOP_LEFT', 'RADEON_RE_WIDTH_HEIGHT']:
        names[p0(V(n))] = 'PACKET0(%s)' % n
    for label, words in clear_stream([(10, 20, 110, 70)], 0.5):
        out.append('# %s' % label)
        for i, w in enumerate(words):
            note = names.get(w, '')
            if label.startswith('3D') and i >= 2:
                k = (i - 2) % 4
                note = ['x', 'y', 'z', 'w'][k] + ' = %g' % struct.unpack('<f', struct.pack('<I', w))[0]
            out.append('  0x%08x  %s' % (w, note))
    out.append('```')
    return '\n'.join(out)


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    if argv[1:] == ['--markdown']:
        print(markdown())
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
