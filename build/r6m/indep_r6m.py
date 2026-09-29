"""R6m independent recount: own parser, own rasteriser, own tiling, own digest arithmetic.

  python3 build/r6m/indep_r6m.py <boot nonce> [log file]

Nothing here imports the oracles or check_r6a.  The triangle, the coverage rule, Mesa's depth tile
formula (r200_span.c r200_mba_z32, copied from the source, not from our oracle), the ZPREP pattern
and the driver's digest arithmetic are all written out again from docs/R6M_PLAN.md and the
reference, so that one mistake cannot pass both.  What it recomputes is the thing R6m is about:
the ABSOLUTE address every word went to -- the digest's xor and weighted sum run over the whole
16 KiB surface, pattern words included, so they only come out right if the surface really sat where
the case's row says it does.
"""
import math
import re
import sys
from fractions import Fraction as Fr

N = sys.argv[1]
MAPW, PITCH, M32 = 32, 64, 0xffffffff
BUF_WORDS = 4096                                # 64 x 64 x 4 bytes
TEX_BYTES = 1024
T1 = [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]     # every R6m case draws this triangle
PIX_A = 0x78123456                              # the flat colour of MA, MB and ME
Z_FLAT = 0xffffff                               # their vertices carry z = 1.0
Z_TEX = 0x800000                                # the textured cases carry z = 0.5: floor(z * 2^24)
# case -> (number, colour offset, depth offset, texture offset or None)
CASES = {
    'MA': (166, 0x08010, 0x00000, None),
    'MB': (167, 0x3c000, 0x10000, None),
    'MC': (168, 0x3c000, 0x00000, 0x14020),
    'MD': (169, 0x08010, 0x10000, 0x14020),
    'ME': (170, 0x3c000, 0x00000, None),
}
NAME = dict((v[0], k) for k, v in CASES.items())
PAD = {161: 'BA', 162: 'BB'}                    # the ring-padding tail, judged only on its pointers


def pattern(i):
    return (0xa5000000 | (i & 0xffff)) & M32


def bit(v, k):
    return (v >> k) & 1


def mba_z32(x, y, pitch=PITCH):
    """Mesa 6.5.3 r200_span.c r200_mba_z32, depthHasSurface false -- transcribed from the C"""
    b = ((y & 0x7ff) >> 4) * ((pitch & 0xfff) >> 5) + ((x & 0x7ff) >> 5)
    return ((bit(x, 0) << 2) | (bit(y, 0) << 3) | (bit(x, 1) << 4) | (bit(y, 1) << 5) |
            (bit(x, 3) << 6) | (bit(x, 4) << 7) | (bit(x, 2) << 8) | (bit(y, 2) << 9) |
            (bit(y, 3) << 10) |
            (((b & 1) if (pitch & 0x20) else ((b & 1) ^ bit(y, 4))) << 11) | ((b >> 1) << 12))


def covered(tri):
    """the measured rule: vertices truncated to 1/16, the sample at pixel + 1/2, top-left edges in"""
    P = [(Fr(math.floor(x * 16), 16), Fr(math.floor(y * 16), 16)) for x, y in tri]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if A == 0:
        return []
    sgn = 1 if A > 0 else -1
    out = []
    for y in range(MAPW):
        for x in range(MAPW):
            sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
            ins = True
            for i in range(3):
                j = (i + 1) % 3
                dx, dy = (P[j][0] - P[i][0]) * sgn, (P[j][1] - P[i][1]) * sgn
                e = dx * (sy - P[i][1]) - dy * (sx - P[i][0])
                if e < 0 or (e == 0 and not ((dy == 0 and dx > 0) or dy < 0)):
                    ins = False
                    break
            if ins:
                out.append((x, y))
    return out


PIXELS = covered(T1)


def digest(words, first, count):
    """what the driver logs: xor, a position-weighted sum, how many differ from the pattern, the
    xor and sum of their relative indexes"""
    x = s = n = ix = isum = 0
    for k in range(first, first + count):
        w = words[k]
        x ^= w
        s = (s + w * (2 * (k - first) + 1)) & M32
        if w != pattern(k):
            n += 1
            ix ^= (k - first)
            isum = (isum + (k - first)) & M32
    return dict(xor=x, wsum=s, changed=n, ixor=ix, isum=isum)


def surfaces(case):
    """(the colour digest, the depth digest) this case must log, built from the pattern up"""
    _num, co, zf, tf = CASES[case]
    words = [pattern(i) for i in range(0x40000 // 4)]
    if tf is not None:                          # the CPU's 8 x 8 texture, 32-byte rows
        for v in range(8):
            for u in range(8):
                words[(tf + v * 32) // 4 + u] = 0xff000000 | ((u * 32) << 16) | ((v * 32) << 8) | 0x55
    z = Z_TEX if tf is not None else Z_FLAT
    for (x, y) in PIXELS:
        if tf is None:                          # a textured pixel's colour is the planes' business
            words[(co + 4 * (x + PITCH * y)) // 4] = PIX_A
        else:
            words[(co + 4 * (x + PITCH * y)) // 4] = 0           # unknown: only the count is checked
        k = (zf + mba_z32(x, y)) // 4
        words[k] = (words[k] & 0xff000000) | z
    return (digest(words, co // 4, BUF_WORDS), digest(words, zf // 4, BUF_WORDS), tf is not None)


# ---- the log, one operation at a time ------------------------------------------------------
LOG = sys.argv[2] if len(sys.argv) > 2 else 'build/r6/boot-%s.full.log' % N
# the target's /usr/adm/messages holds every boot; take only this one's lines -- the first line
# naming this nonce up to the first later line naming another (without this the ring pointers of
# older boots come along and the wrap analysis is nonsense)
_lines = open(LOG, errors='replace').read().splitlines()
_mine = [k for k, l in enumerate(_lines) if 'boot=%s' % N in l]
if not _mine:
    sys.exit('no line names boot %s in %s' % (N, LOG))
_other = [k for k in range(_mine[0] + 1, len(_lines))
          if re.search(r'boot=(?!%s)[0-9a-f]{8}\b' % re.escape(N), _lines[k])]
text = '\n'.join(_lines[_mine[0]:_other[0] if _other else len(_lines)])
wptr, runs = [], []
for chunk in text.split('RDN-R5 begin ')[1:]:
    chunk = chunk.split('RDN-R5 begin ')[0]
    m = re.search(r'wptr=(\d+)', chunk)
    if m:
        wptr.append(int(m.group(1)))
    m = re.search(r'RDN-R6 zclear case=(\d+) stage=3', chunk)
    if not m:
        continue
    c = int(m.group(1))
    if c not in NAME and c not in PAD:
        continue
    d = {'case': c}
    m = re.search(r'RDN-R6 zsurf coff=([0-9a-f]{8}) zoff=([0-9a-f]{8}) toff=([0-9a-f]{8}) texbad=(\d+)', chunk)
    if m:
        d['surf'] = (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16), int(m.group(4)))
    for tag in ('zd', 'zc'):
        m = re.search(r'RDN-R6 %s1 xor=([0-9a-f]{8}) wsum=([0-9a-f]{8}) changed=(\d+) ixor=(\d+) isum=(\d+)' % tag, chunk)
        if m:
            d[tag] = dict(xor=int(m.group(1), 16), wsum=int(m.group(2), 16), changed=int(m.group(3)),
                          ixor=int(m.group(4)), isum=int(m.group(5)))
    w = {}
    for cm in re.finditer(r'RDN-R6 cov(\d) ((?:[0-9a-f]{8} ?){8})', chunk):
        w[int(cm.group(1))] = [int(x, 16) for x in cm.group(2).split()]
    if sorted(w) == list(range(8)):
        d['cov'] = [x for k in range(8) for x in w[k]]
    m = re.search(r'RDN-R6 zr rest0=(\d+) rest1=(\d+)', chunk)
    if m:
        d['rest'] = (int(m.group(1)), int(m.group(2)))
    runs.append(d)

bad = 0
for r in runs:
    c = r['case']
    if c in PAD:
        print('%-3s (%d): the ring-padding tail, judged on the pointers only' % (PAD[c], c))
        continue
    n = NAME[c]
    _num, co, zf, tf = CASES[n]
    want_surf = (co, zf, tf or 0)
    got_surf = (r.get('surf') or (None, None, None, None))[:3]
    if got_surf != want_surf:
        print('%-3s: the driver used %s, this file says %s' % (n, got_surf, want_surf))
        bad += 1
    if (r.get('surf') or (0, 0, 0, 1))[3] != 0:
        print('%-3s: the texture surface did not read back after the draw (%d words)' % (n, r['surf'][3]))
        bad += 1
    # the coverage map: every pixel of the triangle, and nothing else
    if 'cov' in r:
        seen = set()
        for i in range(1024):
            if (r['cov'][i >> 4] >> (2 * (i & 15))) & 3:
                seen.add((i % MAPW, i // MAPW))
        if seen != set(PIXELS):
            print('%-3s: the coverage map covers %d pixels, this file counts %d (%d differ)' %
                  (n, len(seen), len(PIXELS), len(seen ^ set(PIXELS))))
            bad += 1
    else:
        print('%-3s: no coverage map' % n)
        bad += 1
    ec, ed, textured = surfaces(n)
    for tag, e in (('zc', ec), ('zd', ed)):
        g = r.get(tag)
        if g is None:
            print('%-3s: no %s digest' % (n, tag))
            bad += 1
            continue
        keys = ('changed', 'ixor', 'isum') if (textured and tag == 'zc') else \
               ('changed', 'ixor', 'isum', 'xor', 'wsum')
        diff = [k for k in keys if g[k] != e[k]]
        if diff:
            print('%-3s: the %s digest differs on %s (%s vs %s)' %
                  (n, tag, diff, [g[k] for k in diff], [e[k] for k in diff]))
            bad += 1
    if r.get('rest') != (0, 0):
        print('%-3s: %s words outside the case\'s surfaces changed' % (n, r.get('rest')))
        bad += 1
    print('%-3s: colour 0x%05x depth 0x%05x texture %s -- %d pixels, digests recomputed here' %
          (n, co, zf, ('0x%05x' % tf) if tf else 'the usual place', len(PIXELS)))

drops = [(a, b) for a, b in zip(wptr, wptr[1:]) if b < a]
pads = [(a, b) for a, b in drops if b != 0]
print('the ring wrapped %d time(s): %s' % (len(drops), ' '.join('%d>%d' % d for d in drops) or 'never'))
for a, b in drops:
    # only the pointer before and after is logged, not the prefix submission in between, so the
    # exact number of padding words is not recoverable here -- the BRANCH is
    print('  %d -> %d: %s' % (a, b, 'the padding branch (a submission did not fit before the ring end)'
                              if b else 'an exact fit, no padding'))
if not pads:
    print('the PADDING branch did not run in this boot (task #30 is not done)')
    bad += 1
print('indep_r6m: %d case(s), %d disagreement(s)' % (len([r for r in runs if r['case'] in NAME]), bad))
sys.exit(1 if bad else 0)
