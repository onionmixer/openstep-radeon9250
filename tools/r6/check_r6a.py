#!/usr/bin/env python3
"""Judge one R6a boot (docs/R6_PLAN.md 7) against the oracle.

  check_r6a.py <log> --boot N --build X [--procedure r6a|r6b|r6c]
  check_r6a.py --self-test

r6b (docs/R6B_PLAN.md 5) adds cases D (C with SCISSOR_ENABLE) and E (TL moved,
RE_CNTL 0), a REC3D after D and at the end, and judges every case by rule H
(zclear_oracle.covered); a case that misses it is fitted to every rectangle of
its area and the fits are named.

r6c (docs/R6C_PLAN.md 6-8) runs A F G H F' with colour: A as before, F and F' must
fill the colour buffer linearly with 0x78123456 (full digest equality; a +-1 channel
is named "approximate" and is NOT a PASS), G and H are measured and named from the
hypothesis table (7), every case's depth must be A's.

The r6a procedure: RECORD, REC3D, LOAD, MAP, RESET, START, REC3D, (ZPREP, ZCLEAR) for
cases 1 2 3, REC3D, STOP, RECORD, then the mode cycle (r6b and r6c: ORDERS).  Every ZCLEAR is judged
through the driver's digests of the 256 KiB block against
tools/r6/zclear_oracle.py: the depth buffer must equal the Mesa-tiled
expectation (the linear one is computed too and reported by name), the colour
buffer and the rest of the block must be untouched.  Case B's depth may be
Mesa's truncation (0x7fffff) or rounding (0x800000): which one is recorded.
"""

import importlib.util
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
do = _load('depth_oracle', os.path.join(HERE, 'depth_oracle.py'))     # R6f
te = _load('tex_oracle', os.path.join(HERE, 'tex_oracle.py'))         # R6h
pe = _load('persp_oracle', os.path.join(HERE, 'persp_oracle.py'))     # R6i
sc = _load('scissor_oracle', os.path.join(HERE, 'scissor_oracle.py'))  # R6k
ba = _load('batch_oracle', os.path.join(HERE, 'batch_oracle.py'))     # R6l
ru = _load('reuse_oracle', os.path.join(HERE, 'reuse_oracle.py'))     # R6m
vo = _load('verify_oracle', os.path.join(os.path.dirname(HERE), 'r7', 'verify_oracle.py'))  # R7a
import numpy as np  # noqa: E402
from fractions import Fraction  # noqa: E402
MODELOG = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_modelog.m')
CPM = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.m')

ORDERS = {
    'r6a': (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d',
             'zprep', 'zclear', 'zprep', 'zclear', 'zprep', 'zclear', 'rec3d', 'stop', 'record'], [1, 2, 3]),
    'r6b': (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d',
             'zprep', 'zclear', 'zprep', 'zclear', 'zprep', 'zclear', 'rec3d',
             'zprep', 'zclear', 'zprep', 'zclear', 'rec3d', 'stop', 'record'], [1, 3, 4, 3, 5]),
    # G4-7 (docs/G4_7_TRIPERF_PLAN.md 4): read TRI_PERF before the CP, after START, and after one prefix;
    # no STOP -- the CP stays up for the GLQuake run that follows in the same boot
    'g47': (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d', 'zprep', 'zclear', 'rec3d', 'record'], [1]),
    'g49': (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d', 'zprep', 'zclear', 'rec3d', 'record'], [1]),   # G4-9, same shape
    'r6c': (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d',
             'zprep', 'zclear', 'zprep', 'zclear', 'zprep', 'zclear', 'zprep', 'zclear', 'zprep', 'zclear',
             'rec3d', 'stop', 'record'], [1, 6, 7, 8, 6]),
    # R6d (docs/R6D_PLAN.md 11): A, F, then the seventeen triangle cases in order
    'r6d': (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] * 19 +
            ['rec3d', 'stop', 'record'], [1, 6] + [to.CASE_NUM[n] for n in to.ORDER]),
}
# R7b (docs/R7_PLAN.md 10-9): F, then the sixteen client streams -- each one rdnr7dev run is a
# zprep by the runner and the ZCLEAR its SUBMIT performs.  The refusals that never reach the CP
# (a second open, a bad word count, an unknown command) are not operations and are not listed.
ORDERS['r7b'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] +
                 ['zprep', 'zclear'] * 17 + ['rec3d', 'stop', 'record'], [6] + [171] * 16)
# REC3D's register count per build: 60 through R6b, 64 from R6c (docs/R6C_PLAN.md 8)
ORDERS['r6e'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] * 2 +
                 [x for n in go.ORDER for x in ['zprep', 'zclear'] + ['plane'] * (4 * bin(go.lanes_mask(n)).count('1'))] +
                 ['rec3d', 'stop', 'record'], [1, 6] + [go.CASE_NUM[n] for n in go.ORDER])     # docs/R6E_PLAN.md 9, 13
PLANE_ORDER = dict((n, [(l, ch) for l in range(4) if go.lanes_mask(n) >> l & 1 for ch in range(4)])
                   for n in go.ALL_ORDER)                                                          # (lane, chunk) per case
R6E3 = ['G1', 'S3'] + go.ORDER3                  # docs/R6E_PLAN.md 18: two repeats, then the confirmation cases
ORDERS['r6e3'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] * 2 +
                  [x for n in R6E3 for x in ['zprep', 'zclear'] + ['plane'] * (4 * bin(go.lanes_mask(n)).count('1'))] +
                  ['rec3d', 'stop', 'record'], [1, 6] + [go.CASE_NUM[n] for n in R6E3])
# R6f (docs/R6F_PLAN.md 6): A, F, G1 (regression), the anchors, then the z-sloped triangles at 24 and 16 bits
PLANE_ORDER.update(dict((n, [(l, ch) for l in range(4) if do.lanes(n) >> l & 1 for ch in range(4)]) for n in do.ORDER))
R6F = ['G1'] + do.ORDER
ORDERS['r6f'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] * 2 +
                 [x for n in R6F for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                 ['rec3d', 'stop', 'record'], [1, 6] + [go.CASE_NUM['G1']] + [do.CASE_NUM[n] for n in do.ORDER])
# R6g (docs/R6G_PLAN.md 3): A, F, then the twenty depth-test cases
PLANE_ORDER.update(dict((n, [(l, ch) for l in range(4) if (0x3 if do.g_bits(n) == 16 else 0x7) >> l & 1
                             for ch in range(4)]) for n in do.GORDER))
ORDERS['r6g'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] * 2 +
                 [x for n in do.GORDER for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                 ['rec3d', 'stop', 'record'], [1, 6] + [do.GCASE_NUM[n] for n in do.GORDER])
# R6h (docs/R6H_PLAN.md 3): F, then the seven texture cases, each read back as four colour planes
PLANE_ORDER.update(dict((n, [(l, ch) for l in range(4) for ch in range(4)]) for n in te.ORDER))
ORDERS['r6h'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] +
                 [x for n in te.ORDER for x in ['zprep', 'zclear'] + ['plane'] * 16] +
                 ['rec3d', 'stop', 'record'], [6] + [te.CASE_NUM[n] for n in te.ORDER])
# R6i (docs/R6I_PLAN.md 3): F, the two control cases (V8 affine, I1_24 affine), then the sixteen
# perspective / bilinear cases.  PZ reads the 24-bit depth (three lanes), everything else four colour lanes
PLANE_ORDER.update(dict((n, [(l, ch) for l in range(4) if (7 if pe.kind(n) == 'depth' else 0xf) >> l & 1
                             for ch in range(4)]) for n in pe.ORDER))
R6I = ['V8', 'I1_24'] + pe.ORDER1
ORDERS['r6i'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] +
                 [x for n in R6I for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                 ['rec3d', 'stop', 'record'],
                 [6, go.CASE_NUM['V8'], do.CASE_NUM['I1_24']] + [pe.CASE_NUM[n] for n in pe.ORDER1])
# R6i-2 (docs/R6I2_PLAN.md 3): F, LD (the R6i control), then the six dyadic-gradient cases
R6I2 = ['LD'] + pe.ORDER2
ORDERS['r6i2'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] +
                  [x for n in R6I2 for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                  ['rec3d', 'stop', 'record'], [6] + [pe.CASE_NUM[n] for n in R6I2])
# R6j (docs/R6J_PLAN.md 3): F, the R6i-3 control N5, then the ten blend cases
R6J = ['N5'] + pe.ORDER4
ORDERS['r6j'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] +
                 [x for n in R6J for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                 ['rec3d', 'stop', 'record'], [6] + [pe.CASE_NUM[n] for n in R6J])
# R6i-3 (docs/R6I3_PLAN.md 3): F, the two R6i-2 controls, then the five cases
R6I3 = ['Q1', 'Q3'] + pe.ORDER3
ORDERS['r6i3'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] +
                  [x for n in R6I3 for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                  ['rec3d', 'stop', 'record'], [6] + [pe.CASE_NUM[n] for n in R6I3])
# R6k (docs/R6K_PLAN.md 4): F, then the fifteen scissor cases -- only the depth one reads planes
PLANE_ORDER.update(dict((n, [(l, ch) for l in range(3) for ch in range(4)] if sc.read_of(n) == 'depth' else [])
                        for n in sc.ORDER))
ORDERS['r6k'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] +
                 [x for n in sc.ORDER for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                 ['rec3d', 'stop', 'record'], [6] + [sc.CASE_NUM[n] for n in sc.ORDER])
# R6l (docs/R6L_PLAN.md 4): F, then BA BB BA BB BA BC BD BF -- the third BA is the one that wraps
PLANE_ORDER.update(dict((n, []) for n in ba.ORDER))
ORDERS['r6l'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] +
                 ['zprep', 'zclear'] * (1 + len(ba.BOOT)) + ['rec3d', 'stop', 'record'],
                 [6] + [ba.CASE_NUM[n] for n in ba.BOOT])
# R6m (docs/R6M_PLAN.md 4): F, the six reuse cases, then BA BB BB -- the third BB pads the ring
PLANE_ORDER.update(dict((n, [(l, ch) for l in range(4) for ch in range(4)] if ru.is_tex(n) else [])
                        for n in ru.ORDER))
ORDERS['r6m'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] + ['zprep', 'zclear'] +
                 [x for n in ru.BOOT for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                 ['zprep', 'zclear'] * len(ru.PAD_TAIL) + ['rec3d', 'stop', 'record'],
                 [6] + [ru.CASE_NUM[n] for n in ru.BOOT] + [ba.CASE_NUM[n] for n in ru.PAD_TAIL])
# r6m0: the FIRST R6m boot (00ef86d4) ran without the leading F control -- I ran the preamble and
# then run_r6m.sh, and r6l's plan_ops.txt leaves F to be run by hand.  The R6m gates do not use F,
# so the measurement stands; what it cost is the ring trajectory: everything started 112 words
# earlier and the last submission landed on 4000 instead of wrapping, so P5 (task #30) could not
# fire.  This entry describes what ran -- 'r6m' still describes what should run.
ORDERS['r6m0'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] +
                  [x for n in ru.BOOT for x in ['zprep', 'zclear'] + ['plane'] * len(PLANE_ORDER[n])] +
                  ['zprep', 'zclear'] * len(ru.PAD_TAIL) + ['rec3d', 'stop', 'record'],
                  [ru.CASE_NUM[n] for n in ru.BOOT] + [ba.CASE_NUM[n] for n in ru.PAD_TAIL])
# R7a (docs/R7_PLAN.md 5): F as the control, then one ZPREP/ZCLEAR per staged stream.  Staging
# goes through its own parameter and is NOT a CP operation, so it does not appear in this list --
# it shows up as the RDN-R7 stage lines the judge reads beside them.
R7_CASES = [n for n, _w, _y in vo.cases(0)]
PLANE_ORDER['UC'] = []
ORDERS['r7a'] = (['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d'] +
                 ['zprep', 'zclear'] * (1 + len(R7_CASES) + 1) + ['rec3d', 'stop', 'record'],
                 [6] + [171] * len(R7_CASES) + [171])
REC_WANT = {'r6a': 60, 'r6b': 60, 'r6c': 64, 'r6d': 64, 'r6e': 64, 'r6e3': 64, 'r6f': 64, 'r6g': 64, 'r6h': 64,
            'r6i': 64, 'r6i2': 64, 'r6i3': 64, 'r6j': 64, 'r6k': 64, 'r6l': 64, 'r6m': 64, 'r6m0': 64, 'r7a': 64,
            'g47': 68,      # G4-7: TRI_PERF, PERF_CNTL, TXFILTER_0, TXFORMAT_0 appended
            'g49': 72}      # G4-9: TAM_DEBUG3, TXFORMAT_X_0, TXSIZE_0, TXPITCH_0 appended
REC_LATEST = 'g49'          # the count the driver source must match (older keys judge older logs)
ORDER = ORDERS['r6a'][0]
CASE_NAME = {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'E', 6: 'F', 7: 'G', 8: 'H'}
CASE_NAME.update(dict((v, k) for k, v in to.CASE_NUM.items()))     # R6d: 9 .. 25
CASE_NAME.update(dict((v, k) for k, v in go.CASE_NUM.items()))     # R6e: 26 .. 49, R6e-3: 50 .. 59
CASE_NAME.update(dict((v, k) for k, v in do.CASE_NUM.items()))     # R6f: 60 .. 81
CASE_NAME.update(dict((v, k) for k, v in do.GCASE_NUM.items()))    # R6g: 82 .. 101
CASE_NAME.update(dict((v, k) for k, v in te.CASE_NUM.items()))     # R6h: 102 .. 108
CASE_NAME.update(dict((v, k) for k, v in sc.CASE_NUM.items()))     # R6k: 146 .. 160
CASE_NAME.update(dict((v, k) for k, v in ba.CASE_NUM.items()))     # R6l: 161 .. 165
CASE_NAME.update(dict((v, k) for k, v in ru.CASE_NUM.items()))     # R6m: 166 .. 170
CASE_NAME[171] = 'UC'                                              # R7a: the client's own stream
# a rung that reuses another rung's case name silently overwrites its PLANE_ORDER and its judging
# (R6i-3 hit it with S1..S5, R6k with M1 -- the names must be disjoint, and this proves it)
_NAMESETS = [set(d) for d in (to.CASE_NUM, go.CASE_NUM, do.CASE_NUM, do.GCASE_NUM, te.CASE_NUM,
                              pe.CASE_NUM, sc.CASE_NUM, ba.CASE_NUM, ru.CASE_NUM)]
assert sum(len(x) for x in _NAMESETS) == len(set().union(*_NAMESETS)), (
    'two rungs share a case name: %s' % sorted(n for x in _NAMESETS for n in x
                                               if sum(n in y for y in _NAMESETS) > 1))
CASE_NAME.update(dict((v, k) for k, v in pe.CASE_NUM.items()))     # R6i: 109 .. 124
P_RGBA = zo.argb(*zo.RGBA)                      # 0x78123456: Mesa's order
r_, g_, b_, a_ = zo.RGBA
P_BGRA = zo.argb(b_, g_, r_, a_)                # 0x78563412: the word read b g r a


def pixel_names():
    """every named pixel a colour case could leave: the 24 byte orders of the word (named
    by which source byte lands in a r g b of the pixel) and +-1 on each channel of Mesa's"""
    src = dict(zip('rgba', zo.RGBA))
    out = {}
    import itertools
    for perm in itertools.permutations('rgba'):
        v = zo.argb(src[perm[0]], src[perm[1]], src[perm[2]], src[perm[3]])
        nm = 'bytes %s->rgba' % ''.join(perm)
        if perm == tuple('rgba'):
            nm = 'Mesa order (r g b a)'
        elif perm == tuple('bgra'):
            nm = 'R and B swapped (b g r a)'
        out.setdefault(v, nm)
    for ch, sh in (('a', 24), ('r', 16), ('g', 8), ('b', 0)):
        for d in (1, -1):
            v = (P_RGBA & ~(0xff << sh)) | ((((P_RGBA >> sh) & 0xff) + d) << sh)
            out.setdefault(v, 'approximate: %s %+d' % (ch, d))
    return out


_colour_digests = {}


def classify_colour(name, dig):
    """[(layout, pixel name)] whose expected colour digest equals dig, or []"""
    out = []
    for pix, nm in sorted(pixel_names().items()):
        for layout in ('linear', 'tiled'):
            key = (name, layout, pix)
            if key not in _colour_digests:
                _colour_digests[key] = zo.digest(zo.expected_block(name, clayout=layout, pixel=pix),
                                                 zo.COLOR_OFF // 4, zo.BUF_BYTES // 4)
            e = _colour_digests[key]
            if e == dig:
                out.append((layout, nm, pix))
    return out


def pair_name(f, g):
    """docs/R6C_PLAN.md 7 and 8-2: the F/G observation; two readings give the same pair"""
    table = {(P_RGBA, P_BGRA): 'the order bit works as Mesa assumes',
             (P_RGBA, P_RGBA): 'the order bit is ignored on this path',
             (P_BGRA, P_RGBA): 'the order bit is reversed = OR the colour buffer swaps R and B (the same observation)',
             (P_BGRA, P_BGRA): 'the order bit is ignored and the bytes land b g r a'}
    return table.get((f, g), 'unnamed (F %s, G %s)' % (f if f is None else '%08x' % f, g if g is None else '%08x' % g))


_sig = []


def tri_signatures():
    """[(rule name, maps of the gated cases)] over every NAMED rule (docs/R6D_PLAN.md 11)"""
    if not _sig:
        _sig.append(to.named_signatures())
    return _sig[0]


def judge_triangle(o, name, tag, p, notes):
    """one triangle case (docs/R6D_PLAN.md 10): the map exists, the colour buffer changed only
    where the map says, depth covers exactly what colour covers, the gated cases are pure"""
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    cov = [w for k in range(8) for w in cl[k]]
    o['cov'] = cov
    codes = to.decode_map(cov)
    nz, n3 = int((codes != 0).sum()), int((codes == 3).sum())
    zc, zd = o['dig'].get(('zc', 1)), o['dig'].get(('zd', 1))
    if zc is None or zd is None:
        p.append('%s: no digest' % tag)
        return
    if zc['changed'] != nz:
        p.append('%s: %d colour words changed, the 32 x 32 map has %d -- a write outside the map' % (tag, zc['changed'], nz))
    if name in to.GATED and n3:
        p.append('%s: %d pixels hold neither case colour (code 3)' % (tag, n3))
    c1, c2 = to.map_colours(name)
    px = np.full((64, 64), -1, np.int64)
    sub = px[:32, :32]
    sub[codes == 1] = c1
    sub[codes == 2] = c2
    sub[codes == 3] = 0x01010101            # a stand-in: depth coverage does not depend on it
    ed = zo.digest(to.block_from_pixels(px), zo.DEPTH_OFF // 4, zo.BUF_BYTES // 4)
    if (zd['changed'], zd['ixor'], zd['isum']) != (ed['changed'], ed['ixor'], ed['isum']):
        p.append('%s: the depth buffer covers other pixels than the colour buffer (changed %d vs %d)' % (
            tag, zd['changed'], ed['changed']))
    elif zd != ed:
        notes.append('%s: depth coverage = colour coverage, depth VALUES %s (measured, want a5ffffff)' % (
            tag, ['%08x' % v for v in zd['vals']]))
    if n3 == 0:
        ec = zo.digest(to.block_from_pixels(px), zo.COLOR_OFF // 4, zo.BUF_BYTES // 4)
        if zc != ec:
            p.append('%s: the colour digest disagrees with the map' % tag)
    if name == 'T7':
        notes.append('T7 (flat shading): last vertex %d px, first %d px, other %d px, values %s' % (
            int((codes == 1).sum()), int((codes == 2).sum()), n3, ['%08x' % v for v in zc['vals']]))
    for reg in ('zd', 'zc'):
        if o['dig'].get((reg, 0)) != o['dig'].get((reg, 1)):
            notes.append('%s: the two read passes of %s differ' % (tag, reg))


def judge_rule(zs, p, notes):
    """the class of hypotheses that explains every gated triangle case, by name"""
    byname = dict((CASE_NAME.get(o['len']), o) for o in zs)
    maps = [byname.get(n, {}).get('cov') for n in to.GATED]
    if any(m is None for m in maps):
        p.append('the rule: a gated case has no map')
        return
    got = tuple(tuple(m) for m in maps)
    sig = tri_signatures()
    match = [name for name, sg in sig if sg == got]
    if match:
        notes.append('the rule (class of %d): %s%s' % (len(match), match[:8], '' if len(match) <= 8 else ' ...'))
        notes.append('the SE_CNTL reading %s is %sin the class' % (to.EXPECTED, '' if ('gated', to.EXPECTED) in match else 'NOT '))
        t1r = byname.get('T1r', {}).get('cov')
        rules = dict((r[0], r) for r in to.named_rules())
        if t1r:
            ok = [n for n in match if list(to.named_map('T1r', rules[n])) == t1r]
            notes.append('T1r (other winding): explained by %s of the class' % (ok[:8] or 'none'))
    else:
        p.append('no named rule explains T1-T6, X1-X8 and Y1 together')
        for k, (n, m) in enumerate(zip(to.GATED, maps)):
            d = [to.map_distance(r[1][k], m) for r in sig]
            best = min(d)
            names = [sig[j][0] for j, x in enumerate(d) if x == best]
            notes.append('%s: %d rules are nearest, %d pixels off (first %s)' % (n, len(names), best, names[0]))
        # one rule for all cases (code re-review m3): the smallest total distance
        tot = [sum(to.map_distance(sg[k], m) for k, m in enumerate(maps)) for _, sg in sig]
        best = min(tot)
        names = [sig[j][0] for j, x in enumerate(tot) if x == best]
        notes.append('nearest over all cases: %d pixels off in total, %d rules (%s)' % (best, len(names), names[:4]))
    # an empty map names itself (a culled winding would leave X1, X5 and T1r empty -- code review m2)
    for o in zs:
        n = CASE_NAME.get(o['len'])
        if n in to.TRI and o.get('cov') is not None and not any(o['cov']):
            notes.append('%s: EMPTY map (signed area %+.1f: %s winding)' % (
                n, to.signed_area(n), 'negative' if to.signed_area(n) < 0 else 'positive'))
    # T7 has T1's geometry: its coverage (any code) must be T1's (code review m4, measured)
    t1, t7 = byname.get('T1', {}).get('cov'), byname.get('T7', {}).get('cov')
    if t1 and t7:
        same = ((to.decode_map(t1) != 0) == (to.decode_map(t7) != 0)).all()
        notes.append('T7 covers %s T1' % ('the same pixels as' if same else 'OTHER pixels than'))


def attach_planes(ops, nonce, p):
    """R6e (docs/R6E_PLAN.md 13-14): each PLANE belongs to the nearest earlier successful ZCLEAR with no
    ZPREP or ZCLEAR in between; its header must name that ZCLEAR's operation number and case and this
    boot; every (lane, chunk) exactly once, eight lines indexed chunk*8 .. chunk*8+7"""
    owner = None
    for o in ops:
        if o['op'] in ('zprep', 'zclear'):
            owner = o if (o['op'] == 'zclear' and o['rc'] == 0) else None
            if owner is not None:
                owner['pll'] = {}
            continue
        if o['op'] != 'plane':
            continue
        if owner is None:
            p.append('plane n=%d: no successful ZCLEAR before it' % o['n'])
            continue
        h = o.get('plh')
        lane, chunk = o['len'] >> 2, o['len'] & 3
        if h != (nonce, owner['n'], owner['len'], lane, chunk):
            p.append('plane n=%d: header %s, want boot %s zc %d case %d lane %d chunk %d' % (
                o['n'], h, nonce, owner['n'], owner['len'], lane, chunk))
            continue
        lines = (o.get('pll') or {}).get(lane, {})
        want = list(range(chunk * 8, chunk * 8 + 8))
        if sorted(lines) != want:
            p.append('plane n=%d: lines %s, want %s' % (o['n'], sorted(lines), want))
            continue
        owner.setdefault('plsrcs', set()).add(o.get('plsrc'))           # R6f: the source each PLANE named
        dst = owner['pll'].setdefault(lane, {})
        if any(k in dst for k in want):
            p.append('plane n=%d: lane %d chunk %d logged twice' % (o['n'], lane, chunk))
            continue
        dst.update(lines)


def judge_rule_b(zs, p, notes):
    """R6e-3 gate (docs/R6E_PLAN.md 18): every logged plane equals rule B byte for byte, under one
    weight-rounding reading (half up or half even) for all planes"""
    fits = {'round': 0, 'even': 0}
    total = 0
    for o in zs:
        n = CASE_NAME.get(o['len'])
        if n not in go.GCASES:
            continue
        for lane in go.GCASES[n][2]:
            words = (o.get('planes') or {}).get(lane)
            if words is None:
                p.append('rule B: plane %s %s missing' % (n, lane))
                return
            pts = go.GCASES[n][0]
            seen = go.unpack_plane(words, go.covered(pts))
            total += len(seen)
            for m in fits:
                d = sum(1 for a, b in zip(go.rule_b(pts, go.lane_triple(n, lane), m), seen) if a != b)
                fits[m] += d
                if d and m == 'round':
                    notes.append('rule B (half up) %s %s: %d bytes differ' % (n, lane, d))
    ok = [m for m, d in fits.items() if d == 0]
    if ok:
        notes.append('rule B holds on all %d bytes; weight rounding: %s' % (total, ' or '.join(ok)))
    else:
        p.append('rule B does not hold: half up %d, half even %d bytes differ of %d' % (fits['round'], fits['even'], total))


def judge_gouraud(o, name, tag, p, notes):
    """one Gouraud case (docs/R6E_PLAN.md 9): coverage = the measured R6d rule, colour and depth
    cover the same pixels, the named lanes' planes are complete, the constant lanes held"""
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    codes = to.decode_map([w for k in range(8) for w in cl[k]])
    pts = go.GCASES[name][0]
    want = to.cover(pts, to.MEASURED, 32)
    if not ((codes != 0) == want).all():
        p.append('%s: coverage is not the measured rule (%d pixels differ)' % (tag, int(((codes != 0) != want).sum())))
    zc, zd = o['dig'].get(('zc', 1)), o['dig'].get(('zd', 1))
    nz = int((codes != 0).sum())
    if zc is None or zd is None or zc['changed'] != nz:
        p.append('%s: colour words changed %s, the map has %d' % (tag, zc and zc['changed'], nz))
        return
    px = np.full((64, 64), -1, np.int64)
    px[:32, :32][codes != 0] = 0x01010101
    ed = zo.digest(to.block_from_pixels(px), zo.DEPTH_OFF // 4, zo.BUF_BYTES // 4)
    if (zd['changed'], zd['ixor'], zd['isum']) != (ed['changed'], ed['ixor'], ed['isum']):
        p.append('%s: the depth buffer covers other pixels than the colour buffer' % tag)
    lanes = go.lanes_mask(name)
    if o.get('lanes') != lanes:
        p.append('%s: lanes %s logged, want %x' % (tag, o.get('lanes'), lanes))
        return
    o['planes'] = {}
    for l in 'BGRA':
        if not lanes & go.LANE_BIT[l]:
            continue
        lines = (o.get('pll') or {}).get('BGRA'.index(l), {})
        if sorted(lines) != list(range(32)):
            p.append('%s: plane %s lines %d of 32' % (tag, l, len(lines)))
            return
        o['planes'][l] = [w for k in range(32) for w in lines[k]]
    off = o.get('off') or [None] * 4
    missed = ['%s=%s' % (l, off['BGRA'.index(l)]) for l in 'BGRA'
              if l not in go.GCASES[name][3] and off['BGRA'.index(l)] != 0]
    if missed and name == 'G0':
        notes.append('G0 (constant colour under Gouraud): lanes left their constant %s (measured)' % missed)
    elif missed:
        p.append('%s: constant lanes moved %s' % (tag, missed))


def judge_depth(o, name, tag, p, notes):
    """one R6f case (docs/R6F_PLAN.md 3-3): coverage = the R6d rule in C1's pixel, the colour digest, the
    planes complete from the case's source, the depth buffer rebuilt from them = both depth digests,
    uncovered pixels hold the pattern, a grid cell's pixels agree"""
    bits = do.fmt_bits(name)
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    words = [w for k in range(8) for w in cl[k]]
    if words != do.coverage_words(name):
        codes = to.decode_map(words)
        want = np.zeros((32, 32), bool)
        for x, y in do.covered(name):
            want[y][x] = True
        p.append('%s: coverage is not the R6d rule in C1 (%d pixels differ, codes %s)' % (
            tag, int(((codes != 0) != want).sum()), sorted(set(int(c) for c in codes.ravel()))))
    blk = do.full_block(name)                   # its colour region: C1 on the covered pixels
    ecol = zo.digest(blk, zo.COLOR_OFF // 4, zo.BUF_BYTES // 4)
    if o['dig'].get(('zc', 1)) != ecol:
        p.append('%s: colour digest %s, want C1 on the covered pixels %s' % (tag, o['dig'].get(('zc', 1)), ecol))
    if (o.get('lanes'), o.get('off')) != (do.lanes(name), [0, 0, 0, 0]):
        p.append('%s: lanes %s misses %s, want %x and none' % (tag, o.get('lanes'), o.get('off'), do.lanes(name)))
        return
    if o.get('plsrcs') != {do.dsrc(name)}:
        p.append('%s: the planes name source %s, want %d' % (tag, sorted(o.get('plsrcs') or [], key=str), do.dsrc(name)))
        return
    planes = {}
    for l in range(4):
        if do.lanes(name) >> l & 1:
            lines = (o.get('pll') or {}).get(l, {})
            if sorted(lines) != list(range(32)):
                p.append('%s: plane %d lines %d of 32' % (tag, l, len(lines)))
                return
            planes[l] = [w for k in range(32) for w in lines[k]]
    vals = do.values_from_planes(planes, bits)
    o['dvals'] = vals
    rebuilt = zo.digest(do.block_from_values(vals, bits), 0, zo.BUF_BYTES // 4)
    for k in (0, 1):
        if o['dig'].get(('zd', k)) != rebuilt:
            p.append('%s: the planes do not rebuild depth pass %d (placement, a write outside the 32 x 32, the %s)' % (
                tag, k, 'stencil byte' if bits == 24 else 'other half of a word'))
    pat = do.pattern_block()
    cov = do.covered(name)
    out = [(x, y) for (x, y), v in vals.items() if (x, y) not in cov and v != do.read_depth(pat, x, y, bits)]
    if out:
        p.append('%s: %d uncovered pixels changed depth (first %s)' % (tag, len(out), sorted(out)[0]))
    same = [q for q in cov if vals[q] == do.read_depth(pat, q[0], q[1], bits)]
    if same:
        notes.append('%s: %d covered pixels hold a value equal to the pattern there (not separable, recorded)' % (tag, len(same)))
    if name.startswith('K'):
        o['anchors'] = []
        for z, cell in do.cell_values(name, vals):
            if len(set(cell)) != 1:
                p.append('%s: the cell of z %s has values %s' % (tag, do.tohex(z), cell))
                o['anchors'].append(None)
            else:
                o['anchors'].append(cell[0])


def judge_ztest(o, name, tag, p, notes):
    """one R6g case (docs/R6G_PLAN.md 2-3): the prefill read back, the colour buffer = the pass set,
    the depth = the new value where the test passed and the write bit was on, the planes rebuild the
    depth buffer.  GZE and the two comparison readings are named, not gated."""
    bits = do.g_bits(name)
    if o.get('pfbad') not in (0, None):
        p.append('%s: the prefill did not read back (%s words)' % (tag, o.get('pfbad')))
        return
    lanes = 0x3 if bits == 16 else 0x7
    if (o.get('lanes'), o.get('off')) != (lanes, [0, 0, 0, 0]) or o.get('plsrcs') != {2 if bits == 16 else 1}:
        p.append('%s: lanes %s misses %s source %s' % (tag, o.get('lanes'), o.get('off'),
                                                       sorted(o.get('plsrcs') or [], key=str)))
        return
    planes = {}
    for l in range(4):
        if lanes >> l & 1:
            lines = (o.get('pll') or {}).get(l, {})
            if sorted(lines) != list(range(32)):
                p.append('%s: plane %d lines %d of 32' % (tag, l, len(lines)))
                return
            planes[l] = [w for k in range(32) for w in lines[k]]
    vals = do.values_from_planes(planes, bits)
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    cov = [w for k in range(8) for w in cl[k]]
    rebuilt = zo.digest(do.block_from_values(vals, bits), 0, zo.BUF_BYTES // 4)
    for k in (0, 1):
        if o['dig'].get(('zd', k)) != rebuilt:
            p.append('%s: the planes do not rebuild depth pass %d' % (tag, k))
    # the readings this case can tell apart: RB3D_CNTL.Z_ENABLE and what the test compares
    names = []
    for ze in ('none', 'pass', 'off'):
        for cmp in ('int', 'exact'):
            if cov == do.g_coverage_words(name, ze, cmp) and vals == do.g_predict(name, ze, cmp)[1]:
                names.append((ze, cmp))
    o['ztest'] = names
    want = [(ze, cmp) for ze, cmp in names if ze == 'none']          # Z_ENABLE on: the bit plays no part
    if do.grow(name)[4] == do.RB3D_Z_ON:
        if not want:
            near = [(do.g_coverage_words(name, 'none', cmp) == cov,
                     sum(1 for q, v in do.g_predict(name, 'none', cmp)[1].items() if vals.get(q) != v)) for cmp in ('int', 'exact')]
            p.append('%s: neither reading explains this case (colour/depth match %s)' % (tag, near))
        elif len(want) == 1:                    # a case that tells the two readings apart
            notes.append('%s: the test compares the %s value' % (
                tag, 'floored' if want[0][1] == 'int' else 'unfloored'))
    elif names:
        notes.append('%s (recorded): Z_ENABLE = 0 behaves as %s' % (tag, names))
    else:
        notes.append('%s (recorded): Z_ENABLE = 0 matches no named reading; colour pixels %d, depth values %d'
                     % (tag, sum(1 for w in cov for k in range(16) if (w >> (2 * k)) & 3),
                        len(set(vals.values()))))


def judge_texture(o, name, tag, p, notes):
    """one R6h case (docs/R6H_PLAN.md 2-3): the texture read back, the coverage = the R6d rule, the
    four colour planes complete; the per-pixel texels go to the boot-level rule search"""
    if o.get('pfbad') not in (0, None):
        p.append('%s: the texture did not read back (%s words)' % (tag, o.get('pfbad')))
        return
    # the driver's lane-miss counters compare against a CONSTANT lane; a textured pixel varies in
    # every lane, so for R6h they are a record, not a gate (the case rows carry gconst = gvary = 0)
    if o.get('lanes') != 0xf or o.get('plsrcs') != {0}:
        p.append('%s: lanes %s source %s, want f and the colour buffer' % (tag, o.get('lanes'),
                                                                           sorted(o.get('plsrcs') or [], key=str)))
        return
    notes.append('%s: lane misses %s (a textured pixel varies in every lane -- recorded)' % (tag, o.get('off')))
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    codes = to.decode_map([w for k in range(8) for w in cl[k]])
    want = to.cover(te.GEOM, to.MEASURED, 32)
    if not ((codes != 0) == want).all():
        p.append('%s: coverage is not the R6d rule (%d pixels differ)' % (tag, int(((codes != 0) != want).sum())))
    planes = {}
    for l in range(4):
        lines = (o.get('pll') or {}).get(l, {})
        if sorted(lines) != list(range(32)):
            p.append('%s: plane %d lines %d of 32' % (tag, l, len(lines)))
            return
        planes[l] = [w for k in range(32) for w in lines[k]]
    px = {}
    for x, y in go.covered(te.GEOM):
        i = y * 32 + x
        px[(x, y)] = sum(((planes[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
    o['texpix'] = px


def judge_texture_all(zs, p, notes):
    """R6h (docs/R6H_PLAN.md 2-3): one named ST -> texel rule must explain every case's safe pixels;
    XE says whether POT addressing reads PP_TXPITCH, and the fetched word's byte order is named"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in te.CASE_NUM)
    if not by:
        return
    fits = []
    for rule in te.RULES + [te.MEASURED]:
        miss = 0
        for n, o in by.items():
            if 'texpix' not in o:
                continue
            for q, (want, safe) in te.rule_map(n, rule).items():
                if safe and o['texpix'].get(q) != want:
                    miss += 1
        fits.append((miss, rule))
    fits.sort()
    if fits and fits[0][0] == 0:
        names = [r for m, r in fits if m == 0]
        notes.append('R6h: the ST rule is %s (%d named rules fit)' % (names[0], len(names)))
    else:
        p.append('R6h: no named ST rule explains the safe pixels (FAIL, measured) -- nearest %s' %
                 [(m, r) for m, r in fits[:3]])
    o = by.get('XE')
    if o is not None and 'texpix' in o:
        for lab, stride in (('the width, floored at 32 bytes (POT ignores PP_TXPITCH)', None), ('PP_TXPITCH', 64)):
            m = te.rule_map('XE', te.MEASURED, stride_assumed=stride)
            bad = sum(1 for q, (want, safe) in m.items() if safe and o['texpix'].get(q) != want)
            if bad == 0:
                notes.append('R6h: the sampler takes the row stride from %s' % lab)
    o = by.get('XA')
    if o is not None and 'texpix' in o:
        m = te.rule_map('XA', te.MEASURED)
        same = sum(1 for q, (want, safe) in m.items() if safe and o['texpix'].get(q) == want)
        swapped = sum(1 for q, (want, safe) in m.items() if safe and o['texpix'].get(q) ==
                      ((want & 0xff00ff00) | ((want & 0xff) << 16) | ((want >> 16) & 0xff)))
        notes.append('R6h: the fetched word reaches the pixel unchanged on %d safe pixels (byte-swapped on %d)' %
                     (same, swapped))


def judge_ptex(o, name, tag, p, notes):
    """one R6i textured case (docs/R6I_PLAN.md 2-3), or an R6j blend case: the texture read back
    (textured cases only), the coverage = the R6d rule, four complete colour planes; the pixels go
    to the boot-level rule search"""
    if o.get('pfbad') not in (0, None):
        p.append('%s: the texture did not read back (%s words)' % (tag, o.get('pfbad')))
        return
    if o.get('lanes') != 0xf or o.get('plsrcs') != {0}:
        p.append('%s: lanes %s source %s, want f and the colour buffer' % (tag, o.get('lanes'),
                                                                           sorted(o.get('plsrcs') or [], key=str)))
        return
    notes.append('%s: lane misses %s (a textured pixel varies in every lane -- recorded)' % (tag, o.get('off')))
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    codes = to.decode_map([w for k in range(8) for w in cl[k]])
    G = pe.geom_of(name)                        # R6i-2: the case says which triangle it draws
    want = to.cover(G, to.MEASURED, 32)
    if not ((codes != 0) == want).all():
        p.append('%s: coverage is not the R6d rule (%d pixels differ)' % (tag, int(((codes != 0) != want).sum())))
    planes = {}
    for l in range(4):
        lines = (o.get('pll') or {}).get(l, {})
        if sorted(lines) != list(range(32)):
            p.append('%s: plane %d lines %d of 32' % (tag, l, len(lines)))
            return
        planes[l] = [w for k in range(32) for w in lines[k]]
    px = {}
    for x, y in go.covered(G):
        i = y * 32 + x
        px[(x, y)] = sum(((planes[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
    o['texpix'] = px


def _ptex_fits(name, o, rules):
    """[(pixels missed, rule)] for one case, over a rule space -- safe pixels only"""
    out = []
    for r in rules:
        m = pe.predict(name, r)
        out.append((sum(1 for q, (want, safe) in m.items() if safe and o['texpix'].get(q) != want), r))
    out.sort(key=lambda t: t[0])
    return out


def judge_persp_all(zs, p, notes):
    """R6i across the boot (docs/R6I_PLAN.md 2-3): P1 the perspective model, P2 VTX_W0_FMT,
    P3 the colour, P4 the depth, B1 the bilinear rule, B2 the constant channels, B3 the axes"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in pe.CASE_NUM)
    ctl = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in ('V8', 'I1_24'))
    if not by:
        return
    # ---- P1: the model axis, over the cases whose W the driver gives as the vertex word
    P1 = [n for n in ('PA', 'PB', 'PC', 'PD', 'PH') if 'texpix' in by.get(n, {})]
    models = set(pe.MODELS)
    for n in P1:
        fits = _ptex_fits(n, by[n], pe.NRULES)
        if fits[0][0] != 0:
            p.append('R6i P1 %s: no named nearest rule explains the safe pixels (FAIL, measured) -- nearest %s' %
                     (n, fits[:3]))
            continue
        ok = set(r[0] for m, r in fits if m == 0)
        notes.append('R6i P1 %s: models that fit %s (%d named rules)' % (n, sorted(ok), sum(1 for m, _ in fits if m == 0)))
        if n in ('PB', 'PC'):                   # only a W != 1 case can tell the models apart
            models &= ok
    if len(models) == 1:
        notes.append('R6i P1: the perspective model is %s' % sorted(models)[0])
        offs = set(pe.OFFS)
        for n2 in ('PB', 'PC'):
            if 'texpix' in by.get(n2, {}):
                offs &= set(r[1] for m, r in _ptex_fits(n2, by[n2], pe.NRULES) if m == 0)
        if sorted(models) == ['A']:
            notes.append('R6i P1: the sample position cannot be separated -- this machine ignores W, '
                         'so the ST is linear in screen space and every offset fits (%s)' % sorted(offs))
        elif len(offs) == 1:
            notes.append('R6i P1: the ST is sampled at pixel + %s (the perspective cases separate it; '
                         'an affine ST cannot)' % sorted(offs)[0])
        else:
            p.append('R6i P1: the sample position is not pinned: %s' % sorted(offs))
    elif P1:
        p.append('R6i P1: the W != 1 cases leave %s (want exactly one model)' % sorted(models))
    # PA, PD and PH must be the affine picture, word for word
    for n in ('PA', 'PD', 'PH'):
        o = by.get(n)
        if o is None or 'texpix' not in o:
            continue
        m = pe.predict(n, ('A', pe.MEASURED_OFF, None))
        bad = sum(1 for q, (want, safe) in m.items() if safe and o['texpix'].get(q) != want)
        if bad:
            p.append('R6i P1 %s: %d safe pixels differ from the affine picture' % (n, bad))
        else:
            notes.append('R6i P1 %s: the affine picture, safe pixels all equal' % n)
    # ---- P2: VTX_W0_FMT.  PF gives W = 1, 8, 2 with the bit set: either the reciprocal is taken
    # (the same picture as PB's q model) or it is not
    o = by.get('PF')
    if o is not None and 'texpix' in o:
        b = by.get('PB')
        if b is not None and 'texpix' in b:
            same = sum(1 for q in b['texpix'] if o['texpix'].get(q) == b['texpix'][q])
            notes.append('R6i P2: PF (VTX_W0_FMT set, W = 1, 8, 2) equals PB (bit clear, W = 1, 1/8, 1/2) '
                         'on %d of %d pixels%s' % (same, len(b['texpix']),
                                                   ' -- the hardware takes the reciprocal' if same == len(b['texpix']) else ''))
        got = []
        for m in pe.MODELS:
            miss = min(sum(1 for q, (want, safe) in pe.nearest_map('PF', (m, off, None)).items()
                           if safe and o['texpix'].get(q) != want) for off in pe.OFFS)
            got.append((miss, m))
        got.sort()
        if got[0][0] == 0:
            notes.append('R6i P2: with VTX_W0_FMT set the sampler uses %s (0 safe pixels differ); the others %s' %
                         (got[0][1], got[1:]))
        else:
            p.append('R6i P2: VTX_W0_FMT gives no named model (FAIL, measured) -- %s' % got)
    # ---- P3: the colour under perspective
    o = by.get('PE')
    if o is not None and (o.get('planes') or {}):
        # the gate is the model; the last LSB is the hardware's fixed-point divide, which this rung
        # records rather than names (as R6f left the depth setup's rounding open)
        fits = []
        for m in pe.MODELS:
            for wmode in ('round', 'even'):
                d = mx = 0
                for lane in go.GCASES['V8'][2]:
                    seen = go.unpack_plane(o['planes'][lane], go.covered(pe.GEOM_V8))
                    for u, v in zip(pe.gouraud_bytes('PE', lane, m, wmode), seen):
                        d += u != v
                        mx = max(mx, abs(u - v))
                fits.append((mx, d, m, wmode))
        fits.sort()
        near = [f for f in fits if f[0] <= 1]
        far = [f for f in fits if f[0] > 8]
        notes.append('R6i P3: (largest byte error, bytes off, model, weight rounding) %s' % fits[:4])
        if near and len(set(f[2] for f in near)) == 1 and len(set(f[2] for f in far)) == len(pe.MODELS) - 1:
            notes.append('R6i P3: the colour follows %s -- %d of 312 bytes are off by one LSB '
                         '(the divide is not exact to the last bit)' % (near[0][2], near[0][1]))
        else:
            p.append('R6i P3: the colour model is not named within one LSB (FAIL, measured) -- %s' % fits[:3])
    # ---- P4: the depth under perspective
    o = by.get('PZ')
    c = ctl.get('I1_24')
    if o is not None and 'dvals' in o:
        # the affine control calibrates the noise floor: R6f left the setup's gradient rounding
        # unnamed, so "affine plane, floored" is exact only to a few LSBs (docs/R6F_PLAN.md 12)
        base = pe.depth_values('PZ', 'A')
        floor = None
        if c is not None and 'dvals' in c:
            floor = max(abs(c['dvals'][q] - base[q]) for q in base if q in c['dvals'])
            notes.append('R6i P4: the affine control I1_24 differs from the exact affine plane by at most %d LSB' % floor)
        tol = min(max(floor if floor is not None else 0, 4), 64)   # a control that is far off cannot widen it
        fits = sorted((max(abs(o['dvals'].get(q, -1 << 40) - want[q]) for q in want), m)
                      for m, want in ((m, pe.depth_values('PZ', m)) for m in pe.MODELS))
        near = [m for d, m in fits if d <= tol]
        far = [(d, m) for d, m in fits if d > 64 * max(tol, 1)]
        notes.append('R6i P4: largest depth difference per model %s (tolerance %d)' % (fits, tol))
        if len(near) == 1 and len(far) == len(fits) - len(near):
            notes.append('R6i P4: the depth follows %s' % near[0])
        else:
            p.append('R6i P4: the depth names %s within %d LSB (want exactly one, the others far) -- %s' %
                     (near, tol, fits))
        if c is not None and 'dvals' in c:
            same = sum(1 for q in c['dvals'] if o['dvals'].get(q) == c['dvals'][q])
            notes.append('R6i P4: PZ and the affine control I1_24 agree on %d of %d pixels%s' % (
                same, len(c['dvals']),
                ' -- the depth is NOT perspective-corrected' if same == len(c['dvals']) else ''))
    # ---- B1: the bilinear rule, one name across the linear cases
    lin = [n for n in pe.ORDER1 if pe.kind(n) == 'tex' and pe.filter_of(n) == 'linear' and n != 'PL'
           and 'texpix' in by.get(n, {})]
    named = []
    if lin:
        # B1a (gate): the texel-space offset a.  The exact bilinear value at the measured sample
        # point must be within 8 LSB for exactly one a, and the other must be far out
        worst = {}
        for a in pe.AOFF:
            d = 0
            for n2 in lin:
                m2 = pe.bilinear_map(n2, ('A', pe.MEASURED_OFF, a, None, 'floor', 'floor'))
                for q, (want, safe) in m2.items():
                    if not safe:
                        continue
                    got = by[n2]['texpix'].get(q, 0)
                    d = max(d, max(abs(((want >> (8 * l)) & 0xff) - ((got >> (8 * l)) & 0xff)) for l in range(4)))
            worst[a] = d
        near = [a for a, d in worst.items() if d <= 8]
        far = [a for a, d in worst.items() if d >= 64]
        notes.append('R6i B1a: largest difference from exact bilinear per texel offset %s' %
                     dict((str(a), d) for a, d in sorted(worst.items())))
        if len(near) == 1 and len(far) == len(worst) - 1:
            notes.append('R6i B1a: the texel offset is a = %s (the OpenGL half-texel convention)' % near[0])
        else:
            p.append('R6i B1a: the texel offset is not named: within 8 LSB %s, far %s' % (near, far))
        # B1b (measurement): does a named quantum explain the last few LSBs?
        fits = []
        for r in pe.BRULES:
            if r[0] != 'A' or r[1] != pe.MEASURED_OFF or (near and r[2] != near[0]):
                continue
            fits.append((sum(sum(1 for q, (want, safe) in pe.bilinear_map(n, r).items()
                                 if safe and by[n]['texpix'].get(q) != want) for n in lin), r))
        fits.sort(key=lambda t: t[0])
        if fits and fits[0][0] == 0:
            named = [r for m, r in fits if m == 0]
            notes.append('R6i B1b: the bilinear rule is %s (%d named rules fit, over %s)' %
                         (named[0], len(named), ' '.join(lin)))
        elif fits:
            p.append('R6i B1b: no named weight arithmetic explains the safe pixels (FAIL, measured) -- '
                     'nearest %s' % [(m, r) for m, r in fits[:3]])
    # ---- B2: the constant channels
    for n in lin:
        o = by[n]
        pat = pe.tex_of(n)[3]
        want = dict(A=0xff)
        if pat == 2:
            want['B'] = 0x55
        bad = dict((k, sum(1 for q, v in o['texpix'].items()
                           if ((v >> (24 if k == 'A' else 0)) & 0xff) != w)) for k, w in want.items())
        if any(bad.values()):
            notes.append('R6i B2 %s: constant channels moved %s (measured: the weights do not sum to one)' % (n, bad))
        else:
            notes.append('R6i B2 %s: the constant channels held (%s)' % (n, ' '.join(sorted(want))))
    # ---- B3 and the nearest controls: LB, LE, LN must be the R6h rule, word for word
    for n in ('LB', 'LE', 'LN'):
        o = by.get(n)
        if o is None or 'texpix' not in o:
            continue
        m = pe.nearest_map(n, ('A', pe.MEASURED_OFF, None))
        bad = sum(1 for q, (want, safe) in m.items() if safe and o['texpix'].get(q) != want)
        if bad:
            p.append('R6i B3 %s: %d safe pixels differ from the R6h rule' % (n, bad))
        elif n == 'LN':
            sw = pe.nearest_map('LN', ('A', pe.MEASURED_OFF, None), wh=(8, 2))
            d = sum(1 for q, (want, safe) in sw.items() if safe and o['texpix'].get(q) != want)
            notes.append('R6i B3: the 2x8 texture reads as 2 wide by 8 high (the swapped reading misses %d)' % d)
    # ---- P5: the perspective divide seen through the named bilinear rule
    o = by.get('PL')
    if o is not None and 'texpix' in o:
        if not named:
            notes.append('R6i P5: not analysed (no named bilinear rule)')
        else:
            r = named[0]
            fits = sorted((sum(1 for q, (want, safe) in pe.bilinear_map('PL', (m,) + r[1:]).items()
                               if safe and o['texpix'].get(q) != want), m) for m in pe.MODELS)
            if fits[0][0] == 0:
                notes.append('R6i P5: the divide is exact under %s at byte precision; the rest %s' % (fits[0][1], fits[1:]))
            else:
                notes.append('R6i P5: no model is exact at byte precision (measured) -- %s' % fits)


def judge_arith(zs, p, notes):
    """R6i-2 across the boot (docs/R6I2_PLAN.md 2-3): G0 the geometry, GA the weight arithmetic,
    GS the axes, GP the divide, GC the R6i control, GF the FILTER_ROUND_MODE bit"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in pe.CASE_NUM)
    if not by:
        return
    # ---- G0: the nearest rule on the new geometry, word for word
    o = by.get('Q0')
    if o is not None and 'texpix' in o:
        m = pe.nearest_map('Q0', ('A', pe.MEASURED_OFF, None))
        bad = sum(1 for q, (want, safe) in m.items() if safe and o['texpix'].get(q) != want)
        if bad:
            p.append('R6i-2 G0: %d safe pixels of Q0 differ from the R6i nearest rule' % bad)
        else:
            notes.append('R6i-2 G0: the 16 x 16 geometry samples as R6i measured (%d safe pixels)' %
                         sum(1 for q, (w, sf) in m.items() if sf))
    # ---- GA: one class of weight arithmetic explains Q1, Q2 and Q3
    sweep = [n for n in ('Q1', 'Q2', 'Q3') if 'texpix' in by.get(n, {})]
    named = []
    if len(sweep) == 3:
        # the two-stage space (docs/R6I2_PLAN.md 8): a quantum per axis and a rounding constant per
        # 1-D mix.  Q1 (fv = 0) pins the horizontal constant, Q3 (fu = 0) the vertical one, Q2 both
        fits = []
        for r in pe.ARULES2:
            d = 0
            for n2 in sweep:
                m2 = pe.arith_map2(n2, r)
                d += sum(1 for q, want in m2.items() if by[n2]['texpix'].get(q) != want)
            fits.append((d, r))
        fits.sort(key=lambda t: (t[0], str(t[1])))
        named = [r for d, r in fits if d == 0]
        if named:
            q, mode, r1, r2 = named[0]
            notes.append('R6i-2 GA: the filter truncates each axis to k/%d (%s) and mixes with '
                         '(a*(%d-k) + b*k + r) >> %d, r = %d across and %d down%s' %
                         (q, mode, q, q.bit_length() - 1, r1 * q // 8, r2 * q // 8,
                          '' if len(named) == 1 else
                          ' -- this sweep cannot separate %d rules that give the same picture: %s'
                          % (len(named), named[:6])))
        else:
            p.append('R6i-2 GA: no named weight arithmetic explains the sweep (FAIL, measured) -- nearest %s' %
                     [(d, r) for d, r in fits[:3]])
    # ---- GS: the horizontal name and the vertical name agree
    if named:
        per = {}
        for n2 in ('Q1', 'Q3'):
            if 'texpix' not in by.get(n2, {}):
                continue
            per[n2] = set(r for r in pe.ARULES2
                          if all(by[n2]['texpix'].get(q) == want for q, want in pe.arith_map2(n2, r).items()))
        if len(per) == 2:
            both = per['Q1'] & per['Q3']
            r1 = set(r[2] for r in per['Q1'])
            r2 = set(r[3] for r in per['Q3'])
            if both:
                notes.append('R6i-2 GS: one rule explains both sweeps (%d in common); the horizontal '
                             'constant is %s and the vertical one %s' % (len(both), sorted(r1), sorted(r2)))
            else:
                p.append('R6i-2 GS: the axes name different arithmetic -- across %s, down %s '
                         '(the two 1-D mixes round differently; whether that follows the AXIS or the '
                         'CHANNEL is confounded here, see docs/R6I2_PLAN.md 8)' % (sorted(r1), sorted(r2)))
    # ---- GP: the perspective divide, seen through the named arithmetic
    o = by.get('Q4')
    if o is not None and 'texpix' in o:
        if not named:
            notes.append('R6i-2 GP: not analysed (no named arithmetic)')
        else:
            m4 = pe.arith_map2('Q4', named[0])
            err = max(max(abs(((want >> (8 * l)) & 0xff) - ((o['texpix'].get(q, 0) >> (8 * l)) & 0xff))
                          for l in range(4)) for q, want in m4.items())
            off = sum(1 for q, want in m4.items() if o['texpix'].get(q) != want)
            notes.append('R6i-2 GP: the perspective divide is exact to %d LSB (%d of %d pixels differ '
                         'from the exact-rational divide)' % (err, off, len(m4)))
            if err > 1:
                p.append('R6i-2 GP: the divide is off by %d LSB, more than the one LSB this gate allows' % err)
    # ---- GC: the R6i control still holds in this build
    o = by.get('LD')
    if o is not None and 'texpix' in o:
        m2 = pe.bilinear_map('LD', ('A', pe.MEASURED_OFF, Fraction(-1, 2), None, 'floor', 'floor'))
        d = max(max(abs(((want >> (8 * l)) & 0xff) - ((o['texpix'].get(q, 0) >> (8 * l)) & 0xff))
                    for l in range(4)) for q, (want, safe) in m2.items() if safe)
        if d > 8:
            p.append('R6i-2 GC: the R6i case LD is %d LSB from exact bilinear in this build (R6i measured 6)' % d)
        else:
            notes.append('R6i-2 GC: the R6i control LD is within %d LSB of exact bilinear, as in R6i' % d)
        if named:
            bad = sum(1 for q, want in pe.arith_map2('LD', named[0]).items() if o['texpix'].get(q) != want)
            notes.append('R6i-2 GC: the named arithmetic explains LD on %d of %d pixels '
                         '(its gradients are not dyadic, so the setup rounding shows here)' %
                         (len(o['texpix']) - bad, len(o['texpix'])))
    # ---- GF: what the FILTER_ROUND_MODE bit does
    o, o1 = by.get('Q5'), by.get('Q1')
    if o is not None and o1 is not None and 'texpix' in o and 'texpix' in o1:
        same = sum(1 for q in o1['texpix'] if o['texpix'].get(q) == o1['texpix'][q])
        if same == len(o1['texpix']):
            notes.append('R6i-2 GF: PP_CNTL.FILTER_ROUND_MODE changes nothing here (%d of %d pixels equal Q1)'
                         % (same, len(o1['texpix'])))
        else:
            fits = sorted(((sum(1 for q, want in pe.arith_map2('Q5', r).items() if o['texpix'].get(q) != want), r)
                           for r in pe.ARULES2), key=lambda t: (t[0], str(t[1])))
            ok = [r for d, r in fits if d == 0]
            if ok:
                rs = sorted(set(r[2] for r in ok))
                notes.append('R6i-2 GF: with FILTER_ROUND_MODE set the horizontal constant is r = %s '
                             '(of %d, quantum %s); Q1 agreed on %d of %d pixels'
                             % ([x * ok[0][0] // 8 for x in rs], ok[0][0], sorted(set(r[0] for r in ok)),
                                same, len(o1['texpix'])))
            else:
                p.append('R6i-2 GF: FILTER_ROUND_MODE gives neither Q1 nor a named arithmetic (FAIL, measured) '
                         '-- nearest %s' % [(d, r) for d, r in fits[:3]])


def judge_axis(zs, p, notes):
    """R6i-3 (docs/R6I3_PLAN.md 2-3): H1 does the rounding constant follow the axis or the channel,
    H2 what FILTER_ROUND_MODE makes of the two constants, H3 the R6i-2 controls"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in pe.CASE_NUM)
    if not by:
        return
    # ---- H3 first: the R6i-2 rule must still hold in this build
    for n2 in ('Q1', 'Q3'):
        o = by.get(n2)
        if o is None or 'texpix' not in o:
            continue
        bad = sum(1 for q, want in pe.arith_map2(n2, pe.MEASURED_ARITH).items() if o['texpix'].get(q) != want)
        if bad:
            p.append('R6i-3 H3: the R6i-2 control %s differs from its measured rule on %d pixels' % (n2, bad))
        else:
            notes.append('R6i-3 H3: the R6i-2 control %s is unchanged (%d pixels)' % (n2, len(o['texpix'])))
    # ---- H1: axis or channel
    reading = None
    for n2 in ('N1', 'N2'):
        o = by.get(n2)
        if o is None or 'texpix' not in o:
            continue
        ax = sum(1 for q, want in pe.arith_map2(n2, pe.MEASURED_ARITH).items() if o['texpix'].get(q) != want)
        ch = sum(1 for q, want in pe.arith_map_chan(n2, pe.MEASURED_ARITH).items() if o['texpix'].get(q) != want)
        notes.append('R6i-3 H1 %s: the axis reading misses %d pixels, the channel reading %d (of %d)' %
                     (n2, ax, ch, len(o['texpix'])))
        this = 'axis' if ax == 0 and ch else 'channel' if ch == 0 and ax else None
        if this is None:
            p.append('R6i-3 H1 %s: neither reading is exact (or both are) -- axis %d, channel %d '
                     '(FAIL, measured)' % (n2, ax, ch))
        elif reading is None:
            reading = this
        elif reading != this:
            p.append('R6i-3 H1: N1 says the constant follows the %s, N2 says the %s' % (reading, this))
    if reading:
        notes.append('R6i-3 H1: the rounding constant follows the %s (48 across, 32 down)'
                     % ('AXIS' if reading == 'axis' else 'COLOUR CHANNEL'))
    # ---- H2: the constants with FILTER_ROUND_MODE set, and the bit-clear control
    fn = pe.arith_map_chan if reading == 'channel' else pe.arith_map2
    o = by.get('N5')
    if o is not None and 'texpix' in o:
        bad = sum(1 for q, want in fn('N5', pe.MEASURED_ARITH).items() if o['texpix'].get(q) != want)
        if bad:
            p.append('R6i-3 H2: the bit-clear control N5 differs from the measured constants on %d pixels' % bad)
        else:
            notes.append('R6i-3 H2: N5 (the same sweep without the bit) matches r = 48 across, 32 down '
                         'on all %d pixels' % len(o['texpix']))
    for n2, lab in (('N3', 'across'), ('N4', 'down')):
        o = by.get(n2)
        if o is None or 'texpix' not in o:
            continue
        fits = sorted(((sum(1 for q, want in fn(n2, r).items() if o['texpix'].get(q) != want), r)
                       for r in pe.ARULES2), key=lambda t: (t[0], str(t[1])))
        ok = [r for d, r in fits if d == 0]
        if not ok:
            p.append('R6i-3 H2 %s: no named arithmetic explains it with the bit set (FAIL, measured) -- '
                     'nearest %s' % (n2, [(d, r) for d, r in fits[:3]]))
            continue
        idx = 2 if lab == 'across' else 3
        vals = sorted(set(r[idx] * r[0] // 8 for r in ok))
        qs = sorted(set(r[0] for r in ok))
        if len(vals) == 1:
            notes.append('R6i-3 H2 %s: with FILTER_ROUND_MODE set the %s constant is r = %d (of %s)' %
                         (n2, lab, vals[0], qs[0] if len(qs) == 1 else qs))
        else:
            notes.append('R6i-3 H2 %s: the %s constant is one of %s (of %s) -- this sweep cannot '
                         'narrow it further' % (n2, lab, vals, qs))


def judge_batch_case(o, name, tag, p, notes):
    """one R6l case (docs/R6L_PLAN.md 5): the coverage map is the oracle's picture, and the colour
    and depth digests say the same pixels changed -- nothing is written outside the map"""
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    cov = [w for k in range(8) for w in cl[k]]
    o['cov'] = cov
    want = ba.coverage_words(name)
    if cov != want:
        got = to.decode_map(cov)
        exp = to.decode_map(want)
        p.append('%s: the coverage map differs from the oracle on %d pixels' %
                 (tag, int((got != exp).sum())))
        return
    px = ba.picture(name)
    zc, zd = o['dig'].get(('zc', 1)), o['dig'].get(('zd', 1))
    ec, ed = ba.digests(name)
    if zc is None or zd is None:
        p.append('%s: no digest' % tag)
        return
    if zc != ec:
        p.append('%s: the colour digest disagrees with the picture (%d words changed, want %d)' %
                 (tag, zc['changed'], ec['changed']))
    if (zd['changed'], zd['ixor'], zd['isum']) != (ed['changed'], ed['ixor'], ed['isum']):
        p.append('%s: the depth covers other pixels than the colour (changed %d vs %d)' %
                 (tag, zd['changed'], ed['changed']))
    o['npix'] = len(px)


def judge_batch_all(zs, p, notes, wptrs):
    """R6l across the boot: M1 the big packets, M2 the order, M3 the clip between packets,
    M4 the ring wrap and the repeats, M5 the regression"""
    by = {}
    for o in zs:
        by.setdefault(CASE_NAME.get(o['len']), []).append(o)
    if not any(n in by for n in ba.ORDER):
        return
    # ---- M1: the big packets drew every triangle
    for n, want in (('BA', 240), ('BB', 640)):
        for k, o in enumerate(by.get(n, [])):
            if o.get('npix') != want:
                p.append('R6l M1: %s run %d wrote %s pixels, the oracle says %d' % (n, k + 1, o.get('npix'), want))
    if by.get('BA') and by.get('BB') and by['BA'][0].get('npix') and by['BB'][0].get('npix'):
        notes.append('R6l M1: one packet of 40 triangles (120 vertices) and one of 80 (240) draw every '
                     'triangle (%d and %d pixels)' % (by['BA'][0]['npix'], by['BB'][0]['npix']))
    # ---- M2 and M3: the order, and the clip that moves mid-batch
    o = (by.get('BC') or [None])[0]
    if o is not None and 'cov' in o:
        if o.get('npix'):
            notes.append('R6l M2: eight packets in one submission draw in order -- the last packet to '
                         'cover a pixel owns it (%d pixels)' % o['npix'])
    o2 = (by.get('BD') or [None])[0]
    if o is not None and o2 is not None and 'cov' in o and 'cov' in o2:
        d = int((to.decode_map(o['cov']) != to.decode_map(o2['cov'])).sum())
        if d != 50:
            p.append('R6l M3: BD differs from BC on %d pixels, the oracle says 50' % d)
        else:
            notes.append('R6l M3: a WAIT_UNTIL and a new clip before the fifth packet change only the '
                         'packets after it (50 pixels differ from BC)')
    # ---- M4: the ring wrapped, and every repeat of a case gave the same picture
    # a wrap that lands on 0 ended exactly at the ring end (cpR6Submit padded nothing); one that
    # lands elsewhere went through the padding.  Say which, rather than assuming (gate-must-log)
    drops = [(a, b) for a, b in zip(wptrs, wptrs[1:]) if b < a]
    if not drops:
        p.append('R6l M4: the ring never wrapped in this boot (wptr %s .. %s)' %
                 (wptrs[:1], wptrs[-1:]))
    else:
        kinds = ['%d>%d %s' % (a, b, 'exactly at the end' if b == 0 else 'through the padding')
                 for a, b in drops]
        notes.append('R6l M4: the ring wrapped %d time(s): %s' % (len(drops), '; '.join(kinds)))
        if all(b == 0 for _, b in drops):
            notes.append('R6l M4: every wrap this boot ended exactly at the ring end -- the PACKET2 '
                         'padding path itself did not run (measured, not assumed)')
    for n in ba.ORDER:
        runs = by.get(n, [])
        if len(runs) > 1:
            same = all(r.get('cov') == runs[0].get('cov') and r['dig'].get(('zc', 1)) == runs[0]['dig'].get(('zc', 1))
                       for r in runs[1:])
            if not same:
                p.append('R6l M4: the %d runs of %s do not agree' % (len(runs), n))
            else:
                notes.append('R6l M4: %s drew the same picture %d times (the last one after the wrap)' %
                             (n, len(runs)))
    # ---- M5: the plain single-triangle case still draws what R6d measured
    o = (by.get('BF') or [None])[0]
    if o is not None and o.get('npix'):
        notes.append('R6l M5: one triangle in one packet is unchanged (%d pixels)' % o['npix'])


def judge_reuse_case(o, name, tag, p, notes):
    """one R6m case (docs/R6M_PLAN.md 5): the driver resolved the surfaces the row names, the
    picture landed in THOSE surfaces word for word, nothing outside them moved, and the texture
    still holds exactly what the CPU wrote into it"""
    co, zf, tf = ru.offsets(name)
    want = (co, zf, tf if ru.is_tex(name) else 0)
    got = o.get('zsurf')
    if got != want:
        p.append('%s: the driver used surfaces %s, the row says %s' %
                 (tag, got and tuple('0x%05x' % v for v in got), tuple('0x%05x' % v for v in want)))
        return
    tp = o.get('texpost')
    if ru.is_tex(name) and (tp is None or tp[0] != 0):
        p.append('%s: after the draw the texture surface does not hold what the CPU wrote '
                 '(%s words differ, first at %s = %08x)' % ((tag,) + (tp if tp else (None, None, 0))))
    if o.get('pfbad') not in (0, None):
        p.append('%s: the texture did not read back before the draw (%s words)' % (tag, o.get('pfbad')))
    # ---- N1: the coverage map, read out of the case's own colour surface
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    cov = [w for k in range(8) for w in cl[k]]
    o['cov'] = cov
    if cov != ru.coverage_words(name):
        got_m, exp_m = to.decode_map(cov), to.decode_map(ru.coverage_words(name))
        p.append('%s: the coverage map differs from the oracle on %d pixels' %
                 (tag, int((got_m != exp_m).sum())))
        return
    # ---- N1: the digests, at the case's own offsets
    ec, ed = ru.digests(name)
    zc, zd = o['dig'].get(('zc', 1)), o['dig'].get(('zd', 1))
    if zc is None or zd is None:
        p.append('%s: no digest' % tag)
        return
    if ru.is_tex(name):
        # a textured pixel's colour is the planes' business (R6h); here the digests say WHERE
        for lab, g, e in (('colour', zc, ec), ('depth', zd, ed)):
            if (g['changed'], g['ixor'], g['isum']) != (e['changed'], e['ixor'], e['isum']):
                p.append('%s: the %s surface changed %d words at %s/%s, the oracle says %d at %s/%s' %
                         (tag, lab, g['changed'], g['ixor'], g['isum'], e['changed'], e['ixor'], e['isum']))
    else:
        if zc != ec:
            p.append('%s: the colour digest is %s, the oracle says %s' % (tag, zc, ec))
        if zd != ed:
            p.append('%s: the depth digest is %s, the oracle says %s' % (tag, zd, ed))
    # ---- N2: nothing outside this case's own surfaces moved
    rest = o.get('rest')
    if rest is None or rest[0] != 0 or rest[1] != 0:
        p.append('%s: %s words outside the case\'s surfaces changed (first %s = %08x)' %
                 ((tag,) + (rest if rest else (None, None, None, 0))[:1] + (rest or (0, 0, None, 0))[2:]))
    o['dig1'] = (zc, zd)
    # ---- the textured cases publish their pixels for the boot-wide comparison
    if ru.is_tex(name):
        planes = {}
        for l in range(4):
            lines = (o.get('pll') or {}).get(l, {})
            if sorted(lines) != list(range(32)):
                p.append('%s: plane %d lines %d of 32' % (tag, l, len(lines)))
                return
            planes[l] = [w for k in range(32) for w in lines[k]]
        px = {}
        for x, y in ru.covered(name):
            i = y * 32 + x
            px[(x, y)] = sum(((planes[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
        o['texpix'] = px


def judge_reuse_all(zs, p, notes, wptrs):
    """R6m across the boot: P1 the regression, P2 the move really moved, P3 the texels are the same
    from the new address, P4 nothing else was touched, P5 the ring took its padding branch"""
    by = {}
    for o in zs:
        by.setdefault(CASE_NAME.get(o['len']), []).append(o)
    if not any(n in by for n in ru.ORDER):
        return
    # ---- P1: ME before and ME after are the same picture
    mes = by.get('ME', [])
    if len(mes) == 2:
        same = (mes[0].get('cov') == mes[1].get('cov') and mes[0].get('dig1') == mes[1].get('dig1'))
        if not same:
            p.append('R6m P1: the two ME runs differ -- moving a surface changed the usual place')
        else:
            notes.append('R6m P1: the unmoved case draws the same picture before and after the moves')
    else:
        p.append('R6m P1: ME ran %d times, want 2' % len(mes))
    # ---- P2: a moved surface changes the same words, at a different address
    base = (mes or [None])[0]
    for n in ('MA', 'MB', 'MD'):
        o = (by.get(n) or [None])[0]
        if o is None or base is None or 'dig1' not in o or 'dig1' not in base:
            continue
        which = 0 if n != 'MB' else 1
        g, b = o['dig1'][which], base['dig1'][which]
        lab = 'colour' if which == 0 else 'depth'
        if (g['changed'], g['ixor'], g['isum']) != (b['changed'], b['ixor'], b['isum']):
            p.append('R6m P2: %s changed different %s words than ME (%d vs %d)' %
                     (n, lab, g['changed'], b['changed']))
        elif (g['xor'], g['wsum']) == (b['xor'], b['wsum']):
            p.append('R6m P2: %s has the SAME %s digest as ME -- the surface did not move' % (n, lab))
        else:
            notes.append('R6m P2: %s writes the same %d %s words at another address (the digest over the '
                         'surface differs: wsum %08x vs %08x)' % (n, g['changed'], lab, g['wsum'], b['wsum']))
    # ---- P3: the texels come back the same from the moved texture
    mc, md = (by.get('MC') or [None])[0], (by.get('MD') or [None])[0]
    m = te.rule_map('XA', te.MEASURED)
    for n, o in (('MC', mc), ('MD', md)):
        if o is None or 'texpix' not in o:
            continue
        bad = sum(1 for q, (v, safe) in m.items() if safe and o['texpix'].get(q) != v)
        if bad:
            p.append('R6m P3: %s reads %d safe pixels differently from XA at its usual address' % (n, bad))
        else:
            notes.append('R6m P3: %s samples the moved texture exactly as XA samples the usual one '
                         '(%d safe pixels)' % (n, sum(1 for _q, (_v, sf) in m.items() if sf)))
    if mc is not None and md is not None and 'texpix' in mc and 'texpix' in md:
        if mc['texpix'] != md['texpix']:
            p.append('R6m P3: MD (all three moved) and MC (texture only) disagree on %d pixels' %
                     sum(1 for q in set(mc['texpix']) | set(md['texpix'])
                         if mc['texpix'].get(q) != md['texpix'].get(q)))
        else:
            notes.append('R6m P3: moving the colour and depth surfaces as well changes nothing')
    # ---- P4: the texture was untouched by every draw that used one
    tp = [(n, (by[n][0].get('texpost') or (None,))[0]) for n in ('MC', 'MD') if by.get(n)]
    if tp and all(v == 0 for _n, v in tp):
        notes.append('R6m P4: the draw wrote nothing into the texture surface (%s)' %
                     ', '.join('%s 0' % n for n, _v in tp))
    # ---- P5 (task #30): the ring's padding branch
    drops = [(a, b) for a, b in zip(wptrs, wptrs[1:]) if b < a]
    pads = [(a, b) for a, b in drops if b != 0]
    if not drops:
        p.append('R6m P5: the ring never wrapped in this boot (wptr %s .. %s)' % (wptrs[:1], wptrs[-1:]))
    elif not pads:
        p.append('R6m P5: the ring wrapped %d time(s) but always landed exactly on the end -- the '
                 'padding branch still has not run (%s)' % (len(drops), ' '.join('%d>%d' % d for d in drops)))
    else:
        notes.append('R6m P5: the ring took its PADDING branch %d time(s) (%s) and the cases after it '
                     'drew normally' % (len(pads), ' '.join('%d>%d' % d for d in pads)))


def judge_r7_all(ops, p, notes, win):
    """R7a (docs/R7_PLAN.md 5): every staged stream must get the verdict the oracle computes, the
    two that pass must draw T1, and every refusal must leave the surfaces alone."""
    zs = [o for o in ops if o['op'] == 'zclear' and o['len'] == 171]
    want = list(vo.cases(0)) + [vo.cases(0)[0]]       # the last one is U1 again, split into pieces
    if len(zs) != len(want):
        p.append('R7a: %d client submissions, the procedure has %d' % (len(zs), len(want)))
        return
    seen_why = {}
    for k, (o, (name, words, why)) in enumerate(zip(zs, want)):
        tag = 'R7a %s' % name if k < len(vo.cases(0)) else 'R7a U2 (U1 in pieces)'
        r7 = o.get('r7')
        if r7 is None:
            # a refusal is on the record twice: the verify line, and the operation's own gate
            # value.  Reading the second means an older driver's log is still judgeable.
            if o.get('rc') == 1 and o.get('why') == 34 and o.get('gv') is not None:
                r7 = dict(words=len(words), why=o['gv'], at=None, word=None,
                          win=(win, win + 0x40000), dropped=0)
            else:
                p.append('%s: no verify line' % tag)
                continue
        if r7['words'] != len(words):
            p.append('%s: the driver staged %d words, the stream is %d' % (tag, r7['words'], len(words)))
            continue
        # the oracle is re-run against the window the DRIVER reported, not one assumed here
        w = [x + (r7['win'][0] if f else 0) for x, f in zip(words, vo.fixup_mask(words))]
        expect, note = vo.verify(w, win_start=r7['win'][0], win_end=r7['win'][1])
        if expect != why:
            p.append('%s: the oracle now says %s, the table said %s' % (
                tag, vo.WHY_NAME.get(expect), vo.WHY_NAME.get(why)))
            continue
        if r7['why'] != why:
            p.append('%s: the driver said %s%s, the oracle says %s (%s)' % (
                tag, vo.WHY_NAME.get(r7['why'], r7['why']),
                '' if r7['at'] is None else ' at word %d (%#010x)' % (r7['at'], r7['word'] or 0),
                vo.WHY_NAME.get(why), note))
            continue
        seen_why.setdefault(why, []).append(name)
        if why == vo.WHY_OK:
            cl = o.get('covl') or {}
            if sorted(cl) != list(range(8)):
                p.append('%s: coverage map lines %s' % (tag, sorted(cl)))
                continue
            cov = [x for j in range(8) for x in cl[j]]
            if cov != to.coverage_map('T1', to.MEASURED):
                got, exp = to.decode_map(cov), to.decode_map(to.coverage_map('T1', to.MEASURED))
                p.append('%s: the client\'s stream drew %d pixels differently from T1' %
                         (tag, int((got != exp).sum())))
            else:
                notes.append('%s: a stream the CLIENT built drew T1 exactly (%d words)' %
                             (tag, len(words)))
        else:
            rest = o.get('rest')
            if rest is None or rest[0] != 0 or rest[1] != 0:
                p.append('%s: refused, but %s words outside the buffers changed' % (tag, rest and rest[1]))
    fired = set(seen_why) - {vo.WHY_OK}
    if len(fired) < 8:
        p.append('R7a: only %d distinct rules refused anything (%s)' %
                 (len(fired), sorted(vo.WHY_NAME.get(x) for x in fired)))
    else:
        notes.append('R7a: %d distinct rules each refused a stream of their own (%s)' %
                     (len(fired), ', '.join(sorted(vo.WHY_NAME.get(x)[4:] for x in fired))))
    ok = seen_why.get(vo.WHY_OK, [])
    if len(ok) < 2:
        p.append('R7a: only %d stream(s) ran; U1 and the split U2 must both run' % len(ok))
    else:
        notes.append('R7a: the same stream ran whole and in three pieces (%s)' % ', '.join(ok))


SC_PLAIN = ('x_low', 'br_incl', 'keep', 'and', 'b0', 16, 16, 'unsigned', 'free')   # the plain reading


def judge_scissor_case(o, name, tag, p, notes):
    """one R6k case (docs/R6K_PLAN.md 5): the coverage map exists, every pixel is the flat colour or
    the pattern, and the colour buffer changed exactly where the map says -- a write outside the
    32 x 32 map is what AS7 is watching for"""
    cl = o.get('covl') or {}
    if sorted(cl) != list(range(8)):
        p.append('%s: coverage map lines %s, want 0 .. 7' % (tag, sorted(cl)))
        return
    cov = [w for k in range(8) for w in cl[k]]
    o['cov'] = cov
    codes = to.decode_map(cov)
    ys, xs = np.nonzero(codes != 0)
    o['px'] = frozenset((int(x), int(y)) for x, y in zip(xs.tolist(), ys.tolist()))
    n3 = int((codes == 3).sum())
    if n3:
        p.append('%s: %d pixels hold neither the flat colour nor the pattern (code 3)' % (tag, n3))
    zc = o['dig'].get(('zc', 1))
    if zc is None:
        p.append('%s: no digest' % tag)
        return
    if zc['changed'] != len(o['px']):
        p.append('%s: %d colour words changed, the map has %d -- a write outside the map' %
                 (tag, zc['changed'], len(o['px'])))
    elif not n3:
        # the whole colour buffer, not just the count: the digest must be the one this picture makes
        ec = zo.digest(sc.block_of(name, o['px']), zo.COLOR_OFF // 4, zo.BUF_BYTES // 4)
        if zc != ec:
            p.append('%s: the colour digest disagrees with the map' % tag)
    zd = o['dig'].get(('zd', 1))
    if zd is not None and sc.read_of(name) != 'depth':
        ed = zo.digest(sc.block_of(name, o['px']), zo.DEPTH_OFF // 4, zo.BUF_BYTES // 4)
        if (zd['changed'], zd['ixor'], zd['isum']) != (ed['changed'], ed['ixor'], ed['isum']):
            p.append('%s: the depth buffer covers other pixels than the colour buffer (changed %d vs %d)' %
                     (tag, zd['changed'], ed['changed']))
    if sc.read_of(name) == 'depth':
        if o.get('lanes') != 7:
            p.append('%s: lanes %s logged, want 7' % (tag, o.get('lanes')))
            return
        planes = {}
        for l in range(3):
            lines = (o.get('pll') or {}).get(l, {})
            if sorted(lines) != list(range(32)):
                p.append('%s: depth plane %d has %d of 32 lines' % (tag, l, len(lines)))
                return
            planes[l] = [w for k in range(32) for w in lines[k]]
        o['dvals'] = do.values_from_planes(planes, 24)


def judge_scissor_all(zs, p, notes):
    """R6k across the boot (docs/R6K_PLAN.md 5): K1 the control, K2 the auxiliary unit's rule,
    K3 that it cannot widen, K4 the depth of a cut pixel, K5 the inverted main scissor"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in sc.SCASES)
    if not by:
        return
    # ---- K1: with no rectangle enabled the box fills the map
    o = by.get('AS0')
    if o is not None and 'px' in o:
        if len(o['px']) != 1024:
            p.append('R6k K1: with no auxiliary rectangle the box left %d of 1024 pixels' % len(o['px']))
        else:
            notes.append('R6k K1: with no auxiliary rectangle the box fills the map (1024 pixels)')
    # ---- K2: the named rule over the gated cases
    gated = [n for n in sc.GATED if 'px' in by.get(n, {})]
    named = []
    if gated:
        fits = []
        for r in sc.RULES:
            d = sum(len(sc.picture(n, r) ^ by[n]['px']) for n in gated)
            fits.append((d, r))
        fits.sort(key=lambda t: (t[0], str(t[1])))
        named = [r for d, r in fits if d == 0]
        if named:
            axn = ('layout', 'end', 'polarity', 'combine', 'bias', 'x width', 'y width', 'sign', 'gate')
            free = []
            for i, nm in enumerate(axn):
                vals = sorted(set(r[i] for r in named if len(r) == len(axn)), key=str)
                if len(vals) > 1:
                    free.append('%s %s' % (nm, vals))
            notes.append('R6k K2: the auxiliary scissor reads as %s%s' %
                         (named[0], '' if len(named) == 1 else
                          ' (%d rules give the same %d pictures; free: %s)' %
                          (len(named), len(gated), '; '.join(free) or 'nothing nameable')))
        else:
            p.append('R6k K2: no named rule explains the auxiliary scissor (FAIL, measured) -- '
                     'nearest %s' % [(d, r) for d, r in fits[:3]])
    rule = named[0] if named else None
    # ---- K3: the auxiliary unit cannot widen what the main scissor allows
    o = by.get('AS7')
    if o is not None and 'px' in o:
        out = [q for q in o['px'] if q[0] >= 32 or q[1] >= 32]
        zc = o['dig'].get(('zc', 1))
        want = 1024 if rule is None else len(sc.picture('AS7', rule))
        if out or (zc and zc['changed'] != len(o['px'])) or len(o['px']) != want:
            p.append('R6k K3: a rectangle over the whole buffer changed the picture (%d pixels, want %d, '
                     'colour words %s)' % (len(o['px']), want, zc and zc['changed']))
        else:
            notes.append('R6k K3: with the geometry wider than the main scissor and an auxiliary '
                         'rectangle over the whole buffer, nothing outside the main scissor is written')
    # ---- K4: does a pixel the auxiliary unit cuts keep its depth?
    o = by.get('AS8')
    if o is not None and 'dvals' in o and rule is not None:
        px, vals = sc.picture('AS8', rule), o['dvals']
        kept = [q for q in vals if q not in px and vals[q] != sc.depth_ramp(q[0], q[1])]
        drawn = [q for q in px if vals.get(q) != 0x800001]
        if kept or drawn:
            p.append('R6k K4: %d cut pixels changed depth, %d drawn pixels did not (first %s)' %
                     (len(kept), len(drawn), sorted(kept or drawn)[0]))
        else:
            notes.append('R6k K4: a pixel the auxiliary scissor cuts keeps its depth -- the unit '
                         'rejects before the depth stage (%d cut, %d drawn)' % (len(vals) - len(px), len(px)))
    # ---- K5: the main scissor with its top-left past its bottom-right
    o = by.get('AS11')
    if o is not None and 'px' in o:
        if not o['px']:
            notes.append('R6k K5: an inverted main scissor (TL past BR) writes nothing')
        elif len(o['px']) == 1024:
            notes.append('R6k K5: an inverted main scissor does not clip at all (the whole map, measured)')
        else:
            notes.append('R6k K5: an inverted main scissor left %d pixels (measured): %s' %
                         (len(o['px']), sorted(o['px'])[:4]))


def judge_blend(zs, p, notes):
    """R6j across the boot (docs/R6J_PLAN.md 2-3): K1 the controls, K2 the blend arithmetic,
    K3 the combine function, K4 ROUND_ENABLE, K5 whether a wait is needed between the draws"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in pe.CASE_NUM)
    if not by:
        return
    # ---- K1: the two controls
    o = by.get('J0')
    if o is not None and 'texpix' in o:
        want = pe.to.pixel(pe.BLEND_SRC)
        bad = sum(1 for v in o['texpix'].values() if v != want)
        if bad:
            p.append('R6j K1: with blending off the second draw left %d of %d pixels unlike its flat '
                     'colour' % (bad, len(o['texpix'])))
        else:
            notes.append('R6j K1: with blending off the second draw replaces the destination '
                         '(%d pixels)' % len(o['texpix']))
    o = by.get('J2')
    if o is not None and 'texpix' in o:
        dst = pe.blend_dst()
        bad = 0
        for q, d in dst.items():
            w = (d[3] << 24) | (d[0] << 16) | (d[1] << 8) | d[2]      # a r g b, the framebuffer order
            bad += o['texpix'].get(q) != w
        # whether ONE preserves the destination exactly is a measurement (it says how the 0..255
        # factor becomes a multiplier), not a gate: the arithmetic itself is gated by K2
        notes.append('R6j K1: (ZERO, ONE) %s the Gouraud destination (%d of %d pixels differ)' %
                     ('changes' if bad else 'leaves exactly', bad, len(dst)))
    # ---- K2: the blend arithmetic over the five gated cases
    gated = [n for n in ('J1', 'J2', 'J3', 'J4', 'J5', 'J6') if 'texpix' in by.get(n, {})]
    named = []
    if gated:
        fits = []
        for r in pe.BLEND_RULES:
            d = 0
            for n2 in gated:
                m2 = pe.blend_map(n2, r)
                d += sum(1 for q, want in m2.items() if by[n2]['texpix'].get(q) != want)
            fits.append((d, r))
        fits.sort(key=lambda t: (t[0], str(t[1])))
        named = [r for d, r in fits if d == 0]
        if named:
            notes.append('R6j K2: the blend is (src*Fs + r) >> 8 + (dst*Fd + r) >> 8 with the factor '
                         'read as %s and r = %s%s' %
                         (named[0][0], named[0][1],
                          '' if len(named) == 1 else ' (%d rules give the same picture: %s)'
                          % (len(named), named[:6])))
        else:
            p.append('R6j K2: no named blend arithmetic explains the five cases (FAIL, measured) -- '
                     'nearest %s' % [(d, r) for d, r in fits[:3]])
    # ---- K3: the combine function of J8
    o = by.get('J8')
    if o is not None and 'texpix' in o and named:
        for comb in ('SUB_CLAMP', 'RSUB_CLAMP', 'SUB_NOCLAMP', 'ADD_CLAMP'):
            bad = sum(1 for q, want in pe.blend_map('J8', named[0], comb).items()
                      if o['texpix'].get(q) != want)
            if bad == 0:
                notes.append('R6j K3: COMB_FCN = SUB_CLAMP computes %s' %
                             ('source minus destination' if comb == 'SUB_CLAMP' else
                              'destination minus source' if comb == 'RSUB_CLAMP' else comb))
                break
        else:
            p.append('R6j K3: the subtract case matches no named reading of the combine function '
                     '(FAIL, measured)')
    # ---- K4: ROUND_ENABLE
    o, o4 = by.get('J7'), by.get('J4')
    if o is not None and o4 is not None and 'texpix' in o and 'texpix' in o4:
        same = sum(1 for q in o4['texpix'] if o['texpix'].get(q) == o4['texpix'][q])
        if same == len(o4['texpix']):
            notes.append('R6j K4: RB3D_CNTL.ROUND_ENABLE changes nothing here (%d pixels equal J4)' % same)
        else:
            fits = sorted(((sum(1 for q, want in pe.blend_map('J7', r).items()
                                if o['texpix'].get(q) != want), r) for r in pe.BLEND_RULES),
                          key=lambda t: (t[0], str(t[1])))
            if fits[0][0] == 0:
                notes.append('R6j K4: with ROUND_ENABLE the arithmetic is %s (J4 agreed on %d of %d)' %
                             (fits[0][1], same, len(o4['texpix'])))
            else:
                p.append('R6j K4: ROUND_ENABLE gives neither J4 nor a named arithmetic (FAIL, measured) '
                         '-- nearest %s' % [(d, r) for d, r in fits[:3]])
    # ---- K5: the wait between the draws
    o, o4 = by.get('J9'), by.get('J4')
    if o is not None and o4 is not None and 'texpix' in o and 'texpix' in o4:
        same = sum(1 for q in o4['texpix'] if o['texpix'].get(q) == o4['texpix'][q])
        notes.append('R6j K5: the same pair with a WAIT_UNTIL between the draws agrees with J4 on '
                     '%d of %d pixels%s' % (same, len(o4['texpix']),
                                            ' -- no wait is needed' if same == len(o4['texpix']) else ''))


def judge_ztest_all(zs, p, notes):
    """R6g across the boot: one reading of the comparison must explain every gated case, and the
    two-draw cases say whether a wait is needed between draws (docs/R6G_PLAN.md 6)"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs)
    gated = [n for n in do.GORDER if do.grow(n)[4] == do.RB3D_Z_ON and 'ztest' in by.get(n, {})]
    for cmp in ('int', 'exact'):
        ok = [n for n in gated if ('none', cmp) in by[n]['ztest']]
        if len(ok) == len(gated):
            notes.append('R6g: every gated case is explained by "the test compares the %s value"' %
                         ('floored' if cmp == 'int' else 'unfloored'))
            break
    else:
        p.append('R6g: no single comparison reading explains every case: %s' %
                 [(n, by[n]['ztest']) for n in gated if not by[n]['ztest']])
    for a, b in (('GH1', 'GH1w'),):
        if a in by and b in by:
            fa, fb = bool(by[a].get('ztest')), bool(by[b].get('ztest'))
            notes.append('R6g: two draws in one submission %s; with a WAIT_UNTIL between them %s' % (
                'hold' if fa else 'do NOT hold', 'hold' if fb else 'do NOT hold'))
            if not fa and fb:
                p.append('R6g: a WAIT_UNTIL is needed between two draws (GH1 failed, GH1w held) -- the driver must emit it')


def judge_values(zs, p, notes):
    """R6f (docs/R6F_PLAN.md 3-3): the anchors name a conversion per format (gate); the z-sloped
    triangles are recorded against the analysis families under that conversion, and 16 against 24"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs)
    conv = {}
    for bits in (16, 24):
        obs = []
        for g in 'abcd':
            a = by.get('K%d%s' % (bits, g), {}).get('anchors')
            obs += a if a is not None else [None] * 16
        if None in obs:
            p.append('%d-bit anchors: %d of 64 not read' % (bits, obs.count(None)))
            continue
        names, near = do.name_conversion(bits, obs)
        if not names:
            p.append('%d-bit conversion: no named rule gives the 64 anchors (FAIL, measured) -- nearest %s' % (
                bits, [(k, d) for k, d in near]))
            continue
        conv[bits] = names[0]
        notes.append('%d-bit conversion = %s (%d names in the class: %s)' % (bits, names[0], len(names), names[:6]))
    for n in do.IORDER:
        for bits in (24, 16):
            o = by.get('%s_%d' % (n, bits))
            if o is None or 'dvals' not in o:
                continue
            if bits not in conv:
                notes.append('%s_%d: not analysed (no named %d-bit conversion)' % (n, bits, bits))
                continue
            rep = do.interp_report('%s_%d' % (n, bits), o['dvals'], conv[bits])
            notes.append('%s_%d: families by pixels missed %s' % (n, bits, rep[:4]))
        o16, o24 = by.get(n + '_16'), by.get(n + '_24')
        if o16 and o24 and 'dvals' in o16 and 'dvals' in o24:
            pix = sorted(do.covered(n + '_24'))
            rel = {'v24 >> 8': sum(o16['dvals'][q] == o24['dvals'][q] >> 8 for q in pix),
                   'round(v24 / 257)': sum(o16['dvals'][q] == (2 * o24['dvals'][q] + 257) // 514 for q in pix),
                   '(v24 + 128) >> 8': sum(o16['dvals'][q] == min(0xffff, (o24['dvals'][q] + 128) >> 8) for q in pix)}
            notes.append('%s: 16 against 24 over %d pixels %s' % (n, len(pix), rel))


def judge_interp(zs, p, notes):
    """the interpolation rule classes (docs/R6E_PLAN.md 9): RGB planes and alpha planes separately"""
    byname = dict((CASE_NAME.get(o['len']), o) for o in zs)
    for n in ('G7', 'G7p'):
        pl = byname.get(n, {}).get('planes') or {}
        if 'R' in pl and 'A' in pl and pl['R'] == pl['A']:
            p.append('%s: the A plane is the R plane -- alpha copies red (docs/R6E_PLAN.md 10 #2)' % n)
    for kind in ('RGB', 'A'):
        planes, sig, by = go.classes(kind)
        obs = {}
        for n, l in planes:
            pl = byname.get(n, {}).get('planes') or {}
            if l not in pl:
                p.append('%s rule: plane %s %s missing' % (kind, n, l))
                return
            obs[(n, l)] = pl[l]
        got = go.observed_sig(planes, obs)
        members = [go.ALL[k] for k in by.get(got, [])]
        if members:
            gated = sum(1 for k in by[got] if k < go.NG)
            notes.append('%s rule (class of %d, %d gated): %s%s' % (kind, len(members), gated, members[:6],
                                                                    '' if len(members) <= 6 else ' ...'))
            if not all(go.high_precision(r) for r in members) and len(members) > 1:
                notes.append('%s rule: the class mixes precisions below 2^-10' % kind)
        else:
            p.append('%s: no named interpolation rule explains every plane' % kind)
            # nearest gated rule at the measured setup: one exact evaluation per (arith, scale) and
            # plane, the four conversions share it (seconds, not a search over the space)
            dist = {}
            for n, l in dict.fromkeys(planes):
                pts, tr = go.GCASES[n][0], go.lane_triple(n, l)
                seen = go.unpack_plane(obs[(n, l)], go.covered(pts))
                for a in go.ARITH:
                    for sc in go.SCALE:
                        r = go.raw(pts, tr, ('t16', (8, 8), a, sc))
                        vals = [r[xy] for xy in sorted(r)]
                        for f in go.FS:
                            d = sum(1 for v, b in zip(vals, seen) if go.conv(v, f) != b)
                            key = ('t16', (8, 8), a, sc, f)
                            dist[key] = dist.get(key, 0) + d
            best = min(dist, key=dist.get)
            notes.append('%s: nearest rule at the measured setup %s, %d bytes off over %d planes' % (kind, best, dist[best], len(planes)))


def fit_rectangles(dig):
    """every rectangle inside 64 x 64 whose tiled depth write would give this digest
    (its area is the changed count; the depth is the one changed value's low 24 bits)"""
    if not dig or dig['changed'] == 0 or len(dig['vals']) != 1:
        return None
    d = dig['vals'][0] & 0xffffff
    n = dig['changed']
    base = zo.digest([zo.pattern(i) for i in range(4096)], 0, 4096)
    out = []
    for w in range(1, 65):
        if n % w or n // w > 64:
            continue
        h = n // w
        for y0 in range(0, 65 - h):
            for x0 in range(0, 65 - w):
                xr, ws, ix, isum = base['xor'], base['wsum'], 0, 0
                for y in range(y0, y0 + h):
                    for x in range(x0, x0 + w):
                        k = zo.mba_z32(64, x, y) // 4
                        old = zo.pattern(k)
                        new = (old & 0xff000000) | d
                        xr ^= old ^ new
                        ws = (ws + (new - old) * (2 * k + 1)) & 0xffffffff
                        ix ^= k
                        isum = (isum + k) & 0xffffffff
                if (xr, ws, ix, isum) == (dig['xor'], dig['wsum'], dig['ixor'], dig['isum']):
                    out.append((x0, y0, x0 + w, y0 + h))
    return out


def named(case):
    """the rectangles a case could plausibly give, by name (docs/R6B_PLAN.md 4 m5, code review m3)"""
    (tx, ty, wx, wy), geom = zo.CASES[case][0], zo.CASES[case][1]
    out = {}
    for rect, label in (((tx, ty, wx, wy), 'the clip rectangle (TL..WH)'), ((0, 0, wx, wy), 'origin..WH (TL not applied)'),
                        ((tx, ty, wx - 1, wy - 1), 'TL..WH exclusive'), ((tx, ty, tx + wx, ty + wy), 'WH relative to TL'),
                        ((tx // 16, ty // 16, wx, wy), 'TL in 1/16 pixel'), (geom, 'the whole geometry')):
        out[rect] = label if rect not in out else out[rect] + ' = ' + label   # one rectangle, two readings
    return out
OPS = 'record|load|map|reset|start|submit|negctl|stop|inject|rec3d|zprep|zclear|plane|bad'


def cut(text, nonce):
    """the boot's lines: the first line naming its nonce to the first later line naming another"""
    lines = text.splitlines()
    mine = [k for k, l in enumerate(lines) if 'boot=%s' % nonce in l]
    if not mine:
        return None
    s = mine[0]
    other = [k for k, l in enumerate(lines) if k > s and re.search(r'boot=(?!%s)[0-9a-f]{8}\b' % re.escape(nonce), l)]
    return lines[s:other[0] if other else len(lines)]


def parse(lines, nonce):
    ops, cur = [], None
    win = keys = None
    cycle = None
    for i, l in enumerate(lines):
        m = re.search(r'RDN-R4 alias boot=%s win=([0-9a-f]{8}) .* ok$' % nonce, l)
        if m:
            win = int(m.group(1), 16)
        m = re.search(r'RDN-R5 keys boot=%s test=(\d) inject=(\d)(?: 3d=(\d))? build=([0-9a-f]{8})' % nonce, l)
        if m:
            keys = (m.group(1), m.group(2), m.group(3), m.group(4))
        m = re.search(r'RDN-R5 (%s) boot=%s n=(\d+) arg=([0-9a-f]{8}) len=(\d+) rc=(-?\d+) why=(\d+)'
                      r'(?: gv=([0-9a-f]{8}))?' % (OPS, nonce), l)
        if m:
            cur = dict(op=m.group(1), n=int(m.group(2)), arg=int(m.group(3), 16), len=int(m.group(4)), rc=int(m.group(5)),
                       why=int(m.group(6)), gv=None if m.group(7) is None else int(m.group(7), 16),
                       r3={}, dig={})
            ops.append(cur)
            continue
        if re.search(r'RDN-R2B cycled boot=%s live=' % nonce, l):
            for l2 in lines[i + 1:i + 6]:
                m = re.search(r'RDN-R2B cycle n=(\d+) why=(-?\d+) .* verdict=(-?\d+)', l2)
                if m:
                    cycle = tuple(int(x) for x in m.groups())
                    break
            cur = None
            continue
        if cur is None:
            continue
        m = re.search(r'RDN-R6 r3 ((?:[0-9a-f]{4}=[0-9a-f]{8} ?)+)', l)
        if m:
            for a, v in re.findall(r'([0-9a-f]{4})=([0-9a-f]{8})', m.group(1)):
                cur['r3'][int(a, 16)] = int(v, 16)
        m = re.search(r'RDN-R6 zprep bad=(\d+)', l)
        if m:
            cur['prepbad'] = int(m.group(1))
        m = re.search(r'RDN-R6 zclear case=(\d+) stage=(\d+) surf=([0-9a-f]{8}) reg0=([0-9a-f]{8}) reg2=([0-9a-f]{8}) '
                      r'prebad=([0-9a-f]{2,3})(?: pfbad=(\d+))?', l)     # G4-7: bits 9, 10 make three digits
        if m:
            cur.update(case=int(m.group(1)), stage=int(m.group(2)), surf=int(m.group(3), 16), reg0=int(m.group(4), 16),
                       reg2=int(m.group(5), 16), prebad=int(m.group(6), 16),
                       pfbad=None if m.group(7) is None else int(m.group(7)))      # R6g
        m = re.search(r'RDN-R6 zpre ((?:[0-9a-f]{8} ?){9,12})', l)      # G4-7: 11, G4-9: 12; 9 in the older logs
        if m:
            cur['pre'] = [int(x, 16) for x in m.group(1).split()]
        m = re.search(r'RDN-R6 (zd|zc)(\d) xor=([0-9a-f]{8}) wsum=([0-9a-f]{8}) changed=(\d+) ixor=(\d+) isum=(\d+) n=(\d) '
                      r'v=([0-9a-f]{8}),([0-9a-f]{8}),([0-9a-f]{8}),([0-9a-f]{8})', l)
        if m:
            n = int(m.group(8))
            cur['dig'][(m.group(1), int(m.group(2)))] = dict(
                xor=int(m.group(3), 16), wsum=int(m.group(4), 16), changed=int(m.group(5)), ixor=int(m.group(6)),
                isum=int(m.group(7)), vals=[int(m.group(9 + j), 16) for j in range(n)])
        m = re.search(r'RDN-R5 state state=\d+ latched=\d+ reset=\d+ failed=\d+ wptr=(\d+)', l)
        if m:
            cur['wptr'] = int(m.group(1))       # R6l: the ring pointer this operation left behind
        m = re.search(r'RDN-R6 off (\d+) (\d+) (\d+) (\d+) lanes=([0-9a-f]+)$', l)
        if m:
            cur['off'] = [int(m.group(k)) for k in range(1, 5)]
            cur['lanes'] = int(m.group(5), 16)
        m = re.search(r'RDN-R6 plh boot=([0-9a-f]{8}) zc=(\d+) case=(\d+) lane=(\d) chunk=(\d)(?: src=(\d+))?$', l)
        if m:
            cur['plh'] = (m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
            cur['plsrc'] = None if m.group(6) is None else int(m.group(6))      # R6f
        m = re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})$', l)
        if m:
            cur.setdefault('pll', {}).setdefault(int(m.group(1)), {})[int(m.group(2))] = [int(x, 16) for x in m.group(3).split()]
        m = re.search(r'RDN-R6 cov(\d) ((?:[0-9a-f]{8} ?){8})$', l)
        if m:
            cur.setdefault('covl', {})[int(m.group(1))] = [int(x, 16) for x in m.group(2).split()]
        m = re.search(r'RDN-R7 verify boot=[0-9a-f]{8} words=(\d+) why=(\d+) at=(\d+) '
                      r'word=([0-9a-f]{8}) win=([0-9a-f]{8})\.\.([0-9a-f]{8}) dropped=(\d+)', l)
        if m:                                   # R7a: what the verifier made of the client's stream
            cur['r7'] = dict(words=int(m.group(1)), why=int(m.group(2)), at=int(m.group(3)),
                             word=int(m.group(4), 16),
                             win=(int(m.group(5), 16), int(m.group(6), 16)), dropped=int(m.group(7)))
        m = re.search(r'RDN-R6 zsurf coff=([0-9a-f]{8}) zoff=([0-9a-f]{8}) toff=([0-9a-f]{8}) '
                      r'texbad=(\d+) at=(\d+) val=([0-9a-f]{8})', l)
        if m:                                   # R6m: which surfaces this case actually used
            cur['zsurf'] = (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16))
            cur['texpost'] = (int(m.group(4)), int(m.group(5)), int(m.group(6), 16))
        m = re.search(r'RDN-R6 zr rest0=(\d+) rest1=(\d+) first=(\d+) val=([0-9a-f]{8})'
                      r'(?: skipped=(\d+))?', l)
        if m:
            cur['rest'] = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4), 16))
            # M1h: the driver may now decline to run the whole-alias scan (it does
            # that only for the client's own stream).  A 0 with skipped=1 means
            # "not looked at", and an R6 case must never see it -- those cases
            # are the ones the scan exists for.
            cur['restskipped'] = int(m.group(5)) if m.group(5) is not None else 0
    return ops, win, keys, cycle


def judge(text, nonce, build, procedure='r6a'):
    p, notes = [], []
    order, cases = ORDERS[procedure]
    lines = cut(text, nonce)
    if lines is None:
        return ['no line names boot %s' % nonce], notes
    ops, win, keys, cycle = parse(lines, nonce)
    if keys is None or keys[0] != '1' or keys[2] != '1' or keys[3] != build:
        p.append('keys line %s, want test=1 3d=1 build=%s' % (keys, build))
    if win is None:
        return p + ['no R4 alias line: the engine key is off, ZPREP has no block'], notes
    names = [o['op'] for o in ops]
    if names != order:
        return p + ['the operations were %s, the procedure is %s' % (names, order)], notes
    zl = [o['len'] for o in ops if o['op'] == 'zclear']
    if zl != cases:
        return p + ['zclear cases %s, the procedure is %s' % (zl, cases)], notes
    for o in ops:
        if o['rc'] == 0:
            continue
        # R7a: most client streams are SUPPOSED to be refused, and the verifier's own refusal
        # (CP_WHY_R7) is the measurement.  Every OTHER refusal is still a failure.
        if procedure == 'r7a' and o['op'] == 'zclear' and o['len'] == 171 and o['why'] == 34:
            continue
        p.append('%s: rc %d why %d' % (o['op'], o['rc'], o['why']))
    # M1h: the whole-alias scan may be skipped, but ONLY for the client's own
    # stream (case 171).  An R6 case that reports skipped=1 would be handing
    # back rest0=0 as a measurement nobody made.
    for o in ops:
        if o['op'] == 'zclear' and o['len'] != 171 and o.get('restskipped'):
            p.append('zclear %s: the whole-alias scan was skipped, so rest0/rest1 are '
                     'not measurements' % o['len'])
    r3s = [o for o in ops if o['op'] == 'rec3d']
    for k, o in enumerate(r3s):
        if o['r3'].get(0x0b00) != 0x100:
            p.append('rec3d %d: SURFACE_CNTL %08x, want 00000100' % (k + 1, o['r3'].get(0x0b00, 0)))
        surf = [(a, v) for a, v in sorted(o['r3'].items()) if 0x0b04 <= a <= 0x0b7c and v]
        if surf:
            notes.append('rec3d %d: non-zero surface registers %s' % (k + 1, ['%04x=%08x' % x for x in surf]))
    if r3s and r3s[-1]['r3'].get(0x1c3c) != 0:
        p.append('the last rec3d: RB3D_CNTL %08x, want 0 (operator D1)' % r3s[-1]['r3'].get(0x1c3c, 0))
    if r3s and len(r3s[0]['r3']) != REC_WANT[procedure]:
        p.append('rec3d: %d registers, want %d' % (len(r3s[0]['r3']), REC_WANT[procedure]))
    if len(r3s) >= 2:
        ch = ['%04x %08x->%08x' % (a, r3s[0]['r3'][a], r3s[1]['r3'].get(a, 0)) for a in sorted(r3s[0]['r3'])
              if r3s[0]['r3'][a] != r3s[1]['r3'].get(a)]
        notes.append('rec3d boot -> after START: %s' % (ch or 'no change'))
        notes.append('rec3d at boot: %s' % ' '.join('%04x=%08x' % (a, v) for a, v in sorted(r3s[0]['r3'].items())))
    for o in [o for o in ops if o['op'] == 'zprep']:
        if o.get('prepbad') != 0:
            p.append('zprep: %s words read back otherwise' % o.get('prepbad'))
    if procedure in ('r6e', 'r6e3', 'r6f', 'r6g', 'r6h', 'r6i', 'r6i2', 'r6i3', 'r6j', 'r6k', 'r6m', 'r6m0'):
        attach_planes(ops, nonce, p)
    for o in [o for o in ops if o['op'] == 'zclear']:
        c = o['len']
        tag = 'zclear %s' % CASE_NAME.get(c, c)
        if procedure == 'r7a' and c == 171 and o.get('rc') == 1 and o.get('why') == 34:
            continue            # R7a: a refused stream never reaches the prefix; judge_r7_all has it
        if o.get('case') != c or o.get('stage') != 3 or o.get('surf') != 0x100 or (o.get('prebad', 1) & zo.PRE_GATE):
            p.append('%s: case %s stage %s surf %s prebad %s' % (tag, o.get('case'), o.get('stage'), o.get('surf'), o.get('prebad')))
            continue
        if o.get('reg0') != o['arg'] or o.get('reg2') != (~o['arg'] & 0xffffffff):
            p.append('%s: markers reg0 %08x reg2 %08x for seed %08x' % (tag, o.get('reg0', 0), o.get('reg2', 0), o['arg']))
        pname = 'F' if (CASE_NAME.get(c) in to.TRI or CASE_NAME.get(c) in go.GCASES or
                        CASE_NAME.get(c) in do.CASE_NUM or
                        (procedure == 'r6g' and CASE_NAME.get(c) in do.GCASE_NUM) or
                        (procedure in ('r6h', 'r6i') and CASE_NAME.get(c) in te.CASE_NUM) or
                        (procedure in ('r6i', 'r6i2', 'r6i3', 'r6j') and CASE_NAME.get(c) in pe.CASE_NUM) or
                        (procedure in ('r6m', 'r6m0') and CASE_NAME.get(c) in ru.SCASES)) else CASE_NAME.get(c, 'A')
        want_pre = [v for _, v in zo.prefix_expect(win, pname)]
        if procedure in ('r6m', 'r6m0') and CASE_NAME.get(c) in ru.SCASES:
            # R6m: the prefix names THIS case's surfaces (docs/R6M_PLAN.md 4)
            rco, rzf, _rtf = ru.offsets(CASE_NAME[c])
            want_pre[0], want_pre[2] = win + rzf, win + rco
        pre = o.get('pre') or [None] * len(want_pre)
        if procedure in ('g47', 'g49') and len(pre) != len(want_pre):
            p.append('%s: prefix read back %d registers, want %d' % (tag, len(pre), len(want_pre)))
        bad = [k for k in range(min(len(pre), len(want_pre))) if pre[k] != want_pre[k]]
        if any(zo.PRE_GATE >> k & 1 for k in bad):
            p.append('%s: prefix read back %s, want %s' % (tag, pre, want_pre))
        elif bad:
            notes.append('%s: front-end registers read back otherwise (recorded, not gated): %s' % (
                tag, ['%04x=%08x' % (zo.prefix_expect(win, pname)[k][0], pre[k]) for k in bad]))
        rest = o.get('rest')
        if rest is None or rest[1] != 0:
            p.append('%s: %s words outside the two buffers changed (first %s value %s)' % (
                tag, rest and rest[1], rest and rest[2], rest and '%08x' % rest[3]))
        name = CASE_NAME.get(c)
        if name is None:
            p.append('%s: no such case' % tag)
            continue
        if procedure == 'r7a' and name == 'UC':
            continue                            # R7a: judge_r7_all reads these together
        if procedure in ('r6m', 'r6m0') and name in ru.SCASES:
            judge_reuse_case(o, name, tag, p, notes)
            continue
        if procedure in ('r6l', 'r6m', 'r6m0') and name in ba.SCASES:
            judge_batch_case(o, name, tag, p, notes)
            continue
        if procedure == 'r6k' and name in sc.SCASES:
            judge_scissor_case(o, name, tag, p, notes)
            continue
        if procedure in ('r6i', 'r6i2', 'r6i3', 'r6j') and name in pe.CASE_NUM:
            if pe.kind(name) in ('tex', 'blend'):
                judge_ptex(o, name, tag, p, notes)
            elif pe.kind(name) == 'gouraud':
                judge_gouraud(o, pe.SIM_ALIAS[name], tag, p, notes)      # V8's geometry and lanes
            else:
                judge_depth(o, pe.SIM_ALIAS[name], tag, p, notes)        # I1_24's placement and lanes
            continue
        if procedure == 'r6h' and name in te.CASE_NUM:
            judge_texture(o, name, tag, p, notes)
            continue
        if procedure == 'r6g' and name in do.GCASE_NUM:
            judge_ztest(o, name, tag, p, notes)
            continue
        if name in do.CASE_NUM:
            judge_depth(o, name, tag, p, notes)
            continue
        if name in go.GCASES:
            judge_gouraud(o, name, tag, p, notes)
            continue
        if name in to.TRI:
            judge_triangle(o, name, tag, p, notes)
            continue
        got = o['dig'].get(('zd', 1))
        o['depth'] = got
        hyp = {}
        for layout in ('tiled', 'linear'):
            for rounding in ('trunc', 'round'):
                hyp[(layout, rounding)] = zo.digest(zo.expected_block(name, layout, rounding), zo.DEPTH_OFF // 4,
                                                   zo.BUF_BYTES // 4)
        match = [k for k, v in hyp.items() if v == got]
        allowed = [('tiled', 'trunc'), ('tiled', 'round')] if name == 'B' else [('tiled', 'trunc')]
        if not any(m in allowed for m in match):
            fits = fit_rectangles(got)
            nm = named(name)
            named_fits = [nm.get(r, 'unnamed') for r in (fits or [])]
            p.append('%s: depth digest matches %s -- want %s (rule H covers %s); rectangle fits %s %s' % (
                tag, match or 'no hypothesis', allowed, zo.covered(name), fits, named_fits))
        else:
            notes.append('%s: depth buffer = %s' % (tag, ', '.join('%s/%s' % m for m in match)))
        gcol = o['dig'].get(('zc', 1))
        ecol = zo.digest(zo.expected_block(name, 'tiled', 'trunc'), zo.COLOR_OFF // 4, zo.BUF_BYTES // 4)
        if name not in zo.COLOUR:
            if gcol != ecol:
                p.append('%s: colour buffer digest %s, want untouched %s' % (tag, gcol, ecol))
        else:
            # R6c: name what the colour buffer holds; F (and F') must be Mesa's pixel, linear
            cls = classify_colour(name, gcol) if gcol else []
            o['colour'] = cls[0][2] if len(cls) == 1 and cls[0][0] == 'linear' else None
            o['colour_names'] = ['%s/%s' % (lay, nm) for lay, nm, _ in cls]
            desc = ', '.join(o['colour_names'])
            if not desc:
                # docs/R6C_PLAN.md 7: the rows that name a failure rather than a byte order
                hint = ('plane mask or blend stage (7)' if gcol and gcol['changed'] == 0 else
                        'SE_VTX_STATE_CNTL or a vertex slot mismatch -- compare H (7)')
                desc = 'no named hypothesis (changed %s, values %s): %s' % (
                    gcol and gcol['changed'], gcol and ['%08x' % v for v in gcol['vals']], hint)
            if name == 'F':
                if not (len(cls) == 1 and cls[0][0] == 'linear' and cls[0][2] == P_RGBA):
                    p.append('%s: colour buffer is %s -- want linear/Mesa order (r g b a) = %08x' % (tag, desc, P_RGBA))
                else:
                    notes.append('%s: colour buffer = %s' % (tag, desc))
            else:
                notes.append('%s: colour buffer (measured, not gated) = %s' % (tag, desc))
        for reg in ('zd', 'zc'):
            if o['dig'].get((reg, 0)) != o['dig'].get((reg, 1)):
                notes.append('%s: the two read passes of %s differ (a stale read on the first)' % (tag, reg))
        if rest and rest[0] != rest[1]:
            notes.append('%s: rest pass 0 %d, pass 1 %d' % (tag, rest[0], rest[1]))
    if procedure == 'r6b':
        zs = [o for o in ops if o['op'] == 'zclear']
        d_ok = zs[2].get('depth') == zs[0].get('depth')
        if not d_ok:
            p.append('D depth digest differs from A\'s in the same boot (rule H says they are equal)')
        if zs[3].get('depth') != zs[1].get('depth'):
            p.append('C\' depth digest differs from C\'s in the same boot (a delayed or sticky effect)')
        rc2 = r3s[2]['r3'].get(0x1c50)
        if rc2 != 2:
            # never read back non-zero before: when D itself obeyed rule H, a 0 here means the
            # register does not read back, not that the write was lost (code review m1)
            if d_ok:
                notes.append('the REC3D after D reads RE_CNTL %08x though D clipped at TL: RE_CNTL does not read back' % (rc2 or 0))
            else:
                p.append('the REC3D after D: RE_CNTL %08x, want 2' % (rc2 or 0))
        if r3s[2]['r3'].get(0x26c0) != 0x00030005:
            p.append('the REC3D after D: RE_TOP_LEFT %08x, want 00030005' % r3s[2]['r3'].get(0x26c0, 0))
        if r3s[-1]['r3'].get(0x26c0) != 0x000c0014:
            p.append('the last REC3D: RE_TOP_LEFT %08x, want 000c0014 (E wrote it)' % r3s[-1]['r3'].get(0x26c0, 0))
        if r3s[-1]['r3'].get(0x1c50) not in (0, None):
            p.append('the last REC3D: RE_CNTL %08x, want 0 (C\' and E put it back)' % r3s[-1]['r3'].get(0x1c50, 0))
    if procedure == 'r6d':
        judge_rule([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6e':
        judge_interp([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6e3':
        judge_rule_b([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6f':
        judge_rule_b([o for o in ops if o['op'] == 'zclear'], p, notes)      # G1 (the only R6e case here): rule B holds
        judge_values([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6g':
        judge_ztest_all([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6h':
        judge_texture_all([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6i':
        zs = [o for o in ops if o['op'] == 'zclear']
        judge_rule_b(zs, p, notes)          # the V8 control: rule B still holds in this build
        judge_persp_all(zs, p, notes)
    if procedure == 'r6i2':
        judge_arith([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6i3':
        judge_axis([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6j':
        judge_blend([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6k':
        judge_scissor_all([o for o in ops if o['op'] == 'zclear'], p, notes)
    if procedure == 'r6l':
        judge_batch_all([o for o in ops if o['op'] == 'zclear'], p, notes,
                        [o['wptr'] for o in ops if o.get('wptr') is not None])
    if procedure == 'r7a':
        judge_r7_all(ops, p, notes, win)
    if procedure in ('r6m', 'r6m0'):
        judge_reuse_all([o for o in ops if o['op'] == 'zclear'], p, notes,
                        [o['wptr'] for o in ops if o.get('wptr') is not None])
    if procedure == 'r6c':
        zs = [o for o in ops if o['op'] == 'zclear']
        for o in zs[1:]:
            if o.get('depth') != zs[0].get('depth'):
                p.append('zclear %s: depth digest differs from A\'s in the same boot (a vertex size mismatch?)' %
                         CASE_NAME.get(o['len']))
        if zs[4]['dig'].get(('zc', 1)) != zs[1]['dig'].get(('zc', 1)):
            p.append('F\' colour digest differs from F\'s in the same boot (not repeatable)')
        notes.append('F/G: %s' % pair_name(zs[1].get('colour'), zs[2].get('colour')))
        notes.append('H: %s' % ('the same as F -- SE_VTX_STATE_CNTL 0x10000 or 0 makes no difference here'
                                if zs[3]['dig'].get(('zc', 1)) == zs[1]['dig'].get(('zc', 1))
                                else 'differs from F -- SE_VTX_STATE_CNTL matters (%s)' % zs[3].get('colour_names')))
        # the state the last draw (F') leaves; recorded, not gated (docs/R6C_PLAN.md 5 m4)
        left = {0x1c38: 0x1000, 0x1d84: 0xffffffff, 0x2088: 0x803, 0x1c50: 2, 0x2180: 0x10000,
                0x2f00: 0x1000, 0x2f04: 0x11000, 0x2f08: 0x1000, 0x2f0c: 0x11000}
        diff = ['%04x=%08x (want %08x)' % (a, r3s[-1]['r3'].get(a, 0), v) for a, v in sorted(left.items())
                if r3s[-1]['r3'].get(a) != v]
        notes.append('the last REC3D, F\'s state: %s' % (diff or 'as written'))
    if 'stop' not in order:
        # G4-7: a procedure that leaves the CP running (check_plan_ops '# tail nostop') has no cycle after STOP
        notes.append('no STOP in this procedure: the CP is left running for the boot\'s next run')
    elif cycle is None or cycle[0] != 1 or cycle[2] != 0:
        p.append('the cycle after STOP: %s, want n=1 verdict 0' % (cycle,))
    return p, notes


# ---- self-test: a boot written in the driver's own formats ------------------------------
def synth(nonce='abcd0001', build='11111111', win=0x0029e000, layout='tiled', rounding='round', last_rb3d=0,
          procedure='r6a', override=None, recntl_after_d=2, last_recntl=0, colour=None, fdepth=None,
          rule=None, trimap=None, grule=None, grule_a=None, gedit=None, gcov=None, bmode='round',
          dfun=None, dedit=None, psrc=None, gcmp='int', gze='off', gedit2=None, trule=None,
          tstride=None, tedit=None, pmodel='Pq', pbil=None, pedit=None, pwh=None, parith=None,
          pchan=False, pblend=None, pscissor=None, sedit=None, sdepth=None, bedit=None, wptr0=1536,
          redit=None, rsurf=None, rtex=None):
    """override: {case: (x0, y0, x1, y1)} -- draw that rectangle instead of rule H's;
    colour: {key: (clayout, pixel)} for the colour cases (key F, G, H or Fp for F');
    fdepth: {key: (x0, y0, x1, y1)} -- that colour case's depth rectangle instead;
    rule: the triangle hypothesis the synthetic hardware follows (default the SE_CNTL reading);
    trimap: {case: callable(pixels 64x64 array) -> array} edits a triangle case's pixels;
    R6f: dfun(case) -> {(x, y): depth} instead of the model's values; dedit {case: callable(depth block,
    bits, values) -> block} edits the depth buffer the driver then reads; psrc {case: src} for the plh lines.
    R6g: gcmp ('int' or 'exact') is what the synthetic machine's depth test compares, gze what
    RB3D_CNTL.Z_ENABLE = 0 does there, gedit2 {case: callable(colour, depth) -> (colour, depth)} edits one case.
    R6h: trule is the ST -> texel rule the synthetic machine follows, tstride what it takes the row
    stride from (None: the width), tedit {case: callable(pixels) -> pixels} edits one case.
    R6i: pmodel is the perspective model the synthetic machine interpolates with, pbil the bilinear
    rule (default exact, a = 0), pwh {case: (w, h)} the size it reads a texture at, pedit
    {case: callable(pixels) -> pixels}.  R6i-2: parith is the weight arithmetic (quantum, its
    rounding, where it applies, the final rounding) the machine filters with.
    R6m: redit {case: callable(pixels) -> pixels} edits what a reuse case draws, rsurf {case:
    callable(coff, zoff, toff) -> (coff, zoff, toff)} makes the machine use OTHER surfaces than the
    row asks for, and rtex {case: callable(texture words) -> words} spills into the texture surface"""
    L = ['mach: RDN-R4 alias boot=%s win=%08x ceiling=07c00000 page=8192 len=00040000 ok' % (nonce, win),
         'mach: RDN-R5 keys boot=%s test=1 inject=0 3d=1 build=%s' % (nonce, build),
         'mach: RDN-R5 block boot=%s va=00040000 phys=00040000 len=00010000 ok' % nonce,
         'mach: RDN-R3 select boot=%s res=800x600 fmt=RGB:888/32 rdflt=0' % nonce]
    n = [0]
    regs = [0x0b00] + [0x0b04 + 0x10 * s + 4 * j for s in range(8) for j in range(3)] + [
        0x1c14, 0x1c18, 0x1c1c, 0x1c20, 0x1c24, 0x1c28, 0x1c2c, 0x1c38, 0x1c3c, 0x1c40, 0x1c44, 0x1c48, 0x1c4c, 0x1c50,
        0x1cd8, 0x1cdc, 0x1d60, 0x1d7c, 0x1d80, 0x1d84, 0x2080, 0x2088, 0x208c, 0x20b0, 0x2140, 0x2180, 0x26c0, 0x26c4,
        0x26f0, 0x2c1c, 0x2cc4, 0x3250, 0x3254, 0x3258, 0x325c]
    if procedure in ('r6c', 'r6d', 'r6e', 'r6e3', 'r6f', 'r6g', 'r6h', 'r6i', 'r6i2', 'r6i3', 'r6j', 'r6k',
                     'r6l', 'r6m', 'g47', 'g49'):
        regs += [0x2f00, 0x2f04, 0x2f08, 0x2f0c]
    if procedure in ('g47', 'g49'):
        regs += [0x2cf8, 0x2cfc, 0x2c00, 0x2c04]       # G4-7
    if procedure == 'g49':
        regs += [0x2d9c, 0x2c08, 0x2c0c, 0x2c10]       # G4-9
    # R6l: the synthetic ring advances like cpR6Submit's, so the wrap shows in the wptr lines
    ring = [wptr0]

    def advance(words):
        length = (words + 15) & ~15
        pad = 4096 - ring[0] if length > 4096 - ring[0] else 0
        ring[0] = (ring[0] + pad + length) & 0xfff

    def op(name, arg=0, ln=0, extra=()):
        n[0] += 1
        if name == 'zclear' and procedure == 'r6l' and CASE_NAME.get(ln) in ba.SCASES:
            advance(ba.words_needed(CASE_NAME[ln]))
        if name == 'zclear' and procedure == 'r6m':     # R6m: the prefix is its own submission
            nm = CASE_NAME.get(ln)
            advance(28)     # G4-7 + G4-9: the prefix grew by three pairs (zclear_oracle.prefix_words)
            advance(ru.words_needed(nm) if nm in ru.SCASES else
                    ba.words_needed(nm) if nm in ba.SCASES else 65)
        L.append('mach: RDN-R5 begin boot=%s op=%d arg=%08x len=%d' % (nonce, 1, arg, ln))
        L.append('mach: RDN-R5 %s boot=%s n=%d arg=%08x len=%d rc=0 why=0 gv=00000000 greg=0000 us=100' % (name, nonce, n[0], arg, ln))
        L.append('mach: RDN-R5 state state=3 latched=0 reset=1 failed=0 wptr=%d phys=00040000 post=00000000 '
                 'csqstat=02000000 csq2stat=04010080 csqread=1' % ring[0])
        L.append('mach: RDN-R5 io wr=0 rd=60 aicstat=00000004 inject=0 injected=0')
        L.extend(extra)

    def dline(tag, k, d):
        v = d['vals'] + [0] * (4 - len(d['vals']))
        return 'mach: RDN-R6 %s%d xor=%08x wsum=%08x changed=%d ixor=%d isum=%d n=%d v=%08x,%08x,%08x,%08x' % (
            tag, k, d['xor'], d['wsum'], d['changed'], d['ixor'], d['isum'], len(d['vals']), v[0], v[1], v[2], v[3])

    r3 = ['mach: RDN-R6 r3 ' + ' '.join('%04x=%08x' % (a, 0x100 if a == 0x0b00 else 0) for a in regs[k:k + 4])
          for k in range(0, len(regs), 4)]
    op('record')
    op('rec3d', extra=r3)
    for nm in ('load', 'map', 'reset', 'start'):
        op(nm)
    op('rec3d', extra=r3)
    def blockfor(name, key):
        if name in zo.COLOUR:
            lay, pix = (colour or {}).get(key, ('linear', None))
            if lay == 'none':                   # no colour written: the block A leaves
                blk = zo.expected_block('A')
            else:
                blk = zo.expected_block(name, clayout=lay, pixel=pix)
            if fdepth and key in fdepth:        # that depth rectangle instead of rule H's
                x0, y0, x1, y1 = fdepth[key]
                for k in range(zo.BUF_BYTES // 4):
                    blk[k] = zo.pattern(k)
                for y in range(y0, y1):
                    for x in range(x0, x1):
                        k = zo.mba_z32(64, x, y) // 4
                        blk[k] = (blk[k] & 0xff000000) | 0xffffff
            return blk
        if override and key in override:
            x0, y0, x1, y1 = override[key]
            w = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
            for y in range(y0, y1):
                for x in range(x0, x1):
                    k = zo.mba_z32(64, x, y) // 4
                    w[k] = (w[k] & 0xff000000) | 0xffffff
            return w
        return zo.expected_block(name, layout, rounding if name == 'B' else 'trunc')

    for i, c in enumerate(ORDERS[procedure][1]):
        if procedure == 'r6b' and i == 3:
            op('rec3d', extra=[l.replace('1c50=00000000', '1c50=%08x' % recntl_after_d)
                               .replace('26c0=00000000', '26c0=00030005') for l in r3])
        op('zprep', extra=['mach: RDN-R6 zprep bad=0'])
        seed = 0x5eed0000 | (c << 4) | i
        name = CASE_NAME[c]
        key = 'Cp' if (procedure == 'r6b' and i == 3) else name     # the second C is C'
        if procedure == 'r6c' and i == 4:
            key = 'Fp'
        covl = []
        if procedure in ('r6i', 'r6i2', 'r6i3', 'r6j') and name in pe.CASE_NUM:
            # R6i: the synthetic machine interpolates with pmodel and filters with pbil
            pm = pmodel if pe.recntl_of(name) & 8 else 'A'      # the bit decides, as on the card
            if pe.kind(name) == 'blend':
                # R6j: the synthetic machine blends with pblend (default: the plain reading)
                pxmap = dict(pe.blend_map(name, pblend or ('id', 0)))
                if pedit and name in pedit:
                    pxmap = pedit[name](dict(pxmap))
                blk = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
                zv = do.space(24)[do.SIM_CONV](0.5)
                for (x, y), v in pxmap.items():
                    blk[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = v
                    k = (zo.DEPTH_OFF + do.mba_z32(x, y)) // 4
                    blk[k] = (blk[k] & 0xff000000) | zv
                planes = dict((l, go.plane_words(dict((q, (v >> (8 * l)) & 0xff) for q, v in pxmap.items())))
                              for l in range(4))
                cw = [0] * 64
                for (x, y) in pxmap:
                    i = y * 32 + x
                    cw[i >> 4] |= 3 << (2 * (i & 15))
                covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cw[8 * k:8 * k + 8]))
                        for k in range(8)]
                covl.append('mach: RDN-R6 off 0 0 0 0 lanes=f')
            elif pe.kind(name) == 'tex':
                if pe.filter_of(name) == 'linear' and (parith is not None or name in pe.ORDER2 + pe.ORDER3):
                    # R6i-2/R6i-3: the machine's two-stage filter (a quantum per axis and a rounding
                    # constant per 1-D mix); pchan makes the constant follow the colour channel
                    fn2 = pe.arith_map_chan if pchan else pe.arith_map2
                    m = dict((q, (v, True)) for q, v in fn2(name, parith or pe.MEASURED_ARITH).items())
                elif pe.filter_of(name) == 'linear':
                    m = pe.bilinear_map(name, pbil or (pm, pe.MEASURED_OFF, Fraction(-1, 2), None, 'floor', 'floor'))
                else:
                    m = pe.nearest_map(name, (pm, pe.MEASURED_OFF, None), wh=(pwh or {}).get(name))
                pxmap = dict((q, v) for q, (v, _) in m.items())
                if pedit and name in pedit:
                    pxmap = pedit[name](dict(pxmap))
                blk = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
                tex = pe.texture_words(name)
                blk[pe.TEX_OFF // 4:pe.TEX_OFF // 4 + len(tex)] = tex
                zv = do.space(24)[do.SIM_CONV](0.5)
                for (x, y), v in pxmap.items():
                    blk[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = v
                    k = (zo.DEPTH_OFF + do.mba_z32(x, y)) // 4
                    blk[k] = (blk[k] & 0xff000000) | zv
                planes = dict((l, go.plane_words(dict((q, (v >> (8 * l)) & 0xff) for q, v in pxmap.items())))
                              for l in range(4))
                cw = [0] * 64
                for (x, y) in pxmap:
                    i = y * 32 + x
                    cw[i >> 4] |= 3 << (2 * (i & 15))
                covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cw[8 * k:8 * k + 8])) for k in range(8)]
                covl.append('mach: RDN-R6 off 0 0 0 0 lanes=f')
            elif pe.kind(name) == 'gouraud':
                a = pe.SIM_ALIAS[name]
                vals = dict((l, pe.gouraud_bytes(name, l, pm)) for l in go.GCASES[a][2])
                if pedit and name in pedit:
                    vals = pedit[name](dict(vals))
                pts = pe.GEOM_V8
                planes = dict((l, go.plane_words(dict(zip(go.covered(pts), vals[l])))) for l in vals)
                blk = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
                zv = do.space(24)[do.SIM_CONV](1.0)
                for k, q in enumerate(go.covered(pts)):
                    px = sum(vals[l][k] << (8 * 'BGRA'.index(l)) for l in vals)
                    blk[(zo.COLOR_OFF + 4 * (q[0] + zo.PITCH * q[1])) // 4] = px
                    j = (zo.DEPTH_OFF + do.mba_z32(q[0], q[1])) // 4
                    blk[j] = (blk[j] & 0xff000000) | zv
                m = np.where(to.cover(pts, to.MEASURED, 32), 3, 0).astype(np.int64).reshape(-1, 16)
                cov = [int(w) for w in m.dot(4 ** np.arange(16, dtype=np.int64))]
                covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cov[8 * k:8 * k + 8])) for k in range(8)]
                covl.append('mach: RDN-R6 off 0 0 0 0 lanes=%x' % go.lanes_mask(a))
            else:
                a = pe.SIM_ALIAS[name]
                vals = pe.depth_values(name, pm)
                if pedit and name in pedit:
                    vals = pedit[name](dict(vals))
                dblk = do.block_from_values(vals, 24)
                blk = do.full_block(a)
                blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(dblk)] = dblk
                planes = do.plane_words(dblk, 24)
                cov = do.coverage_words(a)
                covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cov[8 * k:8 * k + 8])) for k in range(8)]
                covl.append('mach: RDN-R6 off 0 0 0 0 lanes=%x' % do.lanes(a))
        elif procedure in ('r6l', 'r6m', 'r6m0') and name in ba.SCASES:
            # R6l: the synthetic machine draws the packets in order, as the oracle says
            px = dict(ba.picture(name))
            if bedit and name in bedit:
                px = bedit[name](dict(px))
            blk = ba.block_of(name, px)
            planes = {}
            cov = ba.cov_words_of(px)
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cov[8 * k:8 * k + 8]))
                    for k in range(8)]
            covl.append('mach: RDN-R6 off 0 0 0 0 lanes=0')
        elif procedure in ('r6m', 'r6m0') and name in ru.SCASES:
            # R6m: the synthetic machine draws the reused case's picture into the case's OWN surfaces
            co, zf, tf = ru.offsets(name)
            if rsurf and name in rsurf:
                co, zf, tf = rsurf[name](co, zf, tf)
            pxmap = dict(ru.colour_words(name))
            if redit and name in redit:
                pxmap = redit[name](dict(pxmap))
            blk = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
            tx = ru.texture_expect(name)
            if tx is not None:
                if rtex and name in rtex:
                    tx = rtex[name](list(tx))
                blk[tf // 4:tf // 4 + len(tx)] = tx
            zv = ru.XA_Z if ru.is_tex(name) else ru.BF_Z
            for (x, y), v in pxmap.items():
                blk[(co + 4 * (x + zo.PITCH * y)) // 4] = v
                k = (zf + do.mba_z32(x, y)) // 4
                blk[k] = (blk[k] & 0xff000000) | zv
            planes = (dict((l, go.plane_words(dict((q, (v >> (8 * l)) & 0xff) for q, v in pxmap.items())))
                           for l in range(4)) if ru.is_tex(name) else {})
            code = 3 if ru.is_tex(name) else 1
            cw = [0] * 64
            for (x, y) in pxmap:
                if x < 32 and y < 32:
                    i = y * 32 + x
                    cw[i >> 4] |= code << (2 * (i & 15))
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cw[8 * k:8 * k + 8])) for k in range(8)]
            covl.append('mach: RDN-R6 off 0 0 0 0 lanes=%x' % (0xf if ru.is_tex(name) else 0))
        elif procedure == 'r6k' and name in sc.SCASES:
            # R6k: the synthetic machine's auxiliary scissor is pscissor (default: the plain reading)
            px = set(sc.picture(name, pscissor or SC_PLAIN))
            if sedit and name in sedit:
                px = sedit[name](set(px))
            dv = sc.depth_map(name, px)
            if sdepth and name in sdepth:
                dv = sdepth[name](dict(dv))
            blk = sc.block_of(name, px, dv)
            planes = sc.planes_of(name, px, dv) if sc.read_of(name) == 'depth' else {}
            cov = sc.cov_words_of(px)
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cov[8 * k:8 * k + 8]))
                    for k in range(8)]
            covl.append('mach: RDN-R6 off 0 0 0 0 lanes=%x' % (7 if sc.read_of(name) == 'depth' else 0))
        elif procedure == 'r6h' and name in te.CASE_NUM:
            # R6h: the synthetic machine samples with trule (and tstride for XE)
            m = te.rule_map(name, trule or te.MEASURED, stride_assumed=tstride if name == 'XE' else None)
            pxmap = dict((q, v) for q, (v, _) in m.items())
            if tedit and name in tedit:
                pxmap = tedit[name](dict(pxmap))
            blk = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
            tex = te.texture_words(name)
            blk[te.TEX_OFF // 4:te.TEX_OFF // 4 + len(tex)] = tex
            zv = do.space(24)[do.SIM_CONV](0.5)
            for (x, y), v in pxmap.items():
                blk[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = v
                k = (zo.DEPTH_OFF + do.mba_z32(x, y)) // 4
                blk[k] = (blk[k] & 0xff000000) | zv
            planes = dict((l, go.plane_words(dict((q, (v >> (8 * l)) & 0xff) for q, v in pxmap.items())))
                          for l in range(4))
            cw = [0] * 64
            for (x, y) in pxmap:
                i = y * 32 + x
                cw[i >> 4] |= 3 << (2 * (i & 15))
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cw[8 * k:8 * k + 8])) for k in range(8)]
            covl.append('mach: RDN-R6 off 0 0 0 0 lanes=f')
        elif procedure == 'r6g' and name in do.GCASE_NUM:
            # R6g: the synthetic machine's test (gcmp) and its reading of Z_ENABLE = 0 (gze)
            bits = do.g_bits(name)
            colour, depth = do.g_predict(name, gze, gcmp)
            if gedit2 and name in gedit2:
                colour, depth = gedit2[name](dict(colour), dict(depth))
            blk = [zo.pattern(i) for i in range(zo.ALIAS_BYTES // 4)]
            dblk = do.block_from_values(depth, bits)
            blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(dblk)] = dblk
            for (x, y), px in colour.items():
                blk[(zo.COLOR_OFF + 4 * (x + zo.PITCH * y)) // 4] = px
            planes = do.plane_words(dblk, bits)
            cw = [0] * 64
            for (x, y), px in colour.items():
                i = y * 32 + x
                cw[i >> 4] |= (1 if px == to.pixel(do.C1) else 2) << (2 * (i & 15))
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cw[8 * k:8 * k + 8])) for k in range(8)]
            covl.append('mach: RDN-R6 off 0 0 0 0 lanes=%x' % (0x3 if bits == 16 else 0x7))
        elif name in do.CASE_NUM:
            # R6f: the model's depth (or dfun's), edited as asked, read back as the driver reads it
            bits = do.fmt_bits(name)
            vals = (dfun or do.sim_values)(name)
            if procedure == 'r6i' and name == 'I1_24' and dfun is None:
                vals = pe.depth_values('PZ', 'A')      # the affine control of PZ: the same ramp
            dblk = do.block_from_values(vals, bits)
            if dedit and name in dedit:
                dblk = dedit[name](dblk, bits, vals)
            blk = do.full_block(name)
            blk[zo.DEPTH_OFF // 4:zo.DEPTH_OFF // 4 + len(dblk)] = dblk
            planes = do.plane_words(dblk, bits)
            cov = do.coverage_words(name)
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cov[8 * k:8 * k + 8])) for k in range(8)]
            covl.append('mach: RDN-R6 off 0 0 0 0 lanes=%x' % do.lanes(name))
        elif name in go.GCASES:
            gr = grule or ('t16', (8, 8), ('q', 8, 'trunc', 'v0'), 'c', 'floor')
            ga = grule_a or gr
            planes = {}
            for l in 'BGRA':
                if go.lanes_mask(name) & go.LANE_BIT[l]:
                    if procedure in ('r6e3', 'r6f', 'r6i'):   # the synthetic machine follows rule B (bmode)
                        planes[l] = go.plane_words(dict(zip(go.covered(go.GCASES[name][0]),
                                                            go.rule_b(go.GCASES[name][0], go.lane_triple(name, l), bmode))))
                    else:
                        planes[l] = go.plane_words(go.expected_values(name, l, ga if l == 'A' else gr))
            offs = [0, 0, 0, 0]
            blk = go.expected_block(name, gr, ga)
            if gedit and name in gedit:
                planes, offs, blk = gedit[name](planes, offs, blk)
            pts = go.GCASES[name][0]
            m = np.where(to.cover(pts, to.MEASURED, 32), 3, 0).astype(np.int64).reshape(-1, 16)
            cov = [int(w) for w in m.dot(4 ** np.arange(16, dtype=np.int64))]
            if gcov and name in gcov:
                cov = gcov[name](cov)
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cov[8 * k:8 * k + 8])) for k in range(8)]
            covl.append('mach: RDN-R6 off %d %d %d %d lanes=%x' % (tuple(offs) + (go.lanes_mask(name),)))
        elif name in to.TRI:
            px = to.pixels(name, rule or to.EXPECTED)
            if trimap and name in trimap:
                px = trimap[name](px.copy())
            blk = to.block_from_pixels(px)
            cov = to.coverage_map(name, observed=px[:32, :32])
            covl = ['mach: RDN-R6 cov%d %s' % (k, ' '.join('%08x' % w for w in cov[8 * k:8 * k + 8])) for k in range(8)]
        else:
            blk = blockfor(name, key)
        sco, szf, stf = zo.COLOR_OFF, zo.DEPTH_OFF, 0
        if procedure in ('r6m', 'r6m0') and name in ru.SCASES:        # R6m: the case's own surfaces
            sco, szf, stf = ru.offsets(name)
            if not ru.is_tex(name):
                stf = 0
        dd = zo.digest(blk, szf // 4, zo.BUF_BYTES // 4)
        dc = zo.digest(blk, sco // 4, zo.BUF_BYTES // 4)
        pre = ' '.join('%08x' % v for _, v in zo.prefix_expect(win, 'F' if (name in to.TRI or name in go.GCASES or
                                                                               name in do.CASE_NUM or
                                                                               name in do.GCASE_NUM or
                                                                               name in te.CASE_NUM or
                                                                               name in pe.CASE_NUM or
                                                                               name in sc.SCASES or
                                                                               name in ba.SCASES or
                                                                               name in ru.SCASES) else name))
        if procedure in ('r6m', 'r6m0') and name in ru.SCASES:    # the prefix carries the moved offsets
            pw = pre.split()
            pw[0], pw[2] = '%08x' % (win + szf), '%08x' % (win + sco)
            pre = ' '.join(pw)
        texbad = 0
        if procedure == 'r6m' and name in ru.SCASES and ru.is_tex(name):
            # the driver reads the texture back at the ROW's offset, whatever the machine did
            want_tx = ru.texture_expect(name)
            texbad = sum(1 for k, wv in enumerate(want_tx) if blk[stf // 4 + k] != wv)
        op('zclear', seed, c, extra=[
            'mach: RDN-R6 zclear case=%d stage=3 surf=00000100 reg0=%08x reg2=%08x prebad=00 pfbad=0' % (c, seed, ~seed & 0xffffffff),
            'mach: RDN-R6 zpre %s' % pre, dline('zd', 0, dd), dline('zc', 0, dc), dline('zd', 1, dd), dline('zc', 1, dc)] +
           covl + ['mach: RDN-R6 zsurf coff=%08x zoff=%08x toff=%08x texbad=%u at=0 val=00000000'
                   % (sco, szf, stf, texbad),
                   # M1m added dw= (the client's digest is a sample) and M1n
                   # added the zq line (the submit log has a switch).  The
                   # self-test keeps one synthetic line per driver format, so
                   # a format the driver gained and this did not is a FAIL.
                   'mach: RDN-R6 zq quiet=0 budget=0 swallowed=0 touch=00000000,00000000 loud=0',  # M2g: loud= appended
                   'mach: RDN-R6 zr rest0=0 rest1=0 first=0 val=00000000 skipped=0 dw=4096'])
        if (name in go.GCASES or name in do.CASE_NUM or (procedure == 'r6g' and name in do.GCASE_NUM) or
                (procedure == 'r6h' and name in te.CASE_NUM) or (procedure == 'r6k' and name in sc.SCASES) or
                (procedure == 'r6m' and name in ru.SCASES and ru.is_tex(name)) or
                (procedure in ('r6i', 'r6i2', 'r6i3', 'r6j') and name in pe.CASE_NUM)):
            zop = n[0]
            src = ''
            if procedure in ('r6f', 'r6g', 'r6h', 'r6i', 'r6i2', 'r6i3', 'r6j', 'r6k', 'r6m'):   # these builds name the plane's source on every plh line
                dflt = ((1 if sc.read_of(name) == 'depth' else 0) if name in sc.SCASES else
                        do.dsrc(name) if name in do.CASE_NUM else
                        (2 if name in do.GCASE_NUM and do.g_bits(name) == 16 else 1) if name in do.GCASE_NUM else
                        (1 if name in pe.CASE_NUM and pe.kind(name) == 'depth' else 0))
                src = ' src=%d' % ((psrc or {}).get(name, dflt))
            for lane, ch in PLANE_ORDER[name]:
                words = (planes[lane] if (name in sc.SCASES or name in ru.SCASES or
                                          name in do.CASE_NUM or name in do.GCASE_NUM or name in te.CASE_NUM or
                                          (name in pe.CASE_NUM and pe.kind(name) != 'gouraud'))
                         else planes['BGRA'[lane]])
                op('plane', 0, lane * 4 + ch, extra=[
                    'mach: RDN-R6 plh boot=%s zc=%d case=%d lane=%d chunk=%d%s' % (nonce, zop, c, lane, ch, src)] +
                   ['mach: RDN-R6 pl%d %d %s' % (lane, k, ' '.join('%08x' % w for w in words[8 * k:8 * k + 8]))
                    for k in range(ch * 8, ch * 8 + 8)])
    if procedure in ('r6c', 'r6d', 'r6e', 'r6e3', 'r6f', 'r6g', 'r6h', 'r6i', 'r6i2', 'r6i3', 'r6j', 'r6k',
                     'r6l', 'r6m'):
        last_recntl = 2
    r3last = [l.replace('1c3c=00000000', '1c3c=%08x' % last_rb3d).replace('1c50=00000000', '1c50=%08x' % last_recntl)
              .replace('26c0=00000000', '26c0=%08x' % (0x000c0014 if procedure == 'r6b' else 0)) for l in r3]
    op('rec3d', extra=r3last)
    op('stop')
    op('record')
    L.append('mach: RDN-R2B cycled boot=%s live=1' % nonce)
    L.append('mach: RDN-R2B cycle n=1 why=0 checked=1 cwhy=0 bad=0 vga=0 palette=0 kernel=0 verdict=0')
    return '\n'.join(L) + '\n'


def format_check():
    """every RDN-R6 driver format has a synthetic line it renders to"""
    text = open(MODELOG).read()
    fm = []
    for m in re.finditer(r'IOLog\(((?:"[^"]*"\s*)+)', text):
        s = ''.join(re.findall(r'"([^"]*)"', m.group(1))).replace('\\n', '')
        if s.startswith('RDN-R6 '):
            fm.append(s)
    g = (synth() + synth(procedure='r6d') + synth(procedure='r6e') + synth(procedure='r6f') +
         synth(procedure='r6g') + synth(procedure='r6h'))
    bad = []
    for f in fm:
        pat = re.escape(f)
        for a, b in (('%08x', '[0-9a-f]{8}'), ('%04x', '[0-9a-f]{4}'), ('%02x', '[0-9a-f]{2}'), ('%u', r'\d+'),
                     ('%d', r'-?\d+'), ('%s', r'\w+'), ('%x', '[0-9a-f]+')):
            pat = pat.replace(re.escape(a), b)
        if not re.search(pat, g):
            bad.append(f[:60])
    return fm, bad


def judge_mix(colour, depth):
    """GFG answered as if the test compared the unfloored value while the rest are floored"""
    c, d = do.g_predict('GFG', 'none', 'exact')
    return dict(c), dict(d)


def self_test():
    fails = 0
    fm, bad = format_check()
    ok = len(fm) >= 6 and not bad
    print('  %-4s the synthetic lines match the driver\'s %d RDN-R6 formats%s' % ('ok' if ok else 'FAIL', len(fm), '' if ok else ': %s' % bad))
    fails += 0 if ok else 1
    regs_src = re.search(r'osrdnCpR3Regs\[CP_R6_REC_COUNT\] = \{([^}]*)\}', open(CPM).read()).group(1)
    n_src = len(re.findall(r'0x[0-9a-f]{4}', regs_src))
    hdr = open(os.path.join(os.path.dirname(CPM), 'osrdn_cp.h')).read()
    n_h = int(re.search(r'#define CP_R6_REC_COUNT\s+(\d+)', hdr).group(1))
    ok = n_src == n_h == REC_WANT[REC_LATEST] and n_h % 4 == 0 and 'k += 4)' in open(MODELOG).read()
    print('  %-4s the driver reads %d REC3D registers (header %d, want %d, printed four a line)' % (
        'ok' if ok else 'FAIL', n_src, n_h, REC_WANT[REC_LATEST]))
    fails += 0 if ok else 1
    g = synth()
    p, notes = judge(g, 'abcd0001', '11111111')
    print('  %-4s the clean boot passes%s' % ('FAIL' if p else 'ok', '' if not p else ': %s' % p[:3]))
    fails += 1 if p else 0
    b_note = [x for x in notes if x.startswith('zclear B')]
    ok = b_note == ['zclear B: depth buffer = tiled/round']
    print('  %-4s case B names its rounding: %s' % ('ok' if ok else 'FAIL', b_note))
    fails += 0 if ok else 1
    BAD = [
        ('the depth buffer is linear', lambda: synth(layout='linear')),
        ('the colour buffer changed', lambda: re.sub(r'(RDN-R6 zc1 xor=[0-9a-f]{8} wsum=)[0-9a-f]{8}', r'\g<1>12345678', synth(), count=1)),
        ('a word outside the buffers changed', lambda: synth().replace('zr rest0=0 rest1=0', 'zr rest0=1 rest1=1', 1)),
        ('an R6 case says the scan was skipped',
         lambda: synth().replace('first=0 val=00000000 skipped=0',
                                 'first=0 val=00000000 skipped=1', 1)),
        ('the prefix read back otherwise', lambda: synth().replace('prebad=00', 'prebad=01', 1)),
        ('translation not disabled', lambda: synth().replace('0b00=00000100', '0b00=00000000', 1)),
        ('a marker missing', lambda: re.sub(r'reg2=[0-9a-f]{8}', 'reg2=00000000', synth(), count=1)),
        ('an operation missing', lambda: re.sub(r'mach: RDN-R5 begin[^\n]*\nmach: RDN-R5 zprep boot[^\n]*\n(?:mach: RDN-R[56] (?:state|io|zprep)[^\n]*\n)+',
                                                '', synth(), count=1)),
        ('another build', lambda: synth(build='22222222')),
        ('the cycle failed', lambda: synth().replace('verdict=0', 'verdict=1')),
        ('no R4 alias line', lambda: '\n'.join(l for l in synth().splitlines() if 'RDN-R4 alias' not in l) + '\n'),
        ('the alias failed', lambda: synth().replace('len=00040000 ok', 'len=00040000 map', 1)),
        ('RB3D_CNTL not put back', lambda: synth(last_rb3d=0x1902)),
        ('DEPTHXY read back otherwise', lambda: re.sub(r'(RDN-R6 zpre (?:[0-9a-f]{8} ){8})00000000', r'\g<1>00000010',
                                                        synth(), count=1)),
    ]
    for label, f in BAD:
        t = f()
        q, _ = judge(t, 'abcd0001', '11111111')
        print('  %-4s %-44s %s' % ('ok' if q else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if q else 1
    # r6b (docs/R6B_PLAN.md 5)
    g = synth(procedure='r6b')
    q, notes = judge(g, 'abcd0001', '11111111', 'r6b')
    print('  %-4s r6b: the clean boot passes%s' % ('FAIL' if q else 'ok', '' if not q else ': %s' % q[:3]))
    fails += 1 if q else 0
    RBAD = [
        ('r6b: D ignores TL like C (H refuted)', lambda: synth(procedure='r6b', override={'D': (0, 0, 37, 21)}), 'origin..WH'),
        ('r6b: C clips at TL (the refuted R6a rule)', lambda: synth(procedure='r6b', override={'C': (5, 3, 37, 21)}), 'the clip rectangle'),
        ('r6b: D uses WH relative to TL', lambda: synth(procedure='r6b', override={'D': (5, 3, 42, 24)}), 'WH relative to TL'),
        ('r6b: RE_CNTL 2 did not land (and D ignored TL)',
         lambda: synth(procedure='r6b', recntl_after_d=0, override={'D': (0, 0, 37, 21)}), 'RE_CNTL 00000000, want 2'),
        ('r6b: E clips at TL', lambda: synth(procedure='r6b', override={'E': (20, 12, 37, 21)}), 'the clip rectangle'),
        ('r6b: E takes TL in 1/16 pixel', lambda: synth(procedure='r6b', override={'E': (1, 0, 37, 21)}), 'TL in 1/16 pixel'),
        ('r6b: C\' differs from C', lambda: synth(procedure='r6b', override={'C': (0, 0, 37, 21), 'Cp': (0, 0, 37, 20)}), None),
        ('r6b: RE_CNTL left at 2', lambda: synth(procedure='r6b', last_recntl=2), None),
        ('r6b: judged as r6a', lambda: synth(procedure='r6b'), None),
    ]
    for label, f, name in RBAD:
        t = f()
        q, _ = judge(t, 'abcd0001', '11111111', 'r6a' if 'as r6a' in label else 'r6b')
        ok = bool(q) and (name is None or any(name in x for x in q))
        print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    # r6c (docs/R6C_PLAN.md 6-8)
    g = synth(procedure='r6c')
    q, notes = judge(g, 'abcd0001', '11111111', 'r6c')
    print('  %-4s r6c: the clean boot passes%s' % ('FAIL' if q else 'ok', '' if not q else ': %s' % q[:3]))
    fails += 1 if q else 0
    fg = [x for x in notes if x.startswith('F/G')]
    ok = fg == ['F/G: the order bit works as Mesa assumes']
    print('  %-4s r6c: the clean F/G pair is named %s' % ('ok' if ok else 'FAIL', fg))
    fails += 0 if ok else 1
    CBAD = [
        ('r6c: F is R/B swapped', dict(colour={'F': ('linear', P_BGRA), 'Fp': ('linear', P_BGRA)}), 'R and B swapped'),
        ('r6c: F is tiled', dict(colour={'F': ('tiled', P_RGBA), 'Fp': ('tiled', P_RGBA)}), 'tiled/Mesa order'),
        ('r6c: F red +1 (approximate is not PASS)', dict(colour={'F': ('linear', P_RGBA + 0x10000),
                                                                 'Fp': ('linear', P_RGBA + 0x10000)}), 'approximate: r +1'),
        ('r6c: F wrote no colour', dict(colour={'F': ('none', None), 'Fp': ('none', None)}), 'plane mask or blend stage'),
        ('r6c: F\' differs from F', dict(colour={'Fp': ('linear', P_BGRA)}), 'not repeatable'),
        ('r6c: G\'s depth differs from A\'s', dict(fdepth={'G': (0, 0, 37, 21)}), 'vertex size'),
    ]
    for label, kw, want in CBAD:
        t = synth(procedure='r6c', **kw)
        q, nt = judge(t, 'abcd0001', '11111111', 'r6c')
        ok = bool(q) and (want is None or any(want in x for x in q))
        print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    # the measured cases are named, not gated
    MEAS = [
        ('r6c: G = F names "ignored"', dict(colour={'G': ('linear', P_RGBA)}), 'F/G: the order bit is ignored on this path'),
        ('r6c: F/G reversed gives both readings', dict(colour={'F': ('linear', P_BGRA), 'Fp': ('linear', P_BGRA),
                                                              'G': ('linear', P_RGBA)}), 'the same observation'),
        ('r6c: H differs from F is named', dict(colour={'H': ('linear', P_BGRA)}), 'SE_VTX_STATE_CNTL matters'),
    ]
    for label, kw, want in MEAS:
        q, nt = judge(synth(procedure='r6c', **kw), 'abcd0001', '11111111', 'r6c')
        ok = any(want in x for x in nt) and (not q or 'F' in kw.get('colour', {}))
        print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', label, [x for x in nt if want in x][:1] or (q[:1], nt[-4:])))
        fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6c'), 'abcd0001', '11111111', 'r6b')
    print('  %-4s %-44s %s' % ('ok' if q else 'FAIL', 'r6c: judged as r6b', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if q else 1
    # r6d (docs/R6D_PLAN.md 10)
    g = synth(procedure='r6d')
    q, notes = judge(g, 'abcd0001', '11111111', 'r6d')
    rule = [x for x in notes if x.startswith('the rule')]
    ok = not q and rule == ["the rule (class of 1): [('gated', (8, 'trunc', 8, 'tl', 'n'))]"]
    print('  %-4s r6d: the clean boot passes and names the rule%s' % ('ok' if ok else 'FAIL', '' if ok else ': %s %s' % (q[:2], rule)))
    fails += 0 if ok else 1
    other = (16, 'round', 8, 'bl', 'n')
    q, notes = judge(synth(procedure='r6d', rule=other), 'abcd0001', '11111111', 'r6d')
    rule = [x for x in notes if x.startswith('the rule')]
    ok = not q and any(str(other) in x for x in rule) and any('is NOT in the class' in x for x in notes)
    print('  %-4s r6d: another rule passes under ITS name, SE_CNTL reading marked absent %s' % ('ok' if ok else 'FAIL', rule[:1]))
    fails += 0 if ok else 1
    q, notes = judge(synth(procedure='r6d', rule=(8, 'trunc', 8, 'tl', 'w')), 'abcd0001', '11111111', 'r6d')
    ok = not q and any("(8, 'trunc', 8, 'tl', 'w')" in x for x in notes if x.startswith('the rule'))
    print('  %-4s r6d: a winding-dependent rule is told apart' % ('ok' if ok else 'FAIL'))
    fails += 0 if ok else 1

    def flip(y, x):
        def f(px):
            px[y][x] = -1 if px[y][x] >= 0 else to.pixel(to.C1)
            return px
        return f

    def stray(px):
        px[40][40] = to.pixel(to.C1)            # outside the 32 x 32 map
        return px

    def impure(px):
        ys, xs = np.nonzero(px >= 0)
        px[ys[0]][xs[0]] = 0x01020304
        return px
    DBAD = [
        ('r6d: one pixel of X5 off every rule', dict(trimap={'X5': flip(20, 12)}), 'no named rule explains'),
        ('r6d: a colour write outside the map', dict(trimap={'T2': stray}), 'outside the map'),
        ('r6d: an impure pixel in T5', dict(trimap={'T5': impure}), 'neither case colour'),
        ('r6d: judged as r6c', dict(), 'the operations were'),
    ]
    for label, kw, want in DBAD:
        q, nt = judge(synth(procedure='r6d', **kw), 'abcd0001', '11111111', 'r6c' if 'as r6c' in label else 'r6d')
        ok = any(want in x for x in q)
        near = [x for x in nt if 'nearest' in x][:1]
        print('  %-4s %-44s %s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT', near))
        fails += 0 if ok else 1
    q, nt = judge(synth(procedure='r6d', trimap={'X5': flip(20, 12)}), 'abcd0001', '11111111', 'r6d')
    tot = [x for x in nt if x.startswith('nearest over all cases')]
    ok = bool(q) and tot and tot[0].startswith('nearest over all cases: 1 pixels off in total, 1 rules') and str(to.EXPECTED) in tot[0]
    print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', 'r6d: the nearest rule over all cases is the one drawn', tot[:1]))
    fails += 0 if ok else 1
    # the FAIL diagnostics fire (code review AS1, m2)
    fam = [f for f in to.diagnostic_families() if f[1] == '1/256 round then 1/8 trunc, sample 8/16, tl, n'][0]

    def by_family(name):
        def f(px):
            out = np.full((64, 64), -1, np.int64)
            for pts, cols in to.TRI[name]:
                out[to.cover_general(pts, fam[2], fam[3], fam[4], fam[5], fam[6])] = to.pixel(cols[2])
            return out
        return f
    q, nt = judge(synth(procedure='r6d', trimap=dict((n, by_family(n)) for n in to.ORDER)), 'abcd0001', '11111111', 'r6d')
    rule = [x for x in nt if x.startswith('the rule')]
    ok = not q and bool(rule) and fam[1] in rule[0] and 'gated' not in rule[0] and any('is NOT in the class' in x for x in nt)
    print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', 'r6d: a double-rounding rule passes under its OWN name', rule[:1] or q[:1]))
    fails += 0 if ok else 1

    def empty(px):
        px[:, :] = -1
        return px
    q, nt = judge(synth(procedure='r6d', trimap={'X1': empty, 'X5': empty, 'T1r': empty}), 'abcd0001', '11111111', 'r6d')
    em = [x for x in nt if 'EMPTY map' in x]
    ok = bool(q) and len(em) == 3 and all('negative' in x for x in em if not x.startswith('T1r'))
    print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', 'r6d: a culled winding names its empty maps', em))
    fails += 0 if ok else 1

    def t7other(px):
        px[4][10] = -1
        return px
    q, nt = judge(synth(procedure='r6d', trimap={'T7': t7other}), 'abcd0001', '11111111', 'r6d')
    ok = not q and 'T7 covers OTHER pixels than T1' in nt
    print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', 'r6d: T7 covering other pixels than T1 is named', [x for x in nt if x.startswith('T7 covers')]))
    fails += 0 if ok else 1
    # depth coverage must equal colour coverage: shift the depth of T1 by editing its digest line
    g = synth(procedure='r6d')
    t = re.sub(r'(boot=abcd0001 n=\d+ arg=5eed0092 len=9[^\n]*\n(?:[^\n]*\n)*?mach: RDN-R6 zd1 xor=[0-9a-f]{8} wsum=[0-9a-f]{8} changed=)(\d+)',
               lambda m: m.group(1) + str(int(m.group(2)) + 1), g, count=1)
    q, _ = judge(t, 'abcd0001', '11111111', 'r6d')
    ok = t != g and any('depth buffer covers other pixels' in x for x in q)
    print('  %-4s %-44s %s' % ('ok' if ok else 'FAIL', 'r6d: depth covers other pixels than colour', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6e (docs/R6E_PLAN.md 9-10)
    base_rule = ('t16', (8, 8), ('q', 8, 'trunc', 'v0'), 'c', 'floor')

    def run(label, want_fail, want_text, **kw):
        nonlocal fails
        q, nt = judge(synth(procedure='r6e', **kw), 'abcd0001', '11111111', 'r6e')
        hay = q if want_fail else nt
        ok = (bool(q) == want_fail) and any(want_text in x for x in hay)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, (q[:1] if q else [x for x in nt if want_text in x][:1]) or nt[-3:]))
        fails += 0 if ok else 1

    run('r6e: the clean boot passes, RGB rule named', False, str(base_rule), )
    run('r6e: an exact-round machine passes under its class', False, "('exact',), 'c', 'round')",
        grule=('t16', (8, 8), ('exact',), 'c', 'round'))
    run('r6e: alpha follows its own rule', False, "A rule (class of", grule_a=('t16', (8, 8), ('exact',), 'c', 'round'))

    def flip_s3(planes, offs, blk):
        planes['R'] = list(planes['R'])
        k = next(i for i, w in enumerate(planes['R']) if w)
        planes['R'][k] ^= 1 << (8 * next(j for j in range(4) if (planes['R'][k] >> (8 * j)) & 0xff))
        return planes, offs, blk
    run('r6e: one S3 byte off every rule', True, 'no named interpolation rule', gedit={'S3': flip_s3})

    def copy_ra(planes, offs, blk):
        planes['A'] = list(planes['R'])
        return planes, offs, blk
    run('r6e: G7 alpha copies red', True, 'alpha copies red', gedit={'G7': copy_ra})

    def off_g1(planes, offs, blk):
        return planes, [0, 3, 0, 0], blk
    run('r6e: a constant lane moves in G1', True, 'constant lanes moved', gedit={'G1': off_g1})
    def one_less(cov):
        cov = list(cov)
        k = next(i for i, w in enumerate(cov) if w)
        cov[k] &= ~(3 << (2 * next(j for j in range(16) if (cov[k] >> (2 * j)) & 3)))
        return cov
    run('r6e: coverage one pixel short of the measured rule', True, 'coverage is not the measured rule', gcov={'S5': one_less})
    run('r6e: G0 constant lanes moving is only measured', False, 'G0 (constant colour under Gouraud)', gedit={'G0': off_g1})
    # PLANE attach rules (docs/R6E_PLAN.md 14): a wrong header, a missing chunk, a chunk logged twice
    g = synth(procedure='r6e')
    t = re.sub(r'(RDN-R6 plh boot=abcd0001 zc=)(\d+)( case=35 lane=2 chunk=1)', lambda m: m.group(1) + str(int(m.group(2)) - 2) + m.group(3), g, count=1)
    q, _ = judge(t, 'abcd0001', '11111111', 'r6e')
    ok = t != g and any('header' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6e: a plane header naming another ZCLEAR', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    blocks = re.split(r'(?=mach: RDN-R5 begin )', g)
    k3 = [k for k, b in enumerate(blocks) if 'case=40 lane=3 chunk=2' in b]
    t = ''.join(re.sub(r'mach: RDN-R6 pl3 19 [^\n]*\n', '', b, count=1) if k in k3 else b for k, b in enumerate(blocks))
    q, _ = judge(t, 'abcd0001', '11111111', 'r6e')
    ok = len(k3) == 1 and t != g and any('lines' in x and 'want [16' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6e: one line of a plane chunk missing', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    k0 = [k for k, b in enumerate(blocks) if 'case=40 lane=2 chunk=0' in b]
    k1 = [k for k, b in enumerate(blocks) if 'case=40 lane=2 chunk=1' in b]
    n1 = re.search(r'RDN-R5 plane boot=abcd0001 n=(\d+)', blocks[k1[0]]).group(1)
    twin = re.sub(r'(RDN-R5 plane boot=abcd0001 n=)\d+', lambda m: m.group(1) + n1, blocks[k0[0]])
    t = ''.join(twin if k in k1 else b for k, b in enumerate(blocks))
    q, _ = judge(t, 'abcd0001', '11111111', 'r6e')
    ok = len(k0) == len(k1) == 1 and any('logged twice' in x or 'header' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6e: chunk 0 logged where chunk 1 belongs', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6e3 (docs/R6E_PLAN.md 18)
    for bm, want in (('round', 'weight rounding: round'), ('even', 'weight rounding: even')):
        q, nt = judge(synth(procedure='r6e3', bmode=bm), 'abcd0001', '11111111', 'r6e3')
        ok = not q and any(want in x for x in nt)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6e3: a rule-B machine (%s) passes and is named' % bm,
                                     [x for x in nt if 'rule B holds' in x][:1] or q[:1]))
        fails += 0 if ok else 1

    def flip_v3(planes, offs, blk):
        planes['R'] = list(planes['R'])
        k = next(i for i, w in enumerate(planes['R']) if w)
        planes['R'][k] ^= 1 << (8 * next(j for j in range(4) if (planes['R'][k] >> (8 * j)) & 0xff))
        return planes, offs, blk
    q, _ = judge(synth(procedure='r6e3', gedit={'V3': flip_v3}), 'abcd0001', '11111111', 'r6e3')
    ok = any('rule B does not hold' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6e3: one V3 byte off rule B', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6e'), 'abcd0001', '11111111', 'r6d')
    ok = any('the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6e: judged as r6d', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6f (docs/R6F_PLAN.md 3-3, 5): the baseline passes and names the model's conversion; each fault fails
    q, nt = judge(synth(procedure='r6f'), 'abcd0001', '11111111', 'r6f')
    named = [x for x in nt if 'conversion = %s' % (do.SIM_CONV,) in x]
    ok = not q and len(named) == 2
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6f: the model passes, both formats named', q[:1] or named[:1]))
    fails += 0 if ok else 1

    def off_by_one(case):                  # one anchor of K16b converts one higher: no rule gives the 64
        v = do.sim_values(case)
        if case == 'K16b':
            x0, y0 = do.CELLS[5]
            for q_ in do.covered(case):
                if q_ in [p_ for p_ in v if abs(p_[0] - x0) < 3 and abs(p_[1] - y0) < 3]:
                    v[q_] += 1
        return v

    def linear16(blk, bits, vals):         # the machine lays 16-bit depth out linearly
        b = do.pattern_block()
        for (x, y), v in vals.items():
            a = 2 * (x + 64 * y)
            sh = 16 * ((a >> 1) & 1)
            b[a // 4] = (b[a // 4] & ~(0xffff << sh) & 0xffffffff) | (v << sh)
        return b

    def clobber(blk, bits, vals):          # a 16-bit write zeroes the other half of its word -- where that half
        b = list(blk)                      # is an UNCOVERED pixel (a covered partner's half is its data: plan 3-3)
        x, y = next(q_ for q_ in sorted(vals) if (q_[0] ^ 1, q_[1]) not in vals)
        a = do.mba_z16(x, y)
        b[a // 4] &= 0xffff << (16 * ((a >> 1) & 1))
        return b

    def clobber_cov(blk, bits, vals):      # a cell's (x0+1, y0) write zeroes its covered partner (x0, y0)
        b = list(blk)
        x, y = do.CELLS[0]
        a = do.mba_z16(x + 1, y)
        b[a // 4] &= 0xffff << (16 * ((a >> 1) & 1))
        return b

    def stencil(blk, bits, vals):          # a 24-bit write changes the stencil byte
        b = list(blk)
        x, y = sorted(vals)[0]
        b[do.mba_z32(x, y) // 4] ^= 0x01000000
        return b

    def stray(blk, bits, vals):            # an uncovered pixel of the 32 x 32 changes
        b = list(blk)
        do.put_depth(b, 31, 0, bits, 0x1234)
        return b

    def cell_split(case):                  # one pixel of a cell differs from the other two
        v = do.sim_values(case)
        if case == 'K24c':
            v[(2, 2)] ^= 1
        return v
    for label, kw, want in [
            ('r6f: one anchor outside every rule', dict(dfun=off_by_one), '16-bit conversion: no named rule'),
            ('r6f: 16-bit laid out linearly', dict(dedit={'K16a': linear16}), 'do not rebuild depth'),
            ('r6f: a 16-bit write clobbers an uncovered half', dict(dedit={'I2_16': clobber}), 'uncovered pixels changed depth'),
            ('r6f: a grid write clobbers its covered partner', dict(dedit={'K16c': clobber_cov}), 'the cell of z'),
            ('r6f: a 24-bit write changes the stencil', dict(dedit={'K24a': stencil}), 'do not rebuild depth'),
            ('r6f: an uncovered pixel changes depth', dict(dedit={'I1_24': stray}), 'uncovered pixels changed depth'),
            ('r6f: a cell\'s pixels disagree', dict(dfun=cell_split), 'the cell of z'),
            ('r6f: the planes name the colour source', dict(psrc={'I5_16': 0}), 'the planes name source')]:
        q, _ = judge(synth(procedure='r6f', **kw), 'abcd0001', '11111111', 'r6f')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6f'), 'abcd0001', '11111111', 'r6e3')
    ok = any('the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6f: judged as r6e3', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6g (docs/R6G_PLAN.md 2-3, 6)
    for cmp, want in (('int', 'floored'), ('exact', 'unfloored')):
        q, nt = judge(synth(procedure='r6g', gcmp=cmp), 'abcd0001', '11111111', 'r6g')
        named = [x for x in nt if 'every gated case is explained by "the test compares the %s value"' % want in x]
        ok = not q and named
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6g: a %s-compare machine passes and is named' % want,
                                   (named or q)[:1]))
        fails += 0 if ok else 1

    def flip_one(colour, depth):                 # one pixel passes that should not
        c = dict(colour)
        for x in range(4, 28):
            if (x, 4) not in c:
                c[(x, 4)] = P_BGRA
                break
        return c, depth

    def wrote_anyway(colour, depth):             # the write mask was ignored
        d = dict(depth)
        for q_ in list(colour)[:5]:
            d[q_] = 32768
        return colour, d

    def stale(colour, depth):                    # GH1: the second draw read the ZPREP pattern, not the first draw's depth
        pat = do.pattern_block()
        c, d = {}, dict(depth)
        first = do.space(16)[do.SIM_CONV](0.9)
        for q_ in do.go.covered(do.GEOM[do.GEOM_G]):
            new = do.space(16)[do.SIM_CONV](0.5)
            if new < do.read_depth(pat, q_[0], q_[1], 16):
                c[q_], d[q_] = to.pixel(do.C2), new
            else:
                c[q_], d[q_] = to.pixel(do.C1), first
        return c, d
    for label, kw, want in [
            ('r6g: one pixel passes that should not', dict(gedit2={'GL': flip_one}), 'neither reading explains'),
            ('r6g: the write mask is ignored', dict(gedit2={'GLW': wrote_anyway}), 'neither reading explains'),
            ('r6g: the prefill did not read back', dict(gedit2={}), None),
            ('r6g: one case answers the other reading', dict(gedit2={'GFG': lambda c, d: judge_mix(c, d)}), 'no single comparison reading'),
            ('r6g: two draws need a wait (GH1 stale, GH1w fine)', dict(gedit2={'GH1': stale}), 'a WAIT_UNTIL is needed')]:
        if want is None:
            t = synth(procedure='r6g').replace('case=%d stage=3 surf=00000100' % do.GCASE_NUM['GL'],
                                               'case=%d stage=3 surf=00000100' % do.GCASE_NUM['GL'], 1)
            t = re.sub(r'(case=%d stage=3 surf=00000100 reg0=[0-9a-f]{8} reg2=[0-9a-f]{8} prebad=00 pfbad=)0'
                       % do.GCASE_NUM['GL'], r'\g<1>7', t)
            q, _ = judge(t, 'abcd0001', '11111111', 'r6g')
            ok = any('the prefill did not read back' in x for x in q)
        else:
            q, _ = judge(synth(procedure='r6g', **kw), 'abcd0001', '11111111', 'r6g')
            ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6g'), 'abcd0001', '11111111', 'r6f')
    ok = any('the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6g: judged as r6f', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6h (docs/R6H_PLAN.md 2-3)
    for rule, lab in ((te.MEASURED, 'the measured rule'), ((Fraction(1, 2), 0, 'clamp'), 'the pixel centre, clamp'),
                      ((Fraction(0), Fraction(-1, 2), 'clamp'), 'floor(s*w - 1/2), clamp')):
        q, nt = judge(synth(procedure='r6h', trule=rule), 'abcd0001', '11111111', 'r6h')
        named = [x for x in nt if 'the ST rule is %s' % (rule,) in x]
        ok = not q and named
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6h: a %s machine passes and is named' % lab,
                                   (named or q)[:1]))
        fails += 0 if ok else 1
    q, nt = judge(synth(procedure='r6h', tstride=64), 'abcd0001', '11111111', 'r6h')
    ok = any('the row stride from PP_TXPITCH' in x for x in nt)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6h: XE names the pitch reading',
                               [x for x in nt if 'row stride' in x][:1] or q[:1]))
    fails += 0 if ok else 1

    def one_pixel(px):                           # one safe pixel gets another texel
        d = dict(px)
        for q_ in sorted(d):
            if te.rule_map('XA', te.MEASURED)[q_][1]:
                d[q_] ^= 0x00010000
                break
        return d

    def swap_axes(px):                           # the sampler read (v, u) instead of (u, v)
        m = te.rule_map('XD', te.MEASURED)
        out = {}
        for q_, (v, _) in m.items():
            out[q_] = ((v & 0xff00ffff) | ((v >> 8 & 0xff) << 16) & 0xffffffff) if False else \
                      (0xff000000 | ((v >> 8 & 0xff) << 16) | ((v >> 16 & 0xff) << 8) | 0x55)
        return out
    for label, kw, want in [('r6h: one safe pixel holds another texel', dict(tedit={'XA': one_pixel}), 'no named ST rule'),
                            ('r6h: the sampler swaps u and v', dict(tedit={'XD': swap_axes}), 'no named ST rule')]:
        q, _ = judge(synth(procedure='r6h', **kw), 'abcd0001', '11111111', 'r6h')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    t = re.sub(r'(case=%d stage=3 surf=00000100 reg0=[0-9a-f]{8} reg2=[0-9a-f]{8} prebad=00 pfbad=)0' % te.CASE_NUM['XA'],
               r'\g<1>3', synth(procedure='r6h'))
    q, _ = judge(t, 'abcd0001', '11111111', 'r6h')
    ok = any('the texture did not read back' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6h: the texture did not read back', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6h'), 'abcd0001', '11111111', 'r6g')
    ok = any('the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6h: judged as r6g', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6i (docs/R6I_PLAN.md 2-3)
    for model in ('A', 'Pq', 'Pw'):
        q, nt = judge(synth(procedure='r6i', pmodel=model), 'abcd0001', '11111111', 'r6i')
        named = [x for x in nt if x == 'R6i P1: the perspective model is %s' % model]
        depth = [x for x in nt if x == 'R6i P4: the depth follows %s' % model]
        ok = not q and named and depth
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i: a %s machine passes and is named' % model,
                                   (named + depth or q)[:1]))
        fails += 0 if ok else 1
    for rule, lab in (((pe.MEASURED_OFF, Fraction(-1, 2), None, 'floor', 'floor'), 'the half-texel offset'),
                      ((pe.MEASURED_OFF, Fraction(-1, 2), 32, 'round', 'floor'), 'weights quantised to 1/32'),
                      ((pe.MEASURED_OFF, Fraction(-1, 2), None, 'floor', 'round'), 'the rounded blend')):
        want = ('A',) + rule
        q, nt = judge(synth(procedure='r6i', pmodel='A', pbil=want), 'abcd0001', '11111111', 'r6i')
        named = [x for x in nt if 'B1b: the bilinear rule is %s' % (want,) in x]
        ok = not q and named
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i: a machine with %s is named' % lab, (named or q)[:1]))
        fails += 0 if ok else 1

    def one_tex_pixel(px):                       # one safe pixel of LD holds another blend
        d = dict(px)
        for q_, (_, safe) in sorted(pe.bilinear_map('LD', ('A', pe.MEASURED_OFF, Fraction(-1, 2), None, 'floor', 'floor')).items()):
            if safe:
                d[q_] ^= 0x00010000
                break
        return d

    def a_byte(vals):                            # one byte of PE's R plane moves by more than the
        d = dict(vals)                           # one LSB the divide's own rounding is allowed
        d['R'] = bytes([(d['R'][0] + 5) & 0xff]) + d['R'][1:]
        return d

    def a_depth(vals):                           # one pixel of PZ moves by more than the tolerance
        d = dict(vals)
        k = sorted(d)[10]
        d[k] = (d[k] + 4096) & 0xffffff
        return d

    def alpha_off(px):                           # the filter did not conserve the alpha channel
        d = dict(px)
        for q_ in sorted(d)[:5]:
            d[q_] = (d[q_] & 0x00ffffff) | 0xfe000000
        return d
    for label, kw, want in [
            ('r6i: one safe bilinear pixel moves', dict(pedit={'LD': one_tex_pixel}), 'no named weight arithmetic'),
            ('r6i: the 2x8 texture is read as 8x2', dict(pwh={'LN': (8, 2)}), 'differ from the R6h rule'),
            ('r6i: one byte of the perspective colour moves', dict(pedit={'PE': a_byte}), 'P3'),
            ('r6i: one pixel of the perspective depth moves', dict(pedit={'PZ': a_depth}), 'P4'),
            ('r6i: PD is drawn with perspective anyway',
             dict(pedit={'PD': lambda px: dict(pe.nearest_map('PD', ('Pq', pe.MEASURED_OFF, None)) and
                                               ((q_, v) for q_, (v, _) in pe.nearest_map('PD', ('Pq', pe.MEASURED_OFF, None)).items()))}),
             'differ from the affine picture')]:
        q, _ = judge(synth(procedure='r6i', **kw), 'abcd0001', '11111111', 'r6i')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    q, nt = judge(synth(procedure='r6i', pedit={'LA': alpha_off}), 'abcd0001', '11111111', 'r6i')
    ok = any('constant channels moved' in x for x in nt)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i: the filter loses a constant channel',
                               [x for x in nt if 'constant channels' in x][:1]))
    fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6i'), 'abcd0001', '11111111', 'r6h')
    ok = any('the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i: judged as r6h', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6i2 (docs/R6I2_PLAN.md 2-3)
    for ar in ((64, 'floor', 6, 4), (32, 'round', 2, 5), (128, 'floor', 0, 7)):
        q, nt = judge(synth(procedure='r6i2', parith=ar), 'abcd0001', '11111111', 'r6i2')
        # the rung names a CLASS: the machine's own rule must be in it (the note lists the members)
        named = [x for x in nt if x.startswith('R6i-2 GA: the filter truncates each axis to k/%d' % ar[0])
                 and (('r = %d across and %d down' % (ar[2] * ar[0] // 8, ar[3] * ar[0] // 8)) in x
                      or str(ar) in x)]
        ok = not q and named
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i2: a %s machine is named' % (ar,), (named or q)[:1]))
        fails += 0 if ok else 1

    def one_q_pixel(px):                         # one pixel of the sweep holds another value
        d = dict(px)
        k = sorted(d)[7]
        d[k] ^= 0x00040000
        return d

    def other_arith(name):
        return lambda px: dict(pe.arith_map2(name, (32, 'floor', 2, 2)))
    for label, kw, want in [
            ('r6i2: one pixel of the sweep moves', dict(pedit={'Q1': one_q_pixel}), 'GA: no named weight arithmetic'),
            ('r6i2: the vertical axis rounds otherwise', dict(pedit={'Q3': other_arith('Q3')}), 'GA: no named weight'),
            ('r6i2: the new geometry samples otherwise',
             dict(pedit={'Q0': lambda px: dict((q, v ^ 0x00010000) for q, v in px.items())}), 'G0')]:
        q, _ = judge(synth(procedure='r6i2', **kw), 'abcd0001', '11111111', 'r6i2')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    q, nt = judge(synth(procedure='r6i2', pedit={'Q5': other_arith('Q5')}), 'abcd0001', '11111111', 'r6i2')
    ok = any('GF: with FILTER_ROUND_MODE set the horizontal constant is' in x for x in nt)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i2: FILTER_ROUND_MODE changes the arithmetic',
                               [x for x in nt if 'GF' in x][:1] or q[:1]))
    fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6i2'), 'abcd0001', '11111111', 'r6i')
    ok = any('the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i2: judged as r6i', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1

    # r6i3 (docs/R6I3_PLAN.md 2-3)
    for kw, want in ((dict(), 'follows the AXIS'), (dict(pchan=True), 'follows the COLOUR CHANNEL')):
        q, nt = judge(synth(procedure='r6i3', **kw), 'abcd0001', '11111111', 'r6i3')
        named = [x for x in nt if want in x]
        ok = not q and named
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i3: a machine whose constant %s is named' % want,
                                   (named or q)[:1]))
        fails += 0 if ok else 1

    def bitset(name, rule):
        return lambda px: dict(pe.arith_map2(name, rule))
    q, nt = judge(synth(procedure='r6i3', pedit={'N3': bitset('N3', (64, 'floor', 2, 4)),
                                                 'N4': bitset('N4', (64, 'floor', 6, 1))}),
                  'abcd0001', '11111111', 'r6i3')
    ok = (not q and any('the across constant is r = 16' in x for x in nt)
          and any('the down constant is r = 8' in x for x in nt))
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i3: the bit-set constants are named',
                               [x for x in nt if 'H2 S' in x][:2] or q[:1]))
    fails += 0 if ok else 1

    def one_s1(px):
        d = dict(px)
        k = sorted(d)[9]
        d[k] ^= 0x00000400
        return d
    for label, kw, want in [('r6i3: one pixel of N1 moves', dict(pedit={'N1': one_s1}), 'H1 N1'),
                            ('r6i3: the R6i-2 control moved', dict(pedit={'Q1': one_s1}), 'H3')]:
        q, _ = judge(synth(procedure='r6i3', **kw), 'abcd0001', '11111111', 'r6i3')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6i3'), 'abcd0001', '11111111', 'r6i2')
    ok = any('zclear cases' in x or 'the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6i3: judged as r6i2', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1

    # r6j (docs/R6J_PLAN.md 2-3)
    # the last is the reading the hardware turned out to use: it must be named as itself and not as
    # one of the three saturations (docs/R6J_PLAN.md 7.2), either as the class's name or inside it
    for bl in (('id', 0), ('sat256', 128), ('expand', 255), ('plus1', 0)):
        q, nt = judge(synth(procedure='r6j', pblend=bl), 'abcd0001', '11111111', 'r6j')
        named = [x for x in nt if x.startswith('R6j K2:')
                 and (('as %s and r = %d' % bl) in x or str(bl) in x)]
        ok = not q and named
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6j: a %s machine is named' % (bl,), (named or q)[:1]))
        fails += 0 if ok else 1

    def one_blend_pixel(px):
        d = dict(px)
        k = sorted(d)[11]
        d[k] ^= 0x00010000
        return d
    for label, kw, want in [
            ('r6j: one blended pixel moves', dict(pedit={'J4': one_blend_pixel}), 'K2: no named blend'),
            ('r6j: the second draw does not replace with blending off',
             dict(pedit={'J0': one_blend_pixel}), 'K1: with blending off')]:
        q, _ = judge(synth(procedure='r6j', **kw), 'abcd0001', '11111111', 'r6j')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    q, nt = judge(synth(procedure='r6j',
                        pedit={'J8': lambda px: dict(pe.blend_map('J8', ('id', 0), 'RSUB_CLAMP'))}),
                  'abcd0001', '11111111', 'r6j')
    ok = any('K3: COMB_FCN = SUB_CLAMP computes destination minus source' in x for x in nt)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6j: the subtract direction is named',
                               [x for x in nt if 'K3' in x][:1] or q[:1]))
    fails += 0 if ok else 1
    q, nt = judge(synth(procedure='r6j',
                        pedit={'J9': lambda px: dict((k, v ^ 0x00000100) for k, v in px.items())}),
                  'abcd0001', '11111111', 'r6j')
    ok = any('K5' in x and 'no wait is needed' not in x for x in nt)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6j: a wait that changes the picture is recorded',
                               [x for x in nt if 'K5' in x][:1]))
    fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6j'), 'abcd0001', '11111111', 'r6i3')
    ok = any('zclear cases' in x or 'the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6j: judged as r6i3', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # r6k (docs/R6K_PLAN.md 5)
    def named_rule(nt):
        import ast
        m = [x for x in nt if x.startswith('R6k K2: the auxiliary scissor reads as ')]
        if not m:
            return None
        t = m[0][len('R6k K2: the auxiliary scissor reads as '):]
        return ast.literal_eval(t[:t.index(')') + 1])

    q, nt = judge(synth(procedure='r6k'), 'abcd0001', '11111111', 'r6k')
    got = named_rule(nt)
    ok = (not q and got is not None and sum(1 for x in nt if x.startswith('R6k K')) == 5 and
          all(sc.picture(c, got) == sc.picture(c, SC_PLAIN) for c in sc.GATED))
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6k: the plain reading, all five gates',
                               got or q[:1]))
    fails += 0 if ok else 1

    for rule, what in ((('x_low', 'br_incl', 'drop', 'and', 'b0', 16, 16, 'unsigned', 'free'), 'an excluding unit'),
                       (('x_low', 'br_incl', 'keep', 'or', 'b0', 16, 16, 'unsigned', 'free'), 'a unioning unit'),
                       (('y_low', 'br_excl', 'keep', 'and', 'b0', 16, 16, 'unsigned', 'free'), 'y in the low half'),
                       (('x_low', 'br_incl', 'keep', 'and', 'b0', 11, 16, 'unsigned', 'free'), 'an 11-bit x half'),
                       (('x_low', 'br_incl', 'keep', 'and', 'b1440', 16, 16, 'unsigned', 'free'), 'a 1440 bias'),
                       (('x_low', 'br_incl', 'keep', 'and', 'b0', 16, 16, 'unsigned', 'gated'), 'a gated unit'),
                       (('none',), 'a unit that does nothing')):
        q, nt = judge(synth(procedure='r6k', pscissor=rule), 'abcd0001', '11111111', 'r6k')
        got = named_rule(nt)
        # the judge may name another member of the same class; it must give the same pictures
        ok = not q and got is not None and all(sc.picture(c, got) == sc.picture(c, rule) for c in sc.GATED)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6k: %s is named' % what, got or q[:1]))
        fails += 0 if ok else 1

    def move_one(px):
        d = set(px)
        d.discard(sorted(d)[7])
        return d

    def outside(px):
        return set(px) | {(40, 5)}

    for label, kw, want in [
            ('r6k: one pixel of AS1 is not written', dict(sedit={'AS1': move_one}), 'K2: no named rule'),
            ('r6k: AS7 writes outside the map', dict(sedit={'AS7': outside}), 'a write outside the map'),
            ('r6k: the control does not fill the map', dict(sedit={'AS0': move_one}), 'K1: with no auxiliary'),
            ('r6k: a cut pixel changed depth',
             dict(sdepth={'AS8': lambda v: dict(list(v.items()) + [((0, 0), 0x123456)])}), 'K4: 1 cut pixels'),
            ('r6k: a drawn pixel kept the prefill',
             dict(sdepth={'AS8': lambda v: dict(list(v.items()) + [((10, 5), sc.depth_ramp(10, 5))])}),
             'drawn pixels did not'),
            ('r6k: the depth covers one pixel fewer than the colour',
             dict(sdepth={'AS1': lambda v: dict((k, x) for k, x in v.items() if k != (10, 5))}),
             'covers other pixels than the colour')]:
        q, _ = judge(synth(procedure='r6k', **kw), 'abcd0001', '11111111', 'r6k')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    q, nt = judge(synth(procedure='r6k', sedit={'AS11': lambda px: {(1, 1)}}), 'abcd0001', '11111111', 'r6k')
    ok = any('K5' in x and 'left 1 pixels' in x for x in nt)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6k: an inverted scissor that clips partly',
                               [x for x in nt if 'K5' in x][:1] or q[:1]))
    fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6k'), 'abcd0001', '11111111', 'r6j')
    ok = any('zclear cases' in x or 'the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6k: judged as r6j', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1

    # r6l (docs/R6L_PLAN.md 5)
    q, nt = judge(synth(procedure='r6l'), 'abcd0001', '11111111', 'r6l')
    ok = not q and sum(1 for x in nt if x.startswith('R6l M')) == 7
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6l: the clean boot, every gate',
                               q[:1] or [x for x in nt if x.startswith('R6l M4: the ring')][:1]))
    fails += 0 if ok else 1

    def drop_one(px):
        d = dict(px)
        del d[sorted(d)[7]]
        return d

    for label, kw, want in [
            ('r6l: a triangle of the big packet is missing', dict(bedit={'BA': drop_one}),
             'the coverage map differs from the oracle'),
            ('r6l: the eight packets came out in the other order',
             dict(bedit={'BC': lambda px: dict((q, 3 - v) for q, v in px.items())}),
             'the coverage map differs from the oracle'),
            ('r6l: the clip change was lost', dict(bedit={'BD': lambda px: dict(ba.picture('BC'))}),
             'the coverage map differs from the oracle')]:
        q, _ = judge(synth(procedure='r6l', **kw), 'abcd0001', '11111111', 'r6l')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if ok else 1
    g = synth(procedure='r6l')
    q, _ = judge(re.sub(r'wptr=\d+', 'wptr=100', g), 'abcd0001', '11111111', 'r6l')
    ok = any('the ring never wrapped' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6l: the ring never wrapped', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    # the two wraps must be told apart: landing on 0 is the exact fit, anything else is the padding
    for w, want in ((0, 'exactly at the end'), (656, 'through the padding')):
        t = g.replace('wptr=3456', 'wptr=%d' % (4000 + w % 7)).replace('wptr=656\n', 'wptr=%d\n' % w)
        t = re.sub(r'(wptr=)656\b', r'\g<1>%d' % w, g).replace('wptr=3456', 'wptr=4000')
        q2, nt2 = judge(t, 'abcd0001', '11111111', 'r6l')
        ok = any('R6l M4: the ring wrapped' in x and want in x for x in nt2)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6l: a wrap %s is named' % want,
                                   [x for x in nt2 if 'M4: the ring wrapped' in x][:1] or q2[:1]))
        fails += 0 if ok else 1
    # the THIRD run of BA (the one after the wrap) disagrees with the first two
    chunks = g.split('mach: RDN-R5 begin ')
    runs = [k for k, c in enumerate(chunks) if 'zclear case=%d ' % ba.CASE_NUM['BA'] in c]
    c = chunks[runs[2]]
    head = [l for l in c.splitlines() if 'RDN-R6 cov0 ' in l][0]
    words = head.split()
    bad = ' '.join(words[:-1] + ['%08x' % (int(words[-1], 16) ^ 1)])
    chunks[runs[2]] = c.replace(head, bad, 1)
    q, _ = judge('mach: RDN-R5 begin '.join(chunks), 'abcd0001', '11111111', 'r6l')
    ok = any('coverage map differs' in x or 'do not agree' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6l: a repeat of a case differs',
                               q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    q, _ = judge(synth(procedure='r6l'), 'abcd0001', '11111111', 'r6k')
    ok = any('zclear cases' in x or 'the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6l: judged as r6k', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1

    # r6m (docs/R6M_PLAN.md 5): the surfaces move, and every read-back must move with them
    gm = synth(procedure='r6m', wptr0=16)
    q, nt = judge(gm, 'abcd0001', '11111111', 'r6m')
    ok = not q and sum(1 for x in nt if x.startswith('R6m P')) == 9
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6m: the clean boot, every gate',
                               q[:1] or [x for x in nt if x.startswith('R6m P5')][:1]))
    fails += 0 if ok else 1
    for label, kw, want in [
            ('r6m: the draw went to the old colour place',
             dict(rsurf={'MA': lambda co, zf, tf: (ru.COLOR_OFF, zf, tf)}), 'the colour digest is'),
            ('r6m: the draw went to the old depth place',
             dict(rsurf={'MB': lambda co, zf, tf: (co, ru.DEPTH_OFF, tf)}), 'the depth digest is'),
            ('r6m: the texture stayed at its old place',
             dict(rsurf={'MC': lambda co, zf, tf: (co, zf, ru.TEX_OFF)}),
             'the texture surface does not hold what the CPU wrote'),
            ('r6m: the draw spilled into the texture',
             dict(rtex={'MD': lambda w: w[:200] + [0] + w[201:]}),
             'the texture surface does not hold what the CPU wrote'),
            ('r6m: a moved case lost pixels',
             dict(redit={'MA': lambda px: dict(list(px.items())[:-3])}), 'the coverage map differs'),
            ('r6m: the moved texture sampled otherwise',
             dict(redit={'MC': lambda px: dict((q_, v ^ 0x10000) for q_, v in px.items())}),
             'safe pixels differently from XA')]:
        q, _ = judge(synth(procedure='r6m', wptr0=16, **kw), 'abcd0001', '11111111', 'r6m')
        ok = any(want in x for x in q)
        print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', label, (q[:1] if q else ['NOT CAUGHT'])[0][:100]))
        fails += 0 if ok else 1
    # the driver saying it used another surface than the row asks for
    t = gm.replace('zsurf coff=00008010', 'zsurf coff=0003c000', 1)
    q, _ = judge(t, 'abcd0001', '11111111', 'r6m')
    ok = any('the driver used surfaces' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6m: the driver used another surface',
                               (q[:1] if q else ['NOT CAUGHT'])[0][:100]))
    fails += 0 if ok else 1
    # task #30: a boot whose only wrap lands exactly on the ring end has NOT burnt the padding path
    t = re.sub(r'wptr=1264\b', 'wptr=0', gm)
    q, nt2 = judge(t, 'abcd0001', '11111111', 'r6m')
    ok = any('the padding branch still has not run' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6m: an exact-fit wrap is not the pad path',
                               (q[:1] if q else ['NOT CAUGHT'])[0][:100]))
    fails += 0 if ok else 1
    # a word outside the case's own surfaces changed
    t = gm.replace('zr rest0=0 rest1=0 first=0 val=00000000 skipped=0',
                   'zr rest0=1 rest1=1 first=7 val=deadbeef skipped=0', 1)
    q, _ = judge(t, 'abcd0001', '11111111', 'r6m')
    ok = any('outside' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6m: a word outside the surfaces changed',
                               (q[:1] if q else ['NOT CAUGHT'])[0][:100]))
    fails += 0 if ok else 1
    q, _ = judge(gm, 'abcd0001', '11111111', 'r6l')
    ok = any('zclear cases' in x or 'the operations were' in x for x in q)
    print('  %-4s %-48s %s' % ('ok' if ok else 'FAIL', 'r6m: judged as r6l', q[:1] if q else 'NOT CAUGHT'))
    fails += 0 if ok else 1
    print('check_r6a self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    args = sys.argv[1:]
    try:
        opt = dict(zip(args[1::2], args[2::2]))
        path, nonce, build = args[0], opt['--boot'], opt['--build']
    except (IndexError, KeyError):
        sys.exit(__doc__)
    p, notes = judge(open(path, errors='replace').read(), nonce, build, opt.get('--procedure', 'r6a'))
    for n in notes:
        print('  --   %s' % n)
    for x in p:
        print('  FAIL %s' % x)
    print('check_r6a: %s' % ('PASS' if not p else 'FAIL (%d)' % len(p)))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main())
