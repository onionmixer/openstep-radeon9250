#!/usr/bin/env python3
"""M3a: judge the teapot (docs/M3A_PLAN.md 5).

  judge_teapot.py [--recovered N] <dir>   dir holds, per size S (e.g. 64, 256):
                                   accel-S.out  accel-S.ppm  stock-S.ppm
  judge_teapot.py --self-test

COUNTERS BEFORE PICTURES.  The teapot also comes out right when software draws
all of it, so a picture proves nothing about the card until the counters say
who drew it -- and they are checked against a count that does NOT come from our
counters: tea.c draws 32 meshes of grid x grid cells, two triangles a cell, so
Mesa calls the triangle function 64 * grid^2 times (docs/M3A_PLAN.md 5 A).

Two kinds of run:
  CARD  (the surface is within the card's 64 x 64 depth buffer): every triangle
        went to the card -- submitted == 64 grid^2, nothing delegated, nothing
        refused -- and the picture matches software except on edges.
  GUARD (bigger): every triangle was refused as ARGS by the prologue guard and
        drawn by software -- submitted == 0, refused ARGS == delegated ==
        64 grid^2 -- and since software drew it all, the picture is BYTE FOR
        BYTE the stock program's.
"""
import os
import re
import struct
import sys
import tempfile
import zlib

# M3h: the largest surface the library lays the window out for, read from the
# generated header rather than typed (mesa/OSRDNMesaTriTable.h); a width that is
# not whole 8-pixel steps is refused too (docs/M3H_PLAN.md 4-8)
_TAB = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'mesa',
                         'OSRDNMesaTriTable.h')).read()
SURF_MAX_W = int(re.search(r'#define\s+OSRDN_TRI_SURF_MAX_W\s+(\d+)', _TAB).group(1))
SURF_MAX_H = int(re.search(r'#define\s+OSRDN_TRI_SURF_MAX_H\s+(\d+)', _TAB).group(1))


def card_size(w, h):
    return w <= SURF_MAX_W and h <= SURF_MAX_H and w % 8 == 0


# M3j (docs/G1_REMAINING.md): a 2x2 block is an AREA only when its pixels differ by
# MORE than this.  Measured on the M3h run (build/m3h/run-790345421): the four 2x2
# blocks at 256x256 differed by 3..6 -- Gouraud rounding and internal-edge
# assignment that happen to touch in a bigger picture (640x480 had 163 pixels
# past 2 and no block; 256 had 130 and four).  A wrong occlusion shows the OTHER
# surface's shade, and in this scene the lit shades are tens apart (the self-test
# uses 150+).  Below the bound a block is reported, above it it fails.
AREA_DIFF = 24
ARGS = 'ARGS'                   # the prologue guard's reason


def read_ppm(path):
    data = open(path, 'rb').read()
    m = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', data)
    if not m:
        raise ValueError('%s is not a P6/255 PPM' % path)
    w, h = int(m.group(1)), int(m.group(2))
    px = data[m.end():]
    if len(px) != w * h * 3:
        raise ValueError('%s has %d pixel bytes, want %d' % (path, len(px), w * h * 3))
    return w, h, px


def write_png(path, w, h, px):
    raw = b''.join(b'\x00' + px[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' +
                           chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                           chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def read_counts(path):
    """{field: int} from the RDNTEAPOT lines"""
    got = {}
    for ln in open(path, errors='replace'):
        if not ln.startswith('RDNTEAPOT step='):
            continue
        step = ln.split()[1][5:]
        for kv in re.findall(r'(\w+)=(\d+)', ln):
            got['%s.%s' % (step, kv[0])] = int(kv[1])
    return got


def judge_counts(c, recovered=0):
    """-> (kind, bad, ok)"""
    bad, ok = [], []
    need = ('begin.w', 'begin.h', 'begin.grid', 'begin.expected', 'end.delegated',
            'end-tri.submitted', 'end-refused.SUM')
    missing = [k for k in need if k not in c]
    if missing:
        return None, ['the transcript lacks %s -- the program did not finish'
                      % ', '.join(missing)], ok
    w, h, g = c['begin.w'], c['begin.h'], c['begin.grid']
    exp = 64 * g * g
    # M3g (docs/M3G_PLAN.md): what an ordinary program sees -- its own array
    # right after glFinish -- is the picture, and the hook is what copied it.
    if 'finish-sync.same' not in c:
        bad.append('no finish-sync line: the program predates M3g, or did not reach it')
    else:
        if c['finish-sync.same'] != 1:
            bad.append('after glFinish the application array differs from the picture in %d bytes'
                       % c.get('finish-sync.differ', -1))
        if c.get('finish-sync.fmirrors', 0) < 1:
            bad.append('glFinish copied nothing back (fmirrors %d, finishes %d)'
                       % (c.get('finish-sync.fmirrors', -1), c.get('finish-sync.finishes', -1)))
        if not bad:
            ok.append('%dx%d glFinish: the application array IS the picture (%d finish, %d copied back)'
                      % (w, h, c.get('finish-sync.finishes', -1), c['finish-sync.fmirrors']))
    # M3h (docs/M3H_PLAN.md 2, H1): with the fence on, nothing outside the colour surface and the
    # depth buffer the reference would allocate changed
    if 'fence.changed' in c:
        if c['fence.changed'] != 0:
            bad.append('%dx%d fence: %d words OUTSIDE colour [0,%d) and depth [%d,%d) changed '
                       '(first at %d, last at %d)'
                       % (w, h, c['fence.changed'], c.get('fence.colourend', -1),
                          c.get('fence.depthoff', -1), c.get('fence.depthend', -1),
                          c.get('fence.first', -1), c.get('fence.last', -1)))
        else:
            ok.append('%dx%d fence: nothing outside colour and depth changed (window %d bytes)'
                      % (w, h, c.get('fence.window', -1)))
    if c['begin.expected'] != exp:
        bad.append('the program says it expects %d, but 64 x %d^2 is %d'
                   % (c['begin.expected'], g, exp))
    kind = 'CARD' if card_size(w, h) else 'GUARD'
    if c.get('begin.cull', 0) == 1:
        kind = 'CULL'
    sub, dele, rsum = c['end-tri.submitted'], c['end.delegated'], c['end-refused.SUM']
    rargs = c.get('end-refused.%s' % ARGS, -1)
    diag = ('submitted %d, delegated %d, refused %d (ARGS %d), leaves %d, notbound %d, '
            'nosw %d, texproj %d' % (sub, dele, rsum, rargs, c.get('end.leaves', -1),
                                     c.get('end.notbound', -1), c.get('end.nosw', -1),
                                     c.get('end.texproj', -1)))
    # M3j (docs/M3J_PLAN.md, docs/G1_REMAINING.md): a stall the driver RECOVERED from refuses
    # exactly one batch, which the library then draws in software (`replayed`).  The caller
    # says how many the kernel log recovered (rc=8); up to that many REFUSED batches are the
    # planned outcome, and their triangles must show up as replayed, not lost.
    rep = c.get('end.replayed', 0)
    rref = c.get('end-refused.REFUSED', 0)
    recov_note = ''
    if recovered > 0:
        if rref > recovered:
            bad.append('%dx%d: %d batches refused as REFUSED but the kernel recovered only %d -- %s'
                       % (w, h, rref, recovered, diag))
        elif rref > 0:
            recov_note = ' (%d batch%s refused by a recovered stall, %d triangles replayed in software)' % (
                rref, 'es' if rref > 1 else '', rep)
        rsum -= rref
        c = dict(c); c['end-refused.SUM'] = rsum     # the rest of the rules see the unplanned refusals only
        exp_sent = exp - rep
    else:
        exp_sent = exp
    if kind == 'CULL':
        # M3b: culling ALONE, where nobody but us culls.  Mesa still calls the
        # triangle function 64 grid^2 times; each one we either sent or culled.
        cul = c.get('end.culled', -1)
        if not card_size(w, h):
            bad.append('%dx%d: the culling run must be a size the card takes' % (w, h))
        if sub + cul != exp_sent:
            bad.append('%dx%d cull: sent %d + culled %d = %d, want the %d Mesa drew%s -- %s'
                       % (w, h, sub, cul, sub + cul, exp_sent, ' less the %d replayed' % rep if rep else '', diag))
        if cul <= 0:
            bad.append('%dx%d cull: nothing was culled -- the back faces went to the card'
                       % (w, h))
        for k in ('end.delegated', 'end.nosw', 'end.notbound', 'end.texproj',
                  'end-refused.SUM'):
            if c.get(k, -1) != 0:
                bad.append('%dx%d cull: %s is %s, must be 0 -- %s' % (w, h, k, c.get(k), diag))
        if not bad:
            ok.append('%dx%d CULL: %d sent + %d culled by us = %d, none delegated or refused%s'
                      % (w, h, sub, cul, exp_sent, recov_note))
        return kind, bad, ok
    if kind == 'CARD':
        if sub != exp_sent:
            bad.append('%dx%d: the card got %d triangles of the %d Mesa drew%s -- %s'
                       % (w, h, sub, exp_sent, ' less the %d replayed' % rep if rep else '', diag))
        for k in ('end.delegated', 'end.nosw', 'end.notbound', 'end.texproj',
                  'end-refused.SUM'):
            if c.get(k, -1) != 0:
                bad.append('%dx%d: %s is %s, must be 0 -- %s' % (w, h, k, c.get(k), diag))
        if c.get('end-tri.depthsent', 0) <= 0:
            bad.append('%dx%d: no depth-tested triangle was sent' % (w, h))
        if c.get('end-tri.smoothsent', 0) <= 0:
            bad.append('%dx%d: no smooth triangle was sent (lighting is on)' % (w, h))
        if not bad:
            ok.append(('%dx%d CARD: all %d triangles went to the card, none delegated '
                       'or refused, depth %d and smooth %d sent' + recov_note)
                      % (w, h, exp_sent, c['end-tri.depthsent'], c['end-tri.smoothsent']))
    else:
        if sub != 0:
            bad.append('%dx%d: %d depth-tested triangles reached the card at a size its '
                       '64x64 depth buffer cannot hold -- the guard did not stop them -- %s'
                       % (w, h, sub, diag))
        if rargs != exp or dele != exp or rsum != exp:
            bad.append('%dx%d: want every one of the %d triangles refused as ARGS and '
                       'drawn in software -- %s' % (w, h, exp, diag))
        if c.get('end.nosw', -1) != 0:
            bad.append('%dx%d: a refused triangle had no software function to go to'
                       % (w, h))
        if not bad:
            ok.append('%dx%d GUARD: all %d triangles refused as ARGS and drawn in '
                      'software, none reached the card' % (w, h, exp))
    return kind, bad, ok


def judge_pictures(kind, a, s, size):
    """a, s = (w, h, px) for accel and stock -> (bad, ok)"""
    bad, ok = [], []
    if a[:2] != s[:2]:
        return ['%s: the pictures are %dx%d and %dx%d' % (size, a[0], a[1], s[0], s[1])], ok
    w, h, pa, ps = a[0], a[1], a[2], s[2]
    if kind == 'GUARD':
        if pa != ps:
            n = sum(1 for i in range(0, len(pa), 3) if pa[i:i + 3] != ps[i:i + 3])
            bad.append('%s GUARD: software drew both, but %d pixels differ -- they must '
                       'be byte for byte the same' % (size, n))
        else:
            ok.append('%s GUARD: byte for byte the stock picture' % size)
        return bad, ok
    bg = pa[0:3]                           # the corner is clear colour in both
    cov_a = [pa[i:i + 3] != bg for i in range(0, len(pa), 3)]
    cov_s = [ps[i:i + 3] != bg for i in range(0, len(ps), 3)]
    na, ns = sum(cov_a), sum(cov_s)
    if ns == 0 or na == 0:
        return ['%s: nothing was drawn (accel %d, stock %d covered pixels)'
                % (size, na, ns)], ok
    if abs(na - ns) > 0.02 * ns:
        bad.append('%s: covered pixels %d vs %d -- more than 2%% apart' % (size, na, ns))
    # WHAT IS A FAILURE HERE.  The card and Mesa's rasteriser follow different
    # edge rules (R6d: 1/16 truncation, top-left) and different gouraud rounding
    # (R6e), so pixels ON an edge -- the silhouette AND the edges inside the
    # mesh, where two patches meet -- may differ, and interiors differ by a
    # rounding step.  The first draft called any interior difference over 2 a
    # failure and saw only the silhouette as an edge; the first real run
    # (1790263600) then failed on 36 pixels that all lie on the lid seam, the
    # bottom rim and the handle, one pixel wide.
    #
    # The failure this is for -- wrong occlusion, a patch drawn in front of
    # another -- changes an AREA.  So differences over 2 may form lines but
    # never a 2 x 2 block.
    big = set()
    diff = maxd = 0
    hist = {}
    area = set()
    for y in range(h):
        for x in range(w):
            i = y * w + x
            da = pa[i * 3:i * 3 + 3]
            db = ps[i * 3:i * 3 + 3]
            if da == db:
                continue
            diff += 1
            dd = max(abs(p - q) for p, q in zip(da, db))
            maxd = max(maxd, dd)
            hist[min(dd, 3)] = hist.get(min(dd, 3), 0) + 1
            if dd > 2:
                big.add((x, y))
            if dd > AREA_DIFF:
                area.add((x, y))
    small = sorted((x, y) for (x, y) in big
                   if (x + 1, y) in big and (x, y + 1) in big and (x + 1, y + 1) in big)
    blocks = sorted((x, y) for (x, y) in area
                    if (x + 1, y) in area and (x, y + 1) in area and (x + 1, y + 1) in area)
    msg = ('%s: %d of %d pixels differ (by 1: %d, by 2: %d, by more: %d, max %d); '
           'the bigger ones form %d 2x2 block(s), %d of them past %d'
           % (size, diff, w * h, hist.get(1, 0), hist.get(2, 0), hist.get(3, 0), maxd,
              len(small), len(blocks), AREA_DIFF))
    if blocks:
        bad.append(msg + ' -- an AREA changed, first at %s' % (blocks[:3],))
    else:
        ok.append(msg)
    return bad, ok


def judge(d, recovered=0):
    bad, ok, sizes = [], [], []
    for f in sorted(os.listdir(d)):
        m = re.match(r'accel-(\d+(?:x\d+)?c?)\.out$', f)     # M3h: 640x480 too
        if m:
            sizes.append(m.group(1))
    if not sizes:
        return ['no accel-<size>.out in %s' % d], ok
    for size in sizes:
        kind, b, o = judge_counts(read_counts(os.path.join(d, 'accel-%s.out' % size)), recovered)
        bad += b
        ok += o
        if kind is None:
            continue
        try:
            a = read_ppm(os.path.join(d, 'accel-%s.ppm' % size))
            s = read_ppm(os.path.join(d, 'stock-%s.ppm' % size))
        except (OSError, ValueError) as e:
            bad.append('%s: %s' % (size, e))
            continue
        b, o = judge_pictures(kind, a, s, size)
        bad += b
        ok += o
        for tag, img in (('accel', a), ('stock', s)):
            write_png(os.path.join(d, '%s-%s.png' % (tag, size)), *img)
    return bad, ok


def self_test():
    fails = 0

    def one(label, cond):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', label))

    d = tempfile.mkdtemp(prefix='judgeteapot.')

    def transcript(size, sub, dele, refused, grid=10, depth=100, smooth=100, nosw=0,
                   cull=0, culled=0, name=None, same=1, fmirrors=1, replayed=0, refusedk=0):
        e = 64 * grid * grid
        with open(os.path.join(d, name or 'accel-%d.out' % size), 'w') as f:
            f.write('RDNTEAPOT step=begin w=%d h=%d grid=%d expected=%d cull=%d\n'
                    % (size, size, grid, e, cull))
            f.write('RDNTEAPOT step=end installs=1 leaves=0 triangles=%d delegated=%d nosw=%d '
                    'notbound=0 slotsfull=0 texproj=0 replayed=%d zclear=1 zclearbad=0 culled=%d\n'
                    % (e, dele, nosw, replayed, culled))
            f.write('RDNTEAPOT step=end-tri entered=%d submitted=%d smoothsent=%d depthsent=%d\n'
                    % (e, sub, smooth, depth))
            f.write('RDNTEAPOT step=end-refused -=0 NO_ACCEL=0 NOT_RUNNING=0 NO_WINDOW=0 '
                    'ARGS=%d IOCTL=0 REFUSED=%d NOT_DRAWN=0 BATCH_OPEN=0 SUM=%d\n'
                    % (refused, refusedk, refused + refusedk))
            if same is not None:
                f.write('RDNTEAPOT step=finish-sync same=%d differ=%d finishes=1 fmirrors=%d '
                        'foreign=0 notup=0\n' % (same, 0 if same else 4096, fmirrors))

    def ppm(name, size, disk=None, tint=0, hole=None, block=None, line=None, blockshade=None):
        px = bytearray()
        for y in range(size):
            for x in range(size):
                r2 = (x - size / 2) ** 2 + (y - size / 2) ** 2
                inside = r2 < (size / 3) ** 2 if disk is None else r2 < disk ** 2
                if hole and (x, y) == hole:
                    px += bytes((200, 10, 10))
                elif block and block[0] <= x < block[0] + block[2] and block[1] <= y < block[1] + block[2]:
                    px += bytes((200 + blockshade, 150 + blockshade, 50 + blockshade)) if blockshade else bytes((10, 200, 10))
                elif line and y == line[1] and line[0] <= x < line[0] + line[2]:
                    px += bytes((10, 10, 200))
                elif inside:
                    px += bytes((200, 150 + tint, 50))
                else:
                    px += bytes((25, 25, 76))
        with open(os.path.join(d, name), 'wb') as f:
            f.write(b'P6\n%d %d\n255\n' % (size, size) + bytes(px))

    transcript(64, 6400, 0, 0)
    ppm('accel-64.ppm', 64)
    ppm('stock-64.ppm', 64)
    # M3h: 128 is a card size now; 100 is not whole 8-pixel steps and is guarded
    transcript(100, 0, 6400, 6400)
    ppm('accel-100.ppm', 100)
    ppm('stock-100.ppm', 100)
    bad, ok = judge(d)
    # 6 = per run: counts, picture, and (M3g) the glFinish line
    one('the good pair passes (CARD 64, GUARD 100)', not bad and len(ok) == 6)

    transcript(64, 6399, 1, 1)
    bad, ok = judge(d)
    one('ONE triangle delegated at 64x64 is a FAILURE', any('card got 6399' in x for x in bad))
    transcript(64, 6400, 0, 0)

    transcript(100, 12, 6388, 6388)
    bad, ok = judge(d)
    one('ANY triangle reaching the card at a guarded size (100x100) is a FAILURE',
        any('reached the card' in x for x in bad))
    transcript(100, 0, 6400, 6400)

    ppm('accel-100.ppm', 100, tint=1)
    bad, ok = judge(d)
    one('GUARD pictures that are not byte-identical FAIL', any('byte for byte' in x for x in bad))
    ppm('accel-100.ppm', 100)

    ppm('accel-64.ppm', 64, hole=(32, 32))
    bad, ok = judge(d)
    one('one wrong pixel inside passes (it is what an internal edge looks like)', not bad)
    ppm('accel-64.ppm', 64, block=(30, 30, 3))
    bad, ok = judge(d)
    one('a wrong 3x3 AREA inside is a FAILURE (wrong occlusion)', any('AREA changed' in x for x in bad))
    ppm('accel-64.ppm', 64, block=(30, 30, 3), blockshade=6)
    bad, ok = judge(d)
    one('M3j: a 3x3 block that differs by only 6 (rounding) passes', not any('AREA changed' in x for x in bad))
    ppm('accel-64.ppm', 64, line=(20, 32, 12))
    bad, ok = judge(d)
    one('a one-pixel LINE of big differences passes (an edge)', not bad)
    ppm('accel-64.ppm', 64, tint=2)
    bad, ok = judge(d)
    one('a colour 2 off everywhere inside passes (gouraud rounding)', not bad)
    ppm('accel-64.ppm', 64, disk=64 / 3 + 1)
    bad, ok = judge(d)
    one('a silhouette one pixel wider passes (edges differ by rule)',
        not any('AREA changed' in x for x in bad))
    ppm('accel-64.ppm', 64, disk=10)
    bad, ok = judge(d)
    one('a much smaller teapot FAILS on coverage', any('2% apart' in x for x in bad))
    ppm('accel-64.ppm', 64)

    # M3b: culling alone
    transcript(64, 3000, 0, 0, cull=1, culled=3400, name='accel-64c.out')
    ppm('accel-64c.ppm', 64)
    ppm('stock-64c.ppm', 64)
    bad, ok = judge(d)
    one('CULL: 3000 sent + 3400 culled = 6400 passes', not bad and any('CULL' in x for x in ok))
    transcript(64, 3000, 0, 0, cull=1, culled=3399, name='accel-64c.out')
    bad, ok = judge(d)
    one('CULL: one triangle neither sent nor culled is a FAILURE', any('= 6399' in x for x in bad))
    transcript(64, 6400, 0, 0, cull=1, culled=0, name='accel-64c.out')
    bad, ok = judge(d)
    one('CULL: nothing culled (back faces sent) is a FAILURE', any('nothing was culled' in x for x in bad))
    for f_ in ('accel-64c.out', 'accel-64c.ppm', 'stock-64c.ppm'):
        os.unlink(os.path.join(d, f_))

    transcript(64, 6400, 0, 0, depth=0)
    bad, ok = judge(d)
    one('no depth-tested triangle sent is a FAILURE', any('no depth-tested' in x for x in bad))

    # M3g: glFinish must leave the picture in the application's own array
    transcript(64, 6400, 0, 0, same=0)
    bad, ok = judge(d)
    one('M3g: an application array that differs after glFinish is a FAILURE',
        any('after glFinish the application array differs' in x for x in bad))
    transcript(64, 6400, 0, 0, fmirrors=0)
    bad, ok = judge(d)
    one('M3g: a glFinish that copied nothing back is a FAILURE',
        any('glFinish copied nothing back' in x for x in bad))
    transcript(64, 6400, 0, 0, same=None)
    bad, ok = judge(d)
    one('M3g: a transcript without the finish-sync line is a FAILURE',
        any('no finish-sync line' in x for x in bad))

    # M3j: a recovered stall -- one batch refused, its triangles replayed -- passes only
    # when the caller vouches for the recovery, and only for as many as it vouches
    transcript(64, 6393, 0, 0, replayed=7, refusedk=1)
    bad, ok = judge(d)
    one('M3j: a refused batch with nobody vouching is still a FAILURE', bool(bad))
    bad, ok = judge(d, recovered=1)
    one('M3j: one refused batch, 7 replayed, one recovery vouched -> passes',
        not bad and any('recovered stall' in x for x in ok))
    transcript(64, 6386, 0, 0, replayed=14, refusedk=2)
    bad, ok = judge(d, recovered=1)
    one('M3j: two refused batches with one recovery vouched is a FAILURE', any('recovered only 1' in x for x in bad))
    transcript(64, 6393, 0, 0, replayed=6, refusedk=1)
    bad, ok = judge(d, recovered=1)
    one('M3j: replayed does not cover the missing triangles -> FAILURE', bool(bad))
    transcript(64, 6400, 0, 0)

    # M3h: the fence
    transcript(64, 6400, 0, 0)
    with open(os.path.join(d, 'accel-64.out'), 'a') as f:
        f.write('RDNTEAPOT step=fence window=8000000 colourend=16384 depthoff=5242880 '
                'depthend=5251072 changed=0 first=0 last=0\n')
    bad, ok = judge(d)
    one('M3h: a clean fence passes', not bad and any('fence: nothing outside' in x for x in ok))
    transcript(64, 6400, 0, 0)
    with open(os.path.join(d, 'accel-64.out'), 'a') as f:
        f.write('RDNTEAPOT step=fence window=8000000 colourend=16384 depthoff=5242880 '
                'depthend=5251072 changed=3 first=5251072 last=5251080\n')
    bad, ok = judge(d)
    one('M3h: a word changed outside the fence is a FAILURE',
        any('OUTSIDE colour' in x for x in bad))
    transcript(64, 6400, 0, 0)

    for f in os.listdir(d):
        os.unlink(os.path.join(d, f))
    os.rmdir(d)
    print('judge_teapot self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    recovered = 0
    args = list(sys.argv[1:])
    if '--recovered' in args:
        k = args.index('--recovered')
        recovered = int(args[k + 1])
        del args[k:k + 2]
    if len(args) != 1:
        print(__doc__)
        return 2
    bad, ok = judge(args[0], recovered)
    for x in ok:
        print('  ok   %s' % x)
    for x in bad:
        print('  FAIL %s' % x)
    print('judge_teapot: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
